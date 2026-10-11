# TS-Pico v2.6 KiCad project

The v2.2 card with the RP2040 on the board instead of a Pico module, on the v3 outline (130 x 64.25 mm, 56 mm body plus the 8.25 mm tongue, same edge connector, 4 layers). JLCPCB assembles everything surface mount. The flash and SRAM are the original through-hole DIP-32 parts in sockets, soldered by hand. The bus circuit, the designators and the GPIO map are v2.2's, so the standard Pico MicroPython build and the shipped firmware (tspico-firmware-build) run unchanged.

**To order:** the JLCPCB upload files (Gerber zip, BOM, placement), ordering notes, schematic PDF and renders are on the [v2.6-proto2 release](https://github.com/factus10/tspico-hardware/releases/tag/v2.6-proto2). Prototype 1 (74LS glue and a 555 reset, otherwise the same board) is the [v2.6-proto1 release](https://github.com/factus10/tspico-hardware/releases/tag/v2.6-proto1). To regenerate them from this folder, run `python3 scripts/gen_fab.py` (output in `fab/jlcpcb/`).

Status: see "State" at the end. Not built.

Compared with v2.5 (`../hardware-v2.5/`, Pico module, all SMT, bench programming): same bus logic and layout style. The Pico module is replaced by the RP2040 core, the memories go back to DIP, and the bench-programming block is gone: program the SST39SF040 in a ROM programmer before it goes in its socket, as v2.2 boards are built.

## RP2040 core (sheet `mcu`)

From the minimal design in "Hardware design with RP2040":

- U2 RP2040 (QFN-56). Decoupling: 100 nF per IOVDD pin (C21-C26, one shared with USB_VDD), C27 on ADC_AVDD, 1 uF on VREG_VIN (C28) and VREG_VOUT (C29), 100 nF per DVDD pin (C30, C31).
- U21 W25Q16JVSSIQ, 2 MB QSPI flash, the same size as the Pico's, so the RPI_PICO MicroPython build fits as is.
- Y1 12 MHz ABM8-272-T3 with 15 pF loads (C33, C34) and 1 k (R25) on XOUT. This is the design guide's crystal, and the one that passed v3 bring-up.
- J1 USB-C (HRO TYPE-C-31-M-12, as v3), 5.1 k Rd on CC1/CC2 (R26, R27), 27 R series on D+/D- (R28, R29).
- SW4 BOOTSEL (QSPI_SS to GND through R24, 1 k); SW3 RUN (Pico reset) with R9, as v2.2.
- GPIO map: GP0-GP22 and GP26-GP28 carry v2.2's signals. The four the Pico used internally behave as on the Pico: GP23 to test pad TP3, GP24 VBUS sense (R30 5.6 k / R31 10 k), GP25 LED (D5, R34 470 R; the firmware drives it), GP29 VSYS/3 (R32 200 k / R33 100 k). SWCLK/SWDIO go to TP1/TP2.
- Power: VSYS is the edge +5V through D2 (as v2.2) or USB VBUS through D4 (the Schottky inside the Pico). U22 (AMS1117-3.3) supplies +3V3. As with the Pico, USB powers only the 3.3 V side; the 5 V logic and memories run from the 2068.

## Bus logic and reset (prototype 2)

Prototype 1 copied v2.2's 74LS glue gate for gate. Two of those parts were scarce at JLCPCB (SN74LS09: 56 in stock, XL74LS27: 108), and 74LS is fading generally. Prototype 2 rebuilds the same logic in 74LVC at 3.3 V. Every glue output already ended at a 3.3 V part (the Pico through U7, U6's DIR, or the memories' TTL-level inputs), and LVC inputs take the 2068's 5 V directly.

| Signal (Pico pin) | v2.2 / proto1 | Proto2 |
|---|---|---|
| /+RW (GP14), JP4 port pair | LS27 NOR3 + three LS04 inverters + LS32 | U5 74LVC138: A4-A6 select, /IORQ, A7 and /M1 on the enables; JP4 picks O0 ($00-$0F) or O1 ($10-$1F); then one U4 gate |
| /+W (GP11, U6 DIR) | LS27 NOR3 + LS04 | U4: /+RW-select OR /RD. Same as v2.2's except when /M1, /IORQ and /RD are all low, which a Z80 never does |
| /RDROM (GP1) | two LS32 gates | two U4 (74LVC32) gates |
| /MREQ_G (GP13) | LS32 + LS04 | U1 74LVC1G97 (2:1 mux wired as OR with one inverted input) |
| /BE driver (edge A29) | LS09 open-collector AND | U9 74LVC2G07, two open-drain buffers wired-AND; R3 pull-up to 5 V as before |
| /BE_STAT (GP27) | LS09 gate + R4 pull-up | U7 channel 5 (/BE_IN), push-pull; R4 and R7 gone |
| A14/A15 to the memories | LS157 | U8 74LVC157 |
| Power-on reset | NE555 + Q1 + 7 passives, about 2.4 s | U11 TPS3808G01 supervisor: /RESET low while +5V is under 4.09 V (R1/R5) and for 2.7 s after (C12 470 nF), open-drain |

Equivalence was checked by simulating both netlists gate by gate over every input combination (17 inputs, both JP4 positions, 229,376 legal states): all 12 outputs agree. The only difference is /+W in the state excluded above.

Timing changes, all in the direction of more margin: LVC gates are 3-4 ns against LS's 10-15 ns. In `set_ctrl`, /RDROM now settles about 3 ns after /MREQ_G instead of about 14 ns. /+W and /+RW leave U4 after the same number of gates, because `TS_IO` reads /+W one PIO cycle after /+RW falls; on v2.2, /+W arrived slightly first. Every signal still reaches the Pico through U7, as before. Check `set_ctrl` and `TS_IO` with a logic analyser on the first board.

## Other changes from v2.2

As v2.5, minus the bench programming:

- 74LVC245s in TSSOP, SS14, 25 V ceramics.
- On-board micro SD (HRO TF-01A) with 10 k pull-ups on DAT1/DAT2.
- JP1 and P10 are solder jumpers, closed. JP4 is a 3-pad solder jumper, 1-2 ($00-$0F). JP2/JP3/JP5 are DNP pads for external buttons.
- R12 4.7 k from U6 pin 8 (D6) to GND (the later rework on v2.2 boards); R15/R16 10 k on the memory /CE lines.

## Files and commands

Same scheme as v2.5 (see `../hardware-v2.5/README.md`): `scripts/gen_schematic.py` writes the root sheet and the `interface`, `logic`, `memory` and `mcu` sheets; `scripts/gen_layout.py` places the board; `scripts/flow.py` routes it with Freerouting 2.4.1; `scripts/gen_fab.py` writes `fab/jlcpcb/`; `scripts/check.sh` runs ERC and DRC.

```bash
cd hardware-v2.6
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
python3 scripts/gen_schematic.py
$PY scripts/flow.py --jar <freerouting-2.4.1.jar>
python3 scripts/gen_fab.py
scripts/check.sh
```

## Layout

- Top left: the RP2040 block. USB-C comes out of the left edge, the QSPI flash sits below it and the crystal to the right of the chip. The decoupling caps ring the package.
- Top strip: BOOTSEL, the regulator, D2/D4, the 3.3 V pull-ups, then the three buttons with their DNP pads.
- Middle band: the two DIP-32 sockets lie along the board, SRAM (U13) on the left and flash (U10) on the right.
- Left edge: micro SD below the MCU block.
- Glue row across the board: U5 (decode) and JP4, U4, U1, U9 with R8/R3/JP1, U8, U7; the TPS3808 reset (U11) to the right of it, below the flash socket.
- Over the data fingers: U6 and R12.
- Every used bottom-side finger has a locked stub and via into the body, as in v2.5.

## Before ordering

- Hand-soldered and not in the JLCPCB BOM: U10 (SST39SF040-70-4C-PHE) and U13 (AS6C4008-55PCN), plus two 32-pin 600 mil DIP sockets.
- Check rotations in JLCPCB's placement preview, especially U2's pin 1, Y1, J1 and U22.
- The TF-01A footprint and card-detect are the same open items as v3.

## State

Prototype 2, 2026-10-11: ERC clean and board DRC clean at every severity (no errors, no warnings, nothing unconnected); `scripts/check.sh` passes. Routed by `flow.py` on its first attempt with no hand edits: 1870 track segments and 310 vias (all 0.6/0.3 mm), every track on F.Cu or B.Cu, so both planes are unbroken; narrowest track 0.15 mm. All 86 designators on silkscreen.

What it took: the first three routing attempts each left one net open, all around the RP2040's top and bottom pin rows (pin 33 +3V3, A14_B on GP22, A0_L on GP10). The caps for the four IOVDD pins there (C21, C22, C24, C25) now stand on their own pin's lane, and `gen_layout.py` pre-routes each pin to its cap as a locked stub, so no neighbour is boxed in.

Compared with prototype 1: 74 assembled parts instead of 81 (93 footprints instead of 100), no 74LS, no 555, no part with less than about 2,400 in stock at JLCPCB on 2026-10-11. JLC parts plus loading fees: $9.79 per board on a 10-board run ($6.19 parts, $36 fees once; prototype 1 was $9.43), not counting the hand-soldered DIP memories and sockets. Renders in `renders/`.
