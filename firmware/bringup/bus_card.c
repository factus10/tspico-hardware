/*
 * TS-Pico v3 bus test, second design (see bus_card.pio).
 *
 * Every read's class comes from a shadow of the 2068's bank registers (ports
 * F4h and FFh, read by io_snoop on every I/O write), not from /ROSCS and
 * /EXROM. serve (PIO0) reads the address off MD, decides from the top three
 * bits through a chunk table core 1 keeps current, asserts /BE straight away
 * for HOME and EXROM, and drives the byte; addr_read (PIO1) sequences the
 * address buffers and enables U3 when serve asks. The DMA chain fetches only
 * the byte that is needed.
 *
 * Ports 0Eh/0Fh (the TS-Pico protocol): OUTs come in through io_snoop. INs are
 * handled by core 1, which watches the I/O read strobe, forces U1 on through a
 * GPIO override to read the port, and for 0Eh/0Fh hands the reply to io_drive
 * (PIO0) and forces U3 on until the strobe ends. An IN leaves about 600 ns
 * before the Z80 samples the data. mem_write (PIO1) reads every memory write; core 1
 * stores the byte in the DOCK image when the shadow maps that chunk to the dock
 * and DOCK serving is on, so DOCK RAM works.
 *
 * Shadow mode (the default) patches serve's /BE and U3 requests out: the card
 * follows every read and times itself without driving the 2068. 'e 1' serves.
 *
 * Images at 0x20040000 (memmap_bus.ld): the byte for (address, slot) is at
 * IMAGE_REGION + 4 * address + slot; slot 0 HOME (copyright line marked), slot
 * 1 EXROM (mirrored), slot 2 DOCK ("TS-PICO DOCK" at 0x8000). HOME and EXROM
 * come from the TS-Pico ROM (16K EXROM) or the stock 2068's ('m').
 *
 * The TS-Pico protocol responder (docs/PROTOCOL.md in the firmware repo) runs
 * on core 0 from the menu loop: SYNC, pre-header, command body, answer, tail.
 *
 * The 2068 is held in reset until 'g'. USB serial menu: '?' for help.
 */
#include <stdio.h>
#include <string.h>

#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "hardware/pio.h"
#include "hardware/structs/busctrl.h"
#include "hardware/structs/m33.h"
#include "hardware/structs/qmi.h"
#include "hardware/vreg.h"

#include "board.h"
#include "bus_card.pio.h"

extern const unsigned char rom_home[], rom_exrom[], rom_tspico[];
extern const unsigned rom_home_len, rom_exrom_len, rom_tspico_len;

#define IMAGE_REGION 0x20040000u
#define IMAGE_PREFIX (IMAGE_REGION >> 18)
#define SLOT_HOME  0
#define SLOT_EXROM 1
#define SLOT_DOCK  2


#define BUS_CLOCK_KHZ 250000

static const PIO pio_serve = pio0, pio_addr = pio1;
static uint sm_serve, sm_iodrv, sm_addr, sm_write, sm_snoop, off_addr, off_write, off_snoop;
static int ch_ptr, ch_data, ch_log;

// Set by core 0, read by core 1's endless loop: volatile, or the compiler may
// read them once at the top of the loop (it did, once the loop moved to RAM).
static volatile bool serving;     // /BE and U3 requests live
static volatile bool exrom_on;    // EXROM-bank chunks served (with /BE)
static volatile bool dock_on;     // DOCK-bank chunks served (no /BE)
static volatile bool held_2068 = true;

// Timing, in PIO cycles (4 ns at 250 MHz): serve's wait after U2 comes on, its
// wait before sampling A7..A0, and addr_read's U2 and U1 hold loops. See
// bus_card.pio for how they line up: A15..A8 sampled 7 cycles after U2 on,
// A7..A0 7 (HOME, DOCK) or 8 (EXROM) after U1 on, each window held 2 past it.
static uint d_hi = 3, d_lo = 3, hold_hi = 5, hold_lo = 9;
static bool sync_bypass = true;

// ---- logs -------------------------------------------------------------------

#define LOG_N 4096
static uint32_t addr_log[LOG_N] __attribute__((aligned(LOG_N * 4)));
#define BOOT_N     4096
#define BOOT_SLACK 256
static uint32_t boot_log[BOOT_N + BOOT_SLACK];
static volatile bool boot_logging, boot_armed;
static volatile uint32_t ring_seen;

// ---- bank shadow ------------------------------------------------------------

static volatile uint8_t sh_hsr, sh_ff;
static volatile uint32_t io_writes, f4_writes, ff_writes, table_updates;
static volatile uint32_t served[3];
static volatile uint32_t mem_writes, dock_writes;

// ---- ports 0Eh / 0Fh ---------------------------------------------------------

// Reply queue for IN 0Eh (empty reads 00h), and the status byte IN 0Fh returns.
// Any OUT to 0Eh/0Fh makes the status 00h (busy), as v2.1's PIO did, and goes
// to the receive queue for the protocol responder on core 0 (port 0Fh as
// 0x100 | data). In echo mode core 1 instead queues OUT 0Eh bytes for IN 0Eh
// and sets the status back to FFh.
#define TXQ_N 1024
static volatile uint8_t txq[TXQ_N];
static volatile uint32_t txq_head, txq_tail;     // head: core 0 (core 1 in echo mode); tail: core 1
#define RXQ_N 1024
static volatile uint16_t rxq[RXQ_N];
static volatile uint32_t rxq_head, rxq_tail;     // head: core 1; tail: core 0
static volatile uint32_t rxq_lost;
static volatile uint8_t io_status = 0xff;
static volatile bool echo_mode = false;
// Protocol trace, kept by core 1 (it sees every exchange): time in us, and a
// kind: 'O' OUT 0Eh, 'S' OUT 0Fh, 'I' IN 0Eh, 'F' IN 0Fh when the status read
// differs from the last one traced.
#define TRACE_N 512
static uint32_t trace_t[TRACE_N];
static uint16_t trace_v[TRACE_N];
static volatile uint32_t trace_n;
static uint16_t trace_last_status = 0x100;   // none yet
static void __not_in_flash_func(trace)(char kind, uint8_t v) {
    uint32_t i = trace_n % TRACE_N;
    trace_t[i] = timer_hw->timerawl;
    trace_v[i] = (uint16_t)(kind << 8 | v);
    trace_n++;
}
static volatile uint32_t io_ins, io_in_ours, io_outs_ours, io_in_late;
// Core 1's worst gap between checks of nIORD, and worst time from noticing an IN
// to U3 on, in core cycles (DWT counter).
static volatile uint32_t poll_gap_max, respond_max;
static volatile bool io_stats_reset;
static volatile bool in_handling = true;    // 'n 0' leaves every IN alone
#define IOLOG_N 32
static volatile uint32_t iolog[IOLOG_N];    // last I/O writes: port << 8 | data
static volatile uint32_t iolog_n;
static volatile uint32_t iolog_pos[IOLOG_N];   // read-log position at each, for the snapshot

// Snapshot of the read log around a trigger ('z'): the first OUT to port FEh
// (the beeper) with the EXROM paged in, then SNAP_AFTER more reads.
#define SNAP_AFTER 3000
static uint32_t snap[LOG_N];
static volatile bool snap_armed, snap_waiting, snap_ready;
static volatile uint32_t snap_trig;     // ring position of the trigger
static volatile uint32_t snap_base;     // ring position of snap[0]
// Memory writes (address << 8 | data) with the read-log position at each; the
// snapshot copies the last WLOG_N.
#define WLOG_N 2048
static uint32_t wlog[WLOG_N], wlog_pos[WLOG_N], wsnap[WLOG_N], wsnap_pos[WLOG_N];
static volatile uint32_t wlog_n, wsnap_n;
static uint32_t iosnap[IOLOG_N], iosnap_pos[IOLOG_N];
static volatile uint32_t iosnap_n;
static volatile bool side_frozen;

// Copy the write and I/O logs: when the Z80 is seen back at 0000h after the
// trigger (a restart), or when the read snapshot is taken.
static void __not_in_flash_func(freeze_side_logs)(void) {
    uint32_t wn = wlog_n, wf = wn > WLOG_N ? wn - WLOG_N : 0;
    for (uint32_t i = wf; i < wn; i++) {
        wsnap[i - wf] = wlog[i % WLOG_N];
        wsnap_pos[i - wf] = wlog_pos[i % WLOG_N];
    }
    wsnap_n = wn - wf;
    uint32_t n = iolog_n, f = n > IOLOG_N ? n - IOLOG_N : 0;
    for (uint32_t i = f; i < n; i++) {
        iosnap[i - f] = iolog[i % IOLOG_N];
        iosnap_pos[i - f] = iolog_pos[i % IOLOG_N];
    }
    iosnap_n = n - f;
    side_frozen = true;
}

static uint ns(uint32_t cycles) { return (uint)((uint64_t)cycles * 1000000000u / clock_get_hz(clk_sys)); }

// ---- images -----------------------------------------------------------------

// The ROM set the card serves: the TS-Pico ROM (HOME, then a 16K EXROM) or the
// stock 2068's (8K EXROM, mirrored). Either way the copyright line is marked.
static bool tspico_rom = true;

static void load_roms(void) {
    uint8_t *r = (uint8_t *)IMAGE_REGION;
    const uint8_t *home = tspico_rom ? rom_tspico : rom_home;
    const uint8_t *exrom = tspico_rom ? rom_tspico + 0x4000 : rom_exrom;
    uint exrom_len = tspico_rom ? rom_tspico_len - 0x4000 : rom_exrom_len;
    for (uint a = 0; a < 0x10000; a++) {
        r[4 * a + SLOT_HOME] = a < 0x4000 ? home[a] : 0xff;
        r[4 * a + SLOT_EXROM] = exrom[a % exrom_len];
    }
    static const char from[] = "Timex Computer", to[] = "TS-Pico v3 ROM";
    for (uint a = 0; a + sizeof from - 1 <= 0x4000; a++) {
        if (memcmp(&home[a], from, sizeof from - 1) == 0) {
            for (uint k = 0; k < sizeof to - 1; k++) r[4 * (a + k) + SLOT_HOME] = (uint8_t)to[k];
            break;
        }
    }
}

static void load_images(void) {
    uint8_t *r = (uint8_t *)IMAGE_REGION;
    memset(r, 0xff, 256 * 1024);
    load_roms();
    static const char dock_mark[] = "TS-PICO DOCK";
    for (uint k = 0; k < sizeof dock_mark - 1; k++) r[4 * (0x8000 + k) + SLOT_DOCK] = (uint8_t)dock_mark[k];
}

// ---- serve's table and patches ------------------------------------------------

// serve is loaded at offset 0, so its labels are instruction addresses.
static uint16_t serve_insn(uint at) { return serve_program_instructions[at]; }

// One table entry per chunk, from the shadow and the serving switches.
static uint __not_in_flash_func(chunk_target)(uint chunk, uint hsr, uint ff) {
    if ((hsr >> chunk) & 1) {
        if (ff & 0x80) return exrom_on ? serve_offset_path_e : serve_offset_tail;
        return dock_on ? serve_offset_path_d : serve_offset_tail;
    }
    return chunk < 2 ? serve_offset_path_h : serve_offset_tail;
}

static void __not_in_flash_func(write_table)(void) {
    uint hsr = sh_hsr, ff = sh_ff;
    for (uint c = 0; c < 8; c++) pio_serve->instr_mem[c] = pio_encode_jmp(chunk_target(c, hsr, ff));
    table_updates++;
}

// serve has one optional side-set pin, so its instruction word is opt (bit 12),
// side value (bit 11), delay (bits 10:8). Shadow mode drops the /BE side-sets on
// path_e and path_h and turns the U3 request into a nop with the same delay.
#define SIDE_BITS  0x1800u
#define DELAY_BITS 0x0700u
static void set_serving(bool on) {
    serving = on;
    uint16_t e = serve_insn(serve_offset_path_e), h = serve_insn(serve_offset_path_h);
    pio_serve->instr_mem[serve_offset_path_e] = on ? e : (e & ~SIDE_BITS);
    pio_serve->instr_mem[serve_offset_path_h] = on ? h : (h & ~SIDE_BITS);
    uint16_t req = on ? serve_insn(serve_offset_req) : pio_encode_nop();
    pio_serve->instr_mem[serve_offset_req] = (req & ~DELAY_BITS) | (d_lo << 8);
}

// Delays: serve's two by the delay field (3 bits), and addr_read's two hold loops.
static void set_delays(void) {
    if (d_hi > 7) d_hi = 7;
    if (d_lo > 7) d_lo = 7;
    if (hold_hi > 31) hold_hi = 31;
    if (hold_lo > 31) hold_lo = 31;
    pio_serve->instr_mem[serve_offset_entry] = (serve_insn(serve_offset_entry) & ~DELAY_BITS) | (d_hi << 8);
    set_serving(serving);   // the request carries d_lo
    pio_addr->instr_mem[off_addr + addr_read_offset_hi_hold] = pio_encode_set(pio_y, hold_hi);
    // lo_hold also side-sets U1 on (opt bit and value in bits 12:9 for 3 pins + opt).
    pio_addr->instr_mem[off_addr + addr_read_offset_lo_hold] =
        (addr_read_program_instructions[addr_read_offset_lo_hold] & ~0x1fu) | hold_lo;
}

static void set_sync_bypass(bool on) {
    sync_bypass = on;
    // MD and the read strobe in PIO0; those plus nIOWR in PIO1.
    uint32_t b0 = 0xffu | (1u << 15), b1 = 0xffu | (1u << 15) | (1u << 18);
    pio_serve->input_sync_bypass = on ? b0 : 0;
    pio_addr->input_sync_bypass = on ? b1 : 0;
}

// ---- start --------------------------------------------------------------------

static void bus_start(void) {
    pio_set_gpio_base(pio_serve, 0);
    pio_set_gpio_base(pio_addr, 0);

    // serve (PIO0, offset 0): MD and BE_REQ. MD starts as inputs, /BE off.
    sm_serve = pio_claim_unused_sm(pio_serve, true);
    pio_add_program_at_offset(pio_serve, &serve_program, 0);
    pio_sm_config c = serve_program_get_default_config(0);
    sm_config_set_in_pin_base(&c, PIN_MD0);
    sm_config_set_out_pins(&c, PIN_MD0, 8);
    sm_config_set_sideset_pin_base(&c, PIN_BE_REQ);
    sm_config_set_in_shift(&c, false, true, 18);
    sm_config_set_out_shift(&c, true, false, 32);
    pio_sm_set_pins_with_mask(pio_serve, sm_serve, 0, (1u << PIN_BE_REQ));
    pio_sm_set_pindirs_with_mask(pio_serve, sm_serve, 1u << PIN_BE_REQ, (1u << PIN_BE_REQ) | 0xffu);
    for (uint p = PIN_MD0; p < PIN_MD0 + 8; p++) pio_gpio_init(pio_serve, p);
    pio_gpio_init(pio_serve, PIN_BE_REQ);
    pio_sm_init(pio_serve, sm_serve, serve_offset_entry, &c);
    pio_sm_put(pio_serve, sm_serve, IMAGE_PREFIX);
    pio_sm_exec(pio_serve, sm_serve, pio_encode_pull(false, true));
    pio_sm_exec(pio_serve, sm_serve, pio_encode_mov(pio_x, pio_osr));
    write_table();
    set_serving(false);

    // io_drive (PIO0): drives replies to IN 0Eh/0Fh onto MD.
    sm_iodrv = pio_claim_unused_sm(pio_serve, true);
    uint off_iodrv = pio_add_program(pio_serve, &io_drive_program);
    c = io_drive_program_get_default_config(off_iodrv);
    sm_config_set_out_pins(&c, PIN_MD0, 8);
    sm_config_set_out_shift(&c, true, false, 32);
    pio_sm_init(pio_serve, sm_iodrv, off_iodrv, &c);

    // addr_read and io_snoop (PIO1): the three buffer enables, all off.
    const uint32_t en = (1u << PIN_NAEN_LO) | (1u << PIN_NAEN_HI) | (1u << PIN_NDATA_OE);
    sm_addr = pio_claim_unused_sm(pio_addr, true);
    off_addr = pio_add_program(pio_addr, &addr_read_program);
    c = addr_read_program_get_default_config(off_addr);
    sm_config_set_sideset_pin_base(&c, PIN_NAEN_LO);
    sm_config_set_jmp_pin(&c, 15);
    sm_config_set_mov_status(&c, STATUS_IRQ_SET, 2);
    pio_sm_set_pins_with_mask(pio_addr, sm_addr, en, en);
    pio_sm_set_pindirs_with_mask(pio_addr, sm_addr, en, en);
    pio_gpio_init(pio_addr, PIN_NAEN_LO);
    pio_gpio_init(pio_addr, PIN_NAEN_HI);
    pio_gpio_init(pio_addr, PIN_NDATA_OE);
    pio_sm_init(pio_addr, sm_addr, off_addr, &c);

    sm_write = pio_claim_unused_sm(pio_addr, true);
    off_write = pio_add_program(pio_addr, &mem_write_program);
    c = mem_write_program_get_default_config(off_write);
    sm_config_set_in_pin_base(&c, PIN_MD0);
    sm_config_set_sideset_pin_base(&c, PIN_NAEN_LO);
    sm_config_set_in_shift(&c, false, true, 24);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    pio_sm_init(pio_addr, sm_write, off_write, &c);

    sm_snoop = pio_claim_unused_sm(pio_addr, true);
    off_snoop = pio_add_program(pio_addr, &io_snoop_program);
    c = io_snoop_program_get_default_config(off_snoop);
    sm_config_set_in_pin_base(&c, PIN_MD0);
    sm_config_set_sideset_pin_base(&c, PIN_NAEN_LO);
    sm_config_set_in_shift(&c, false, true, 16);
    pio_sm_init(pio_addr, sm_snoop, off_snoop, &c);

    set_delays();
    set_sync_bypass(true);

    // DMA: pointer from serve's RX FIFO -> ch_data's read-address trigger;
    // ch_data copies the byte into serve's TX FIFO, then chains to ch_log,
    // which copies the pointer into the log.
    ch_ptr = dma_claim_unused_channel(true);
    ch_data = dma_claim_unused_channel(true);
    ch_log = dma_claim_unused_channel(true);
    memset(addr_log, 0xff, sizeof addr_log);

    dma_channel_config l = dma_channel_get_default_config(ch_log);
    channel_config_set_transfer_data_size(&l, DMA_SIZE_32);
    channel_config_set_read_increment(&l, false);
    channel_config_set_write_increment(&l, true);
    channel_config_set_ring(&l, true, 14);
    dma_channel_configure(ch_log, &l, addr_log, &dma_hw->ch[ch_data].read_addr, 1, false);

    dma_channel_config d = dma_channel_get_default_config(ch_data);
    channel_config_set_transfer_data_size(&d, DMA_SIZE_8);
    channel_config_set_read_increment(&d, false);
    channel_config_set_write_increment(&d, false);
    channel_config_set_high_priority(&d, true);
    channel_config_set_chain_to(&d, ch_log);
    dma_channel_configure(ch_data, &d, &pio_serve->txf[sm_serve], NULL, 1, false);

    dma_channel_config p = dma_channel_get_default_config(ch_ptr);
    channel_config_set_transfer_data_size(&p, DMA_SIZE_32);
    channel_config_set_read_increment(&p, false);
    channel_config_set_write_increment(&p, false);
    channel_config_set_dreq(&p, pio_get_dreq(pio_serve, sm_serve, false));
    channel_config_set_high_priority(&p, true);
    dma_channel_configure(ch_ptr, &p, &dma_hw->ch[ch_data].al3_read_addr_trig, &pio_serve->rxf[sm_serve],
                          (DMA_CH0_TRANS_COUNT_MODE_VALUE_ENDLESS << DMA_CH0_TRANS_COUNT_MODE_LSB) | 1, true);

    pio_sm_set_enabled(pio_serve, sm_serve, true);
    pio_sm_set_enabled(pio_serve, sm_iodrv, true);
    pio_sm_set_enabled(pio_addr, sm_addr, true);
    pio_sm_set_enabled(pio_addr, sm_write, true);
    pio_sm_set_enabled(pio_addr, sm_snoop, true);
}

// ---- core 1 -------------------------------------------------------------------

#define RING_BITS (DMA_CH0_CTRL_TRIG_RING_SEL_BITS | DMA_CH0_CTRL_TRIG_RING_SIZE_BITS)

static void __not_in_flash_func(log_to_ring)(void) {
    ring_seen = 0;
    hw_write_masked(&dma_hw->ch[ch_log].al1_ctrl,
                    DMA_CH0_CTRL_TRIG_RING_SEL_BITS | (14u << DMA_CH0_CTRL_TRIG_RING_SIZE_LSB), RING_BITS);
    dma_channel_set_write_addr(ch_log, addr_log, false);
}

static void log_boot(void) {
    memset(boot_log, 0xff, sizeof boot_log);
    hw_write_masked(&dma_hw->ch[ch_log].al1_ctrl, 0, RING_BITS);
    dma_channel_set_write_addr(ch_log, boot_log, false);
    boot_logging = true;
    boot_armed = true;
}

// GPIO overrides for core 1's IN handling: OUTOVER = drive low (0b10) is one
// atomic set of bit 13; clearing it hands the pin back to its PIO.
#define FORCE_LOW (1u << (IO_BANK0_GPIO0_CTRL_OUTOVER_LSB + 1))
static inline void force_low(uint gpio) { hw_set_bits(&io_bank0_hw->io[gpio].ctrl, FORCE_LOW); }
static inline void release(uint gpio) { hw_clear_bits(&io_bank0_hw->io[gpio].ctrl, FORCE_LOW); }

#define IORD_MASK (1u << 17)
#define IO_TIMEOUT_US 2   // a real IN holds nIORD low about 0.75 us

// An IN is in progress (nIORD low). Read the port through U1; for 0Eh/0Fh put
// the reply on MD (io_drive) and U3 on until the strobe ends.
static void __not_in_flash_func(handle_in)(void) {
    uint32_t t0c = m33_hw->dwt_cyccnt;
    io_ins++;
    force_low(PIN_NAEN_LO);                   // U1: A7..A0 onto MD
    busy_wait_at_least_cycles(8);             // ~32 ns: U1 enable plus margin
    uint port = sio_hw->gpio_in & 0xff;
    release(PIN_NAEN_LO);
    if ((port & 0xfe) == 0x0e) {
        uint8_t reply;
        if (port & 1) {
            reply = io_status;
        } else if ((int32_t)(txq_head - txq_tail) > 0) {
            reply = txq[txq_tail % TXQ_N];
            txq_tail++;
        } else {
            reply = 0x00;
        }
        pio_serve->txf[sm_iodrv] = reply;     // io_drive: onto MD
        busy_wait_at_least_cycles(4);
        force_low(PIN_NDATA_OE);              // U3: MD onto the Z80's data bus
        io_in_ours++;
        uint32_t dt = m33_hw->dwt_cyccnt - t0c;
        if (dt > respond_max) respond_max = dt;
        if (!(port & 1)) {
            trace('I', reply);
        } else if (reply != trace_last_status) {
            trace('F', reply);
            trace_last_status = reply;
        }
    }
    // Wait for the strobe to end, with a timeout so U3 can never stay on.
    uint32_t t0 = timer_hw->timerawl;
    while (!(sio_hw->gpio_in & IORD_MASK)) {
        if (timer_hw->timerawl - t0 > IO_TIMEOUT_US) { io_in_late++; break; }
    }
    release(PIN_NDATA_OE);
}

// A falling edge on nIORD interrupts core 1 wherever its loop is (polling left
// gaps of up to 370 ns, too many for an IN's 600 ns). Edges only, so a line held
// low in reset is never taken for INs; and never while the 2068 is held.
#define IORD_EDGE_FALL (1u << ((17 % 8) * 4 + 2))
static void __not_in_flash_func(iord_isr)(void) {
    io_bank0_hw->intr[17 / 8] = IORD_EDGE_FALL;
    if (in_handling && !held_2068) handle_in();
}

static void __not_in_flash_func(core1_main)(void) {
    m33_hw->demcr |= M33_DEMCR_TRCENA_BITS;
    m33_hw->dwt_ctrl |= M33_DWT_CTRL_CYCCNTENA_BITS;
    io_bank0_hw->intr[17 / 8] = IORD_EDGE_FALL;
    gpio_set_irq_enabled(17, GPIO_IRQ_EDGE_FALL, true);   // for this core
    irq_set_exclusive_handler(IO_IRQ_BANK0, iord_isr);
    irq_set_priority(IO_IRQ_BANK0, 0);
    irq_set_enabled(IO_IRQ_BANK0, true);
    for (;;) {
        if (io_stats_reset) {
            poll_gap_max = respond_max = 0;
            io_stats_reset = false;
        }

        // I/O writes: the bank shadow, and OUTs to 0Eh/0Fh.
        if (!pio_sm_is_rx_fifo_empty(pio_addr, sm_snoop)) {
            uint32_t w = pio_addr->rxf[sm_snoop];
            uint port = (w >> 8) & 0xff, data = w & 0xff;
            io_writes++;
            uint32_t pos = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
            iolog[iolog_n % IOLOG_N] = w & 0xffff;
            iolog_pos[iolog_n % IOLOG_N] = pos;
            iolog_n++;
            if (snap_armed && port == 0xfe && (sh_ff & 0x80) && sh_hsr) {
                snap_armed = false;
                snap_trig = pos;
                side_frozen = false;
                snap_waiting = true;
            }
            bool changed = false;
            if (port == 0xf4) { changed = sh_hsr != data; sh_hsr = (uint8_t)data; f4_writes++; }
            if (port == 0xff) { changed = (sh_ff ^ data) & 0x80; sh_ff = (uint8_t)data; ff_writes++; }
            if (changed) write_table();
            if ((port & 0xfe) == 0x0e) {
                io_status = 0x00;             // busy until the firmware answers
                io_outs_ours++;
                trace(port & 1 ? 'S' : 'O', (uint8_t)data);
                if (echo_mode) {
                    if (port == 0x0e) {
                        txq[txq_head % TXQ_N] = (uint8_t)data;
                        txq_head++;
                    }
                    io_status = 0xff;
                } else if (rxq_head - rxq_tail < RXQ_N) {
                    rxq[rxq_head % RXQ_N] = (uint16_t)((port & 1) << 8 | data);
                    __dmb();
                    rxq_head++;
                } else {
                    rxq_lost++;
                }
            }
            continue;
        }
        // Memory writes: into the DOCK image when the shadow maps the chunk to
        // the dock. The Z80 may read the byte back about a microsecond later.
        if (!pio_sm_is_rx_fifo_empty(pio_addr, sm_write)) {
            uint32_t w = pio_addr->rxf[sm_write];
            uint addr = (w >> 8) & 0xffff;
            mem_writes++;
            wlog[wlog_n % WLOG_N] = w & 0xffffff;
            wlog_pos[wlog_n % WLOG_N] = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
            wlog_n++;
            if (dock_on && ((sh_hsr >> (addr >> 13)) & 1) && !(sh_ff & 0x80)) {
                ((uint8_t *)IMAGE_REGION)[4 * addr + SLOT_DOCK] = (uint8_t)w;
                dock_writes++;
            }
            continue;
        }
        if (snap_waiting && !boot_logging) {
            uint32_t now = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
            if (((now - snap_trig) & (LOG_N - 1)) >= SNAP_AFTER) {
                for (uint i = 0; i < LOG_N; i++) snap[i] = addr_log[(now + i) & (LOG_N - 1)];
                snap_trig = (snap_trig - now) & (LOG_N - 1);   // now an index into snap
                snap_base = now & (LOG_N - 1);
                if (!side_frozen) freeze_side_logs();
                snap_waiting = false;
                snap_ready = true;
            }
        }
        if (boot_logging && dma_hw->ch[ch_log].write_addr >= (uint32_t)&boot_log[BOOT_N]) {
            log_to_ring();
            boot_logging = false;
        }
        // Count served reads by slot from the log.
        if (!boot_logging) {
            uint32_t now = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
            if (ring_seen != now) {
                uint32_t e = addr_log[ring_seen];
                uint slot = e & 3;
                if (slot < 3) served[slot]++;
                if (snap_waiting && !side_frozen && slot == SLOT_HOME && ((e >> 2) & 0xffff) < 8) freeze_side_logs();
                ring_seen = (ring_seen + 1) & (LOG_N - 1);
            }
        }
    }
}

// ---- the TS-Pico protocol ------------------------------------------------------

// The responder (docs/PROTOCOL.md in the firmware repo, firmware 2.2.1). Core 0
// runs it from the menu loop: core 1 has already made the status busy for each
// OUT and queued the byte. Every transaction opens with a SYNC (any OUT to
// 0Fh): both queues emptied, exactly one 0x01 staged (the pre-load the ROM reads
// straight after the pre-header), status idle. Then a 10-byte pre-header; for a
// command ('B', TADDR 0-3) a body ('D', LEN, text, XOR) and one answer, after
// which the tail stages the next 0x01. Only tpi:info and tpi:nop are known so
// far; LOAD/SAVE blocks and the printer are answered RECOVERED (Report T).

#define ST_IDLE      0xff   // READY + IDLE
#define ST_MID       0xf7   // READY, transaction open
#define ST_RECOVERED 0xfb   // READY + IDLE, RECOVERED (bit 2) low
#define BODY_MAX     300
#define GIVE_UP_US   1000000u     // a half-received pre-header or body
#define TAIL_MAX_US  10000000u    // an answer nobody reads

enum { P_PRE, P_BODY, P_TAIL };
static uint p_state = P_PRE;
static uint8_t pre[10], body[BODY_MAX + 4];
static uint pre_n, body_n, body_len;
static uint32_t p_since;
static uint32_t p_syncs, p_cmds, p_gave_up, p_unsupported, p_xor_bad, p_stray;
static uint8_t p_last_pre[10], p_last_answer;
static char p_last_cmd[48];

static void tx_put(uint8_t b) {
    txq[txq_head % TXQ_N] = b;
    __dmb();
    txq_head++;
}

static void set_status(uint8_t st) {
    __dmb();   // queued bytes first: the Z80 reads 0Eh the moment it sees READY
    io_status = st;
}

// Empty both queues, stage one 0x01, and say idle (or recovered).
static void to_idle(bool recovered) {
    uint32_t t;
    do {
        t = txq_tail;
        txq_head = t;
    } while (txq_tail != t);
    rxq_tail = rxq_head;
    tx_put(0x01);
    pre_n = 0;
    p_state = P_PRE;
    set_status(recovered ? ST_RECOVERED : ST_IDLE);
}

static void answer(const uint8_t *b, uint n) {
    for (uint i = 0; i < n; i++) tx_put(b[i]);
    p_last_answer = b[0];
    set_status(ST_IDLE);
    p_state = P_TAIL;
    p_since = time_us_32();
}

// Response function $81: print the text, then status st.
static void answer_text(uint8_t st, const char *text) {
    static uint8_t b[256];
    uint n = 0;
    b[n++] = 0x81;
    b[n++] = st;
    b[n++] = 0x0d;
    while (*text && n < sizeof b - 1) b[n++] = (uint8_t)*text++;
    b[n++] = 0x00;
    answer(b, n);
}

static void run_command(void) {
    uint len = body[1] | body[2] << 8;
    uint8_t x = 0;
    for (uint i = 0; i < 3 + len; i++) x ^= body[i];
    // The command word, upper-cased, up to the first space (as the firmware).
    uint n = 0;
    for (; n < len && n < sizeof p_last_cmd - 1 && body[3 + n] != ' '; n++) {
        char c = (char)body[3 + n];
        p_last_cmd[n] = c >= 'a' && c <= 'z' ? c - 32 : c;
    }
    p_last_cmd[n] = 0;
    p_cmds++;
    if (body[0] != 'D' || len + 4 != body_len || x != body[3 + len]) {
        p_xor_bad++;
        uint8_t st = 2;   // Report R
        answer(&st, 1);
        return;
    }
    static char msg[200];
    if (pre[1] != 0) {
        // LOAD "tpi:name": mounting; there are no files yet.
        snprintf(msg, sizeof msg, "TS-Pico v3: no files yet\r(%s)", p_last_cmd);
        answer_text(3, msg);   // Report F
    } else if (strcmp(p_last_cmd, "TPI:NOP") == 0) {
        uint8_t st = 1;
        answer(&st, 1);
    } else if (strcmp(p_last_cmd, "TPI:INFO") == 0) {
        snprintf(msg, sizeof msg,
                 "TS-Pico v3 card, RP2350B\r"
                 "Clock %lu MHz\r"
                 "ROM %s, from the card\r"
                 "Bring-up responder: tpi:info\r"
                 "and tpi:nop so far",
                 clock_get_hz(clk_sys) / 1000000, tspico_rom ? "TS-Pico 2.2" : "stock 2068");
        answer_text(1, msg);
    } else {
        snprintf(msg, sizeof msg, "TS-Pico v3: %.24s\ris not here yet", p_last_cmd);
        answer_text(5, msg);   // Report C, as an unknown command
    }
}

static void pre_done(void) {
    memcpy(p_last_pre, pre, sizeof pre);
    uint len = pre[7] | pre[8] << 8;
    if (pre[0] == 'B' && pre[1] <= 3 && len <= BODY_MAX) {
        body_len = len + 4;
        body_n = 0;
        p_state = P_BODY;
        p_since = time_us_32();
        set_status(ST_MID);   // ready for the body
    } else {
        p_unsupported++;
        to_idle(true);
    }
}

static void proto_poll(void) {
    if (echo_mode) return;
    while (rxq_tail != rxq_head) {
        uint16_t w = rxq[rxq_tail % RXQ_N];
        rxq_tail++;
        if (w & 0x100) {          // any OUT to 0Fh: SYNC / abort
            p_syncs++;
            to_idle(false);
            continue;
        }
        uint8_t b = (uint8_t)w;
        p_since = time_us_32();
        if (p_state == P_PRE) {
            pre[pre_n++] = b;
            if (pre_n == sizeof pre) pre_done();
        } else if (p_state == P_BODY) {
            body[body_n++] = b;
            if (body_n == body_len) run_command();
        } else {
            p_stray++;            // a byte while the answer is out (key replies: not yet)
        }
    }
    uint32_t idle = time_us_32() - p_since;
    if ((p_state == P_PRE && pre_n > 0 && idle > GIVE_UP_US) || (p_state == P_BODY && idle > GIVE_UP_US)) {
        p_gave_up++;
        to_idle(true);
    } else if (p_state == P_TAIL) {
        if (txq_head == txq_tail) {   // the Z80 has read the answer: stage the next pre-load
            tx_put(0x01);
            pre_n = 0;
            p_state = P_PRE;
            set_status(ST_IDLE);
        } else if (idle > TAIL_MAX_US) {
            p_gave_up++;
            to_idle(true);
        }
    }
}

static void print_trace(uint n) {
    uint32_t end = trace_n, first = end > n ? end - n : 0;
    if (end - first > TRACE_N) first = end - TRACE_N;
    printf("  protocol trace, %lu events (O OUT 0Eh, S OUT 0Fh, I IN 0Eh, F status read when it changed;\n"
           "  +us since the previous event):\n",
           end);
    for (uint32_t i = first, col = 0; i < end; i++, col++) {
        uint32_t k = i % TRACE_N, dt = i ? trace_t[k] - trace_t[(i - 1) % TRACE_N] : 0;
        printf("%s %c%02x+%lu", col % 8 ? "" : "\n ", trace_v[k] >> 8, trace_v[k] & 0xff, dt);
    }
    printf("\n");
}

static void print_proto(void) {
    static const char *const names[] = {"pre-header", "body", "answer out"};
    printf("  protocol %s: state %s, status %02x, TX %ld, RX %lu (lost %lu)\n", echo_mode ? "off (echo mode)" : "on",
           names[p_state], io_status, (long)(txq_head - txq_tail), rxq_head - rxq_tail, rxq_lost);
    printf("  SYNCs %lu, commands %lu (bad XOR %lu), unsupported %lu, gave up %lu, stray bytes %lu\n", p_syncs, p_cmds,
           p_xor_bad, p_unsupported, p_gave_up, p_stray);
    printf("  last pre-header:");
    for (uint i = 0; i < sizeof p_last_pre; i++) printf(" %02x", p_last_pre[i]);
    printf("; last command %s, answer %02x\n", p_last_cmd[0] ? p_last_cmd : "-", p_last_answer);
}

// ---- reports ------------------------------------------------------------------

static char tag_for(uint32_t p) {
    if ((p >> 18) != IMAGE_PREFIX) return '!';
    uint slot = p & 3;
    return slot == SLOT_HOME ? 'H' : slot == SLOT_EXROM ? 'E' : slot == SLOT_DOCK ? 'D' : '?';
}

static void print_entry(uint32_t p) {
    const uint8_t *img = (const uint8_t *)IMAGE_REGION;
    if (p == 0xffffffffu) printf("  ----   ");
    else printf(" %04lx%c %02x", (p >> 2) & 0xffff, tag_for(p), img[p & 0x3ffff]);
}

static void print_addresses(void) {
    uint32_t next = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
    printf("  last 32 reads the card took (address, slot, byte):\n");
    for (int k = 32; k >= 1; k--) {
        if (k % 8 == 0) printf("  ");
        print_entry(addr_log[(next - k) & (LOG_N - 1)]);
        if (k % 8 == 1) printf("\n");
    }
}

static void print_boot(uint start) {
    if (!boot_armed) {
        printf("  the 2068 has not been released yet ('g')\n");
        return;
    }
    uint logged = boot_logging ? (dma_hw->ch[ch_log].write_addr - (uint32_t)boot_log) / 4 : BOOT_N;
    if (start >= logged) {
        printf("  %u reads logged since the last release\n", logged);
        return;
    }
    uint end = start + 64 < logged ? start + 64 : logged;
    printf("  reads %u-%u the card took after the last release ('b %u' for more):\n", start, end - 1, end);
    for (uint i = start; i < end; i++) {
        if ((i - start) % 8 == 0) printf("  %4u", i);
        print_entry(boot_log[i]);
        if ((i - start) % 8 == 7 || i == end - 1) printf("\n");
    }
}

// Measures how long nIORD stays low, from core 0, for about 100 ms. Uses the
// cycle counter-free way: count polling loops between edges (each loop about
// 4 cycles; calibrated against the microsecond timer).
static void measure_iord(void) {
    static uint32_t hist[8];   // < 0.5, 0.5-1, 1-2, 2-4, 4-8, 8-16, 16-32, >= 32 us
    memset(hist, 0, sizeof hist);
    uint32_t pulses = 0, longest = 0;
    uint32_t t_end = timer_hw->timerawl + 100000;
    uint32_t loops_total = 0, t_start = timer_hw->timerawl;
    while ((int32_t)(timer_hw->timerawl - t_end) < 0) {
        uint32_t n = 0;
        while ((sio_hw->gpio_in & (1u << 17)) && n < 10000000) n++;   // wait for low
        loops_total += n;
        n = 0;
        while (!(sio_hw->gpio_in & (1u << 17)) && n < 10000000) n++;  // time the low
        loops_total += n;
        pulses++;
        if (n > longest) longest = n;
        hist[n < 8 ? 0 : n < 16 ? 1 : n < 32 ? 2 : n < 64 ? 3 : n < 128 ? 4 : n < 256 ? 5 : n < 512 ? 6 : 7]++;
    }
    uint32_t us = timer_hw->timerawl - t_start;
    printf("  nIORD low pulses in %lu us: %lu (poll loops are about %lu ns each; buckets assume 62.5 ns)\n", us, pulses,
           loops_total ? (uint32_t)((uint64_t)us * 1000 / loops_total) : 0);
    printf("   <0.5us %lu  0.5-1 %lu  1-2 %lu  2-4 %lu  4-8 %lu  8-16 %lu  16-32 %lu  >=32 %lu   longest %lu loops\n",
           hist[0], hist[1], hist[2], hist[3], hist[4], hist[5], hist[6], hist[7], longest);
}

static void print_io(void) {
    printf("  ports 0Eh/0Fh: INs seen %lu, answered %lu (late %lu); OUTs %lu; status %02x; queue %lu; echo %s\n",
           io_ins, io_in_ours, io_in_late, io_outs_ours, io_status, txq_head - txq_tail, echo_mode ? "on" : "off");
    uint hz = clock_get_hz(clk_sys) / 1000000;
    printf("  core 1: worst time from entering the IN handler to U3 on: %lu ns ('o 0' resets)\n",
           respond_max * 1000 / hz);
}

static void print_banks(void) {
    uint hsr = sh_hsr, ff = sh_ff;
    printf("  shadow: F4h (HSR) = %02x, FFh = %02x; chunk table:", hsr, ff);
    for (uint c = 0; c < 8; c++) {
        uint t = chunk_target(c, hsr, ff);
        printf(" %c", t == serve_offset_path_h ? 'H' : t == serve_offset_path_e ? 'E' : t == serve_offset_path_d ? 'D' : '-');
    }
    printf("\n  I/O writes %lu (F4h %lu, FFh %lu), table rewrites %lu\n", io_writes, f4_writes, ff_writes,
           table_updates);
    printf("  memory writes %lu, into the DOCK image %lu\n", mem_writes, dock_writes);
    printf("  last I/O writes (port:data), oldest first:\n   ");
    uint n = iolog_n, first = n > IOLOG_N ? n - IOLOG_N : 0;
    for (uint i = first; i < n; i++) printf(" %02lx:%02lx", (iolog[i % IOLOG_N] >> 8) & 0xff, iolog[i % IOLOG_N] & 0xff);
    printf("\n");
}

static void print_stats(uint32_t *last, absolute_time_t *since) {
    uint32_t now[3];
    for (int i = 0; i < 3; i++) now[i] = served[i];
    double s = absolute_time_diff_us(*since, get_absolute_time()) / 1e6;
    *since = get_absolute_time();
    printf("  %.2f s: reads taken by the card: HOME %lu  EXROM %lu  DOCK %lu   (%s)   serve pc %u  addr pc %u\n", s,
           now[0] - last[0], now[1] - last[1], now[2] - last[2], serving ? "serving" : "shadow",
           pio_sm_get_pc(pio_serve, sm_serve), pio_sm_get_pc(pio_addr, sm_addr) - off_addr);
    for (int i = 0; i < 3; i++) last[i] = now[i];
}

// ---- 2068 reset ---------------------------------------------------------------

static void hold_2068(bool hold) {
    if (!hold && held_2068) {
        log_boot();
        // The SCLD powers up with both registers clear; assume that.
        sh_hsr = sh_ff = 0;
        io_writes = f4_writes = ff_writes = 0;
        iolog_n = 0;
        mem_writes = dock_writes = 0;
        write_table();
        if (!echo_mode) to_idle(false);   // as the Pico at power-up: one 0x01 staged
        trace_n = 0;
        trace_last_status = 0x100;
    }
    held_2068 = hold;
    gpio_put(PIN_RESET_HOLD, hold);
    gpio_set_dir(PIN_RESET_HOLD, GPIO_OUT);
}

static void help(void) {
    printf("\nTS-Pico v3 bus test (bank shadow, early /BE). Shadow mode until 'e 1'.\n"
           "  g / h / r   release the 2068, hold it in reset, reset it (200 ms)\n"
           "  s / w       reads the card took, since the last 's' / every second until a key\n"
           "  o           ports 0Eh/0Fh: INs, OUTs, status, reply queue\n"
           "  n [0|1]     IN handling (0 leaves every IN to the 2068)\n"
           "  t           the TS-Pico protocol responder: state, counts, last command\n"
           "  l [n]       the last n protocol events (64)\n"
           "  p [0|1]     echo mode in place of the responder: OUT 0Eh bytes come back on IN 0Eh\n"
           "  m [0|1]     ROM set: 1 TS-Pico (default), 0 stock 2068 (2068 must be held)\n"
           "  u [n]       set the status byte IN 0Fh returns (hex)\n"
           "  a           the last 32 reads the card took\n"
           "  b [n]       reads n to n+63 after the last release\n"
           "  v           bank shadow and chunk table\n"
           "  e [0|1]     serve mode: 1 asserts /BE and enables U3 (2068 must be held)\n"
           "  y [0|1]     serve EXROM-bank chunks (with /BE)\n"
           "  k [0|1]     serve DOCK-bank chunks (no /BE), and store writes to them\n"
           "  x [a b c d] delays in cycles: serve's U2 wait, serve's U1 wait, U2 hold, U1 hold\n"
           "  q [0|1]     input synchroniser bypass on MD and the strobes\n"
           "  ?           this help\n"
           "Clock %lu MHz.\n",
           clock_get_hz(clk_sys) / 1000000);
}

static int read_line(char *buf, int len) {
    int n = 0;
    for (;;) {
        proto_poll();
        int c = getchar_timeout_us(0);
        if (c == PICO_ERROR_TIMEOUT) continue;
        if (c == '\r' || c == '\n') {
            if (n == 0) continue;
            printf("\n");
            buf[n] = 0;
            return n;
        }
        if ((c == 8 || c == 127) && n > 0) {
            n--;
            printf("\b \b");
        } else if (c >= 32 && c < 127 && n < len - 1) {
            buf[n++] = (char)c;
            putchar(c);
        }
    }
}

static void __no_inline_not_in_flash_func(set_flash_clkdiv)(uint div) {
    qmi_hw->m[0].timing = (qmi_hw->m[0].timing & ~QMI_M0_TIMING_CLKDIV_BITS) | (div << QMI_M0_TIMING_CLKDIV_LSB);
}

int main(void) {
    board_safe_init();   // 2068 held in reset (RESET_HOLD floating, R1 pull-up)
    set_flash_clkdiv(3);
    vreg_set_voltage(VREG_VOLTAGE_1_20);
    sleep_ms(2);
    set_sys_clock_khz(BUS_CLOCK_KHZ, true);

    iox_init();
    led_set(true);
    stdio_init_all();

    busctrl_hw->priority = BUSCTRL_BUS_PRIORITY_DMA_W_BITS | BUSCTRL_BUS_PRIORITY_DMA_R_BITS;
    load_images();
    to_idle(false);
    bus_start();
    hold_2068(true);
    multicore_launch_core1(core1_main);

    while (!stdio_usb_connected()) sleep_ms(50);
    sleep_ms(200);
    help();
    printf("The 2068 is held in reset. 'g' to release it.\n");

    uint32_t last[3] = {0};
    absolute_time_t since = get_absolute_time();
    char line[40];
    for (;;) {
        printf("> ");
        read_line(line, sizeof line);
        uint v;
        switch (line[0]) {
        case 'g': hold_2068(false); printf("  2068 running.\n"); break;
        case 'h': hold_2068(true); printf("  2068 held in reset.\n"); break;
        case 'r':
            hold_2068(true);
            sleep_ms(200);
            hold_2068(false);
            printf("  2068 reset.\n");
            break;
        case 's': print_stats(last, &since); break;
        case 'w':
            printf("  any key stops\n");
            while (getchar_timeout_us(0) < 0) {
                for (absolute_time_t t = make_timeout_time_ms(1000); !time_reached(t);) proto_poll();
                print_stats(last, &since);
            }
            break;
        case 'o':
            if (sscanf(line + 1, "%u", &v) == 1 && v == 0) io_stats_reset = true;
            print_io();
            break;
        case 'i': measure_iord(); break;
        case 'n':
            if (sscanf(line + 1, "%u", &v) == 1) in_handling = v != 0;
            printf("  IN handling %s\n", in_handling ? "on" : "off: every IN left to the 2068");
            break;
        case 'p':
            if (sscanf(line + 1, "%u", &v) == 1) {
                echo_mode = v != 0;
                if (!echo_mode) to_idle(false);
            }
            print_io();
            break;
        case 't': print_proto(); break;
        case 'z':
            snap_ready = snap_waiting = false;
            snap_armed = true;
            printf("  armed: the next beep with the EXROM paged in\n");
            break;
        case 'Z':
            if (!snap_ready) {
                printf("  no snapshot (%s)\n", snap_armed ? "armed" : snap_waiting ? "filling" : "not armed");
                break;
            }
            printf("SNAP %lu %lu\n", snap_trig, snap_base);
            for (uint i = 0; i < LOG_N; i++) printf("%08lx%c", snap[i], i % 8 == 7 ? '\n' : ' ');
            printf("IO");
            for (uint32_t i = 0; i < iosnap_n; i++) printf(" %04lx@%lu", iosnap[i], iosnap_pos[i]);
            printf("\nW");
            for (uint32_t i = 0; i < wsnap_n; i++) printf(" %06lx@%lu", wsnap[i], wsnap_pos[i]);
            printf("\nEND\n");
            break;
        case 'l': {
            uint n = 64;
            sscanf(line + 1, "%u", &n);
            print_trace(n);
            break;
        }
        case 'm':
            if (sscanf(line + 1, "%u", &v) == 1) {
                if (!held_2068) printf("  hold the 2068 first ('h')\n");
                else {
                    tspico_rom = v != 0;
                    load_roms();
                }
            }
            printf("  ROM set: %s\n", tspico_rom ? "TS-Pico (HOME + 16K EXROM)" : "stock 2068");
            break;
        case 'u':
            if (sscanf(line + 1, "%x", &v) == 1) io_status = (uint8_t)v;
            print_io();
            break;
        case 'a': print_addresses(); break;
        case 'b': {
            uint n = 0;
            sscanf(line + 1, "%u", &n);
            print_boot(n);
            break;
        }
        case 'v': print_banks(); break;
        case 'e':
            if (sscanf(line + 1, "%u", &v) == 1) {
                if (!held_2068) printf("  hold the 2068 first ('h')\n");
                else set_serving(v != 0);
            }
            printf("  %s\n", serving ? "SERVE: /BE and U3 live" : "shadow: the card follows reads but never drives the 2068");
            break;
        case 'y':
            if (sscanf(line + 1, "%u", &v) == 1) {
                exrom_on = v != 0;
                write_table();
            }
            printf("  EXROM-bank chunks %s\n", exrom_on ? "served (with /BE)" : "left to the 2068");
            break;
        case 'k':
            if (sscanf(line + 1, "%u", &v) == 1) {
                dock_on = v != 0;
                write_table();
            }
            printf("  DOCK-bank chunks %s\n", dock_on ? "served (no /BE), writes stored" : "left alone");
            break;
        case 'x': {
            uint a, b, c, d;
            if (sscanf(line + 1, "%u %u %u %u", &a, &b, &c, &d) == 4) {
                d_hi = a;
                d_lo = b;
                hold_hi = c;
                hold_lo = d;
                set_delays();
            }
            printf("  serve waits %u then %u cycles; U2 held %u, U1 held %u (loop counts)\n", d_hi, d_lo, hold_hi,
                   hold_lo);
            break;
        }
        case 'q':
            if (sscanf(line + 1, "%u", &v) == 1) set_sync_bypass(v != 0);
            printf("  input synchroniser bypass %s\n", sync_bypass ? "on" : "off");
            break;
        default: help(); break;
        }
    }
}
