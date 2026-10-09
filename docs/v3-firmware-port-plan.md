# Porting the TS-Pico v2.1 firmware to v3 (RP2350B)

Status: draft for review with the firmware maintainers, 2026-10-01; phase 1 done and phase 3 revised from its results, 2026-10-09. Companion to [v3-architecture.md](v3-architecture.md), which is the hardware contract this plan targets. Firmware references are to `tspico-firmware-build` at `dc664a5` (v2.1-17).

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
| MicroPython v1.20.0, plain Pico board, Python modules frozen, no C modules | `.github/workflows/build.yml:189`, `src/manifest.py` |
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
| Build, CI | MicroPython v1.20, RP2040 | A MicroPython release with RP2350 support, custom board, C user module | Medium |
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

### Phase 5: Feature parity on v3

1. **Boot order.** Run safe init, then load the configured slots from QSPI into SRAM, then start the memory and I/O state machines, then release RESET_HOLD. The 2068 no longer needs to wait out a 2-3 s reset pulse.
2. **Slots.** Keep the 16-slot numbering so `tpi:memboot`, `tpi:memdock` and existing BASIC keep working. Each slot becomes a file, for example `/slots/NN.bin`. `tools/build-flash.py` and `flash/manifest.json` emit slot files instead of a 512 KB image. `ROM_SM`'s flash/SRAM choice maps to persistent or volatile: a "flash" slot is written back to its file, a "SRAM" slot is lost at power-off. `DCK_IMAGE` (`tspico.py:1194-1263`) already produces the flat 64 KB DCK image the DMA path needs.
3. **ROM and DCK updates.** A new Pico-side command writes a mounted `.ROM`, `.BIN` or `.DCK` straight into a slot file. `romupdate.tap`, `dckupdate.tap`, the upgrade UF2 and `updater.asm` stay v2-only. Whether v3 also emulates the SST39SF040 command sequence, for third-party tools that program the cartridge from the Z80, is decision 4 in section 6.
4. **Everything else unchanged in behaviour.** That covers LOAD, SAVE, the `tpi:` commands, channels, the printer, ZX48 mode, logging and the pre-load chain. Run the full v2 hardware checklist on v3.
5. **Web updater.** Accept the RP2350 family ID, 16 MB flash and the `RP2350` drive name. The vendored picoflash already has an RP2350 reboot path (`web-updater/vendor/picoflash/connection.js:173-239`). Ship an RP2350 `flash_nuke`.

**Exit:** v3 passes the v2 hardware checklist. The user manual gains a v3 section. A v3 release is tagged.

### Phase 6: v3-only features (after parity)

Each of these is independent and can be taken in any order:

- Kempston joystick at $1F, from expander port 1 on /INT;
- OLED status display;
- ESP32-C3: an esptool bridge to install Zimodem through the card's USB (the RP2350 already controls EN and IO9), then the 8251 emulation at $73/$77;
- AY at $FFFD/$BFFD in C on core 1, with PWM audio;
- tape EAR out and SPK/TAP in;
- protocol work that /WAIT makes possible: blocking pulls, so an empty FIFO no longer returns $00 and raises "J". This changes the protocol contract (`docs/PROTOCOL_V2_PROPOSAL.md`), so it needs a ROM revision and is opt-in.

## 5. Risks

- **R1. Memory emulation timing.** This is the risk named in `v3-architecture.md` section 10, and proto1 is its first test on a 2068 (I found no record of the breadboard test in `PLAN.md` having been run). Phase 1 step 1 measures it first. Fallbacks, cheapest first:
  - overclock the RP2350;
  - pre-assert /WAIT on DOCK reads;
  - fewer PIO cycles in the mux sequence.
- **R2. Two state machines on one bus.** Memory and I/O cycles never overlap, but both state machines drive nAEN_LO/HI and MD. They need optional side-set, or pindir changes made only inside their own cycle. The alternative is one front-end state machine that waits on all four strobes and dispatches. *Resolved in phase 1:* five programs share the pins with optional side-set and no side-set on idle waits (a stalled instruction keeps asserting its side-set), and INs go to core 1.
- **R3. Port decode fidelity.** v2.2 decodes $0E/$0F in 74LS glue. If that decode was partial, software may rely on mirror addresses that a full low-byte decode will not answer. Check the v2.2 decode before phase 1 step 3.
- **R4. Bank-rule fidelity.** The "low 16K read" condition is now computed from A14, A15 and /RD in PIO. Test every slot class with the existing ROM images, including `OUT 244,3` (the Spectrum ROM through the DOCK).
- **R5. MicroPython upgrade regressions** on v2 (RAM, `sm.exec`, `asm_pio_encode`). Phase 2 isolates them. Confirm RP2350B 48-pin and PIO GPIOBASE support in the chosen MicroPython release before committing to it.
- **R6. Flash-write stalls.** LittleFS writes stall execute-in-place on the RP2350 just as on the RP2040. The memory path must not depend on flash. *Phase 1:* the memory path and core 1 run from SRAM, and the I/O queues are 1 KB, so a stall of a few milliseconds no longer drops bytes. Core 0's protocol code still has to avoid long stalls in the middle of a block.
- **R7. Hardware.** GP8-GP10 lack pull-ups (fixed in firmware now, in the next board revision later). The ESP32-C3 ships with blank flash.

## 6. Decisions needed

1. **One codebase or a fork?** Recommendation: one repo, with the board layer of phase 4. v2 users keep getting fixes, and the 34 host tests cover both boards.
2. **Where the bus layer lives.** Recommendation: a C user module (`tsbus`), with the I/O FIFOs still exposed as an `rp2.StateMachine`. The PIO and DMA could be set up from Python with `rp2.DMA`, but timing, alignment and SM/DMA ownership are easier to guarantee in C, and the AY emulation needs C anyway (`PLAN.md`, risks).
3. **MicroPython version for both boards,** or v2 pinned at v1.20 (phase 2 decides).
4. **Z80-side writes into ROM slots** (`v3-architecture.md` section 11, question 4): emulate the SST39SF040 command sequence, provide a Pico-side save command, or both. Recommendation: the save command for parity; emulation only if a real tool needs it.
5. **Ports enabled at first release:** only $0E/$0F, or $1C-$1E from the start (section 11, question 2).
6. **Slot storage layout:** file names, whether SD can override QSPI slots, and config migration from a v2 `config.ini`.
