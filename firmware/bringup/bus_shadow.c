/*
 * TS-Pico v3 bus shadow test: phase 1, step 2 of docs/v3-firmware-port-plan.md.
 *
 * With the card in a TS2068 (or its expansion bus), this runs the whole
 * served-memory-read path on every Z80 memory read without driving the 2068:
 *
 *  - bus_fetch (PIO1) reads the address through the U1/U2 byte mux, adds the
 *    cycle class from /ROSCS and /EXROM, and pushes a pointer into the byte
 *    images; a two-channel DMA chain returns the byte, which goes onto MD.
 *    U3 (nDATA_OE) stays off, so MD never reaches the 2068's data bus.
 *  - bus_decide (PIO0) applies the v2.1 HOME / EXROM / DOCK rule and reports
 *    each read to core 1, which counts them. BE_REQ stays low.
 *  - Three marker state machines (PIO2) show the timing on J3 for the logic
 *    analyser: READY (GP42, J3.4) strobe seen to byte on MD, SERVE (GP41,
 *    J3.5) the cycle would be served, BE (GP34, J3.6) /BE would be asserted.
 *    Remove the OLED from J3.
 *  - Self-timing, without an analyser: the READY marker times strobe-to-byte,
 *    so 'm' reports how soon the byte is ready.
 *  - Bank tracking: io_snoop (PIO1) reads every I/O write; core 1 keeps a
 *    shadow of ports F4h (HSR) and FFh and checks every logged read's class
 *    (from /ROSCS and /EXROM) against the class the shadow predicts ('v'). A third DMA channel logs every pointer into a
 *    ring, so 'a' shows the addresses the card captured. The first 4096 reads
 *    after each release from reset are kept separately ('b'): the Z80's start
 *    at 0000 is a known sequence, which checks address capture from cycle one.
 *
 * Serve mode ('e 1', steps 3 and 4 of the plan): bus_serve replaces bus_decide
 * and serves reads for real. HOME and EXROM reads assert /BE and enable U3;
 * DOCK reads enable U3 only, and only with DOCK serving on ('k 1'). The served
 * copies are marked so the 2068 shows who answered: the HOME ROM's copyright
 * line reads "TS-Pico v3 ROM" and the DOCK image holds "TS-PICO DOCK" at
 * 0x8000. The EXROM copy is genuine at boot ('p 1' marks it afterwards).
 *
 * The 2068 is held in reset until the 'g' command. USB serial menu: '?' for help.
 */
#include <stdio.h>
#include <string.h>

#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/structs/qmi.h"
#include "hardware/vreg.h"
#include "hardware/dma.h"
#include "hardware/pio.h"
#include "hardware/structs/busctrl.h"

#include "board.h"
#include "bus.pio.h"

extern const unsigned char rom_home[], rom_exrom[];
extern const unsigned rom_home_len, rom_exrom_len;

// 256 KB at 0x20040000, which memmap_bus.ld keeps out of the C runtime. The
// byte for (Z80 address, class) is at IMAGE_REGION + 4 * address + class.
#define IMAGE_REGION 0x20040000u
#define IMAGE_PREFIX (IMAGE_REGION >> 18)

// Classes: the pointer's low two bits are nEXROM:nROSCS; bus_decide's codes match.
#define CLASS_NONE  0
#define CLASS_EXROM 1
#define CLASS_DOCK  2
#define CLASS_HOME  3

#define PIN_MARK_READY 42
#define PIN_MARK_SERVE 41
#define PIN_MARK_BE    34

static const PIO pio_decide = pio0, pio_fetch = pio1, pio_mark = pio2;
static uint sm_decide, sm_fetch, off_decide, off_fetch, sm_snoop, off_snoop, sm_ready;
static bool snoop_loaded;
static bool sm_fetch_loaded;               // set_settle can patch bus_fetch
static bool serving;                         // bus_serve loaded in PIO0 instead of bus_decide
static bool dock_on;                         // bus_serve also answers DOCK reads
static bool early_be;                        // bus_serve asserts /BE from A15:A14 alone
static uint exrom_mode;                      // bus_serve on EXROM reads: 0 leave, 1 serve with /BE, 2 serve without /BE
static const pio_program_t *prog_pio0;
static int ch_ptr, ch_data, ch_log;

// Every pointer bus_fetch pushes, copied here by ch_log (a 16 KB DMA ring).
#define LOG_N 4096
static uint32_t addr_log[LOG_N] __attribute__((aligned(LOG_N * 4)));

// The first BOOT_N reads after each release from reset go here instead; then
// core 1 points ch_log back at the ring. BOOT_SLACK covers core 1 noticing late.
#define BOOT_N     4096
#define BOOT_SLACK 256
static uint32_t boot_log[BOOT_N + BOOT_SLACK];

// A window of the ring around the first EXROM read after each release, copied
// out by core 1: EX_PRE reads before it and EX_POST from it on.
#define EX_PRE  1024
#define EX_POST 2048
static uint32_t ex_log[EX_PRE + EX_POST];
static volatile int ex_state;      // 0 idle, 1 armed, 2 waiting for EX_POST more, 3 captured
static uint32_t ex_trigger;        // ring index of the trigger
static volatile bool boot_logging;
static bool boot_armed;   // a release has happened since power-up
static bool held_2068 = true;

// PIO cycles from enabling an address buffer to the `in pins` that samples it,
// beyond the minimum; each extra loop is one cycle. Measured on proto1 board 1
// in a 2068 (2026-10-07): a buffer needs about 20 ns from enable to a good
// sample (13 ns fails, 20 ns works for both). The defaults give 33 ns each, one
// cycle of margin: U2 at 3 + 2 cycles, U1 at 1 + 4.
static uint hi_delay = 2, lo_delay = 4;   // at 150 MHz; recomputed for BUS_CLOCK_KHZ in main()

// When both programs sample /ROSCS and /EXROM, in PIO cycles after the strobe
// is seen. bus_fetch reads the address first, so its earliest is settle_min()
// (20 with the delays above). On board 1 the boot's EXROM and DOCK counts were
// the same from 14 cycles (93 ns) to 24, so the earliest is used.
#define SETTLE_MAX 34   // bus_decide's settle loop counts at most 31
static uint settle = 20;

static uint settle_min(void) { return 14 + hi_delay + lo_delay; }

static volatile uint32_t counts[4];

// Timings in PIO cycles, collected by core 1.
#define HIST_BIN 4
#define HIST_N   64
typedef struct {
    uint32_t n, min, max;
    uint64_t sum;
    uint32_t hist[HIST_N];
} timing_t;
static timing_t t_ready;   // strobe seen to byte on MD

// Shadow of the 2068's bank registers, from io_snoop: port F4h, the HSR (one
// bit per 8K chunk, 1 = take the chunk from the cartridge bus), and port FFh
// (bit 7: 1 EXROM, 0 DOCK). Assumed 0 at each release; the SCLD keeps them
// across /RESET, so they are only right after a power-up.
static volatile uint8_t sh_hsr, sh_ff;
static volatile uint32_t io_writes, f4_writes, ff_writes;

// Every logged read's class (from the pins) checked against the shadow's.
static volatile uint32_t ring_seen;          // next addr_log index core 1 checks
static volatile uint32_t pred_checked, pred_mismatch;
static volatile bool pred_reset;
#define MISS_N 16
static struct { uint16_t addr; uint8_t cls, pred, hsr, ff; } miss[MISS_N];

static uint predict_class(uint addr) {
    if (!((sh_hsr >> (addr >> 13)) & 1)) return 3;   // HOME bank: no select (ROM or RAM)
    return (sh_ff & 0x80) ? 1 : 2;                    // EXROM or DOCK
}
static volatile bool timing_reset;

// ---- images -----------------------------------------------------------------

static void load_images(void) {
    uint8_t *r = (uint8_t *)IMAGE_REGION;
    memset(r, 0xff, 256 * 1024);

    // EXROM, mirrored across the 64K window (the 8K chip answers in whichever
    // chunk the HSR maps it to).
    for (uint a = 0; a < 0x10000; a++) {
        if (a < rom_home_len) r[4 * a + CLASS_HOME] = rom_home[a];
        r[4 * a + CLASS_EXROM] = rom_exrom[a % rom_exrom_len];
    }

    // DOCK: an empty dock reads 0xff, apart from a marker at 0x8000.
    static const char dock_mark[] = "TS-PICO DOCK";
    for (uint k = 0; k < sizeof dock_mark - 1; k++) r[4 * (0x8000 + k) + CLASS_DOCK] = (uint8_t)dock_mark[k];

    // Mark the served copy so the boot screen shows who answered: the 2068's
    // "(c) 1983 Timex Computer Corp" becomes "(c) 1983 TS-Pico v3 ROM Corp".
    static const char from[] = "Timex Computer", to[] = "TS-Pico v3 ROM";
    for (uint a = 0; a + sizeof from - 1 <= rom_home_len; a++) {
        if (memcmp(&rom_home[a], from, sizeof from - 1) == 0) {
            for (uint k = 0; k < sizeof to - 1; k++) r[4 * (a + k) + CLASS_HOME] = (uint8_t)to[k];
            break;
        }
    }
}

// ---- PIO --------------------------------------------------------------------

static void set_settle(uint cycles) {
    if (cycles < settle_min()) cycles = settle_min();
    if (cycles > SETTLE_MAX) cycles = SETTLE_MAX;
    settle = cycles;
    // Cycles before each program's `mov osr, pins` (see bus.pio).
    if (sm_fetch_loaded)
        pio_fetch->instr_mem[off_fetch + bus_fetch_offset_class_settle] = pio_encode_set(pio_y, cycles - settle_min());
    // bus_serve tests A15:A14 first, so its `mov osr, pins` comes five cycles later.
    if (serving)
        pio_decide->instr_mem[off_decide + bus_serve_offset_serve_settle] = pio_encode_set(pio_y, cycles - 8);
    else
        pio_decide->instr_mem[off_decide + bus_decide_offset_decide_settle] = pio_encode_set(pio_y, cycles - 3);
}

static void set_mux_delays(uint hi, uint lo) {
    hi_delay = hi > 15 ? 15 : hi;
    lo_delay = lo > 15 ? 15 : lo;
    pio_fetch->instr_mem[off_fetch + bus_fetch_offset_hi_delay] = pio_encode_set(pio_y, hi_delay);
    pio_fetch->instr_mem[off_fetch + bus_fetch_offset_lo_delay] = pio_encode_set(pio_y, lo_delay);
    set_settle(settle);   // the class sample moves with them
}

// Writes (or removes) "TS-PICO EXROM" at EXROM offset 0x1800, in every
// mirror; a command for after boot.
#define EXROM_MARK_AT 0x1800
static const char exrom_mark[] = "TS-PICO EXROM";
static void set_exrom_mark(bool on) {
    uint8_t *r = (uint8_t *)IMAGE_REGION;
    for (uint a = 0; a < 0x10000; a++) {
        uint off = a % rom_exrom_len;
        if (off >= EXROM_MARK_AT && off < EXROM_MARK_AT + sizeof exrom_mark - 1)
            r[4 * a + CLASS_EXROM] = on ? (uint8_t)exrom_mark[off - EXROM_MARK_AT] : rom_exrom[off];
    }
}

// Early /BE: every low-16K read asserts /BE straight from A15:A14. Only
// sensible with EXROM served with /BE ('y 1'); in the other EXROM modes the
// 2068's own EXROM would be switched off for part of the cycle.
static void set_early_be(bool on) {
    early_be = on;
    if (!serving) return;
    uint target = off_decide + (on ? bus_serve_offset_early : bus_serve_offset_settle_set);
    pio_decide->instr_mem[off_decide + bus_serve_offset_early_op] = pio_encode_jmp_not_x(target);
}

// Points bus_serve's EXROM branch at leaving the read to the 2068's own EXROM
// (0), serving it with /BE (1, as v2.1 did), or serving it without /BE (2),
// where the 2068's EXROM drives the same bytes alongside U3. On board 1, mode 1
// crashed the boot after the EXROM-to-RAM copy at 0E0Bh.
static void set_exrom(uint mode) {
    exrom_mode = mode > 2 ? 2 : mode;
    if (!serving) return;
    uint label = exrom_mode == 1 ? bus_serve_offset_be : exrom_mode == 2 ? bus_serve_offset_serve : bus_serve_offset_not_ours;
    uint target = off_decide + label;
    pio_decide->instr_mem[off_decide + bus_serve_offset_exrom_op] = pio_encode_jmp_not_y(target);
}

// Points bus_serve's DOCK branch at serving the read, or at leaving it alone.
static void set_dock(bool on) {
    dock_on = on;
    if (!serving) return;
    uint target = off_decide + (on ? bus_serve_offset_serve : bus_serve_offset_not_ours);
    pio_decide->instr_mem[off_decide + bus_serve_offset_dock_op] = pio_encode_jmp_not_y(target);
}

// U3's enable belongs to io_snoop (PIO1) in shadow mode and to bus_serve
// (PIO0) when serving; io_snoop stops while serving. Only while the 2068 is
// held, so no I/O write is in progress.
static void snoop_enable(bool on) {
    if (!snoop_loaded) return;
    pio_sm_set_enabled(pio_fetch, sm_snoop, false);
    if (!on) return;
    const uint32_t oe = 1u << PIN_NDATA_OE;
    pio_sm_set_pins_with_mask(pio_fetch, sm_snoop, oe, oe);       // U3 off
    pio_sm_set_pindirs_with_mask(pio_fetch, sm_snoop, oe, oe);
    pio_gpio_init(pio_fetch, PIN_NDATA_OE);
    pio_sm_restart(pio_fetch, sm_snoop);
    pio_sm_exec(pio_fetch, sm_snoop, pio_encode_jmp(off_snoop));
    pio_sm_set_enabled(pio_fetch, sm_snoop, true);
}

// Loads bus_decide (shadow) or bus_serve into PIO0. Only while the 2068 is held:
// no reads are happening, so nothing is half-served.
static void load_pio0(bool serve) {
    snoop_enable(false);
    pio_sm_set_enabled(pio_decide, sm_decide, false);
    if (prog_pio0) pio_remove_program(pio_decide, prog_pio0, off_decide);
    // U3 off and /BE released through the SIO while the programs change over.
    gpio_put(PIN_NDATA_OE, 1);
    gpio_put(PIN_BE_REQ, 0);
    gpio_set_function(PIN_NDATA_OE, GPIO_FUNC_SIO);
    gpio_set_function(PIN_BE_REQ, GPIO_FUNC_SIO);

    prog_pio0 = serve ? &bus_serve_program : &bus_decide_program;
    off_decide = pio_add_program(pio_decide, prog_pio0);
    pio_sm_config c = serve ? bus_serve_program_get_default_config(off_decide)
                            : bus_decide_program_get_default_config(off_decide);
    sm_config_set_in_pin_base(&c, 0);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_out_shift(&c, true, false, 32);
    if (serve) {
        const uint32_t pins = (1u << PIN_NDATA_OE) | (1u << PIN_BE_REQ);
        sm_config_set_set_pins(&c, PIN_BE_REQ, 1);
        sm_config_set_sideset_pin_base(&c, PIN_NDATA_OE);
        pio_sm_set_pins_with_mask(pio_decide, sm_decide, 1u << PIN_NDATA_OE, pins);
        pio_sm_set_pindirs_with_mask(pio_decide, sm_decide, pins, pins);
        pio_gpio_init(pio_decide, PIN_NDATA_OE);
        pio_gpio_init(pio_decide, PIN_BE_REQ);
    }
    pio_sm_init(pio_decide, sm_decide, off_decide, &c);
    pio_decide->irq = 1;   // bus_fetch's byte-ready flag, left set by shadow mode
    serving = serve;
    set_settle(settle);
    if (serve) {
        set_dock(dock_on);
        set_exrom(exrom_mode);
        set_early_be(early_be);
    } else {
        snoop_enable(true);
    }
    pio_sm_set_enabled(pio_decide, sm_decide, true);
}

static uint start_marker(const pio_program_t *prog, pio_sm_config (*get_config)(uint), uint pin) {
    uint sm = pio_claim_unused_sm(pio_mark, true);
    uint off = pio_add_program(pio_mark, prog);
    pio_sm_config c = get_config(off);
    sm_config_set_set_pins(&c, pin, 1);
    // marker_ready polls IRQ flag 3 with `mov y, status` (see bus.pio).
    if (prog == &marker_ready_program) sm_config_set_mov_status(&c, STATUS_IRQ_SET, 3);
    pio_sm_set_pins_with_mask64(pio_mark, sm, 0, 1ull << pin);
    pio_sm_set_pindirs_with_mask64(pio_mark, sm, 1ull << pin, 1ull << pin);
    pio_gpio_init(pio_mark, pin);
    pio_sm_init(pio_mark, sm, off, &c);
    pio_sm_set_enabled(pio_mark, sm, true);
    return sm;
}

static void bus_start(void) {
    pio_set_gpio_base(pio_decide, 0);
    pio_set_gpio_base(pio_fetch, 0);
    pio_set_gpio_base(pio_mark, 16);

    // Markers first, with their flags clear.
    pio_mark->irq = 0xff;
    sm_ready = start_marker(&marker_ready_program, marker_ready_program_get_default_config, PIN_MARK_READY);
    start_marker(&marker_serve_program, marker_serve_program_get_default_config, PIN_MARK_SERVE);
    start_marker(&marker_be_program, marker_be_program_get_default_config, PIN_MARK_BE);

    // PIO0: bus_decide (shadow) to start with.
    sm_decide = pio_claim_unused_sm(pio_decide, true);
    load_pio0(false);
    pio_sm_config c;

    // bus_fetch: owns MD0-MD7 and the two address-buffer enables. The enables
    // are already high (board_safe_init); keep them high through the handover.
    sm_fetch = pio_claim_unused_sm(pio_fetch, true);
    off_fetch = pio_add_program(pio_fetch, &bus_fetch_program);
    sm_fetch_loaded = true;
    c = bus_fetch_program_get_default_config(off_fetch);
    sm_config_set_in_pin_base(&c, PIN_MD0);
    sm_config_set_out_pins(&c, PIN_MD0, 8);
    sm_config_set_sideset_pin_base(&c, PIN_NAEN_LO);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_out_shift(&c, true, false, 32);
    const uint32_t enables = (1u << PIN_NAEN_LO) | (1u << PIN_NAEN_HI);
    pio_sm_set_pins_with_mask(pio_fetch, sm_fetch, enables, enables);
    pio_sm_set_pindirs_with_mask(pio_fetch, sm_fetch, enables, enables | 0xffu);
    for (uint p = PIN_MD0; p <= PIN_NAEN_HI; p++) pio_gpio_init(pio_fetch, p);
    pio_sm_init(pio_fetch, sm_fetch, off_fetch, &c);
    // X = image region prefix.
    pio_sm_put(pio_fetch, sm_fetch, IMAGE_PREFIX);
    pio_sm_exec(pio_fetch, sm_fetch, pio_encode_pull(false, true));
    pio_sm_exec(pio_fetch, sm_fetch, pio_encode_mov(pio_x, pio_osr));

    // io_snoop: every I/O write, for the bank-register shadow. Shares the
    // address-buffer enables with bus_fetch; owns U3's enable in shadow mode.
    sm_snoop = pio_claim_unused_sm(pio_fetch, true);
    off_snoop = pio_add_program(pio_fetch, &io_snoop_program);
    c = io_snoop_program_get_default_config(off_snoop);
    sm_config_set_in_pin_base(&c, PIN_MD0);
    sm_config_set_sideset_pin_base(&c, PIN_NAEN_LO);
    sm_config_set_in_shift(&c, false, true, 16);
    pio_sm_init(pio_fetch, sm_snoop, off_snoop, &c);
    snoop_loaded = true;

    set_mux_delays(hi_delay, lo_delay);

    // DMA: ch_ptr takes each pointer from bus_fetch's RX FIFO and writes it to
    // ch_data's read-address trigger; ch_data copies that one byte into
    // bus_fetch's TX FIFO. ch_ptr runs endlessly. After each byte, ch_data
    // chains to ch_log, which copies the pointer (ch_data's read address)
    // into addr_log; that is off the critical path.
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
    dma_channel_configure(ch_data, &d, &pio_fetch->txf[sm_fetch], NULL, 1, false);

    dma_channel_config p = dma_channel_get_default_config(ch_ptr);
    channel_config_set_transfer_data_size(&p, DMA_SIZE_32);
    channel_config_set_read_increment(&p, false);
    channel_config_set_write_increment(&p, false);
    channel_config_set_dreq(&p, pio_get_dreq(pio_fetch, sm_fetch, false));
    channel_config_set_high_priority(&p, true);
    dma_channel_configure(ch_ptr, &p, &dma_hw->ch[ch_data].al3_read_addr_trig, &pio_fetch->rxf[sm_fetch],
                          (DMA_CH0_TRANS_COUNT_MODE_VALUE_ENDLESS << DMA_CH0_TRANS_COUNT_MODE_LSB) | 1, true);

    snoop_enable(!serving);
    pio_sm_set_enabled(pio_fetch, sm_fetch, true);
}

// ---- statistics (core 1) ----------------------------------------------------

static void timing_add(timing_t *t, uint32_t cycles) {
    if (t->n == 0 || cycles < t->min) t->min = cycles;
    if (cycles > t->max) t->max = cycles;
    t->sum += cycles;
    t->n++;
    uint b = cycles / HIST_BIN;
    t->hist[b < HIST_N ? b : HIST_N - 1]++;
}

#define RING_BITS (DMA_CH0_CTRL_TRIG_RING_SEL_BITS | DMA_CH0_CTRL_TRIG_RING_SIZE_BITS)

static void log_to_ring(void) {
    ring_seen = 0;
    hw_write_masked(&dma_hw->ch[ch_log].al1_ctrl,
                    DMA_CH0_CTRL_TRIG_RING_SEL_BITS | (14u << DMA_CH0_CTRL_TRIG_RING_SIZE_LSB), RING_BITS);
    dma_channel_set_write_addr(ch_log, addr_log, false);
}

// Only while the 2068 is held, so ch_log is idle.
static void log_boot(void) {
    memset(boot_log, 0xff, sizeof boot_log);
    hw_write_masked(&dma_hw->ch[ch_log].al1_ctrl, 0, RING_BITS);
    dma_channel_set_write_addr(ch_log, boot_log, false);
    boot_logging = true;
    boot_armed = true;
}

// bus_decide and bus_serve push GP13-GP20: bit 0 A14, bit 1 A15, bit 6
// nROSCS, bit 7 nEXROM.
static uint class_code(uint32_t v) {
    uint sel = (v >> 6) & 3;   // nEXROM:nROSCS
    if (sel == CLASS_EXROM || sel == CLASS_DOCK) return sel;
    if (sel == CLASS_HOME && (v & 3) == 0) return CLASS_HOME;
    return CLASS_NONE;
}

static void core1_main(void) {
    for (;;) {
        if (boot_logging && dma_hw->ch[ch_log].write_addr >= (uint32_t)&boot_log[BOOT_N]) {
            log_to_ring();
            boot_logging = false;
        }
        if (ex_state == 2) {
            uint32_t now = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
            if (((now - ex_trigger) & (LOG_N - 1)) >= EX_POST) {
                for (uint i = 0; i < EX_PRE + EX_POST; i++) ex_log[i] = addr_log[(ex_trigger - EX_PRE + i) & (LOG_N - 1)];
                ex_state = 3;
            }
        }
        if (timing_reset) {
            memset(&t_ready, 0, sizeof t_ready);
            timing_reset = false;
        }
        if (pred_reset) {
            pred_checked = pred_mismatch = 0;
            pred_reset = false;
        }
        // Bank writes first, so they apply to the reads that follow them.
        while (snoop_loaded && !pio_sm_is_rx_fifo_empty(pio_fetch, sm_snoop)) {
            uint32_t w = pio_fetch->rxf[sm_snoop];
            uint port = (w >> 8) & 0xff, data = w & 0xff;
            io_writes++;
            if (port == 0xf4) { sh_hsr = (uint8_t)data; f4_writes++; }
            if (port == 0xff) { sh_ff = (uint8_t)data; ff_writes++; }
        }
        // One logged read per pass, checked against the shadow's prediction.
        if (!boot_logging && !serving) {
            uint32_t now = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
            if (ring_seen != now) {
                uint32_t p = addr_log[ring_seen];
                ring_seen = (ring_seen + 1) & (LOG_N - 1);
                uint addr = (p >> 2) & 0xffff, cls = p & 3, pred = predict_class(addr);
                pred_checked++;
                if (cls != pred) {
                    if (pred_mismatch < MISS_N) {
                        miss[pred_mismatch].addr = (uint16_t)addr;
                        miss[pred_mismatch].cls = (uint8_t)cls;
                        miss[pred_mismatch].pred = (uint8_t)pred;
                        miss[pred_mismatch].hsr = sh_hsr;
                        miss[pred_mismatch].ff = sh_ff;
                    }
                    pred_mismatch++;
                }
            }
        }
        if (!pio_sm_is_rx_fifo_empty(pio_decide, sm_decide)) {
            uint cls = class_code(pio_decide->rxf[sm_decide]);
            counts[cls]++;
            // Trigger only once the boot log is done, so ch_log is on the ring.
            if (cls == CLASS_EXROM && ex_state == 1 && !boot_logging) {
                ex_trigger = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
                ex_state = 2;
            }
        }
        // marker_ready counts three cycles per loop (bus.pio).
        if (!pio_sm_is_rx_fifo_empty(pio_mark, sm_ready)) timing_add(&t_ready, 3 * pio_mark->rxf[sm_ready]);
    }
}

static uint ns(uint32_t cycles) { return (uint)((uint64_t)cycles * 1000000000u / clock_get_hz(clk_sys)); }

static void print_timing(const char *what, const timing_t *t) {
    if (!t->n) {
        printf("  %s: no samples\n", what);
        return;
    }
    printf("  %s: %lu samples, min %u ns, avg %u ns, max %u ns\n    ", what, t->n, ns(t->min),
           ns((uint32_t)(t->sum / t->n)), ns(t->max));
    for (int b = 0; b < HIST_N; b++)
        if (t->hist[b])
            printf("%s%u:%lu ", b == HIST_N - 1 ? ">=" : "", ns(b * HIST_BIN), t->hist[b]);
    printf("\n");
}

static void print_margin(void) {
    timing_t r = t_ready;
    print_timing("strobe seen to byte on MD", &r);
    printf("  (histogram: bin start in ns : count. In normal running the shortest read\n"
           "  strobe, an M1 fetch, is 400 ns; opcode fetches need the byte well before 156 ns.)\n");
    timing_reset = true;
}

static const char *class_name(uint c) {
    static const char *const n[] = {"none", "EXROM", "DOCK", "HOME"};
    return n[c & 3];
}

static void print_banks(void) {
    uint hsr = sh_hsr, ff = sh_ff;
    printf("  shadow: F4h (HSR) = %02x, FFh = %02x -> chunks 0-7:", hsr, ff);
    for (uint c = 0; c < 8; c++)
        printf(" %c", (hsr >> c) & 1 ? ((ff & 0x80) ? 'E' : 'D') : 'H');
    printf("\n  I/O writes seen %lu (F4h %lu, FFh %lu)\n", io_writes, f4_writes, ff_writes);
    if (serving) {
        printf("  (reads are checked only in shadow mode)\n");
        return;
    }
    printf("  reads checked against the shadow: %lu, class mismatches: %lu\n", pred_checked, pred_mismatch);
    uint shown = pred_mismatch < MISS_N ? pred_mismatch : MISS_N;
    for (uint i = 0; i < shown; i++)
        printf("    %04x: pins said %s, shadow said %s (F4h %02x, FFh %02x)\n", miss[i].addr,
               class_name(miss[i].cls), class_name(miss[i].pred), miss[i].hsr, miss[i].ff);
}

static void print_addresses(void) {
    uint32_t next = (dma_hw->ch[ch_log].write_addr - (uint32_t)addr_log) / 4;
    printf("  last 32 reads, oldest first (H HOME, r RAM or other, E EXROM, D DOCK):\n  ");
    for (int k = 32; k >= 1; k--) {
        uint32_t p = addr_log[(next - k) & (LOG_N - 1)];
        uint addr = (p >> 2) & 0xffff, cls = p & 3;
        char tag = cls == CLASS_EXROM ? 'E' : cls == CLASS_DOCK ? 'D' : cls == CLASS_HOME ? (addr < 0x4000 ? 'H' : 'r') : '?';
        if ((p >> 18) != IMAGE_PREFIX) tag = '!';
        if (p == 0xffffffffu) printf("----  %s", k % 8 == 1 ? "\n  " : "");   // not written yet
        else printf("%04x%c%s", addr, tag, k % 8 == 1 ? "\n  " : " ");
    }
    printf("\n");
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
    printf("  reads %u-%u after the last release (address, class, byte served; 'b %u' for more):\n", start,
           end - 1, end);
    const uint8_t *img = (const uint8_t *)IMAGE_REGION;
    for (uint i = start; i < end; i++) {
        if ((i - start) % 8 == 0) printf("  %4u ", i);
        uint32_t p = boot_log[i];
        uint addr = (p >> 2) & 0xffff, cls = p & 3;
        char tag = cls == CLASS_EXROM ? 'E' : cls == CLASS_DOCK ? 'D' : cls == CLASS_HOME ? (addr < 0x4000 ? 'H' : 'r') : '?';
        if ((p >> 18) != IMAGE_PREFIX) printf(" %08lx!   ", p);
        else if (tag == 'r' || tag == '?') printf(" %04x%c --", addr, tag);
        else printf(" %04x%c %02x", addr, tag, img[p & 0x3ffff]);
        printf((i - start) % 8 == 7 || i == end - 1 ? "\n" : "");
    }
}

static void print_ex(int start) {
    if (ex_state != 3) {
        printf("  no EXROM capture yet (state %d)\n", ex_state);
        return;
    }
    // Indices relative to the trigger; the trigger is a few reads late (FIFO).
    int first = start < -EX_PRE ? -EX_PRE : start;
    int last = first + 64 < EX_POST ? first + 64 : EX_POST;
    printf("  reads %d to %d around the first EXROM read ('c %d' for more):\n", first, last - 1, last);
    const uint8_t *img = (const uint8_t *)IMAGE_REGION;
    for (int i = first; i < last; i++) {
        if ((i - first) % 8 == 0) printf("  %5d ", i);
        uint32_t p = ex_log[i + EX_PRE];
        uint addr = (p >> 2) & 0xffff, cls = p & 3;
        char tag = cls == CLASS_EXROM ? 'E' : cls == CLASS_DOCK ? 'D' : cls == CLASS_HOME ? (addr < 0x4000 ? 'H' : 'r') : '?';
        if (tag == 'r' || tag == '?') printf(" %04x%c --", addr, tag);
        else printf(" %04x%c %02x", addr, tag, img[p & 0x3ffff]);
        printf((i - first) % 8 == 7 || i == last - 1 ? "\n" : "");
    }
}

static void print_stats(uint32_t *last, absolute_time_t *since) {
    uint32_t now[4];
    for (int i = 0; i < 4; i++) now[i] = counts[i];
    int64_t us = absolute_time_diff_us(*since, get_absolute_time());
    *since = get_absolute_time();
    uint32_t d[4], total = 0;
    for (int i = 0; i < 4; i++) {
        d[i] = now[i] - last[i];
        total += d[i];
        last[i] = now[i];
    }
    double s = us / 1e6;
    printf("  %.2f s: %lu reads (%.0f/s)  HOME %lu  EXROM %lu  DOCK %lu  other %lu   fetch pc %u  decide pc %u\n", s,
           total, total / s, d[CLASS_HOME], d[CLASS_EXROM], d[CLASS_DOCK], d[CLASS_NONE],
           pio_sm_get_pc(pio_fetch, sm_fetch) - off_fetch, pio_sm_get_pc(pio_decide, sm_decide) - off_decide);
}

// ---- 2068 reset ---------------------------------------------------------------

static void hold_2068(bool hold) {
    if (!hold && held_2068) {
        // Releasing: record the boot from the first read, and time it fresh.
        log_boot();
        timing_reset = true;
        // The SCLD powers up with both registers clear; assume that.
        sh_hsr = sh_ff = 0;
        io_writes = f4_writes = ff_writes = 0;
        pred_reset = true;
        ex_state = 1;
    }
    held_2068 = hold;
    gpio_put(PIN_RESET_HOLD, hold);
    gpio_set_dir(PIN_RESET_HOLD, GPIO_OUT);
}

static void help(void) {
    printf("\nTS-Pico v3 bus shadow test. The card follows every 2068 memory read but never drives the bus.\n"
           "  g        release the 2068 from reset\n"
           "  h        hold the 2068 in reset\n"
           "  r        reset the 2068 (200 ms pulse)\n"
           "  s        read counts since the last 's'\n"
           "  w        read counts every second until a key is pressed\n"
           "  m        timing: strobe seen to byte on MD (then resets)\n"
           "  v [0]    bank-register shadow (ports F4h, FFh) and how well it predicts each read; 'v 0' resets\n"
           "  a        the last 32 addresses captured\n"
           "  c [n]    reads around the first EXROM read after the last release (n from -1024)\n"
           "  b [n]    reads n to n+63 after the last release from reset (default 0)\n"
           "  t [n]    show or set when /ROSCS and /EXROM are sampled, in PIO cycles (6.67 ns) after the strobe\n"
           "  e [0|1]  show or set serve mode: 1 serves HOME reads (and EXROM with 'y 1') with /BE (2068 must be held)\n"
           "  p [0|1]  mark EXROM 0x1800 with TS-PICO EXROM (after boot only)\n"
           "  y [0-2]  EXROM serving in serve mode: 0 leave to the 2068, 1 serve with /BE, 2 serve without /BE\n"
           "  z [0|1]  early /BE: assert it from A15:A14 for every low-16K read (use with 'y 1')\n"
           "  k [0|1]  show or set DOCK serving (in serve mode): 1 answers DOCK reads from the card\n"
           "  x [h l]  show or set the address-buffer delays (0-15 extra cycles); then 'r' and 'b' to check\n"
           "  ?        this help\n"
           "Markers on J3: READY pin 4, SERVE pin 5, BE pin 6. Settle now %u cycles (%u ns).\n",
           settle, settle * 1000 / (clock_get_hz(clk_sys) / 1000000));
}

static int read_line(char *buf, int len) {
    int n = 0;
    for (;;) {
        int c = getchar_timeout_us(100 * 1000);
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

// System clock for the bus programs. At 150 MHz the byte reached the Z80 too
// late for M1 opcode fetches once early /BE switched the 2068's own ROM off
// (board 1, 2026-10-07); 250 MHz makes every PIO and DMA step 40% shorter.
#define BUS_CLOCK_KHZ 250000

// Flash clock divider. Runs from RAM: it changes how flash is read.
static void __no_inline_not_in_flash_func(set_flash_clkdiv)(uint div) {
    qmi_hw->m[0].timing = (qmi_hw->m[0].timing & ~QMI_M0_TIMING_CLKDIV_BITS) | (div << QMI_M0_TIMING_CLKDIV_LSB);
}

static uint cycles_for_ns(uint ns) {
    uint64_t hz = clock_get_hz(clk_sys);
    return (uint)((ns * hz + 999999999u) / 1000000000u);
}

int main(void) {
    board_safe_init();   // 2068 held in reset (RESET_HOLD floating, R1 pull-up)

    // Keep the flash near 83 MHz, then raise the core voltage and the clock.
    set_flash_clkdiv(3);
    vreg_set_voltage(VREG_VOLTAGE_1_20);
    sleep_ms(2);
    set_sys_clock_khz(BUS_CLOCK_KHZ, true);
    // The same delays in nanoseconds as measured at 150 MHz: 33 ns from buffer
    // enable to sample (3 + hi and 1 + lo cycles), class at 133 ns.
    uint buf = cycles_for_ns(33);
    hi_delay = buf > 3 ? buf - 3 : 0;
    lo_delay = buf > 1 ? buf - 1 : 0;
    settle = cycles_for_ns(133);
    iox_init();
    led_set(true);
    stdio_init_all();

    busctrl_hw->priority = BUSCTRL_BUS_PRIORITY_DMA_W_BITS | BUSCTRL_BUS_PRIORITY_DMA_R_BITS;
    load_images();
    bus_start();
    hold_2068(true);
    multicore_launch_core1(core1_main);

    while (!stdio_usb_connected()) sleep_ms(50);
    sleep_ms(200);
    help();
    printf("The 2068 is held in reset. 'g' to release it.\n");

    uint32_t last[4] = {0};
    absolute_time_t since = get_absolute_time();
    char line[32];
    for (;;) {
        printf("> ");
        read_line(line, sizeof line);
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
        case 'm': print_margin(); break;
        case 'v': {
            uint v;
            if (sscanf(line + 1, "%u", &v) == 1 && v == 0) pred_reset = true;
            print_banks();
            break;
        }
        case 'a': print_addresses(); break;
        case 'c': {
            int n = -32;
            sscanf(line + 1, "%d", &n);
            print_ex(n);
            break;
        }
        case 'b': {
            uint n = 0;
            sscanf(line + 1, "%u", &n);
            print_boot(n);
            break;
        }
        case 'w':
            printf("  any key stops\n");
            while (getchar_timeout_us(0) < 0) {
                sleep_ms(1000);
                print_stats(last, &since);
            }
            break;
        case 'e': {
            uint v;
            if (sscanf(line + 1, "%u", &v) == 1) {
                if (!held_2068) printf("  hold the 2068 first ('h')\n");
                else load_pio0(v != 0);
            }
            printf("  %s\n", serving ? "SERVE: HOME reads come from the card (/BE asserted); see 'y' and 'k' for EXROM and DOCK"
                                    : "shadow: the card follows reads but never drives the 2068");
            break;
        }
        case 'p': {
            uint v;
            if (sscanf(line + 1, "%u", &v) == 1) set_exrom_mark(v != 0);
            printf("  EXROM 0x%04x: %s\n", EXROM_MARK_AT,
                   ((uint8_t *)IMAGE_REGION)[4 * EXROM_MARK_AT + CLASS_EXROM] == (uint8_t)exrom_mark[0] ? "marked" : "genuine");
            break;
        }
        case 'z': {
            uint v;
            if (sscanf(line + 1, "%u", &v) == 1) {
                if (!held_2068) printf("  hold the 2068 first ('h')\n");
                else set_early_be(v != 0);
            }
            printf("  early /BE %s%s\n", early_be ? "on: every low-16K read" : "off: /BE once the class is known",
                   serving ? "" : " (takes effect in serve mode)");
            break;
        }
        case 'y': {
            uint v;
            if (sscanf(line + 1, "%u", &v) == 1) set_exrom(v);
            static const char *const what[] = {"off", "on, with /BE", "on, without /BE"};
            printf("  EXROM serving %s%s\n", what[exrom_mode], serving ? "" : " (takes effect in serve mode)");
            break;
        }
        case 'k': {
            uint v;
            if (sscanf(line + 1, "%u", &v) == 1) set_dock(v != 0);
            printf("  DOCK serving %s%s\n", dock_on ? "on" : "off", serving ? "" : " (takes effect in serve mode)");
            break;
        }
        case 'x': {
            uint h, l;
            if (sscanf(line + 1, "%u %u", &h, &l) == 2) set_mux_delays(h, l);
            // Enable to sampled pin state (see bus.pio): 3 + delay cycles for U2, 1 + delay for U1.
            printf("  U2 (A15..A8) sampled %u ns after enable, U1 (A7..A0) %u ns; class at %u cycles\n",
                   (3 + hi_delay) * 1000 / (clock_get_hz(clk_sys) / 1000000),
                   (1 + lo_delay) * 1000 / (clock_get_hz(clk_sys) / 1000000), settle);
            break;
        }
        case 't': {
            uint n = 0;
            if (sscanf(line + 1, "%u", &n) == 1) set_settle(n);
            printf("  /ROSCS and /EXROM sampled %u cycles (%u ns) after the strobe is seen\n", settle,
                   settle * 1000 / (clock_get_hz(clk_sys) / 1000000));
            break;
        }
        default: help(); break;
        }
    }
}
