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
 *    analyser: FRONT (GP43, J3.3) strobe seen to address captured, DMA (GP42,
 *    J3.4) pointer pushed to byte on MD, SERVE (GP41, J3.5) the cycle would be
 *    served, BE (GP34, J3.6) /BE would be asserted. Remove the OLED from J3.
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
#define PIN_MARK_DMA   42
#define PIN_MARK_SERVE 41
#define PIN_MARK_BE    34

static const PIO pio_decide = pio0, pio_fetch = pio1, pio_mark = pio2;
static uint sm_decide, sm_fetch, off_decide, off_fetch;
static int ch_ptr, ch_data;

// When both programs sample /ROSCS and /EXROM, in PIO cycles after the strobe
// is seen. 14 is the earliest bus_fetch can (it reads the address first).
#define SETTLE_MIN 14
#define SETTLE_MAX 34
static uint settle = SETTLE_MIN;

static volatile uint32_t counts[4];

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
    if (cycles < SETTLE_MIN) cycles = SETTLE_MIN;
    if (cycles > SETTLE_MAX) cycles = SETTLE_MAX;
    settle = cycles;
    // Instruction counts before each program's `mov osr, pins` (see bus.pio).
    pio_fetch->instr_mem[off_fetch + bus_fetch_offset_class_settle] = pio_encode_set(pio_y, cycles - 14);
    pio_decide->instr_mem[off_decide + bus_decide_offset_decide_settle] = pio_encode_set(pio_y, cycles - 3);
}

static void start_marker(const pio_program_t *prog, pio_sm_config (*get_config)(uint), uint pin) {
    uint sm = pio_claim_unused_sm(pio_mark, true);
    uint off = pio_add_program(pio_mark, prog);
    pio_sm_config c = get_config(off);
    sm_config_set_set_pins(&c, pin, 1);
    pio_sm_set_pins_with_mask64(pio_mark, sm, 0, 1ull << pin);
    pio_sm_set_pindirs_with_mask64(pio_mark, sm, 1ull << pin, 1ull << pin);
    pio_gpio_init(pio_mark, pin);
    pio_sm_init(pio_mark, sm, off, &c);
    pio_sm_set_enabled(pio_mark, sm, true);
}

static void bus_start(void) {
    pio_set_gpio_base(pio_decide, 0);
    pio_set_gpio_base(pio_fetch, 0);
    pio_set_gpio_base(pio_mark, 16);

    // Markers first, with their flags clear.
    pio_mark->irq = 0xff;
    start_marker(&marker_front_program, marker_front_program_get_default_config, PIN_MARK_FRONT);
    start_marker(&marker_dma_program, marker_dma_program_get_default_config, PIN_MARK_DMA);
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

    set_settle(settle);

    // DMA: ch_ptr takes each pointer from bus_fetch's RX FIFO and writes it to
    // ch_data's read-address trigger; ch_data copies that one byte into
    // bus_fetch's TX FIFO. ch_ptr runs endlessly.
    ch_ptr = dma_claim_unused_channel(true);
    ch_data = dma_claim_unused_channel(true);

    dma_channel_config d = dma_channel_get_default_config(ch_data);
    channel_config_set_transfer_data_size(&d, DMA_SIZE_8);
    channel_config_set_read_increment(&d, false);
    channel_config_set_write_increment(&d, false);
    channel_config_set_high_priority(&d, true);
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
    pio_sm_set_enabled(pio_fetch, sm_fetch, true);
}

// ---- statistics (core 1) ----------------------------------------------------

static void core1_main(void) {
    for (;;) {
        if (!pio_sm_is_rx_fifo_empty(pio_decide, sm_decide)) counts[pio_decide->rxf[sm_decide] & 3]++;
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
           "  t [n]    show or set when /ROSCS and /EXROM are sampled: %d-%d PIO cycles (6.67 ns) after the strobe\n"
           "  ?        this help\n"
           "Markers on J3: FRONT pin 3, DMA pin 4, SERVE pin 5, BE pin 6. Settle now %u cycles (%u ns).\n",
           SETTLE_MIN, SETTLE_MAX, settle, settle * 1000 / (clock_get_hz(clk_sys) / 1000000));
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
        case 'w':
            printf("  any key stops\n");
            while (getchar_timeout_us(0) < 0) {
                sleep_ms(1000);
                print_stats(last, &since);
            }
            break;
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
