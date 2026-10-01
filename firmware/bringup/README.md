# TS-Pico v3 bring-up test

Self-test firmware for the v3 board. It talks over USB serial: connect any
terminal and it runs the automatic tests, prints PASS/FAIL for each, then
offers a menu for the checks that need a person (LED, joystick, audio, OLED).

## Build and flash

Needs the Pico SDK (2.1.1 or later, for RP2350 support), the Arm GNU toolchain
and picotool (`brew install picotool`).

```bash
export PICO_SDK_PATH=~/pico/pico-sdk
export PICO_TOOLCHAIN_PATH=~/pico/arm-gnu-toolchain-13.3.rel1-darwin-arm64-arm-none-eabi
cmake -S . -B build -Dpicotool_DIR=/opt/homebrew/lib/cmake/picotool
make -C build -j8
picotool load -f -x build/bringup.uf2
```

`-f` reboots a board that is already running this firmware into BOOTSEL first;
a blank board is in BOOTSEL already. Alternatively copy `build/bringup.uf2`
onto the `RP2350` drive.

## Run

```bash
screen /dev/cu.usbmodem101
```

The LED (D4) blinks once a second until a terminal connects. The automatic
tests run once on the first connection; `a` runs them again, `h` lists the
rest.

| Key | Test | Checks |
|---|---|---|
| `s` | RP2350B | crystal and clock frequencies, die temperature |
| `f` | QSPI flash | JEDEC ID (GD25Q128E), erase/program/verify of the last sector |
| `x` | expander | XL9555 ACK and register readback, /INT idle, joystick idle |
| `b` | pins | solder bridges and stuck lines on MD0-MD7 and the spares, RESET_HOLD pull-up |
| `d` | microSD | card detect, SPI init, CSD capacity, block reads at 400 kHz and 25 MHz |
| `w` | ESP32-C3 | EN control and ROM boot banner, AT reply, IO9 download-mode strap |
| `o` | OLED | SSD1351 init and colour bars (look) |
| `l` | LED | blinks D4 five times (look) |
| `j` | joystick | 20 s monitor of all six inputs and the /INT line |
| `t` | audio | sine tones left, right, both (listen) |
| `p [baud]` | ESP32-C3 | serial passthrough, Ctrl-] exits |

Nothing here touches a TS2068: RESET_HOLD is left floating (2068 held in
reset), the bus request, NMI, /BE and /WAIT outputs stay deasserted, and the
pin test only drives MD0-MD7 with all three local-bus buffers disabled.

## Board notes from proto1

- GP8-GP10 (nAEN_LO, nAEN_HI, nDATA_OE) have no external pull-ups. The RP2350
  resets its pads with pull-downs on, so while the chip is in reset or in
  BOOTSEL, U1, U2 and U3 are all enabled and U1 and U2 both drive MD0-MD7.
  The firmware drives them high first thing in `main()`; the next board
  revision should add 10k pull-ups to 3V3.
- The ESP32-C3 module arrives with blank flash; Zimodem has to be installed.
