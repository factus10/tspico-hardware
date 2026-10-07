#include "board.h"

#include "pico/stdlib.h"
#include "hardware/i2c.h"
#include "hardware/sync.h"

uint8_t iox_out0 = IOX_OUT0_SAFE;
bool iox_present;

void board_safe_init(void) {
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
    // MD bus: plain inputs (all three buffers are off). No pulls: MD is only
    // sampled while a buffer drives it, and RP2350 erratum E9 can latch a pad
    // with its input and pull-down both enabled at about 2 V.
    for (uint p = PIN_MD0; p < PIN_MD0 + 8; p++) {
        gpio_init(p);
        gpio_disable_pulls(p);
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

// The LED dimmer writes the expander from a timer interrupt, so every
// transfer from thread code runs with interrupts off (about 70 us at 400 kHz).

static int iox_write_unlocked(uint8_t reg, uint8_t v) {
    uint8_t b[2] = {reg, v};
    return i2c_write_timeout_us(i2c0, IOX_ADDR, b, 2, false, 10000);
}

int iox_write(uint8_t reg, uint8_t v) {
    uint32_t irq = save_and_disable_interrupts();
    int r = iox_write_unlocked(reg, v);
    restore_interrupts(irq);
    return r;
}

int iox_read(uint8_t reg, uint8_t *v) {
    uint32_t irq = save_and_disable_interrupts();
    int r = i2c_write_timeout_us(i2c0, IOX_ADDR, &reg, 1, true, 10000);
    if (r == 1) r = i2c_read_timeout_us(i2c0, IOX_ADDR, v, 1, false, 10000);
    restore_interrupts(irq);
    return r;
}

bool iox_set(uint8_t mask, bool on) {
    uint32_t irq = save_and_disable_interrupts();
    if (on) iox_out0 |= mask;
    else iox_out0 &= ~mask;
    bool ok = iox_write_unlocked(IOX_OUT0, iox_out0) == 2;
    restore_interrupts(irq);
    return ok;
}

// ---- LED dimmer -------------------------------------------------------------

#define LED_TICK_US    250
#define LED_PWM_TICKS  40   // 10 ms period: 100 Hz, 2.5% steps

static volatile bool led_on;
static volatile uint led_duty_ticks = (LED_BRIGHTNESS_DEFAULT * LED_PWM_TICKS + 99) / 100;
static uint led_phase;
static repeating_timer_t led_timer;

static bool led_tick(repeating_timer_t *t) {
    (void)t;
    led_phase = (led_phase + 1) % LED_PWM_TICKS;
    bool lit = led_on && led_phase < led_duty_ticks;
    bool is_lit = !(iox_out0 & X_NLED);
    if (lit != is_lit) {
        if (lit) iox_out0 &= ~X_NLED;
        else iox_out0 |= X_NLED;
        iox_write_unlocked(IOX_OUT0, iox_out0);
    }
    return true;
}

void led_set(bool on) { led_on = on; }

void led_brightness(uint percent) {
    if (percent > 100) percent = 100;
    led_duty_ticks = (percent * LED_PWM_TICKS + 99) / 100;
}

void iox_init(void) {
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
    static bool led_started;
    if (iox_present && !led_started)
        led_started = add_repeating_timer_us(-LED_TICK_US, led_tick, NULL, &led_timer);
}
