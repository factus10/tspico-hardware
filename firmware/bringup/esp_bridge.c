/*
 * TS-Pico v3 ESP32-C3 bridge.
 *
 * Turns the card's USB port into a USB-serial adapter wired to the ESP32-C3
 * module (U40), the way the USB-UART chip on an ESP32 dev board is:
 *
 *  - UART0 (GP44 to the module's RXD, GP45 from its TXD) follows the baud
 *    rate, data bits, parity and stop bits the host sets on the USB port.
 *  - DTR and RTS drive the module's EN and IO9 through the expander with the
 *    usual two-transistor auto-reset logic, so esptool can put the module into
 *    its ROM loader and reset it afterwards:
 *        EN  low when RTS is asserted and DTR is not
 *        IO9 low when DTR is asserted and RTS is not
 *    A terminal that asserts both lines, or neither, leaves the module running.
 *
 * Nothing else on the card is used: the local bus stays disabled and the 2068
 * stays in reset. Reflash with `picotool load -f` to leave bridge mode.
 */
#include <stdio.h>

#include "pico/stdlib.h"
#include "hardware/irq.h"
#include "hardware/uart.h"
#include "tusb.h"

#include "board.h"

// Delay between the host releasing EN and the bridge doing so: stands in for
// the RC on a dev board's EN pin, so that when DTR and RTS change one after the
// other IO9 is already low by the time the module leaves reset.
#define EN_RELEASE_DELAY_US 10000

// ---- UART receive ring, filled from the interrupt ---------------------------

#define RX_RING_SIZE 8192
static uint8_t rx_ring[RX_RING_SIZE];
static volatile uint32_t rx_head, rx_tail;
static volatile uint32_t rx_dropped;

static void on_uart_rx(void) {
    while (uart_is_readable(uart0)) {
        uint8_t c = (uint8_t)uart_get_hw(uart0)->dr;
        uint32_t next = (rx_head + 1) % RX_RING_SIZE;
        if (next == rx_tail) {
            rx_dropped++;
            continue;
        }
        rx_ring[rx_head] = c;
        rx_head = next;
    }
}

// ---- host line settings -----------------------------------------------------

static void apply_line_coding(const cdc_line_coding_t *lc) {
    uint data_bits = lc->data_bits >= 5 && lc->data_bits <= 8 ? lc->data_bits : 8;
    uint stop_bits = lc->stop_bits == 2 ? 2 : 1;
    uart_parity_t parity = lc->parity == 1 ? UART_PARITY_ODD : lc->parity == 2 ? UART_PARITY_EVEN : UART_PARITY_NONE;
    uart_set_baudrate(uart0, lc->bit_rate ? lc->bit_rate : 115200);
    uart_set_format(uart0, data_bits, stop_bits, parity);
}

int main(void) {
    board_safe_init();
    iox_init();
    // Module held in reset, normal boot strap, LED on while the bridge runs.
    iox_set(X_WIFI_DL, false);
    iox_set(X_WIFI_EN, false);
    led_set(true);

    stdio_init_all();

    uart_init(uart0, 115200);
    gpio_set_function(PIN_WIFI_TX, GPIO_FUNC_UART);
    gpio_set_function(PIN_WIFI_RX, GPIO_FUNC_UART);
    gpio_pull_up(PIN_WIFI_RX);
    uart_set_fifo_enabled(uart0, true);
    irq_set_exclusive_handler(UART0_IRQ, on_uart_rx);
    irq_set_enabled(UART0_IRQ, true);
    uart_set_irq_enables(uart0, true, false);

    // Start with the module running, as a dev board does with the port closed.
    sleep_ms(10);
    iox_set(X_WIFI_EN, true);
    bool en = true, boot = false;
    absolute_time_t en_release_at = nil_time;

    cdc_line_coding_t coding = {0};
    uint8_t lines = 0xff;
    char buf[256];

    for (;;) {
        // Host line settings: polled, they change rarely.
        cdc_line_coding_t lc;
        tud_cdc_get_line_coding(&lc);
        if (lc.bit_rate != coding.bit_rate || lc.data_bits != coding.data_bits ||
            lc.parity != coding.parity || lc.stop_bits != coding.stop_bits) {
            coding = lc;
            apply_line_coding(&coding);
        }

        uint8_t state = tud_cdc_get_line_state();
        if (state != lines) {
            lines = state;
            bool dtr = state & 1, rts = state & 2;
            bool want_en = !(rts && !dtr);
            bool want_boot = dtr && !rts;
            if (want_boot != boot) {
                boot = want_boot;
                iox_set(X_WIFI_DL, boot);
            }
            if (!want_en && en) {
                en = false;
                en_release_at = nil_time;
                iox_set(X_WIFI_EN, false);
            } else if (want_en && !en && is_nil_time(en_release_at)) {
                en_release_at = make_timeout_time_us(EN_RELEASE_DELAY_US);
            } else if (!want_en) {
                en_release_at = nil_time;
            }
        }
        if (!is_nil_time(en_release_at) && time_reached(en_release_at)) {
            en_release_at = nil_time;
            en = true;
            iox_set(X_WIFI_EN, true);
        }

        // USB to module.
        int n = stdio_get_until(buf, sizeof buf, get_absolute_time());
        if (n > 0) uart_write_blocking(uart0, (const uint8_t *)buf, (size_t)n);

        // Module to USB, in contiguous runs out of the ring.
        uint32_t head = rx_head, tail = rx_tail;
        if (head != tail) {
            uint32_t run = head > tail ? head - tail : RX_RING_SIZE - tail;
            stdio_put_string((const char *)&rx_ring[tail], (int)run, false, false);
            rx_tail = (tail + run) % RX_RING_SIZE;
        }
    }
}
