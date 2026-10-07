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
 *  - Four marker state machines (PIO2) show the timing on J3 for the logic
 *    analyser: FRONT (GP43, J3.3) strobe seen to address captured, READY
 *    (GP42, J3.4) strobe seen to byte on MD, SERVE (GP41, J3.5) the cycle
 *    would be served, BE (GP34, J3.6) /BE would be asserted. Remove the OLED
 *    from J3.
 *  - Self-timing, without an analyser: stopwatch_strobe (PIO1) times every
 *    read strobe and the READY marker times strobe-to-byte, so 'm' reports how
 *    early the byte is ready. A third DMA channel logs every pointer into a
 *    ring, so 'a' shows the addresses the card captured. The first 4096 reads
 *    after each release from reset are kept separately ('b'): the Z80's start
 *    at 0000 is a known sequence, which checks address capture from cycle one.
 *
 * The 2068 is held in reset until the 'g' command. USB serial menu: 'h' for help.
 */
#include <stdio.h>
#include <string.h>

#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "hardware/clocks.h"
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

#define PIN_MARK_FRONT 43
#define PIN_MARK_READY 42
#define PIN_MARK_SERVE 41
#define PIN_MARK_BE    34

static const PIO pio_decide = pio0, pio_fetch = pio1, pio_mark = pio2;
static uint sm_decide, sm_fetch, off_decide, off_fetch, sm_strobe, sm_ready;
static int ch_ptr, ch_data, ch_log;

// Every pointer bus_fetch pushes, copied here by ch_log (a 16 KB DMA ring).
#define LOG_N 4096
static uint32_t addr_log[LOG_N] __attribute__((aligned(LOG_N * 4)));

// The first BOOT_N reads after each release from reset go here instead; then
// core 1 points ch_log back at the ring. BOOT_SLACK covers core 1 noticing late.
#define BOOT_N     4096
#define BOOT_SLACK 256
static uint32_t boot_log[BOOT_N + BOOT_SLACK];
static volatile bool boot_logging;
static bool boot_armed;   // a release has happened since power-up
static bool held_2068 = true;

// PIO cycles from enabling an address buffer to the `in pins` that samples it,
// beyond the minimum; each extra loop is one cycle. Measured on proto1 board 1
// in a 2068 (2026-10-07): a buffer needs about 20 ns from enable to a good
// sample (13 ns fails, 20 ns works for both). The defaults give 33 ns each, one
// cycle of margin: U2 at 3 + 2 cycles, U1 at 1 + 4.
static uint hi_delay = 2, lo_delay = 4;

// When both programs sample /ROSCS and /EXROM, in PIO cycles after the strobe
// is seen. bus_fetch reads the address first, so its earliest is settle_min()
// (20 with the delays above). On board 1 the boot's EXROM and DOCK counts were
// the same from 14 cycles (93 ns) to 24, so the earliest is used.
#define SETTLE_MAX 34
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
static timing_t t_strobe, t_ready;   // read strobe low; strobe seen to byte on MD
static volatile bool timing_reset;

// ---- images -----------------------------------------------------------------

static void load_images(void) {
    uint8_t *r = (uint8_t *)IMAGE_REGION;
    memset(r, 0xff, 256 * 1024);
    for (uint a = 0; a < 0x10000; a++) {
        if (a < rom_home_len) r[4 * a + CLASS_HOME] = rom_home[a];
        r[4 * a + CLASS_EXROM] = rom_exrom[a % rom_exrom_len];
    }
    // No cartridge: DOCK reads find 0xff.
}

// ---- PIO --------------------------------------------------------------------

static void set_settle(uint cycles) {
    if (cycles < settle_min()) cycles = settle_min();
    if (cycles > SETTLE_MAX) cycles = SETTLE_MAX;
    settle = cycles;
    // Cycles before each program's `mov osr, pins` (see bus.pio).
    pio_fetch->instr_mem[off_fetch + bus_fetch_offset_class_settle] = pio_encode_set(pio_y, cycles - settle_min());
    pio_decide->instr_mem[off_decide + bus_decide_offset_decide_settle] = pio_encode_set(pio_y, cycles - 3);
}

static void set_mux_delays(uint hi, uint lo) {
    hi_delay = hi > 15 ? 15 : hi;
    lo_delay = lo > 15 ? 15 : lo;
    pio_fetch->instr_mem[off_fetch + bus_fetch_offset_hi_delay] = pio_encode_set(pio_y, hi_delay);
    pio_fetch->instr_mem[off_fetch + bus_fetch_offset_lo_delay] = pio_encode_set(pio_y, lo_delay);
    set_settle(settle);   // the class sample moves with them
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
    start_marker(&marker_front_program, marker_front_program_get_default_config, PIN_MARK_FRONT);
    sm_ready = start_marker(&marker_ready_program, marker_ready_program_get_default_config, PIN_MARK_READY);
    start_marker(&marker_serve_program, marker_serve_program_get_default_config, PIN_MARK_SERVE);
    start_marker(&marker_be_program, marker_be_program_get_default_config, PIN_MARK_BE);

    // bus_decide: reads pins only.
    sm_decide = pio_claim_unused_sm(pio_decide, true);
    off_decide = pio_add_program(pio_decide, &bus_decide_program);
    pio_sm_config c = bus_decide_program_get_default_config(off_decide);
    sm_config_set_in_pin_base(&c, 0);
    sm_config_set_in_shift(&c, false, false, 32);
    sm_config_set_out_shift(&c, true, false, 32);
    pio_sm_init(pio_decide, sm_decide, off_decide, &c);

    // bus_fetch: owns MD0-MD7 and the two address-buffer enables. The enables
    // are already high (board_safe_init); keep them high through the handover.
    sm_fetch = pio_claim_unused_sm(pio_fetch, true);
    off_fetch = pio_add_program(pio_fetch, &bus_fetch_program);
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

    // stopwatch_strobe: times nMEMRD low.
    sm_strobe = pio_claim_unused_sm(pio_fetch, true);
    uint off_strobe = pio_add_program(pio_fetch, &stopwatch_strobe_program);
    c = stopwatch_strobe_program_get_default_config(off_strobe);
    sm_config_set_jmp_pin(&c, 15);
    pio_sm_init(pio_fetch, sm_strobe, off_strobe, &c);

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

    pio_sm_set_enabled(pio_decide, sm_decide, true);
    pio_sm_set_enabled(pio_fetch, sm_strobe, true);
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

static void core1_main(void) {
    for (;;) {
        if (boot_logging && dma_hw->ch[ch_log].write_addr >= (uint32_t)&boot_log[BOOT_N]) {
            log_to_ring();
            boot_logging = false;
        }
        if (timing_reset) {
            memset(&t_strobe, 0, sizeof t_strobe);
            memset(&t_ready, 0, sizeof t_ready);
            timing_reset = false;
        }
        if (!pio_sm_is_rx_fifo_empty(pio_decide, sm_decide)) counts[pio_decide->rxf[sm_decide] & 3]++;
        // Loop lengths in bus.pio: two cycles per strobe count, three per ready count.
        if (!pio_sm_is_rx_fifo_empty(pio_fetch, sm_strobe)) timing_add(&t_strobe, 2 * pio_fetch->rxf[sm_strobe]);
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
    timing_t s = t_strobe, r = t_ready;
    print_timing("read strobe low (nMEMRD)  ", &s);
    print_timing("strobe seen to byte on MD ", &r);
    if (s.n && r.n)
        printf("  worst case: shortest strobe - slowest byte = %d ns\n"
               "  (histograms: bin start in ns : count. The strobe ends a little after the Z80\n"
               "  samples the bus, and the data needs setup time; the analyser pins that down.)\n",
               (int)ns(s.min) - (int)ns(r.max));
    timing_reset = true;
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
           "  m        timing: strobe length, strobe-to-byte, worst-case margin (then resets)\n"
           "  a        the last 32 addresses captured\n"
           "  b [n]    reads n to n+63 after the last release from reset (default 0)\n"
           "  t [n]    show or set when /ROSCS and /EXROM are sampled, in PIO cycles (6.67 ns) after the strobe\n"
           "  x [h l]  show or set the address-buffer delays (0-15 extra cycles); then 'r' and 'b' to check\n"
           "  ?        this help\n"
           "Markers on J3: FRONT pin 3, READY pin 4, SERVE pin 5, BE pin 6. Settle now %u cycles (%u ns).\n",
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

int main(void) {
    board_safe_init();   // 2068 held in reset (RESET_HOLD floating, R1 pull-up)
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
        case 'a': print_addresses(); break;
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
