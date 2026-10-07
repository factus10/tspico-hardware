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
| `o [64]` | OLED | I2C SSD1306 128x32 (or SSD1309 128x64 with `o 64`) if one answers at 0x3C/0x3D, else SPI SSD1351 colour bars (look) |
| `l` | LED | blinks D4 five times (look) |
| `j` | joystick | 20 s monitor of all six inputs and the /INT line |
| `t` | audio | sine tones left, right, both (listen) |
| `p [baud]` | ESP32-C3 | serial passthrough, Ctrl-] exits |

Nothing here touches a TS2068: RESET_HOLD is left floating (2068 held in
reset), the bus request, NMI, /BE and /WAIT outputs stay deasserted, and the
pin test only drives MD0-MD7 with all three local-bus buffers disabled.

## I2C OLED on J3

J3 is wired for the SPI SSD1351 module, but its DIN and CLK pins (GP43,
GP42) double as I2C1 SCL and SDA, so a 4-pin I2C SSD1306 (128x32) or SSD1309
(128x64) module works with jumper wires. Power and ground are swapped relative
to most modules' headers, so wire by name:

| Module | J3 |
|---|---|
| VCC | 1 (+3V3) |
| GND | 2 |
| SCL | 3 (DIN) |
| SDA | 4 (CLK) |

## ESP32-C3 bridge

`build/esp_bridge.uf2` is a second program: it turns the card's USB port into
a USB-serial adapter for the ESP32-C3 module, wired the way an ESP32 dev
board's USB-UART chip is.

- The module's UART follows whatever baud rate and format the host opens the
  port with.
- DTR and RTS drive the module's EN and IO9 (through the expander) with the
  standard auto-reset logic, so esptool and `pio run -t upload` flash the
  module without buttons. A terminal program leaves the module running.
- The LED is on while the bridge runs. The local bus stays disabled and the
  2068 stays in reset.

```bash
picotool load -f -x build/esp_bridge.uf2
```

`../zimodem/` builds Zimodem and flashes it through this bridge. To go back to
the self-test, load `build/bringup.uf2` the same way.

## Bus shadow test (phase 1)

`build/bus_shadow.uf2` is step 2 of phase 1 in
[docs/v3-firmware-port-plan.md](../../docs/v3-firmware-port-plan.md). With the
card in the 2068's expansion bus, it follows every Z80 memory read but never
drives the 2068: the 2068 runs on its own ROM.

- `bus_fetch` (PIO1) reads the address through U1/U2, adds the class from
  /ROSCS and /EXROM, and pushes a pointer to a DMA chain. The chain fetches
  the byte from the images, and the program puts it on MD. U3 stays off, so
  MD never reaches the 2068's data bus.
- `bus_decide` (PIO0) applies the v2.1 HOME / EXROM / DOCK rule to every
  read. Core 1 counts the results (`s`, `w`). BE_REQ stays low.
- The images are the stock 2068 ROMs, from `TSPICO_ROM_DIR`. The default is
  `~/Documents/github/tspico-firmware-build/ROMs`. They sit at 0x20040000,
  above everything the C runtime uses (`memmap_bus.ld`), interleaved so the
  byte for (address, class) is at `0x20040000 + 4 * address + class`.
- The 2068 is held in reset until `g`. `t n` moves the point where /ROSCS and
  /EXROM are sampled, once capture 0 shows how long they take to settle.
- It times itself, so the margin can be measured without the analyser. `m`
  reports how long the read strobe stays low (`stopwatch_strobe`) and how long
  the card takes from seeing it to having the byte on MD (the READY marker),
  with histograms and the worst case (shortest strobe minus slowest byte).
  The strobe ends a little after the Z80 samples the data, and the data needs
  setup time, so the analyser still has to confirm the real margin.
- `a` prints the last 32 addresses the card captured, from a third DMA
  channel that logs every pointer. ROM code shows up as runs of nearly
  consecutive addresses, which checks both address bytes.
- `b [n]` prints the first reads after the last release from reset (`g` or
  `r`): the first 4096 are kept separately, with the byte served for each.
  The Z80 starts fetching at 0000, so this checks address capture from the
  very first cycle against a known sequence.

Timing markers on J3 (take the OLED off):

| J3 pin | GPIO | Marker | High from ... to ... |
|---|---|---|---|
| 3 | GP43 | FRONT | read strobe seen, to address captured |
| 4 | GP42 | READY | read strobe seen, to byte on MD |
| 5 | GP41 | SERVE | cycle classified as ours, to end of cycle |
| 6 | GP34 | BE | cycle would assert /BE (HOME, EXROM), to end of cycle |

Each marker lags the event inside the chip by two or three PIO cycles (about
15-20 ns). For the LA2016:

| Ch | Signal | Ch | Signal |
|---|---|---|---|
| 0 | /CLK | 8 | FRONT (J3.3) |
| 1 | /M1 | 9 | READY (J3.4) |
| 2 | /MREQ | 10 | SERVE (J3.5) |
| 3 | /RD | 11 | BE (J3.6) |
| 4 | /ROSCS | 12-15 | D0-D3 |
| 5 | /EXROM | | |
| 6 | A14 | | |
| 7 | A15 | | |

## Board notes from proto1

- GP8-GP10 (nAEN_LO, nAEN_HI, nDATA_OE) have no external pull-ups. The RP2350
  resets its pads with pull-downs on, so while the chip is in reset or in
  BOOTSEL, U1, U2 and U3 are all enabled and U1 and U2 both drive MD0-MD7.
  The firmware drives them high first thing in `main()`; the next board
  revision should add 10k pull-ups to 3V3.
- The ESP32-C3 module arrives with blank flash; Zimodem has to be installed.
