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
- `x [h l]` sets how long each address buffer is given between being enabled
  and being sampled. On board 1 a buffer needs about 20 ns; the defaults give
  33 ns each.
- `b [n]` prints the first reads after the last release from reset (`g` or
  `r`): the first 4096 are kept separately, with the byte served for each.
  The Z80 starts fetching at 0000, so this checks address capture from the
  very first cycle against a known sequence.

Timing markers on J3 (take the OLED off):

| J3 pin | GPIO | Marker | High from ... to ... |
|---|---|---|---|
| 4 | GP42 | READY | read strobe seen, to byte on MD |
| 5 | GP41 | SERVE | cycle classified as ours, to end of cycle |
| 6 | GP34 | BE | cycle would assert /BE (HOME, EXROM), to end of cycle |

Each marker lags the event inside the chip by two or three PIO cycles (about
15-20 ns). For the LA2016:

| Ch | Signal | Ch | Signal |
|---|---|---|---|
| 0 | /CLK | 8 | spare |
| 1 | /M1 | 9 | READY (J3.4) |
| 2 | /MREQ | 10 | SERVE (J3.5) |
| 3 | /RD | 11 | BE (J3.6) |
| 4 | /ROSCS | 12-15 | D0-D3 |
| 5 | /EXROM | | |
| 6 | A14 | | |
| 7 | A15 | | |

### First run in a 2068 (board 1, 2026-10-07)

- The 2068 boots normally with the card following it; about 600,000 to
  750,000 reads a second, roughly 80% ROM. The boot reads EXROM 1988 times and
  the dock 12 times, then neither.
- The original address timing sampled each buffer only 13 ns after enabling
  it, which caught MD before the buffer drove it. A sweep showed about 20 ns is
  needed; at 33 ns each the boot log matches the ROM exactly (0000-0007, then
  the memory loop at 0D42-0D47).
- With that timing the byte is on MD 200 ns after the read strobe is seen,
  every time. In normal running the shortest strobe (M1) is 400 ns, so the
  byte is ready 200 ns before the strobe ends. The analyser still has to place
  that against the Z80's clock.
- At boot the 2068's reset line rises slowly after release, so the Z80 fetches
  0000 a couple of hundred times, with some reads cut short (down to about
  250 ns), before it starts properly. That happens at power-on too.

### Serving the HOME ROM (step 3, board 1, 2026-10-07)

`e 1` (with the 2068 held) swaps `bus_decide` for `bus_serve`, which serves
HOME ROM reads for real: it asserts /BE once the class is known, enables U3
when `bus_fetch` signals the byte is on MD, and releases both when the strobe
ends. EXROM, DOCK and RAM reads are left to the 2068. The served copy of the
ROM reads "TS-Pico v3 ROM" where the 2068's says "Timex Computer", so the boot
screen shows which one answered.

On board 1 the 2068 booted to "(c) 1983 TS-Pico v3 ROM Corp" and settled in
its normal idle loop: about 2.5 million HOME reads served in five seconds,
with the byte on MD 200 ns after the strobe, the same as in shadow mode.

### EXROM and DOCK reads (step 4, board 1, 2026-10-07)

`bus_serve` now covers EXROM and DOCK reads too, each switchable while running:

- `y 0|1|2`: EXROM reads left to the 2068 (0, the default), served with /BE
  (1, as v2.1 does), or served without /BE (2), with the 2068's own EXROM
  driving the same bytes alongside U3.
- `k 0|1`: DOCK reads left alone (0, the default, so a real cartridge is never
  fought) or served from the card's dock image (1), without /BE.
- `c [n]`: the reads around the first EXROM read after each release.
- `p 0|1`: marks EXROM 0x1800 with "TS-PICO EXROM", for use after boot.

Results:

- **DOCK reads work.** With `k 1`, mapping chunk 4 to the dock bank in BASIC
  (`OUT 244,16`) and PEEKing 32768 onward printed "TS-PICO DOCK" from the
  card's image.
- **EXROM served without /BE works.** The 2068 boots normally, and the
  EXROM-to-RAM copy the boot makes at 0E0Bh (EXROM 1000h-162Fh to RAM
  6200h-682Fh) sums to 210966, the same as a stock boot.
- **EXROM served with /BE crashes the boot.** The 2068 ends up in the dock bank
  at 0038h (RST 38h on 0xFF). The reads are identical to a stock boot through
  the copy, so the corruption is after it, most likely in the copy's writes
  or the bank state. This 2068's EXROM chip matches `GENUINE-2068-exrom.bin`
  (sum 969547), so wrong data was ruled out. /BE is asserted about 133 ns
  into the cycle, after the class is known; v2.1 asserted it much earlier.
  The logic analyser should show what the 2068 does with a late /BE on an
  EXROM cycle.
- After that crash the 2068 needs a power cycle. The SCLD's bank registers
  (ports F4h and FFh) survive /RESET, so chunk 0 stays mapped to the dock.
- Serving without /BE only works because the chip and the copy are identical.
  The TS-Pico ROM's own EXROM needs /BE.

### Early /BE and opcode timing (board 1, 2026-10-07)

The 2068 decides which of its banks a low-16K read belongs to, but A15 and A14
alone say a read is in the ROM region, and they are valid before /MREQ falls.
`z 1` asserts /BE straight from them, about 60 ns after the strobe, instead of
after /ROSCS and /EXROM have been sampled (133 ns).

- **This corrects step 3.** With late /BE the 2068's own ROM drives the bus for
  much of each cycle. The patched copyright line proves the card's bytes reach
  the Z80 on data reads, but opcode fetches were probably answered by the
  internal ROM, with identical bytes. Early /BE takes the internal ROM away,
  and the boot then depends on the card for opcodes.
- **M1 timing is tight.** With early /BE and the byte on MD 180 ns after the
  strobe, the Z80 got wrong opcodes: the memory loop at 0D42 never ended
  (`DEC HL` not executing). At 156 ns (250 MHz, class sampled at 112 ns) it got
  through.
- **Then the RAM test failed.** The test at 0D48 never ended: RAM did not hold
  what had just been written. Writes straight after a card-served read seem to
  be lost, the same signature as the EXROM-with-/BE crash. Either /BE (open
  drain, pulled up inside the 2068) rises too slowly after the card releases
  it, or the SCLD samples it at a point in the cycle we don't know yet. The
  logic analyser should show which.
- `bus_shadow` now runs at 250 MHz (flash divider 3, core 1.20 V), with the
  same nanosecond delays: 36 ns per address buffer, class at 133 ns
  (`t 28` = 112 ns is the earliest). Early /BE is off by default.

Ways to get the byte out sooner: bypass the input synchronisers on the bus
pins; track ports F4h and FFh on the card so the class comes from the address
alone, without waiting for /ROSCS and /EXROM.

### Bank tracking (board 1, 2026-10-07)

`io_snoop` (PIO1) reads every Z80 I/O write: the port's low address byte
through U1 and the data through U3, which only points from the Z80 onto MD
during writes. Core 1 keeps a shadow of port F4h (the HSR: one bit per 8K
chunk, 1 = cartridge bus) and port FFh (bit 7: EXROM 1, DOCK 0). For every
logged read it predicts the class from the shadow and the address, and
compares it with what /ROSCS and /EXROM said. `v` shows the shadow and the
count of mismatches.

A shadow boot on board 1 made 11 writes to F4h and 9 to FFh. All 3.2 million
reads matched the prediction, including the bank switching around the
EXROM-to-RAM copy. This lets the card classify a read from its address alone,
early enough for early /BE, without waiting for (or depending on) /EXROM and
/ROSCS. io_snoop needs U3's enable, so it runs in shadow mode only for now.

Two diagnostics went to make room in PIO1: the strobe stopwatch (the
400 ns minimum is known) and the FRONT marker on J3.3.

PIO note: a state machine stalled on an instruction with side-set keeps
asserting those pins, so programs sharing pins must not side-set on their idle
`wait`. With side-set on both idle waits, io_snoop (the higher-numbered state
machine) held U1 and U2 off and broke bus_fetch's address capture.

## bus_card: serving from the bank shadow (board 1, 2026-10-07)

`build/bus_card.uf2` is the second bus design (`bus_card.pio`, `bus_card.c`).
The class of each read comes from the card's shadow of ports F4h and FFh, so
/BE goes out about 50 ns into the cycle without waiting for /EXROM or /ROSCS.

| Block | Owns | Programs |
|---|---|---|
| PIO0 | MD0-MD7, BE_REQ | `serve`: reads the address off MD, decides through an 8-entry chunk table core 1 rewrites from the shadow, asserts /BE, pushes the pointer, drives the byte (32 instructions) |
| PIO1 | U1/U2/U3 enables | `addr_read`: buffer windows around serve's samples, U3 on as soon as serve asks; `io_snoop`: every I/O write, for the shadow (23 instructions together) |
| PIO2 | J3.4 | READY marker |

The DMA fetches only the byte needed (slot 0 HOME, 1 EXROM, 2 DOCK).
Synchronisers are bypassed on MD and the strobes. Shadow mode (the default)
patches serve's /BE and U3 requests out; `e 1` serves, `y 1` adds EXROM-bank
chunks, `k 1` DOCK-bank chunks.

Results:

- The byte is on MD about 124 ns after the read strobe is seen (48 ns after
  serve's request, every one of 159 million reads; worst 60 ns). Before:
  156-180 ns.
- **HOME with early /BE works.** The 2068 boots, passes its memory test, shows
  "(c) 1983 TS-Pico v3 ROM Corp" and runs BASIC. The internal ROM is off from
  about 50 ns into each read, so every opcode comes from the card.
- **EXROM with /BE works.** The boot's 1988 EXROM reads come from the card,
  and the EXROM-to-RAM copy sums to 210966, the same as a stock 2068.
- **DOCK works.** With `k 1`, BASIC mapping chunk 4 to the dock read
  "TS-PICO DOCK".
- The earlier EXROM crash and RAM-test failure came from late /BE and tight
  opcode timing, both gone in this design.

### DOCK RAM writes

`mem_write` (PIO1) reads every Z80 memory write: A15..A8 through U2, A7..A0
through U1, the data through U3 (pointing from the Z80 onto MD, since /RD is
high). /WR is low for about 250 ns; the capture takes about 130. Core 1 stores
the byte in the DOCK image when the shadow maps that chunk to the dock and
DOCK serving is on (`k 1`). Its RX FIFO is joined (8 deep) so it never stalls
holding the shared pins. Two instructions came out of `addr_read` to make room
(the stale U3 request is cleared at the end of a read, and "U1 off" shares an
instruction), so PIO1 is full: 13 + 11 + 8.

On board 1, BASIC wrote 256 bytes into the dock through chunk 4 and read them
back with 0 errors, over about four runs (992 bytes stored). The boot's memory
test, 370,000 writes, and 168 million writes since, were all correctly left
alone.

### Ports 0Eh/0Fh (the TS-Pico protocol)

- **OUTs** need no new PIO code. `io_snoop` already reads every I/O write.
  Core 1 takes the 0Eh/0Fh ones, sets the status byte to 00h (busy, as v2.1's
  PIO did) and hands the byte on to the protocol responder. In echo mode
  (`p 1`) a byte sent to 0Eh is queued to come back on IN 0Eh instead, and the
  status returns to FFh.
- **INs** leave the Z80 about 600 ns before it samples the data, enough for
  core 1 to do most of the work. A falling edge on nIORD interrupts core 1. It
  forces U1 on through a GPIO override (which works on a PIO-owned pin), reads
  the port off MD and releases U1. For 0Eh/0Fh it pushes the reply to
  `io_drive`, a 5-instruction PIO0 program that puts it on MD, then forces U3
  on until the strobe ends. IN 0Eh pops the reply queue (00h if empty); IN 0Fh
  returns the status (`u` sets it). Other ports, the keyboard included, are
  left alone.
- **Room in PIO0:** `serve` went from 32 instructions to 27 with no change in
  behaviour (/BE moved to side-set, the table dispatch uses `out pc`, the READY
  marker went), leaving room for `io_drive`. Both PIO0 and PIO1 are now full.

What it took on board 1:

- **Holding the 2068 in reset.** nIORD sits low the whole time, and treating
  that as INs once answered stale MD bytes. INs are now edge-triggered and
  ignored while the 2068 is held.
- **Core 1 polling** left gaps of up to 370 ns between checks, enough to miss
  the reply window (the first IN 0Fh read 7Fh). A GPIO edge interrupt fixed
  that, with core 1's loop and helpers moved to RAM.
- **`exrom_on` and `dock_on` were not volatile.** Once the loop moved to RAM,
  core 1 read them once at start-up, so the chunk table stopped following the
  switches. They are volatile now.

Result: BASIC printed 255 for `IN 15`, and sent all 256 byte values to port 14
and read each one back correctly. 257 INs answered, 256 OUTs, none late. The
worst time from entering the handler to U3 on was 308 ns, mostly the GPIO
override register writes; with the interrupt entry that is under 400 ns of
the roughly 600 available.

### The TS-Pico protocol responder, and ROM 2.2

The card serves the TS-Pico ROM by default (`m 1`; `m 0` is the stock 2068
set): HOME, plus the 16K EXROM over chunks 0-1. CMake takes
the newest `src/rom/TSPICO-NN.ROM` on the firmware repo's `origin/main` (2.3
as of 2026-10-08) with `git show`, so the checkout is left alone (`TSPICO_ROM`
overrides it).

The responder follows `docs/PROTOCOL.md` in the firmware repo (firmware
2.2.1). Core 0 runs it from the menu loop. Core 1 makes the status busy on
every OUT and queues the byte, port 0Fh as `0x100 | data`.

- **SYNC:** any OUT to 0Fh empties both queues, stages exactly one 0x01 (the
  pre-load the ROM reads straight after the pre-header) and says idle (FFh).
- **Pre-header:** 10 bytes. `'B'` with TADDR 0-3 opens a command. Status F7h
  (ready, transaction open), then the body: `'D'`, LEN, the text, and an XOR,
  which is checked (a mismatch answers status 2, Report R).
- **The answer** is queued, then READY. `tpi:info` prints through response
  function 81h, `tpi:nop` answers status 1, and `LOAD "tpi:name"` answers F
  (no files yet). Anything else prints "is not here yet" with Report C.
- **The tail:** once the Z80 has read the answer, the next 0x01 is staged.
  A half-received pre-header or body is dropped after 1 s, and an answer
  nobody reads after 10 s, both with status FBh (RECOVERED, Report T).
- The printer is not handled yet: it answers RECOVERED.

`t` shows the responder's state and counts. `l` shows a trace core 1 keeps of
every OUT, every IN 0Eh and every change in the status read. `z` arms a
snapshot (`Z` prints it): the read log, memory writes and I/O writes around
the first beep with the EXROM paged in.

On board 1 (with the /BE pull-up below), `SAVE "tpi:info"` printed its lines
and `SAVE "tpi:hello"` stopped with "is not here yet" and Report C. Both went
SYNC, pre-header, pre-load, F7h, body, answer, tail as specified, with no bad
XORs, timeouts or lost bytes. Typing works.

**The /BE bug.** Without the pull-up, ROM 2.2 crashed on its first keypress:
mostly a cold restart, sometimes a corrupted screen or a G cursor. ROM 2.2's
key click runs BEEPER in the EXROM through the RAM bank-switch code at $65D0
(copied from EXROM $13D0 at boot). The `z` snapshot showed the opcode fetch at
$65D0, right after the card had served the last byte of `JP $65D0` with /BE,
reading wrong: `EX (SP),HL` (E3h) ran as `EX DE,HL` (EBh). The bank stack got
$C8C8 as a return address, and on the way out SP landed in ROM. The stock ROM
failed the same way after two `SAVE` loops, since its SAVE takes the same
route into the EXROM. /BE comes from the open-drain 74LVC06, and nBE has no
pull-up on proto1, so it rose too slowly for a RAM fetch about 700 ns after a
served byte. (v2 drove /BE push-pull, high within about 30 ns.) A 2.2k from /BE
(edge A29) to +5V fixed it: 50 SAVE loops on the stock ROM, then
ROM 2.2 typing and commands.

MD0-MD7 no longer have pad pull-downs: MD is only sampled while a buffer
drives it, and RP2350 erratum E9 can latch a pad with its input and pull-down
both on at about 2 V.

### LOAD and SAVE, to a tape in RAM

With LOAD/SAVE switched to the card (`SAVE "tpi:sdcard"`, which the ROM handles
itself), blocks go to a 64 KB tape in RAM, in TAP format, until the card is
reset. This stands in for files: the real firmware will stream TAPs from SD or
flash a block at a time, so TAP size is limited only by storage. The rules
follow v2's `SAVE_TS` and `LOAD_TS` (`src/TS/tspico_io.py` in the firmware
repo):

- **SAVE:** status F7h, then the header: 00h, the session, 17 bytes and the
  XOR, 21 in all. The card checks the session, the XOR, a zero length and
  room on the tape, and refuses with R, A or J. Otherwise it answers 01h and
  F7h. The data block follows about a second later with no pre-header: FFh,
  the session, the length from the header, and the XOR. The card stores both
  blocks if the XOR is right and answers 01h plus the next pre-load; if not,
  it answers 02h (R) and keeps nothing.
- **LOAD, VERIFY, MERGE:** the card never sees the name, because the ROM
  compares names itself. It serves the next block whose flag matches the
  request, at most one lap of the tape. It checks the length and the XOR
  before sending anything, since the ROM would stop part way through a bad
  block. The flag and the first bytes are queued before READY. The rest
  streams as the Z80 reads it: core 0 keeps the 1 KB queue topped up from
  the tape, far faster than the Z80's one byte every ~47 us. After both of
  the Z80's echoes the card stages 01h (the final status) and 01h (the next
  pre-load). A header it can't find is refused with Report 8 through v2's
  retry: the refusal goes in the flag slot, and the retry's SYNC stages it
  as the first status.
- `tpi:rew` rewinds the tape and `tpi:newtap` empties it. `T` on the USB
  menu lists the blocks, with `>` at the LOAD position.

On board 1 with ROM 2.3: a 27-byte program and a 6,912-byte `SCREEN$` each
saved, loaded back and verified (2 SAVEs, 7 LOADs counting the header the
second search skipped), with nothing refused, lost or given up.

Next: the printer transactions, or on to the MicroPython port (phase 2 of
`docs/v3-firmware-port-plan.md`).

## Board notes from proto1

- nBE (edge A29) needs a pull-up, or a push-pull drive. The 74LVC06 only pulls
  it low; without a pull-up it rises too slowly, and a RAM opcode fetch right
  after a served ROM byte reads wrong bits (see the /BE bug above). Proto1
  runs with a 2.2k bodge from A29 to +5V.

- GP8-GP10 (nAEN_LO, nAEN_HI, nDATA_OE) have no external pull-ups. The RP2350
  resets its pads with pull-downs on, so while the chip is in reset or in
  BOOTSEL, U1, U2 and U3 are all enabled and U1 and U2 both drive MD0-MD7.
  The firmware drives them high first thing in `main()`; the next board
  revision should add 10k pull-ups to 3V3.
- The ESP32-C3 module arrives with blank flash; Zimodem has to be installed.
