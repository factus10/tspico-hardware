/*
 * TS-Pico v3 pin map, safe start-up and XL9555 expander access, shared by the
 * bring-up test and the ESP32 bridge.
 *
 * Pin map is taken from the schematic netlist (the hardware/ KiCad sheets), which
 * matches docs/v3-architecture.md section 7.
 */
#ifndef TSPICO_BOARD_H
#define TSPICO_BOARD_H

#include <stdbool.h>
#include <stdint.h>

#include "pico/types.h"

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

// Safe state: no bus request, no NMI, OLED in reset, ESP32 off, normal ESP32 boot,
// LED off. Bits 6-7 are spare (left as inputs).
#define IOX_OUT0_SAFE (X_NLED | 0xc0)

extern uint8_t iox_out0;
extern bool iox_present;

// The three 74LVC245s on the local bus (U1, U2, U3) have their /OE pins on
// GP8-GP10 with no external pull-up, and the RP2350 resets its pads with
// pull-downs on, so until firmware runs all three buffers are enabled. Call
// this first thing in main(); it turns them off.
void board_safe_init(void);

// Also starts the LED dimmer: D4 on R5 (100R) is very bright at full current,
// so the LED is switched at 100 Hz with a short on-time.
void iox_init(void);
int iox_write(uint8_t reg, uint8_t v);
int iox_read(uint8_t reg, uint8_t *v);
bool iox_set(uint8_t mask, bool on);

// D4. Use these rather than iox_set(X_NLED, ...); the dimmer owns that bit.
#define LED_BRIGHTNESS_DEFAULT 5   // percent
void led_set(bool on);
void led_brightness(uint percent);

#endif
