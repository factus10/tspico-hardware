# TS-Pico v2.6 KiCad project

The v2.2 card with the RP2040 on the board instead of a Pico module, on the v3 outline (130 x 64.25 mm, 56 mm body plus the 8.25 mm tongue, same edge connector, 4 layers). JLCPCB assembles everything surface mount. The flash and SRAM are the original through-hole DIP-32 parts in sockets, soldered by hand. The bus circuit, the designators and the GPIO map are v2.2's, so the standard Pico MicroPython build and the shipped firmware (tspico-firmware-build) run unchanged.

**To order:** the JLCPCB upload files (Gerber zip, BOM, placement), ordering notes, schematic PDF and renders are on the [v2.6-proto1 release](https://github.com/factus10/tspico-hardware/releases/tag/v2.6-proto1). To regenerate them from this folder, run `python3 scripts/gen_fab.py` (output in `fab/jlcpcb/`).

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

## Other changes from v2.2

As v2.5, minus the bench programming:

- 74LS glue in SOIC, 74LVC245s in TSSOP, NE555, MMBT3904, SS14, 25 V ceramics.
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
- Glue row (U1, U5, U4, U9, U8, U7) across the board, with the 555 reset circuit to the right of it, below the flash socket.
- Over the data fingers: U6 and R12.
- Every used bottom-side finger has a locked stub and via into the body, as in v2.5.

## Before ordering

- Hand-soldered and not in the JLCPCB BOM: U10 (SST39SF040-70-4C-PHE) and U13 (AS6C4008-55PCN), plus two 32-pin 600 mil DIP sockets.
- Check rotations in JLCPCB's placement preview, especially U2's pin 1, Y1, J1 and U22.
- The TF-01A footprint and card-detect are the same open items as v3.

## State

2026-10-11: ERC clean and board DRC clean at every severity (no errors, no warnings, nothing unconnected); `scripts/check.sh` passes. 2286 track segments and 370 vias (all 0.6/0.3 mm), every track on F.Cu or B.Cu, so both planes are unbroken. Two segments are necked to 0.112 mm where clearance needs it (board minimum 0.1 mm, JLCPCB 0.09 mm).

How it closed: `flow.py`'s first attempt routed every connection but left one track 3 um inside clearance next to JP4. Attempts 2 and 3 each left one net open (A0_L, then A14_B). The board here is attempt 1, finished by `finish.py`, whose near-miss rule now also trims thin signal tracks (by 0.01 mm) and recognises the track in either position of the DRC pair. Then `silk.py` (93 designators placed, none hidden).

JLC parts plus loading fees: $9.43 per board on a 10-board run ($6.13 parts, $33 fees once), not counting the hand-soldered DIP memories and sockets. Renders in `renders/`.
