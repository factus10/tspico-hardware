# Porting the TS-Pico v2.1 firmware to v3 (RP2350B)

Status: draft for review with the firmware maintainers, 2026-10-01; phase 1 done and phase 3 revised from its results, 2026-10-09; phase 2 found done (firmware #121) and closed, 2026-10-09; phase 3's exit test passed, 2026-10-10; phase 4's exit passed, 2026-10-10; phase 5 done and v2.3.1 released for v3, 2026-10-12; phase 6's SD slots and the TS2050 modem done, the joystick tested on a second board, the OLED moved to an SSD1309 and the /WAIT work dropped, 2026-10-12. Companion to [v3-architecture.md](v3-architecture.md), which is the hardware contract this plan targets. Firmware references are to `tspico-firmware-build` at `dc664a5` (v2.1-17).

## 1. Summary

Most of the v2.1 firmware is protocol and file handling: the `tpi:` commands, LOAD/SAVE, channels, the printer and catalogue code. That code is hardware-independent and carries over. The memory side does not. On v2.1 two PIO programs only steer bank-address and chip-enable lines while the SST39SF040 flash and the SRAM supply the bytes. On v3 there are no memory chips: PIO and DMA have to answer every Z80 memory cycle from RP2350 SRAM. That part is new work, not a port, and it is the project's main technical risk.

The plan therefore runs in four stages:

1. Prove the bus on real hardware in C.
2. Move MicroPython to a version that supports the RP2350, first on v2 hardware where regressions are easy to spot.
3. Put a board layer under the existing firmware so one codebase builds for both boards.
4. Reach v2.1 feature parity on v3 before adding any v3-only feature.

## 2. What we start from

### 2.1 The v2.1 firmware

| Fact | Source |
|---|---|
| MicroPython v1.20.0, plain Pico board, Python modules frozen, no C modules. (v1.29.0 since firmware #121, 2026-10-02; see phase 2.) | `.github/workflows/build.yml:189`, `src/manifest.py` |
| Clocked at 270 MHz | `src/main.py:59` |
| Three PIO state machines: `TS_IO_DUAL` (PIO0 SM0, ports $0E/$0F), `set_ctrl` (/BE, A14_L and the flash/SRAM chip enables) and `sel_bank` (A15-A18 slot lines) | `src/TS/tspico_io.py:398-684`, `src/TS/tspico.py:5693-5704` |
| All FIFO access is polled: no IRQs, no DMA. The status byte is the I/O state machine's Y register, set by writing instructions straight into PIO0 SM0's registers (`MQX`) | `tspico_io.py:115-129` |
| SD shares GPIO 2-4 with Z80 D0-D2, so every SD access tears down and rebuilds the bus state machine (`ACTIVATE_SD`, `DEACTIVATE_SD`, `ACTIVATE_MQ`, about 70 call sites) | `tspico.py:641-1001` |
| The Pico never programs flash. The Z80 does, with SST39SF040 command sequences, through the dock bank; the Pico only streams the bytes (`tpi:blkrcv`) | `tspico.py:3621-3736`, `src/upgrade/updater.asm:252-296` |
| There is no HAL module: pin numbers are literals across `main.py`, `tspico.py`, `tspico_io.py` and `upgrade/main.py` | |
| 34 host tests run under CPython with fake `machine` and `rp2` modules and a 4-deep FIFO model. They test the protocol, not the PIO | `src/test/*_hosttest.py` |
| `src/dev_tspico.py` must stay byte-identical to `src/TS/tspico.py`; CI enforces it | `c21e68b` |

### 2.2 The v3 board (proto1, verified 2026-10-01)

The `firmware/bringup/` self-test passes on board 1:

- crystal, clocks and die temperature;
- QSPI flash (GD25Q128E, ID and erase/program/verify);
- the XL9555 expander and its /INT line;
- no solder bridges on MD0-MD7 or the spare pins;
- the RESET_HOLD pull-up;
- ESP32-C3 EN control, ROM boot banner and the IO9 download strap;
- the LED.

Not yet tested: SD with a card, audio, the joystick and the OLED. In a TS2068 the board now runs everything phase 1 asked for and more; see phase 1's results.

Three hardware facts the firmware must respect:

- **No PSRAM.** U22 is not fitted, so images live in internal SRAM (520 KB) and on the QSPI filesystem.
- **Pin order at startup.** GP8-GP10 have no external pull-ups, so the first instructions must drive them high. `board_safe_init()` in the bring-up firmware does this; the production firmware has to do the same before MicroPython starts anything else.
- **2068 reset.** RESET_HOLD holds the 2068 in reset until the firmware releases it. That replaces the v2.2 555 timer and removes the boot race.
- **/BE needs a pull-up.** nBE (edge A29) is driven by an open-drain 74LVC06 and has no pull-up on proto1, so it rises too slowly: a RAM opcode fetch straight after a served ROM byte reads wrong bits. Proto1 boards need a 2.2k from A29 to +5V; the next revision needs a pull-up or a push-pull drive. (v2 drove /BE push-pull.)

## 3. What changes, layer by layer

| Layer | v2.1 | v3 | Effort |
|---|---|---|---|
| Memory | PIO selects chip and slot; chips serve bytes | PIO classifies the cycle; DMA moves the byte from or to a SRAM image | **New, large** |
| I/O ports | `TS_IO_DUAL`: hardware decodes $0E/$0F to /PICOSEL; PIO sees A0 and R/W | PIO reads the low address byte through the U1/U2 byte mux and decodes $0E/$0F itself; MD direction and nDATA_OE explicit; /WAIT available | Rewrite the PIO; keep the Python contract |
| Status byte, FIFOs | Y register, 4-deep FIFOs, `MQX` direct register writes | No I/O state machine: core 1 answers INs and queues OUTs, and the status byte is a variable. `MQ` becomes a `tsbus` object with the same methods (phase 3) | Medium; the Python contract is kept |
| Slots | 16 x 32 KB in parallel flash or SRAM; `ROM_SM` picks flash or SRAM | Image files on QSPI flash, loaded into SRAM; slot numbering kept | Medium |
| ROM/DCK updates | Z80 programs flash (`romupdate.tap`, `dckupdate.tap`, upgrade UF2, `updater.asm`) | Pico writes the slot file directly | Medium; simplification |
| SD | SPI0 on GP2-4, shared with the data bus | SPI0 on GP32/37-39, dedicated; can stay mounted | Small, and removes the suspected cause of "Report D" |
| LED | GP25, about 48 call sites | XL9555 bit 5 over I2C (about 100 µs per write) | Small; shim needed |
| 2068 reset | 555 timer, firmware not involved | RESET_HOLD on GP29, released by firmware | Small |
| Clock | 270 MHz | 250 MHz (core at 1.20 V, flash clock divider 3); the bus timing needs it | Measured in phase 1 |
| Build, CI | MicroPython v1.29.0 (v1.20 until #121), RP2040 | MicroPython v1.29.0, custom board, C user module | Medium |
| Web updater | RP2040 family ID only, 2 MB flash, `RPI-RP2` drive | Accept the RP2350 family (`rp2350-arm-s`), 16 MB, `RP2350` drive | Small |

## 4. Plan

Each phase ends with a check on hardware that the next phase depends on.

### Phase 0: Decisions and groundwork

Settle the open questions in section 6, and the four in `v3-architecture.md` section 11. Get a logic analyser on the local bus. Agree where v3 work happens; this plan recommends the existing repo with a board layer (section 6, decision 1).

Exit: decisions recorded, a v3 board plugged into a 2068 on the bench.

### Phase 1: Bus spike in C (the critical path)

Extend `firmware/bringup/` into a bus test. Stay in C on the bare Pico SDK so timing is under full control and nothing else runs.

1. **Serve memory.** Load the genuine HOME ROM (`ROMs/GENUINE-2068-home.bin` in the firmware repo) into a 64 KB-aligned SRAM buffer. Run a memory state machine that, on each memory strobe:
   - reads A15-A8, then A7-A0, through the byte mux;
   - applies the class rule of `v3-architecture.md` section 3.1;
   - hands a 32-bit pointer to a two-channel DMA chain that returns the byte.

   Release RESET_HOLD. **Exit:** the 2068 boots to its copyright screen from the card. Scope the opcode-fetch timing against the 375 ns budget at 150 MHz.
2. **EXROM and DOCK.** Serve the genuine EXROM, then a 64 KB DCK image, including writes into DCK. **Exit:** a cartridge image runs, and a BASIC POKE/PEEK loop into DOCK RAM agrees.
3. **I/O ports.** Add the $0E/$0F responder with the v2.1 behaviour:
   - a read of $0E pops TX, or gives $00 if it is empty;
   - a read of $0F returns Y without consuming anything;
   - a write to either port pushes a 9-bit word to RX and clears Y (auto-busy).

   It has to share the nAEN pins and the MD bus with the memory state machine; see risk R2. **Exit:** a BASIC loopback (OUT then IN through a C echo) runs a long soak with no errors, with /WAIT both on and off.
4. **The TS-Pico ROM.** Serve `TSPICO-21.ROM` (32 KB: HOME plus a 16 KB EXROM). **Exit:** the 2068 boots into ROM 2.1, and the SYNC handshake (`OUT ($0F),3`, wait for READY+IDLE) completes against a minimal C responder.

All state machines go on PIO0 and PIO1 with GPIOBASE 0; every bus pin is in GP0-GP23. The DMA chain and any interrupt handler must run from SRAM, not flash. Flash writes stall execute-in-place, and memory service has to continue through them; v2.1 already works around the same stall on core 1 (`tspico.py:6409`).

**Results (2026-10-07 to 10-09, board 1 in a real 2068).** All four steps pass, and the C bus test went further: the ROM 2.2/2.3 protocol responder, LOAD and SAVE to a tape in RAM, and the printer (LPRINT, LLIST, COPY) all work against the real ROM. The details, and what each step took, are in `firmware/bringup/README.md`. What the later phases need to know:

- **Clock.** 250 MHz. An opcode fetch needs the byte well under about 156 ns after the strobe; the card gets it there in about 124.
- **Bank shadow, not /ROSCS and /EXROM.** The class of each read comes from a shadow of ports F4h and FFh kept by core 1, so /BE goes out about 50 ns after the strobe. With /BE from the 2068's own select lines it came too late for EXROM.
- **PIO0 and PIO1 are full.** PIO0: `serve` (27 instructions) and `io_drive` (5). PIO1: `addr_read`, `mem_write` and `io_snoop` (13 + 11 + 8).
- **No I/O state machine.** OUTs come in through `io_snoop`, which reads every I/O write (the bank shadow needs them all anyway). Core 1 takes INs from a GPIO edge interrupt on /IORD: it reads the port through a GPIO override on U1 and, for $0E/$0F, hands the reply to `io_drive` and enables U3. The worst time from the interrupt to U3 on is 320 ns of about 600. The status byte and the TX and RX queues (1 KB each) are core 1 variables.
- **Long IN strobes.** The 2068 stretches some IN cycles by whole T-states, up to 2.4 µs in all, when the IN runs from RAM or the EXROM: the SCLD drives the Z80's clock and stops it while it updates the screen. The handler keeps U3 on until /IORD rises, with a 4 µs guard counted in core cycles. The first guard (2 µs on the 1 µs timer) could turn U3 off before the Z80 read the reply. `tsbus` keeps the cycle-counted guard (`firmware/bringup/README.md`, "Long IN strobes").
- **Core 1 belongs to the bus.** It runs from SRAM with its interrupt at top priority, and keeps the bank shadow, DOCK writes and the IN replies. Nothing else may run there.
- **/BE pull-up.** See section 2.2. It was found by ROM 2.2's key click, which runs from the RAM bank-switch code on every keypress.

### Phase 2: MicroPython upgrade on v2 hardware

Move the existing v2 build from v1.20.0 to the release that phase 3 will use on the RP2350. Change nothing else, so any regression is clearly MicroPython's.

- Rebuild `dev_tspico.mpy` with the matching `mpy-cross` (the bytecode version changes).
- Re-check `rp2.asm_pio_encode`, which `MQX` uses.
- Check `sm.exec` timing; `MQX` exists because v1.20's `sm.exec` took 9.6 ms.
- Check free RAM on the RP2040; boot logs `gc.mem_free()` at 11 points.

**Exit:** host tests green, and a v2.2 board passes the usual hardware checks (LOAD, SAVE, `tpi:` commands, BLKRCV, ZX48 mode).

If the newer MicroPython costs too much RAM on the RP2040, v2 stays pinned at v1.20 and CI builds the two boards against different MicroPython versions.

**Results (done, 2026-10-09).** The firmware repo had already made this move before phase 1 started: #121 (merged 2026-10-02) moved the v2 build from v1.20.0 to **v1.29.0**, and releases 2.1.1, 2.2, 2.2.1 and 2.3 have shipped on it. Phase 3 uses the same release. Item by item:

- **Release.** v1.29.0 is the newest stable release (v1.30.0 is only a preview tag). It supports the RP2350B: there are 48-GPIO boards in the tree (`WEACTSTUDIO_RP2350B_CORE`, `WAVESHARE_RP2350B_CORE`, with `PICO_NUM_GPIOS 48`), `rp2350b_af.csv`, and `machine.Pin` handles pins above 31. It supports PIO GPIOBASE: `rp2.PIO.gpio_base(0|16)`, with `StateMachine` pin bases checked against it (`ports/rp2/rp2_pio.c`). `tsbus` sets the base from C anyway. (The RP2350B is the QFN-80 package with 48 GPIOs, not a 48-pin package.)
- **pico-sdk.** v1.29.0 bundles pico-sdk 2.3.0. The phase 1 bring-up was built against 2.1.1, so rebuild it on 2.3.0 at the start of phase 3, to keep an SDK change apart from the move into MicroPython. *Done 2026-10-09:* `bus_card` on 2.3.0 passes phase 1's checks on board 1, with the same memory layout, the same RAM-resident code and the same IN timing (`firmware/bringup/README.md`, "pico-sdk 2.3.0").
- **`mpy-cross`.** CI builds `mpy-cross` from the same v1.29.0 tree for `dev_tspico.mpy` (mpy v6.3); `build-dev-mpy.sh` pins `mpy-cross==1.29.*`. `main.py` falls back to the frozen firmware if a `.mpy` from another version is present.
- **`asm_pio_encode`.** Same signature, `(instr, sideset_count, sideset_opt)`, with the count including the enable bit, which is how `MQX` calls it.
- **`sm.exec`.** v1.29's `exec()` still runs the Python assembler on every call given text. Measured on a v2.2 board at 270 MHz (`src/test/mp_timing_bench.py`): `exec(text)` 5.8-7.2 ms (9.6 ms on v1.20), `exec(int)` 5.1 µs, `MQX` about 33 µs. `MQX` stays on v2; on v3 it becomes a `tsbus` call (phase 3).
- **Per-byte Python costs** rose on v1.29 (a function call 5.6 to 7.3 µs). #121 fixed the ZX48 `tpi:` reply. #126-#128 moved the LOAD and pre-header paths to DMA, and #209 moved BLKRCV, which had been broken on v1.29 until then.
- **RAM.** Free RAM at boot is 181 kB on v1.29, against 106 kB on v1.20, so v2 is not pinned at v1.20.
- **Exit.** Host tests green. A v2.2 board passed LOAD, SAVE, `tpi:` commands and ZX48 in #121, and BLKRCV (the ROM update) after #209 (2026-10-06).

A side effect to keep in mind: v1.29's LittleFS writes on-disk format 2.1, which v1.20 can't read, so flashing a v1.20 UF2 over v1.29 reformats the Pico's filesystem.

### Phase 3: MicroPython board and the `tsbus` C module

- **Board definition.** Add `TSPICO_V3` to `ports/rp2/boards`, reusing `firmware/bringup/boards/tspico_v3.h` (RP2350B, 16 MB flash, 12 MHz crystal). Give the LittleFS filesystem most of the 16 MB for slot images, and leave PSRAM support off.
- **`tsbus` C user module.** It wraps the phase 1 PIO programs, DMA chains and core 1 code (`firmware/bringup/bus_card.pio` and `bus_card.c`):
  - safe pin init (first, before anything else);
  - image buffers at fixed addresses, kept outside the MicroPython heap (phase 1 interleaves HOME, EXROM and DOCK four bytes per address at `0x20040000`, 256 KB);
  - `load_slot(kind, bytes)` and `switch_slot(...)` under a running Z80;
  - RESET_HOLD control;
  - claims its PIO state machines and DMA channels through the SDK so MicroPython's `rp2` module cannot hand them out again;
  - starts core 1 itself, with the bus code and its interrupt handler in SRAM.
- **Core 1 is `tsbus`'s.** v2.1 runs `BLINK_LED` and the log writer on core 1 with `_thread`. On v3 they move to core 0 (an idle-loop hook or a timer), and the v3 build must not start `_thread` work on core 1. The flash-write stall that v2.1 works around on core 1 (`tspico.py:6409`) still applies: LittleFS writes stall execute-in-place, so core 1's code must be entirely in SRAM, which phase 1's already is.
- **MQ is a `tsbus` object, not a state machine.** Both PIO blocks are full and the I/O path is core 1 plus queues, so `rp2.StateMachine` is out. `tsbus` provides an object with `MQ`'s methods (`put`, `get`, `tx_fifo`, `rx_fifo`) and the status calls behind `MQ_STATUS`, `MQ_READY` and `MQX`, over core 1's queues and status byte. Auto-busy and the 9-bit RX words (bit 8 for $0F) keep their meaning, so the protocol code and its host tests carry over. Two things change:
  - **Depth.** The queues are 1 KB, not 4 entries. Code that relied on a full 4-deep FIFO to pace itself (`TX_ROOM`, `CMD_PUT`) keeps working, but should be checked; a `tx_fifo()` that reports the real depth is safer than one that pretends to be 4.
  - **Blocks instead of DMA.** v2.1 streams LOAD and BLKRCV blocks into the PIO FIFO by DMA because Python can't keep a 4-deep FIFO fed. On v3 there is no PIO FIFO to feed. `tsbus` takes a whole block instead, as a buffer or a pointer and length (for example `MQ.put_block(buf)`), and C streams it into the queue as the Z80 reads, as phase 1's LOAD does. Python never handles single bytes on these paths.
- **CI.** Add a v3 build job: board `TSPICO_V3`, `USER_C_MODULES=tsbus`, its own artefact name.

**Exit:** the v3 UF2 boots to the REPL. From the REPL, `tsbus` serves the genuine ROM, the 2068 boots, and an `MQ` loopback works.

**Results (2026-10-09 to 10-10, board 1 in a real 2068; firmware #234, #235, #236).** The exit test passes. The details are in the firmware repo's programmer's reference (`docs/reference/firmware/board-v3.md` and `tsbus.md`). What phase 4 needs to know:

- **The board** is `src/boards/TSPICO_V3`, built from outside the MicroPython tree with `BOARD_DIR`. CI's `build-v3` job uploads `tspico-v3-firmware-uf2`, and `tools/pico-serial.py flash --v3` installs it. The filesystem is 14 MB.
  - Safe pins and the XL9555's outputs are set in `MICROPY_BOARD_STARTUP`, right after the clock.
  - Default `UART`/`I2C`/`SPI` pins point at the card's wiring, because the port's defaults land on MD0-MD7 and the buffer enables.
- **Memory.** The GC heap ends at `0x20040000` (about 196 KB), so the top 256 KB of SRAM holds the images.
  - This is a linker override that a deferred CMake call puts ahead of MicroPython's own override directories.
  - The C stack is scratch Y's 8 KB.
  - SRAM is striped across all eight banks, but measured contention between the interpreter and the DMA is negligible.
- **Core 1** runs only `tsbus`, from SRAM, with `_thread` off.
  - It has its own vector table, because MicroPython keeps `machine.Pin`'s handler on `IO_IRQ_BANK0` in the table both cores start with.
  - It is not a multicore lockout victim, so LittleFS writes don't pause it.
  - Serving carried on through 256 KB of writes, and through a soft reset.
- **The clock.** The board boots at 150 MHz, and `tsbus.start()` raises it to 250 MHz at 1.20 V, with the flash at most 84 MHz (divider 3). Two traps:
  - **Booting at 250 MHz hangs before USB.** The SDK sets the clock before MicroPython sets the flash divider.
  - **boot2's divider must be 3.** After every flash erase or program, the SDK re-enables XIP through boot2 before MicroPython restores its own divider, in code that runs from flash. With `PICO_FLASH_SPI_CLKDIV` 2, the first LittleFS write at 250 MHz hung core 0.
  - Nothing yet stops Python calling `machine.freq()` after `start()`, which would break the bus timing.
- **`tsbus`** runs phase 1's five PIO programs unchanged (a copy of `bus_card.pio`), and the IN handler with the 4 µs cycle-counted guard.
  - API: `start`, `load(slot, data)`, `serve`, `exrom`, `dock`, `hold`, `stats`.
  - With the genuine ROMs, each boot took the same 1,988 EXROM and 12 DOCK reads as phase 1.
  - The card's copyright marker appeared on screen, and typing worked.
  - A BASIC DOCK test read 256 bytes back with 0 errors.
- **`MQ`** is `tsbus.MQ()`:
  - `put`, `get` (9-bit words), `tx_fifo` and `rx_fifo` (the real levels, up to 1,024), `put_block`, `status`, and `exec` for exactly the strings `MQX` sends; `active` does nothing.
  - `exec` gives `MQ_STATUS`'s F7h, FBh and FFh.
  - The BASIC loopback (`OUT 14`, wait for 255 on `IN 15`, `IN 14`) over 0-255 had 0 errors, with a worst response of 324 ns.
  - **For phase 4:** the pacing code that relied on a full 4-deep FIFO (`TX_ROOM`, `CMD_PUT`) has to be checked against queues of 1,024.
- **The SCLD keeps its bank registers through a Z80 reset.** After a crashed boot, the next served boot fails too. To recover, power-cycle the 2068 and then boot it from its own ROM first (shadow mode) before serving.
- **Still to do in phase 3:** `switch_slot(...)` under a running Z80. `tsbus.load` already writes a slot.

### Phase 4: Board layer in the shared firmware

Introduce `TS/board.py` with a v2 and a v3 implementation, selected at build time. Move every hardware touch behind it:

| Board call | Replaces | v3 behaviour |
|---|---|---|
| `board.early_init()` | the pin block in `main.py:44-57` | `tsbus` safe init; expander init |
| `board.make_mq()` | the 7 `StateMachine(...)` calls for the bus | the new PIO program on PIO0 SM0 |
| `board.sd_acquire()`, `board.sd_release()` | `ACTIVATE_SD`, `DEACTIVATE_SD`, `ACTIVATE_MQ`, `ENA_SD` | SD stays mounted; acquire just checks the mount |
| `board.led` (`on`, `off`, `toggle`, `value`) | `Pin(25)` | XL9555 bit 5, owned by core 0 |
| `board.map_slots(rom, dock)` | `ROM.put` and `BANK.put` in `MEMBOOT`, `MEMDOCK` and boot | load the slot files into SRAM and switch |
| `board.release_2068()`, `board.reset_2068()` | nothing (the 555) | RESET_HOLD |

v2 behaviour must be unchanged: the host tests pass, and a v2.2 board passes its hardware checks. On v3, `SD_CALL` and `CH_CALL` stop rebuilding `MQ`. That is the dedicated SPI bus paying off, and it removes the race behind the "#40" ordering in `SAVE_TS` (`tspico_io.py:2379-2391`).

LED calls on v3 cost about 100 µs each over I2C. Keep them out of the timing-critical loops listed in `src/CLAUDE.md` (`RX_CAPTURE`, `RX_BLOCK`, `TX_ROOM`, the LOAD and BLKRCV streams). BLINK_LED runs on core 1 today; on v3 it moves to core 0's idle loop (phase 3: core 1 belongs to `tsbus`).

**Exit:** both UF2s build from one tree, and both boards pass the same command list.

**Results (2026-10-10, tspico-firmware-build #239-#244; design in its `docs/v3-board-layer-proposal.md`):**

- **Exit passed.** Firmware `main` (83b06e1) ran the same command list on a v2.2 board and on proto1:
  - `tpi:info`, `CAT`, `tpi:dir`;
  - a LOAD and SAVE round trip of BASIC, SCREEN$ and 16K CODE, byte-exact on both boards (`src/test/sd_roundtrip.py`);
  - BREAK mid-LOAD;
  - folders;
  - a card pulled and put back;
  - the printer capture.
  
  The exceptions, deferred to phase 5: `tpi:boot`, `tpi:dock` and `tpi:blkrcv` refuse on v3 with Report F, and ZX48 needs the Spectrum ROM's slot. On v2 ZX48 passed, including a byte-exact SAVE in Spectrum mode.
- **Where it differs from the table above:**
  - The board is chosen at run time (`from tsbus import MQ` succeeds), not at build time, so one set of frozen modules serves both boards.
  - SD still mounts and unmounts per command on v3. The dedicated pins mean `sd_take_bus` keeps `MQ`, and `tsbus` serves the 2068 throughout.
  - There is no shadow boot: the 2068 is held in reset until the ROM file is loaded into SRAM.
  - `map_slots` is a no-op until phase 5.
- **The deep queues.** `put_block(buf, wait_ms)` in `tsbus` is v3's `STREAM_DMA`; Python never handles single bytes on the block paths. A host test reruns the v2 Z80 models (LOAD, commands, SAVE, ZX48) on 1,024-entry queues. It found one bug: in ZX48 mode a block was "sent" with up to 1,020 bytes unread. Fixed.
- **The LED** (D4, XL9555 bit 5) is dimmed by two soft timers. `config.ini`'s `LED_BRIGHTNESS` is 1-100 %, default 5.
- **SD hot insert** ([#21](https://github.com/factus10/tspico-hardware/issues/21)): two cards died going into a running proto1. The firmware had held CS, SCK and MOSI driven between commands, and clocked an empty socket for about 3.6 s each time it looked; the detect switch was never read. Now:
  - the switch is read before any SD line is touched;
  - a new card gets 250 ms to settle;
  - the lines are plain inputs while no card is mounted, as v2's are.
  
  Three hot inserts were clean afterwards.

### Phase 5: Feature parity on v3

1. **Boot order.** Run safe init, then load the configured slots from QSPI into SRAM, then start the memory and I/O state machines, then release RESET_HOLD. The 2068 no longer needs to wait out a 2-3 s reset pulse.
2. **Slots.** Keep the 16-slot numbering so `tpi:memboot`, `tpi:memdock` and existing BASIC keep working. Each slot becomes a file, for example `/slots/NN.bin`. `tools/build-flash.py` and `flash/manifest.json` emit slot files instead of a 512 KB image. `ROM_SM`'s flash/SRAM choice maps to persistent or volatile: a "flash" slot is written back to its file, a "SRAM" slot is lost at power-off. `DCK_IMAGE` (`tspico.py:1194-1263`) already produces the flat 64 KB DCK image the DMA path needs.
3. **ROM and DCK updates.** A new Pico-side command writes a mounted `.ROM`, `.BIN` or `.DCK` straight into a slot file. `romupdate.tap`, `dckupdate.tap`, the upgrade UF2 and `updater.asm` stay v2-only. Whether v3 also emulates the SST39SF040 command sequence, for third-party tools that program the cartridge from the Z80, is decision 4 in section 6.
4. **Everything else unchanged in behaviour.** That covers LOAD, SAVE, the `tpi:` commands, channels, the printer, ZX48 mode, logging and the pre-load chain. Run the full v2 hardware checklist on v3.
5. **Web updater.** Accept the RP2350 family ID, 16 MB flash and the `RP2350` drive name. The vendored picoflash already has an RP2350 reboot path (`web-updater/vendor/picoflash/connection.js:173-239`). Ship an RP2350 `flash_nuke`.

**Exit:** v3 passes the v2 hardware checklist. The user manual gains a v3 section. A v3 release is tagged.

**Results (2026-10-12, tspico-firmware-build #247-#261; design in its `docs/v3-slots-proposal.md`):**

- **Exit passed.**
  - **The checklist:** `tools/hwcheck.py` (#253, #256) runs the v2 hardware checklist on either board, mostly unattended. On proto1 the automatic part passed 21/21 and the manual part passed, after the two fixes below.
  - **The manual:** Appendix F (#251).
  - **The release:** firmware 2.3.1 on ROM 2.3, released 2026-10-12 with `firmware-v3.uf2` and `v3-slots.zip`.
- **Slots** (#248, #249):
  - **The files:** `/slots/F00.bin` to `F15.bin` are the flash slots, and `S00.bin` to `S15.bin` the SRAM slots, which are deleted at every boot.
  - **The numbering** is v2's, so `tpi:boot`, `tpi:dock` and existing BASIC work unchanged.
  - **Booting:** the ROM is loaded into SRAM before RESET_HOLD is released. If the configured slot is empty, the boot falls back to flash slot 1, then to `/rom/TSPICO-23.ROM`.
  - **`tpi:boot`** resets the 2068 into the new ROM rather than swapping under the running Z80.
  - **`tpi:dock`** is live. A flash dock is read-only, as v2's chip is. A RAM dock is saved back to its files before it is switched away, so an even RAM slot pair gives a program 64K of RAM in the dock.
  - **ZX48 mode** passed on the card, including a byte-exact SAVE.
- **ROM and DCK updates** (#250): the v3 updater tapes `romupd3.tap` and `dckupd3.tap` keep romupdate's questions, warn before slot 0, and end in `tpi:blkrcv`. The Pico then writes the slot file itself. Writing the booted slot is safe on v3, because the 2068 runs from the SRAM image.
- **The updaters** (#252, #260):
  - **The web updater** and **`TS-Pico-Updater.exe`** recognise the card by its MicroPython machine string or its RP2350 drive.
  - **Never a wipe:** the slots share the flash with the firmware, so there is no RP2350 `flash_nuke`. This replaces item 5's plan.
  - **Firmware:** they install the RP2350 UF2, after checking its family ID.
  - **Slots:** slots 0 and 1 are written every time; the others only where the card has none, so a user's ROMs are kept.
- **Found and fixed on the way:**
  - **`tpi:dock` answered before the dock had switched** (#253): a program's next PEEK could read an empty dock.
  - **The APB bridge stalls during flash writes** (#254, #255). While core 0 erases or programs flash, any access through the RP2350's APB bridge can take about 4 µs. The IN path's GPIO IRQ and enable overrides went through APB, so a ZX48 `LOAD "tpi:..."` read a bogus status and crashed the 2068. The IN path now uses only PIO and SIO: `iord_watch` on PIO2 raises the IRQ, and U1/U3 are driven by a spare PIO1 state machine. The stress test that followed read `IN 15` 7.5 million times during flash writes, with 0 bad reads. **Rule:** nothing on core 1's bus path may touch APB.
  - **Power-cycling the 2068 with the card on USB** (#257). The card stays powered, so the 2068 came up frozen until TS Reset. Core 1 now:
    - holds RESET_HOLD while the 2068 is off (/MEMWR, /IORD and /IOWR all low) and for 100 ms after it comes back;
    - lets go of the bus when /MEMRD stops for 100 µs;
    - ignores port F4/FF writes while the bus is idle, which were power-down glitches.
    
    The bank shadow is cleared at power-up only, since the SCLD keeps its registers through a reset. Why the 2068's own power-on reset fails with the card attached is still open: with the 2068 off, every bus input reads 0 V.
- **Not a firmware bug:** a 64K AROS cartridge (Sinistar) crashed within seconds on one 2068 with both v2.2 and v3, and runs cleanly on a second 2068. That first machine has a pattern-sensitive fault that RAM and bus-integrity tests don't show. Lesson: try a second 2068 early.

### Phase 6: v3-only features (after parity)

Each of these is independent and can be taken in any order:

- Kempston joystick at $1F, from expander port 1 on /INT (*firmware done; the DE-9 footprint needs a redesign*, below);
- OLED status display (*now an SSD1309 on I2C; waits for the redone board*, below);
- ESP32-C3: an esptool bridge to install Zimodem through the card's USB (the RP2350 already controls EN and IO9), then the 8251 emulation at $73/$77 (*done*, below);
- tape EAR out and SPK/TAP in;
- ~~protocol work that /WAIT makes possible~~: *dropped, 2026-10-12* (below).

**Done so far:**

- **Slots from the SD card** (firmware #263): MEM 3 boots and docks straight from `/slots/Fnn.bin` on the SD card, falling back to the flash slot of the same number. This revises decision 6's "no SD override": the flash slots are unchanged, and the SD card is a third bank chosen with MEM 3.
- **The TS2050 modem** (design: firmware `docs/v3-modem-proposal.md`, #264):
  - **Port 0 shared** (#266). A shadow of the XL9555's port 0, so the LED, WIFI_EN, WIFI_DL (IO9) and, on proto2, SD_PWR_EN each change only their own bit.
  - **The 8251 at $73/$77** (#267), emulated on core 1 and bridged to Zimodem over UART0 by DMA. It is plain C with a host test, and RX is paced at 300 baud by default.
  - **TS2050 mode** (#268):
    - MTERM's DTR dial pulses become `ATD` to a Zimodem phonebook entry;
    - `CONNECT` raises DSR (carrier);
    - `NO CARRIER` or DTR off hangs up.

    Hayes mode passes AT commands through, for setting up WiFi and the phonebook. Unmodified MTERM/T dials, connects, and hangs up both ways.
  - **`tpi:modem`, the config keys** (`MODEM_MODE`, `MODEM_BAUD`, `MODEM_IDLE_MIN`), and **the ESP32 powered on demand** (#269).
  - **The user manual's v3 build** (#270, #271): a CI artifact until the card ships. Its Appendix F is the modem.
  - **Installing Zimodem:**
    - Zimodem 4.0.3 is built in CI and published to the updater (#272).
    - `tsbus.esp_relay` joins the card's USB to the ESP32's ROM loader (#273).
    - The web updater (#274) and the Windows exe (#275) write Zimodem through the relay with their own loader clients and check its MD5. Zimodem's WiFi and phonebook settings stay.
  - **Notes on the 2068's modem software:** MTERM, MTERM II and the BASIC dialers (#265, `docs/ts2050-software-notes.md`).
  - **Still open:** what RTS does on a real 2050, and Specterm-64, ZX-Term*80 and the 2068 BBS, which are untested.
- **The Kempston joystick** (firmware branch `v3-kempston`, not yet merged): core 1 answers IN $1F with a byte core 0 keeps current. The expander's /INT (GP35) triggers a read of port 1, which is converted to the Kempston byte 000FUDLR; fire 2 counts as fire. `config.ini` has `KEMPSTON` (on by default).
  - **On proto1**, the DE-9's switches never reached the expander: port 1 read 3Fh whatever the stick did, even read directly over I2C. The joystick part of the board needs a redesign.
  - **On a second board** with the socket mounted on the back, every direction gave its bit (up 8, down 4, left 2, right 1, fire 16), and the IRQ path followed each movement within 10 ms.
  - **Left:** `IN 31` and a Kempston game on a 2068, then the PR.
- **The OLED** (design: firmware `docs/v3-oled-proposal.md`, #277): the panel is now a 128x64 **SSD1309 on I2C**, not the Waveshare SSD1351 on SPI that J3 was laid out for. The board is being redone for it.
  - **Proved on proto1**, wired to J3 by four wires with the power pins crossed: the panel answers at 3Ch on I2C1 (GP43 SCL, GP42 SDA) at 400 kHz. It ignores horizontal addressing, so it is written a page at a time, and a full frame takes about 30 ms.
  - **The firmware waits for the new board,** which fixes the I2C pins and the header. A header in the modules' own order (GND VCC SCL SDA) would let one plug straight in.
- **/WAIT protocol work: dropped** (2026-10-12). The protocol runs fast and reliably without blocking reads, so the ROM revision it needs isn't worth it. It can be revisited if an empty FIFO's "J" ever becomes a reported problem.

### Phase 7: AY sound

AY at $FFFD/$BFFD in C on core 1, with PWM audio. Moved out of phase 6 on 2026-10-12.

## 5. Risks

- **R1. Memory emulation timing.** This is the risk named in `v3-architecture.md` section 10, and proto1 is its first test on a 2068 (I found no record of the breadboard test in `PLAN.md` having been run). Phase 1 step 1 measures it first. Fallbacks, cheapest first:
  - overclock the RP2350;
  - pre-assert /WAIT on DOCK reads;
  - fewer PIO cycles in the mux sequence.
- **R2. Two state machines on one bus.** Memory and I/O cycles never overlap, but both state machines drive nAEN_LO/HI and MD. They need optional side-set, or pindir changes made only inside their own cycle. The alternative is one front-end state machine that waits on all four strobes and dispatches. *Resolved in phase 1:* five programs share the pins with optional side-set and no side-set on idle waits (a stalled instruction keeps asserting its side-set), and INs go to core 1.
- **R3. Port decode fidelity.** v2.2 decodes $0E/$0F in 74LS glue. If that decode was partial, software may rely on mirror addresses that a full low-byte decode will not answer. Check the v2.2 decode before phase 1 step 3.
- **R4. Bank-rule fidelity.** The "low 16K read" condition is now computed from A14, A15 and /RD in PIO. Test every slot class with the existing ROM images, including `OUT 244,3` (the Spectrum ROM through the DOCK).
- **R5. MicroPython upgrade regressions** on v2 (RAM, `sm.exec`, `asm_pio_encode`). Phase 2 isolates them. Confirm RP2350B 48-pin and PIO GPIOBASE support in the chosen MicroPython release before committing to it. *Resolved in phase 2:* v1.29.0 supports both; RAM rose, `sm.exec` is still slow with text (`MQX` stays), and the per-byte slowdowns were fixed in the firmware.
- **R6. Flash-write stalls.** LittleFS writes stall execute-in-place on the RP2350 just as on the RP2040. The memory path must not depend on flash. *Phase 1:* the memory path and core 1 run from SRAM, and the I/O queues are 1 KB, so a stall of a few milliseconds no longer drops bytes. Core 0's protocol code still has to avoid long stalls in the middle of a block.
- **R7. Hardware.** GP8-GP10 lack pull-ups (fixed in firmware now, in the next board revision later). The ESP32-C3 ships with blank flash.

## 6. Decisions needed

1. **One codebase or a fork?** Recommendation: one repo, with the board layer of phase 4. v2 users keep getting fixes, and the 34 host tests cover both boards.
2. **Where the bus layer lives.** Recommendation: a C user module (`tsbus`), with the I/O FIFOs still exposed as an `rp2.StateMachine`. The PIO and DMA could be set up from Python with `rp2.DMA`, but timing, alignment and SM/DMA ownership are easier to guarantee in C, and the AY emulation needs C anyway (`PLAN.md`, risks).
3. **MicroPython version for both boards,** or v2 pinned at v1.20 (phase 2 decides). *Decided:* v1.29.0 for both boards.
4. **Z80-side writes into ROM slots** (`v3-architecture.md` section 11, question 4): emulate the SST39SF040 command sequence, provide a Pico-side save command, or both. Recommendation: the save command for parity; emulation only if a real tool needs it. *Decided (phase 5):* the Pico-side command only. A v3 updater tape asks romupdate's questions and ends in `tpi:blkrcv`, and the Pico writes the slot file. SST39SF040 emulation is left out until a real tool needs it.
5. **Ports enabled at first release:** only $0E/$0F, or $1C-$1E from the start (section 11, question 2).
6. **Slot storage layout:** file names, whether SD can override QSPI slots, and config migration from a v2 `config.ini`. *Decided (phase 5):*
   - **File names:** `/slots/Fnn.bin` for the flash slots and `/slots/Snn.bin` for the SRAM slots, which are deleted at boot.
   - **No SD override:** slots live only on the card's flash. A ROM or DCK on SD goes into a slot through the updater tapes. *Revised in phase 6 (firmware #263):* MEM 3 reads the slots straight from the SD card, falling back to the flash; the flash slots stay as decided here.
   - **No config migration:** `config.ini` keeps v2's keys (`ROM_SM`, `ROM_SLOT`, `DCK_SLOT`) with the same meaning.
   - **A v2.2 flash image** converts slot for slot (`build-flash.py --slots`).
