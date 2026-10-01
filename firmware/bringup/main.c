/*
 * TS-Pico v3 bring-up test.
 *
 * Runs over USB serial (any terminal, 115200 or anything; it's CDC). On first
 * connect it runs every automatic test and prints a PASS/FAIL report, then
 * offers a menu for the tests that need a person to look, listen or press.
 *
 * Pin map is taken from the schematic netlist (hardware/*.kicad_sch), which
 * matches docs/v3-architecture.md section 7.
 *
 * Safety: the three 74LVC245s on the local bus (U1, U2, U3) have their /OE
 * pins on GP8-GP10 with no external pull-up, and the RP2350 resets its pads
 * with pull-downs on, so until firmware runs all three buffers are enabled.
 * board_safe_init() is the first thing main() does and turns them off.
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

// ---- pins -------------------------------------------------------------------

#define PIN_MD0        0   // MD0-MD7 on GP0-GP7
#define PIN_NAEN_LO    8
#define PIN_NAEN_HI    9
#define PIN_NDATA_OE   10
#define PIN_BE_REQ     11
#define PIN_WAIT_REQ   12
#define PIN_Z80_A14    13  // GP13-GP22: inputs from U4 / U6
#define PIN_TAPE_IN    22
#define PIN_TAPE_OUT   23
#define PIN_I2C_SDA    24
#define PIN_I2C_SCL    25
#define PIN_RESET_HOLD 29
#define PIN_AUDIO_R    30
#define PIN_SD_MISO    32
#define PIN_OLED_DC    34
#define PIN_NIOX_INT   35
#define PIN_SD_CS      37
#define PIN_SD_SCK     38
#define PIN_SD_MOSI    39
#define PIN_OLED_CS    41
#define PIN_OLED_SCK   42
#define PIN_OLED_MOSI  43
#define PIN_WIFI_TX    44
#define PIN_WIFI_RX    45
#define PIN_AUDIO_L    46
#define PIN_PSRAM_CS   47

static const uint SPARE_PINS[] = {26, 27, 28, 31, 33, 36, 40};

static const char *const INPUT_NAMES[] = {
    "Z80_A14", "Z80_A15", "nMEMRD", "nMEMWR", "nIORD",
    "nIOWR", "nROSCS_L", "nEXROM_L", "nINT_L", "TAPE_IN",
};

// ---- XL9555 expander (PCA9555 registers) ------------------------------------

#define IOX_ADDR 0x20
#define IOX_IN0  0
#define IOX_IN1  1
#define IOX_OUT0 2
#define IOX_POL1 5
#define IOX_CFG0 6
#define IOX_CFG1 7

// port 0, outputs
#define X_BUSRQ     (1u << 0)
#define X_NMI_REQ   (1u << 1)
#define X_NOLED_RST (1u << 2)
#define X_WIFI_EN   (1u << 3)
#define X_WIFI_DL   (1u << 4)
#define X_NLED      (1u << 5)
// port 1, inputs (all active low)
#define X_JOY_MASK  0x3f
#define X_NBUSAK    (1u << 6)
#define X_SD_CD     (1u << 7)

static const char *const JOY_NAMES[] = {"UP", "DOWN", "LEFT", "RIGHT", "FIRE1", "FIRE2"};

// Safe state: no bus request, no NMI, OLED in reset, ESP32 off, normal ESP32 boot,
// LED off. Bits 6-7 are spare (left as inputs).
#define IOX_OUT0_SAFE (X_NLED | 0xc0)

static uint8_t iox_out0 = IOX_OUT0_SAFE;
static bool iox_present;

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

// ---- board init -------------------------------------------------------------

static void board_safe_init(void) {
    // Local bus buffers off before anything else.
    const uint high_outs[] = {PIN_NAEN_LO, PIN_NAEN_HI, PIN_NDATA_OE};
    for (unsigned i = 0; i < count_of(high_outs); i++) {
        gpio_init(high_outs[i]);
        gpio_put(high_outs[i], 1);
        gpio_set_dir(high_outs[i], GPIO_OUT);
    }
    const uint low_outs[] = {PIN_BE_REQ, PIN_WAIT_REQ, PIN_TAPE_OUT};
    for (unsigned i = 0; i < count_of(low_outs); i++) {
        gpio_init(low_outs[i]);
        gpio_put(low_outs[i], 0);
        gpio_set_dir(low_outs[i], GPIO_OUT);
    }
    // MD bus: inputs with pull-downs (all three buffers are off).
    for (uint p = PIN_MD0; p < PIN_MD0 + 8; p++) {
        gpio_init(p);
        gpio_pull_down(p);
    }
    // Bus-side inputs: plain inputs.
    for (uint p = PIN_Z80_A14; p <= PIN_TAPE_IN; p++) {
        gpio_init(p);
        gpio_disable_pulls(p);
    }
    // RESET_HOLD: leave floating so R1 holds the 2068 in reset.
    gpio_init(PIN_RESET_HOLD);
    gpio_disable_pulls(PIN_RESET_HOLD);
    // Expander /INT has its own 10k pull-up.
    gpio_init(PIN_NIOX_INT);
    gpio_disable_pulls(PIN_NIOX_INT);
    // PSRAM is not fitted; keep its CS high anyway.
    gpio_init(PIN_PSRAM_CS);
    gpio_pull_up(PIN_PSRAM_CS);

    gpio_init(PIN_SD_CS);
    gpio_put(PIN_SD_CS, 1);
    gpio_set_dir(PIN_SD_CS, GPIO_OUT);
    gpio_init(PIN_OLED_CS);
    gpio_put(PIN_OLED_CS, 1);
    gpio_set_dir(PIN_OLED_CS, GPIO_OUT);
    gpio_init(PIN_OLED_DC);
    gpio_set_dir(PIN_OLED_DC, GPIO_OUT);
}

static int iox_write(uint8_t reg, uint8_t v) {
    uint8_t b[2] = {reg, v};
    return i2c_write_timeout_us(i2c0, IOX_ADDR, b, 2, false, 10000);
}

static int iox_read(uint8_t reg, uint8_t *v) {
    int r = i2c_write_timeout_us(i2c0, IOX_ADDR, &reg, 1, true, 10000);
    if (r != 1) return r;
    return i2c_read_timeout_us(i2c0, IOX_ADDR, v, 1, false, 10000);
}

static bool iox_set(uint8_t mask, bool on) {
    if (on) iox_out0 |= mask;
    else iox_out0 &= ~mask;
    return iox_write(IOX_OUT0, iox_out0) == 2;
}

static void iox_init(void) {
    i2c_init(i2c0, 400 * 1000);
    gpio_set_function(PIN_I2C_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_I2C_SCL, GPIO_FUNC_I2C);
    // R6/R7 are the pull-ups; leave the internal ones off.
    gpio_disable_pulls(PIN_I2C_SDA);
    gpio_disable_pulls(PIN_I2C_SCL);
    // Output register first, then direction: the outputs come up at the safe
    // values instead of the register's reset value of all ones.
    iox_out0 = IOX_OUT0_SAFE;
    iox_present = iox_write(IOX_OUT0, iox_out0) == 2 &&
                  iox_write(IOX_POL1, 0x00) == 2 &&
                  iox_write(IOX_CFG1, 0xff) == 2 &&
                  iox_write(IOX_CFG0, 0xc0) == 2;
}

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
    bool ok = rd && out0 == iox_out0 && cfg0 == 0xc0 && cfg1 == 0xff;
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

static void test_oled(void) {
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
    bool ok = true;
    for (int i = 0; i < 5; i++) {
        ok &= iox_set(X_NLED, false);
        sleep_ms(200);
        ok &= iox_set(X_NLED, true);
        sleep_ms(200);
    }
    report(ok ? R_LOOK : R_FAIL, "blink", ok ? "D4 should have blinked 5 times" : "I2C write failed");
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
    test_oled();
    printf("\n== Summary: %d pass, %d fail, %d to check by eye\n", n_pass, n_fail, n_look);
}

static void help(void) {
    printf("\nCommands:\n"
           "  a       all automatic tests\n"
           "  s f x b system, flash, expander, pins/bridges\n"
           "  d w o   SD card, ESP32-C3, OLED\n"
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
        while (!stdio_usb_connected()) {
            iox_set(X_NLED, !(iox_out0 & X_NLED));
            sleep_ms(500);
        }
        iox_set(X_NLED, true);
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
            case 'o': test_oled(); break;
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
