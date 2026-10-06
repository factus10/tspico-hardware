/*
 * TS-Pico v3 bring-up test.
 *
 * Runs over USB serial (any terminal, 115200 or anything; it's CDC). On first
 * connect it runs every automatic test and prints a PASS/FAIL report, then
 * offers a menu for the tests that need a person to look, listen or press.
 *
 * Pins and board start-up are in board.c.
 */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "pico/stdlib.h"
#include "pico/flash.h"
#include "pico/unique_id.h"
#include "hardware/adc.h"
#include "hardware/clocks.h"
#include "hardware/flash.h"
#include "hardware/i2c.h"
#include "hardware/pwm.h"
#include "hardware/spi.h"
#include "hardware/uart.h"

#include "board.h"

static const uint SPARE_PINS[] = {26, 27, 28, 31, 33, 36, 40};

static const char *const INPUT_NAMES[] = {
    "Z80_A14", "Z80_A15", "nMEMRD", "nMEMWR", "nIORD",
    "nIOWR", "nROSCS_L", "nEXROM_L", "nINT_L", "TAPE_IN",
};

static const char *const JOY_NAMES[] = {"UP", "DOWN", "LEFT", "RIGHT", "FIRE1", "FIRE2"};

// ---- reporting --------------------------------------------------------------

static int n_pass, n_fail, n_look;

typedef enum { R_PASS, R_FAIL, R_INFO, R_LOOK, R_SKIP } result_t;

static void report(result_t r, const char *name, const char *fmt, ...) {
    static const char *const tag[] = {"PASS", "FAIL", "info", "LOOK", "skip"};
    if (r == R_PASS) n_pass++;
    if (r == R_FAIL) n_fail++;
    if (r == R_LOOK) n_look++;
    printf("  [%s] %-10s ", tag[r], name);
    va_list ap;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
}

static void heading(const char *s) { printf("\n== %s\n", s); }

// ---- line input -------------------------------------------------------------

static int read_line(char *buf, int len) {
    int n = 0;
    for (;;) {
        int c = getchar_timeout_us(100 * 1000);
        if (c == PICO_ERROR_TIMEOUT) {
            if (!stdio_usb_connected()) return -1;
            continue;
        }
        if (c == '\r' || c == '\n') {
            if (n == 0) continue;
            printf("\n");
            buf[n] = 0;
            return n;
        }
        if ((c == 8 || c == 127) && n > 0) {
            n--;
            printf("\b \b");
            continue;
        }
        if (c >= 32 && c < 127 && n < len - 1) {
            buf[n++] = (char)c;
            putchar(c);
        }
    }
}

// ---- system -----------------------------------------------------------------

static void test_system(void) {
    heading("RP2350B");
    char id[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];
    pico_get_unique_board_id_string(id, sizeof id);
    // rp2350_chip_version() does not tell A3 from A4; picotool info does.
    report(R_INFO, "chip", "RP2350, %u GPIOs, unique id %s", NUM_BANK0_GPIOS, id);

    uint32_t xosc = frequency_count_khz(CLOCKS_FC0_SRC_VALUE_XOSC_CLKSRC);
    bool xosc_ok = xosc > 11940 && xosc < 12060;
    report(xosc_ok ? R_PASS : R_FAIL, "crystal", "%lu kHz (expect 12000)", xosc);

    uint32_t sys = frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLK_SYS);
    uint32_t usb = frequency_count_khz(CLOCKS_FC0_SRC_VALUE_CLK_USB);
    report(usb > 47900 && usb < 48100 ? R_PASS : R_FAIL, "clocks",
           "clk_sys %lu kHz, clk_usb %lu kHz", sys, usb);

    adc_init();
    adc_set_temp_sensor_enabled(true);
    adc_select_input(ADC_TEMPERATURE_CHANNEL_NUM);
    sleep_ms(1);
    uint32_t acc = 0;
    for (int i = 0; i < 64; i++) acc += adc_read();
    float v = (acc / 64.0f) * 3.3f / 4096.0f;
    float t = 27.0f - (v - 0.706f) / 0.001721f;
    adc_set_temp_sensor_enabled(false);
    // Assumes a 3.3 V ADC reference, so this also sanity-checks ADC_AVDD.
    report(t > 5 && t < 75 ? R_PASS : R_FAIL, "die temp", "%.1f C (sensor %.3f V)", t, v);
}

// ---- QSPI flash -------------------------------------------------------------

#define FLASH_TEST_OFFSET (PICO_FLASH_SIZE_BYTES - FLASH_SECTOR_SIZE)

typedef struct {
    uint8_t jedec[3];
    const uint8_t *data;
    int op;  // 0 = JEDEC ID, 1 = erase test sector, 2 = program test sector
} flash_job_t;

static void __no_inline_not_in_flash_func(flash_job)(void *arg) {
    flash_job_t *j = arg;
    if (j->op == 0) {
        uint8_t tx[4] = {0x9f, 0, 0, 0}, rx[4];
        flash_do_cmd(tx, rx, 4);
        memcpy(j->jedec, rx + 1, 3);
    } else if (j->op == 1) {
        flash_range_erase(FLASH_TEST_OFFSET, FLASH_SECTOR_SIZE);
    } else {
        flash_range_program(FLASH_TEST_OFFSET, j->data, FLASH_SECTOR_SIZE);
    }
}

static void test_flash(void) {
    heading("QSPI flash (U21)");
    flash_job_t j = {.op = 0};
    if (flash_safe_execute(flash_job, &j, 1000) != PICO_OK) {
        report(R_FAIL, "jedec", "flash_safe_execute failed");
        return;
    }
    const char *maker = j.jedec[0] == 0xc8 ? "GigaDevice" : j.jedec[0] == 0xef ? "Winbond" : "unknown";
    unsigned mbytes = j.jedec[2] >= 0x14 && j.jedec[2] <= 0x20 ? (1u << j.jedec[2]) >> 20 : 0;
    bool id_ok = j.jedec[0] == 0xc8 && j.jedec[1] == 0x40 && j.jedec[2] == 0x18;
    report(id_ok ? R_PASS : R_FAIL, "jedec", "%02x %02x %02x = %s, %u MB (expect c8 40 18, GD25Q128E)",
           j.jedec[0], j.jedec[1], j.jedec[2], maker, mbytes);

    static uint8_t pattern[FLASH_SECTOR_SIZE];
    uint32_t x = time_us_32() | 1;
    for (unsigned i = 0; i < sizeof pattern; i++) {
        x ^= x << 13; x ^= x >> 17; x ^= x << 5;
        pattern[i] = (uint8_t)x;
    }
    const uint8_t *mem = (const uint8_t *)(XIP_NOCACHE_NOALLOC_BASE + FLASH_TEST_OFFSET);

    j.op = 1;
    flash_safe_execute(flash_job, &j, 1000);
    j.op = 2;
    j.data = pattern;
    flash_safe_execute(flash_job, &j, 1000);
    int bad = 0;
    for (unsigned i = 0; i < sizeof pattern; i++) bad += mem[i] != pattern[i];
    j.op = 1;
    flash_safe_execute(flash_job, &j, 1000);
    int not_blank = 0;
    for (unsigned i = 0; i < sizeof pattern; i++) not_blank += mem[i] != 0xff;
    report(bad == 0 && not_blank == 0 ? R_PASS : R_FAIL, "rw",
           "last sector @ 0x%06x: program/verify %d bad bytes, erase %d not blank",
           FLASH_TEST_OFFSET, bad, not_blank);

    report(R_INFO, "psram", "U22 (APS6404L) is DNP on proto1; not tested");
}

// ---- expander ---------------------------------------------------------------

static void test_expander(void) {
    heading("I2C expander (U15, XL9555)");
    if (!iox_present) iox_init();
    if (!iox_present) {
        report(R_FAIL, "i2c", "no ACK at 0x%02x on GP24/GP25 (SDA/SCL %d/%d)",
               IOX_ADDR, gpio_get(PIN_I2C_SDA), gpio_get(PIN_I2C_SCL));
        return;
    }
    uint8_t out0 = 0, cfg0 = 0, cfg1 = 0, in1 = 0;
    bool rd = iox_read(IOX_OUT0, &out0) == 1 && iox_read(IOX_CFG0, &cfg0) == 1 &&
              iox_read(IOX_CFG1, &cfg1) == 1;
    bool ok = rd && (out0 | X_NLED) == (iox_out0 | X_NLED) && cfg0 == 0xc0 && cfg1 == 0xff;
    report(ok ? R_PASS : R_FAIL, "i2c", "ACK at 0x%02x, registers read back %s (out0 %02x cfg0 %02x cfg1 %02x)",
           IOX_ADDR, ok ? "correctly" : "WRONG", out0, cfg0, cfg1);

    iox_read(IOX_IN1, &in1);  // reading the inputs clears /INT
    sleep_us(50);
    report(gpio_get(PIN_NIOX_INT) ? R_PASS : R_FAIL, "/INT", "GP35 %s after input read",
           gpio_get(PIN_NIOX_INT) ? "high (idle)" : "LOW (stuck or not pulled up)");

    report((in1 & X_JOY_MASK) == X_JOY_MASK ? R_PASS : R_FAIL, "joystick",
           "idle inputs %02x (expect 3f: all released)", in1 & X_JOY_MASK);
    report(R_INFO, "nBUSAK_L", "%s (only meaningful in a 2068)", in1 & X_NBUSAK ? "high" : "low");
    report(R_INFO, "SD detect", "%s", in1 & X_SD_CD ? "high (no card?)" : "low (card in?)");
}

// ---- pin-level checks -------------------------------------------------------

// Drives one pin while the rest of the group sit on pulls the other way, to
// find solder bridges and pins stuck to a rail. Only for pins whose other end
// is high-impedance: MD0-MD7 with all three 245s disabled, and the spares.
static void test_pins(void) {
    heading("Pins (bridges and stuck lines)");
    if (!gpio_get_out_level(PIN_NAEN_LO) || !gpio_get_out_level(PIN_NAEN_HI) ||
        !gpio_get_out_level(PIN_NDATA_OE)) {
        report(R_FAIL, "bridges", "refusing: a local bus buffer is enabled");
        return;
    }
    uint pins[16];
    unsigned n = 0;
    for (uint p = PIN_MD0; p < PIN_MD0 + 8; p++) pins[n++] = p;
    for (unsigned i = 0; i < count_of(SPARE_PINS); i++) pins[n++] = SPARE_PINS[i];

    int faults = 0;
    for (int level = 1; level >= 0; level--) {
        // Pull-only first: every pin should follow its pull.
        for (unsigned i = 0; i < n; i++) {
            gpio_init(pins[i]);
            gpio_set_pulls(pins[i], !level, level);
        }
        sleep_us(100);
        for (unsigned i = 0; i < n; i++) {
            if (gpio_get(pins[i]) != !level) {
                printf("    GP%u stuck %s (does not follow its pull-%s)\n", pins[i],
                       level ? "high" : "low", level ? "down" : "up");
                faults++;
            }
        }
        // Then drive each one in turn against the others' pulls.
        for (unsigned i = 0; i < n; i++) {
            gpio_put(pins[i], level);
            gpio_set_dir(pins[i], GPIO_OUT);
            sleep_us(50);
            for (unsigned k = 0; k < n; k++) {
                if (k != i && gpio_get(pins[k]) == level) {
                    printf("    GP%u follows GP%u driven %s: bridged?\n", pins[k], pins[i],
                           level ? "high" : "low");
                    faults++;
                }
            }
            gpio_set_dir(pins[i], GPIO_IN);
        }
    }
    for (unsigned i = 0; i < n; i++) gpio_pull_down(pins[i]);
    report(faults ? R_FAIL : R_PASS, "bridges", "MD0-MD7 and 7 spares: %d fault%s", faults,
           faults == 1 ? "" : "s");

    report(gpio_get(PIN_RESET_HOLD) ? R_PASS : R_FAIL, "RESET_HOLD",
           "GP29 %s with the pin floating (R1 4k7 pull-up holds the 2068 in reset)",
           gpio_get(PIN_RESET_HOLD) ? "high" : "LOW");

    char line[160];
    int o = 0;
    for (uint p = PIN_Z80_A14; p <= PIN_TAPE_IN; p++)
        o += snprintf(line + o, sizeof line - o, "%s=%d ", INPUT_NAMES[p - PIN_Z80_A14], gpio_get(p));
    report(R_INFO, "bus inputs", "%s(floating without a 2068)", line);
}

// ---- SD card ----------------------------------------------------------------

static uint8_t sd_xfer(uint8_t b) {
    uint8_t r;
    spi_write_read_blocking(spi0, &b, &r, 1);
    return r;
}

static uint8_t sd_cmd(uint8_t cmd, uint32_t arg) {
    uint8_t crc = cmd == 0 ? 0x95 : cmd == 8 ? 0x87 : 0x01;
    uint8_t f[6] = {0x40 | cmd, arg >> 24, arg >> 16, arg >> 8, arg, crc};
    sd_xfer(0xff);
    spi_write_blocking(spi0, f, 6);
    for (int i = 0; i < 16; i++) {
        uint8_t r = sd_xfer(0xff);
        if (!(r & 0x80)) return r;
    }
    return 0xff;
}

static bool sd_read_data(uint8_t *buf, unsigned len) {
    absolute_time_t until = make_timeout_time_ms(200);
    uint8_t t;
    while ((t = sd_xfer(0xff)) == 0xff)
        if (time_reached(until)) return false;
    if (t != 0xfe) return false;
    uint8_t ff[512];
    memset(ff, 0xff, sizeof ff);
    spi_write_read_blocking(spi0, ff, buf, len);
    sd_xfer(0xff);  // CRC, ignored
    sd_xfer(0xff);
    return true;
}

static bool sd_read_block(uint32_t lba, bool sdhc, uint8_t *buf) {
    if (sd_cmd(17, sdhc ? lba : lba * 512) != 0) return false;
    return sd_read_data(buf, 512);
}

static void sd_deselect(void) {
    gpio_put(PIN_SD_CS, 1);
    sd_xfer(0xff);
}

static void test_sd(void) {
    heading("microSD (J2, SPI0)");
    uint8_t in1 = 0xff;
    bool cd_known = iox_present && iox_read(IOX_IN1, &in1) == 1;
    bool cd_says_card = cd_known && !(in1 & X_SD_CD);

    spi_init(spi0, 400 * 1000);
    gpio_set_function(PIN_SD_MISO, GPIO_FUNC_SPI);
    gpio_set_function(PIN_SD_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_SD_MOSI, GPIO_FUNC_SPI);
    gpio_pull_up(PIN_SD_MISO);

    gpio_put(PIN_SD_CS, 1);
    for (int i = 0; i < 10; i++) sd_xfer(0xff);
    gpio_put(PIN_SD_CS, 0);

    uint8_t r = 0xff;
    for (int i = 0; i < 10 && r != 0x01; i++) r = sd_cmd(0, 0);
    if (r != 0x01) {
        sd_deselect();
        if (cd_known && !cd_says_card)
            report(R_SKIP, "card", "no card (detect switch high, CMD0 no response). Insert one and run 'd'");
        else
            report(R_FAIL, "card", "CMD0 got %02x, expect 01 (detect switch %s)", r,
                   cd_says_card ? "says a card is in" : "unknown");
        return;
    }
    report(cd_known ? (cd_says_card ? R_PASS : R_FAIL) : R_INFO, "detect",
           cd_says_card ? "switch low with a card in" : "switch HIGH but a card answered: polarity or switch fault");

    bool v2 = false;
    uint8_t r7[4];
    if (sd_cmd(8, 0x1aa) == 0x01) {
        for (int i = 0; i < 4; i++) r7[i] = sd_xfer(0xff);
        v2 = r7[3] == 0xaa;
    }
    absolute_time_t until = make_timeout_time_ms(1500);
    do {
        sd_cmd(55, 0);
        r = sd_cmd(41, v2 ? 0x40000000 : 0);
    } while (r != 0 && !time_reached(until));
    if (r != 0) {
        sd_deselect();
        report(R_FAIL, "init", "ACMD41 never left idle (last %02x)", r);
        return;
    }
    uint8_t ocr[4] = {0};
    bool sdhc = false;
    if (sd_cmd(58, 0) == 0) {
        for (int i = 0; i < 4; i++) ocr[i] = sd_xfer(0xff);
        sdhc = ocr[0] & 0x40;
    }
    uint8_t csd[16];
    uint64_t bytes = 0;
    if (sd_cmd(9, 0) == 0 && sd_read_data(csd, 16)) {
        if ((csd[0] >> 6) == 1) {
            uint32_t c_size = ((csd[7] & 0x3f) << 16) | (csd[8] << 8) | csd[9];
            bytes = (uint64_t)(c_size + 1) * 512 * 1024;
        } else {
            uint32_t c_size = ((csd[6] & 0x03) << 10) | (csd[7] << 2) | (csd[8] >> 6);
            uint32_t mult = ((csd[9] & 0x03) << 1) | (csd[10] >> 7);
            uint32_t bl = csd[5] & 0x0f;
            bytes = (uint64_t)(c_size + 1) << (mult + 2 + bl);
        }
    }
    report(R_PASS, "init", "SD v%d %s, %llu MB, OCR %02x%02x%02x%02x", v2 ? 2 : 1,
           sdhc ? "SDHC/SDXC" : "SDSC", bytes >> 20, ocr[0], ocr[1], ocr[2], ocr[3]);

    static uint8_t b0[512], b1[512];
    if (!sd_read_block(0, sdhc, b0)) {
        sd_deselect();
        report(R_FAIL, "read", "block 0 read failed at 400 kHz");
        return;
    }
    bool mbr = b0[510] == 0x55 && b0[511] == 0xaa;
    report(R_PASS, "read", "block 0 at 400 kHz, %s", mbr ? "boot signature 55 aa present" : "no 55 aa signature (unformatted?)");

    uint actual = spi_set_baudrate(spi0, 25 * 1000 * 1000);
    absolute_time_t t0 = get_absolute_time();
    bool ok = true;
    for (uint32_t lba = 0; lba < 256 && ok; lba++) {
        ok = sd_read_block(lba, sdhc, b1);
        if (ok && lba == 0) ok = memcmp(b0, b1, 512) == 0;
    }
    int64_t us = absolute_time_diff_us(t0, get_absolute_time());
    sd_deselect();
    if (ok)
        report(R_PASS, "speed", "256 blocks at %u kHz in %lld ms (%lld KB/s), block 0 matches",
               actual / 1000, us / 1000, 128LL * 1000000 / us);
    else
        report(R_FAIL, "speed", "reads at %u kHz failed or block 0 differs", actual / 1000);
}

// ---- ESP32-C3 ---------------------------------------------------------------

static int wifi_capture(char *buf, int len, uint32_t ms) {
    int n = 0;
    absolute_time_t until = make_timeout_time_ms(ms);
    while (!time_reached(until)) {
        while (uart_is_readable(uart0)) {
            char c = uart_getc(uart0);
            if (n < len - 1) buf[n++] = c;
        }
    }
    buf[n] = 0;
    return n;
}

// Prints captured module output, folding runs of identical lines (a module
// with blank flash repeats "invalid header" until it is reset).
static void print_indented(const char *s) {
    char prev[96] = "", cur[96];
    int repeats = 0;
    while (*s) {
        int n = 0;
        for (; *s && *s != '\n'; s++) {
            if (*s == '\r') continue;
            if (n < (int)sizeof cur - 6) {
                if (*s >= 32 && *s < 127) cur[n++] = *s;
                else n += snprintf(cur + n, sizeof cur - n, "<%02x>", (uint8_t)*s);
            }
        }
        if (*s) s++;
        cur[n] = 0;
        if (n == 0) continue;
        if (strcmp(cur, prev) == 0) {
            repeats++;
            continue;
        }
        if (repeats) printf("    |   (previous line repeated %d more times)\n", repeats);
        repeats = 0;
        printf("    | %s\n", cur);
        strcpy(prev, cur);
    }
    if (repeats) printf("    |   (previous line repeated %d more times)\n", repeats);
}

static void wifi_uart_init(uint baud) {
    uart_init(uart0, baud);
    gpio_set_function(PIN_WIFI_TX, GPIO_FUNC_UART);
    gpio_set_function(PIN_WIFI_RX, GPIO_FUNC_UART);
    gpio_pull_up(PIN_WIFI_RX);
}

static void wifi_power(bool on, bool download) {
    iox_set(X_WIFI_EN, false);
    iox_set(X_WIFI_DL, download);
    if (!on) return;
    sleep_ms(50);
    while (uart_is_readable(uart0)) uart_getc(uart0);
    iox_set(X_WIFI_EN, true);
}

static void test_wifi(void) {
    heading("ESP32-C3 (U40, UART0 GP44/GP45)");
    if (!iox_present) {
        report(R_SKIP, "esp32", "needs the expander for EN and IO9");
        return;
    }
    static char buf[2048];
    wifi_uart_init(115200);  // the C3 ROM logs at 115200

    wifi_power(true, false);
    wifi_capture(buf, sizeof buf, 1500);
    bool rom = strstr(buf, "ESP-ROM") != NULL;
    report(rom ? R_PASS : R_FAIL, "boot", rom ? "ROM banner received (EN control and module TX -> GP45 work)"
                                              : "no ROM banner on GP45 after EN high");
    if (buf[0]) print_indented(buf);

    if (strstr(buf, "invalid header")) {
        report(R_INFO, "firmware", "module flash is blank: no application (Zimodem) installed yet");
    } else {
        uart_puts(uart0, "AT\r\n");
        wifi_capture(buf, sizeof buf, 500);
        if (strstr(buf, "OK"))
            report(R_PASS, "AT", "firmware answered AT at 115200 (GP44 -> module RX works)");
        else
            report(R_INFO, "AT", "no OK at 115200: the firmware may use another baud; try 'p 1200'");
        if (buf[0]) print_indented(buf);
    }

    wifi_power(true, true);
    wifi_capture(buf, sizeof buf, 800);
    bool dl = strstr(buf, "DOWNLOAD") != NULL;
    report(dl ? R_PASS : R_FAIL, "IO9 strap", dl ? "download mode entered with WIFI_DL set"
                                                 : "WIFI_DL set but the module did not enter download mode");
    if (buf[0]) print_indented(buf);

    wifi_power(false, false);
}

static void wifi_passthrough(uint baud) {
    printf("ESP32-C3 passthrough at %u baud, module booting normally. Ctrl-] to exit.\n", baud);
    wifi_uart_init(baud);
    wifi_power(true, false);
    for (;;) {
        int c = getchar_timeout_us(0);
        if (c == 0x1d) break;
        if (c >= 0) uart_putc_raw(uart0, (char)c);
        while (uart_is_readable(uart0)) putchar_raw(uart_getc(uart0));
        if (!stdio_usb_connected()) break;
    }
    wifi_power(false, false);
    printf("\nPassthrough closed, module off.\n");
}

// ---- OLED (SSD1351 on J3) ---------------------------------------------------

static void oled_cmd(uint8_t c, const uint8_t *args, int n) {
    gpio_put(PIN_OLED_CS, 0);
    gpio_put(PIN_OLED_DC, 0);
    spi_write_blocking(spi1, &c, 1);
    if (n) {
        gpio_put(PIN_OLED_DC, 1);
        spi_write_blocking(spi1, args, n);
    }
    gpio_put(PIN_OLED_CS, 1);
}

#define OLED_CMD(c, ...)                                   \
    do {                                                   \
        static const uint8_t a_[] = {0, ##__VA_ARGS__};    \
        oled_cmd(c, a_ + 1, sizeof a_ - 1);                \
    } while (0)

// ---- OLED alternative: 4-pin I2C SSD1306 128x32 on J3 -----------------------
//
// J3 pins 3 and 4 (GP43, GP42) are also I2C1 SCL and SDA. Wiring: module VCC
// to J3.1, GND to J3.2, SCL to J3.3 (DIN), SDA to J3.4 (CLK). The modules
// carry their own pull-ups.

#define PIN_OLED_I2C_SDA PIN_OLED_SCK   // GP42
#define PIN_OLED_I2C_SCL PIN_OLED_MOSI  // GP43

// 5x7 glyphs, one byte per column, bit 0 at the top.
static const struct { char c; uint8_t col[5]; } GLYPHS[] = {
    {' ', {0x00, 0x00, 0x00, 0x00, 0x00}}, {'-', {0x08, 0x08, 0x08, 0x08, 0x08}},
    {'3', {0x21, 0x41, 0x45, 0x4b, 0x31}}, {'C', {0x3e, 0x41, 0x41, 0x41, 0x22}},
    {'D', {0x7f, 0x41, 0x41, 0x22, 0x1c}}, {'E', {0x7f, 0x49, 0x49, 0x49, 0x41}},
    {'I', {0x00, 0x41, 0x7f, 0x41, 0x00}}, {'K', {0x7f, 0x08, 0x14, 0x22, 0x41}},
    {'L', {0x7f, 0x40, 0x40, 0x40, 0x40}}, {'O', {0x3e, 0x41, 0x41, 0x41, 0x3e}},
    {'P', {0x7f, 0x09, 0x09, 0x09, 0x06}}, {'S', {0x46, 0x49, 0x49, 0x49, 0x31}},
    {'T', {0x01, 0x01, 0x7f, 0x01, 0x01}}, {'V', {0x1f, 0x20, 0x40, 0x20, 0x1f}},
};

static void fb_text(uint8_t *fb, int page, const char *s) {
    int x = (128 - 6 * (int)strlen(s)) / 2;
    for (; *s; s++, x += 6)
        for (unsigned g = 0; g < count_of(GLYPHS); g++)
            if (GLYPHS[g].c == *s)
                for (int k = 0; k < 5; k++) fb[page * 128 + x + k] |= GLYPHS[g].col[k];
}

static int ssd1306_cmds(uint8_t addr, const uint8_t *cmds, int n) {
    uint8_t buf[32] = {0x00};  // control byte: commands follow
    memcpy(buf + 1, cmds, n);
    return i2c_write_timeout_us(i2c1, addr, buf, n + 1, false, 10000);
}

// Probes 0x3C and 0x3D with a NOP command; leaves I2C1 on GP42/43 if found.
static bool ssd1306_probe(uint8_t *addr) {
    gpio_put(PIN_OLED_CS, 1);
    i2c_init(i2c1, 400 * 1000);
    gpio_set_function(PIN_OLED_I2C_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_OLED_I2C_SCL, GPIO_FUNC_I2C);
    // Weak internal pull-ups keep the lines idle when nothing is plugged in.
    gpio_pull_up(PIN_OLED_I2C_SDA);
    gpio_pull_up(PIN_OLED_I2C_SCL);
    static const uint8_t nop[] = {0xe3};
    for (uint8_t a = 0x3c; a <= 0x3d; a++) {
        if (ssd1306_cmds(a, nop, 1) == 2) {
            *addr = a;
            return true;
        }
    }
    i2c_deinit(i2c1);
    gpio_set_function(PIN_OLED_I2C_SDA, GPIO_FUNC_NULL);
    gpio_set_function(PIN_OLED_I2C_SCL, GPIO_FUNC_NULL);
    return false;
}

// rows = 32: SSD1306 128x32 (0.91in). rows = 64: SSD1309 128x64 (2.42in), which
// takes its panel supply from the module's boost converter, so no charge pump.
// The two cannot be told apart over I2C, so the caller says which is fitted.
static void test_i2c_oled(uint8_t addr, int rows) {
    static const uint8_t init32[] = {
        0xae,        // display off
        0xd5, 0x80,  // clock
        0xa8, 0x1f,  // multiplex: 32 rows
        0xd3, 0x00,  // no display offset
        0x40,        // start line 0
        0x8d, 0x14,  // charge pump on
        0x20, 0x00,  // horizontal addressing
        0xa1, 0xc8,  // flip so the header is at the top
        0xda, 0x02,  // COM pins for 128x32
        0x81, 0x8f,  // contrast
        0xd9, 0xf1,  // precharge
        0xdb, 0x40,  // VCOMH
        0xa4, 0xa6,  // show RAM, not inverted
        0xaf,        // display on
    };
    static const uint8_t init64[] = {
        0xae,        // display off
        0xd5, 0xa0,  // clock
        0xa8, 0x3f,  // multiplex: 64 rows
        0xd3, 0x00,  // no display offset
        0x40,        // start line 0
        0x20, 0x00,  // horizontal addressing
        0xa1, 0xc8,  // flip so the header is at the top
        0xda, 0x12,  // COM pins for 128x64
        0x81, 0x6f,  // contrast
        0xd9, 0x82,  // precharge
        0xdb, 0x34,  // VCOMH
        0xa4, 0xa6,  // show RAM, not inverted
        0xaf,        // display on
    };
    const int pages = rows / 8;
    const uint8_t *init = rows == 64 ? init64 : init32;
    int init_len = rows == 64 ? (int)sizeof init64 : (int)sizeof init32;
    const uint8_t window[] = {0x21, 0, 127, 0x22, 0, (uint8_t)(pages - 1)};
    bool ok = ssd1306_cmds(addr, init, init_len) == init_len + 1 &&
              ssd1306_cmds(addr, window, sizeof window) == (int)sizeof window + 1;

    static uint8_t fb[1 + 1024];
    uint8_t *px = fb + 1;
    int len = 1 + pages * 128;
    memset(fb, 0, sizeof fb);
    fb[0] = 0x40;  // control byte: data follows
    for (int x = 0; x < 128; x++) {
        px[x] |= 0x01;                        // top row
        px[(pages - 1) * 128 + x] |= 0x80;    // bottom row
    }
    for (int p = 0; p < pages; p++) px[p * 128] = px[p * 128 + 127] = 0xff;
    fb_text(px, pages / 2 - 1, "TS-PICO V3");
    fb_text(px, pages / 2, "OLED OK");
    ok = ok && i2c_write_timeout_us(i2c1, addr, fb, len, false, 100000) == len;

    const char *chip = rows == 64 ? "SSD1309" : "SSD1306";
    if (ok)
        report(R_LOOK, rows == 64 ? "128x64" : "128x32",
               "%s at 0x%02x: border with TS-PICO V3 / OLED OK%s", chip, addr,
               rows == 32 ? " (a 128x64 SSD1309 needs 'o 64')" : "");
    else
        report(R_FAIL, rows == 64 ? "128x64" : "128x32", "%s at 0x%02x stopped answering", chip, addr);
}

// rows: 32 or 64 for an I2C panel; the SPI SSD1351 is used if none answers.
static void test_oled(int rows) {
    uint8_t addr;
    if (ssd1306_probe(&addr)) {
        heading(rows == 64 ? "OLED (J3, I2C SSD1309 128x64 on I2C1)" : "OLED (J3, I2C SSD1306 128x32 on I2C1)");
        test_i2c_oled(addr, rows);
        return;
    }
    heading("OLED (J3, SSD1351 128x96 on SPI1)");
    if (!iox_present) {
        report(R_SKIP, "oled", "needs the expander for reset");
        return;
    }
    spi_init(spi1, 8 * 1000 * 1000);
    gpio_set_function(PIN_OLED_SCK, GPIO_FUNC_SPI);
    gpio_set_function(PIN_OLED_MOSI, GPIO_FUNC_SPI);

    iox_set(X_NOLED_RST, false);
    sleep_ms(10);
    iox_set(X_NOLED_RST, true);
    sleep_ms(10);

    // Adafruit's sequence for the 1.27in 128x96 panel.
    OLED_CMD(0xfd, 0x12);
    OLED_CMD(0xfd, 0xb1);
    OLED_CMD(0xae);
    OLED_CMD(0xb3, 0xf1);
    OLED_CMD(0xca, 127);
    OLED_CMD(0xa2, 0x00);
    OLED_CMD(0xb5, 0x00);
    OLED_CMD(0xab, 0x01);
    OLED_CMD(0xb1, 0x32);
    OLED_CMD(0xbe, 0x05);
    OLED_CMD(0xa6);
    OLED_CMD(0xc1, 0xc8, 0x80, 0xc8);
    OLED_CMD(0xc7, 0x0f);
    OLED_CMD(0xb4, 0xa0, 0xb5, 0x55);
    OLED_CMD(0xb6, 0x01);
    OLED_CMD(0xa0, 0x74);
    OLED_CMD(0xa1, 96);
    OLED_CMD(0xaf);

    OLED_CMD(0x15, 0, 127);
    OLED_CMD(0x75, 0, 95);
    OLED_CMD(0x5c);
    static const uint16_t bars[8] = {0xffff, 0xffe0, 0x07ff, 0x07e0, 0xf81f, 0xf800, 0x001f, 0x0000};
    gpio_put(PIN_OLED_CS, 0);
    gpio_put(PIN_OLED_DC, 1);
    for (int y = 0; y < 96; y++) {
        uint8_t row[256];
        for (int x = 0; x < 128; x++) {
            bool edge = x == 0 || x == 127 || y == 0 || y == 95;
            uint16_t c = edge ? 0xffff : bars[x / 16];
            row[2 * x] = c >> 8;
            row[2 * x + 1] = c;
        }
        spi_write_blocking(spi1, row, sizeof row);
    }
    gpio_put(PIN_OLED_CS, 1);
    report(R_LOOK, "bars", "should show 8 bars: white yellow cyan green magenta red blue black, white border");
}

// ---- LED, joystick, audio (need a person) -----------------------------------

static void test_led(void) {
    heading("LED (D4, expander bit 5)");
    bool ok = iox_present;
    for (int i = 0; i < 5 && ok; i++) {
        led_set(true);
        sleep_ms(200);
        led_set(false);
        sleep_ms(200);
    }
    report(ok ? R_LOOK : R_FAIL, "blink", ok ? "D4 should have blinked 5 times (dimmed)" : "expander not found");
}

static void test_joystick(void) {
    heading("Joystick (J5 via expander port 1)");
    if (!iox_present) {
        report(R_SKIP, "joystick", "needs the expander");
        return;
    }
    printf("  Move the stick and press both fire buttons. 20 seconds, or any key to stop.\n");
    uint8_t seen = 0, last = 0xff, in1;
    int ints = 0;
    bool int_was = true;
    iox_read(IOX_IN1, &last);
    absolute_time_t until = make_timeout_time_ms(20000);
    while (!time_reached(until) && getchar_timeout_us(0) < 0) {
        bool int_now = gpio_get(PIN_NIOX_INT);
        if (int_was && !int_now) ints++;
        int_was = int_now;
        if (!int_now) {
            iox_read(IOX_IN1, &in1);
            uint8_t pressed = ~in1 & X_JOY_MASK;
            if (in1 != last) {
                printf("    ");
                for (int b = 0; b < 6; b++)
                    if (pressed & (1u << b)) printf("%s ", JOY_NAMES[b]);
                printf(pressed ? "\n" : "(released)\n");
                seen |= pressed;
                last = in1;
            }
        }
        sleep_ms(2);
    }
    printf("  Seen:");
    for (int b = 0; b < 6; b++) printf(" %s%s", JOY_NAMES[b], seen & (1u << b) ? "" : "(no)");
    printf("\n");
    report(seen == X_JOY_MASK ? R_PASS : seen ? R_LOOK : R_FAIL, "joystick",
           "%d of 6 inputs seen, %d /INT pulses", __builtin_popcount(seen), ints);
}

static volatile uint audio_phase, audio_step, audio_mask;
static const int16_t *audio_table;

static bool audio_tick(repeating_timer_t *t) {
    (void)t;
    audio_phase += audio_step;
    uint16_t level = 512 + audio_table[(audio_phase >> 24) & 0x3f];
    if (audio_mask & 1) pwm_set_gpio_level(PIN_AUDIO_L, level);
    if (audio_mask & 2) pwm_set_gpio_level(PIN_AUDIO_R, level);
    return true;
}

static void test_audio(void) {
    heading("Audio (PWM GP46 left, GP30 right -> U50 -> jack)");
    static int16_t sine[64];
    for (int i = 0; i < 64; i++) {
        // parabolic sine approximation is enough for a test tone; amplitude 1/4 scale
        float a = 6.2831853f * i / 64;
        float s = a < 3.1415927f ? a * (3.1415927f - a) : -(a - 3.1415927f) * (6.2831853f - a);
        sine[i] = (int16_t)(s * 0.405f * 256);
    }
    audio_table = sine;
    const uint pins[2] = {PIN_AUDIO_L, PIN_AUDIO_R};
    for (int i = 0; i < 2; i++) {
        gpio_set_function(pins[i], GPIO_FUNC_PWM);
        uint slice = pwm_gpio_to_slice_num(pins[i]);
        pwm_set_wrap(slice, 1023);  // ~146 kHz carrier at 150 MHz
        pwm_set_gpio_level(pins[i], 512);
        pwm_set_enabled(slice, true);
    }
    repeating_timer_t timer;
    const int rate = 32000;
    add_repeating_timer_us(-1000000 / rate, audio_tick, NULL, &timer);
    struct { const char *what; uint mask; uint hz; } steps[] = {
        {"left only, 440 Hz", 1, 440}, {"right only, 660 Hz", 2, 660}, {"both, 880 Hz", 3, 880}};
    for (unsigned i = 0; i < count_of(steps); i++) {
        printf("  %s\n", steps[i].what);
        audio_step = (uint)((uint64_t)steps[i].hz * 64 * (1ull << 24) / rate);
        audio_mask = steps[i].mask;
        sleep_ms(1500);
        audio_mask = 0;
        pwm_set_gpio_level(PIN_AUDIO_L, 512);
        pwm_set_gpio_level(PIN_AUDIO_R, 512);
        sleep_ms(300);
    }
    cancel_repeating_timer(&timer);
    for (int i = 0; i < 2; i++) {
        pwm_set_enabled(pwm_gpio_to_slice_num(pins[i]), false);
        gpio_init(pins[i]);
    }
    report(R_LOOK, "tones", "heard left 440, right 660, then both 880?");
}

// ---- menu -------------------------------------------------------------------

static void run_auto(void) {
    n_pass = n_fail = n_look = 0;
    printf("\nTS-Pico v3 bring-up: automatic tests\n");
    test_system();
    test_flash();
    test_expander();
    test_pins();
    test_sd();
    test_wifi();
    test_oled(32);
    printf("\n== Summary: %d pass, %d fail, %d to check by eye\n", n_pass, n_fail, n_look);
}

static void help(void) {
    printf("\nCommands:\n"
           "  a       all automatic tests\n"
           "  s f x b system, flash, expander, pins/bridges\n"
           "  d w     SD card, ESP32-C3\n"
           "  o [64]  OLED: I2C 128x32, or 'o 64' for I2C 128x64; SPI SSD1351 if neither\n"
           "  l       blink the LED\n"
           "  j       joystick monitor (20 s)\n"
           "  t       audio test tones\n"
           "  p [baud] ESP32-C3 serial passthrough (default 115200, Ctrl-] exits)\n"
           "  h       this help\n");
}

int main(void) {
    board_safe_init();
    iox_init();
    stdio_init_all();

    for (;;) {
        // Heartbeat on D4 until a terminal connects.
        bool lit = false;
        while (!stdio_usb_connected()) {
            led_set(lit = !lit);
            sleep_ms(500);
        }
        led_set(false);
        sleep_ms(300);
        static bool ran;
        if (!ran) {
            run_auto();
            ran = true;
        }
        help();
        char line[32];
        for (;;) {
            printf("> ");
            if (read_line(line, sizeof line) < 0) break;
            n_pass = n_fail = n_look = 0;
            switch (line[0]) {
            case 'a': run_auto(); break;
            case 's': test_system(); break;
            case 'f': test_flash(); break;
            case 'x': test_expander(); break;
            case 'b': test_pins(); break;
            case 'd': test_sd(); break;
            case 'w': test_wifi(); break;
            case 'o': {
                int rows = 32;
                sscanf(line + 1, "%d", &rows);
                test_oled(rows == 64 ? 64 : 32);
                break;
            }
            case 'l': test_led(); break;
            case 'j': test_joystick(); break;
            case 't': test_audio(); break;
            case 'p': {
                uint baud = 0;
                sscanf(line + 1, "%u", &baud);
                wifi_passthrough(baud ? baud : 115200);
                break;
            }
            default: help(); break;
            }
        }
    }
}
