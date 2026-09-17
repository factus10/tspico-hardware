# TS-Pico v3 plan: RP2350B, surface mount, expanded features

Goal: a new TS-Pico card for the TS2068 built around an on-board RP2350B, assembled by JLCPCB, with a redesigned bus interface that gives the Pico direct read and write access to the flash and SRAM, keeps the Z80 data path permanently connected, adds WiFi, a small display, a Kempston joystick port, AY-3-8910 emulation with stereo audio, and an SD socket on its own SPI bus.

The v2.2 through-hole board in `old/` is the reference for the edge-connector geometry, the memory bank model, and the I/O port protocol. Its circuit is not being copied; the firmware's view of the hardware is what must be preserved, and where that view changes it is listed in section 6.

Companion files:

- [docs/v3-architecture.md](docs/v3-architecture.md): block diagram, bus behaviour, register map, GPIO map, timing, chip list, open questions. The spec the schematic is drawn from.
- [docs/smt-part-mapping.csv](docs/smt-part-mapping.csv): v2.2 part to SMT package mapping for the parts that survive.
- [docs/archive/v3-pico2-architecture.md](docs/archive/v3-pico2-architecture.md): the earlier Pico 2 variant, superseded.

## 1. Decisions taken

| Topic | Decision |
|---|---|
| EDA | KiCad 10. Old Altium binaries are used only for geometry (Gerbers) and reference (PDF). |
| MCU | RP2350B chip-down with 16 MB QSPI flash and 8 MB PSRAM, USB-C, BOOTSEL and RUN buttons. Decided 2026-09-16. |
| Assembly | JLCPCB PCBA. All SMT: 0603 passives, SOIC/TSSOP logic, TSOP-32 flash, SOP-32 SRAM, QFN-80 MCU. Through-hole only for the DE-9 joystick, the OLED header, and optional pin headers paralleling solder jumpers. |
| Memories | No flash or SRAM chips. The RP2350B serves the card's memory from internal SRAM with PIO and DMA; images live on its 16 MB QSPI flash and the SD card, cached in 8 MB PSRAM; a slot map file replaces the fixed flash banks. Z80 reads and writes work as today; persistence of ROM-slot writes is a firmware policy. Decided 2026-09-16. |
| Bank logic | In PIO: the class decision (DOCK / EXROM / HOME) selects which image base pointer is used for the DMA fetch. No hardware bank logic. |
| I/O ports | All port decode in PIO. $0E/$0F (legacy), optionally $1C to $1E, $1F Kempston, $FFFD/$BFFD AY. Port-pair jumper eliminated; it is a firmware setting. |
| Wait states | /WAIT driven by PIO side-set, enabled by a firmware flag. |
| SD | On-board push-push micro SD socket on SPI0. |
| Display | 7-pin header for a 1.27" 128x96 SSD1351 SPI module on SPI1. |
| WiFi | ESP32-C3-WROOM-02 (castellated SMT, 4 MB) running Zimodem (native ESP32-C3 target) over UART0, flashed through the card's USB-C via the RP2350 as a bridge. The RP2350 emulates the TS2050's Intel 8251 at ports $73/$77 (as in the TS-2050-Wifi project) and pipes it to Zimodem. |
| Joystick | DE-9 Kempston, read through the STAT buffer and served at $1F by PIO. |
| Audio | AY-3-8910 emulated on core 1, PWM stereo, mixed with the 2068 SOUND line by an op-amp, 3.5 mm jack. |
| Reset | 555 removed. Pico-controlled /RESET line that defaults to asserted while the Pico boots. |
| Power | The card's 5 V rail is a Schottky diode-OR of the edge connector +5 V (B4) and USB-C VBUS. It runs from the 2068 or expansion bus, from USB alone on the bench (programming), or both at once while debugging, with no back-feed either way. Two 3.3 V LDOs (logic, WiFi). +15 V unused. |
| Jumpers | /BE_OUT and flash write-protect eliminated. Anything remaining is a solder jumper with a parallel through-hole header. |
| DMA | Hardware provision (74LVC126 drivers, ALO/AHI latches, bidirectional address transceivers) for Pico access to the 2068's own memory after a bus grant, for snapshots. Validated on the prototype. |
| Tape | EAR out and SPK/TAP in wired to GPIO through dividers for TZX playback and SAVE capture. |

## 2. What the current firmware needs from the hardware

From `tspico-firmware-build` (current), the memory note in `TS2068-PICO/doc`, and the TS2068 Technical Manual in the reference library (`docs/technical-manual/02-hardware-guide.md`: SCLD signal table and rear-connector pinout, which confirm /BE as the external "disable internal memory" input, /ROSCS as the Dock bank enable, /EXROM as the extension ROM select, and /WAIT, /BUSRQ, /BUSAK on the connector).

- Ports $0E (data) and $0F (status); the PIO sees a select line, a read/write discriminator and A0. In v3 the PIO sees the full low address byte instead and decodes itself.
- Per-cycle bank rule in PIO: /ROSCS low is a DOCK access served from the DCK slot with the Z80's own A14/A15; /ROSCS high with /EXROM low is EXROM; /ROSCS high with a read in the low 16K is HOME ROM. HOME is the first 16 KB of a 32 KB ROM slot, EXROM the second. The rule completes within about 150 ns of /MREQ today; v3 keeps it in PIO with the same inputs.
- No hardware /WAIT today, which the dual-port work identified as the reason blocking pulls cannot be used. v3 adds it.
- SD shares D0 to D2 today, forcing a bus hand-off around every SD access; the team's working hypothesis for the intermittent "Report D" fault is a tri-state window during that hand-off. v3 gives SD its own pins.
- Flash and SRAM are 512 KB each, 8 banks of 64 KB, DCK images per bank and ROM images per 32 KB half. The Pico cannot address the memories today; flash and SRAM content is written by Z80 code (the ROM update TAPs). That path stays; v3 adds Pico-direct access alongside it.
- Reset: the 555 holds the 2068 in reset for 2 to 3 s so the Pico can boot. NMI button is not connected to the Pico today.

## 3. Part-count picture

| | v2.2 (through-hole) | Pico 2 plan (archived) | RP2350B plan |
|---|---|---|---|
| Glue logic packages | 8 (74LS/LVC) + 555 | about 20 (74HCT/LVC) | 15 (74LVC) |
| Memory | DIP flash + DIP SRAM | TSOP + SOP | none: RP2350B SRAM, QSPI flash, PSRAM |
| MCU | Pico on headers | Pico 2 castellated | RP2350B + flash + PSRAM + crystal + USB |
| Bank logic | 74LS157 + PIO | hardware mux + registers | PIO |
| Port decode | 74LS glue | comparator + flip-flop | PIO |

Emulating the memories in the RP2350B (decided 2026-09-16) removes the memory chips and the bank hardware; the multiplexed local bus adds two muxes. A breadboard latency test is scheduled before v3 layout is final.

## 4. Work plan

### Phase 0: Repo and libraries (done 2026-09-16)
- `hardware/` KiCad project. Project library for the TS2068 card-edge footprint (from the v2.2 Gerbers: 32 positions at 0.100 in, 31 fingers per side, slot at position 6, fingers 65 x 325 mil), RP2350B, PSRAM, ESP32-C3 module, SD socket, DE-9, OLED header.
- README with the two versions and fab notes.
- Done: project, 4-layer board skeleton with outline and edge connector generated from the v2.2 Gerbers, mounting holes, fiducials, eight empty hierarchical sheets, lib tables, `scripts/check.sh` (ERC and DRC clean). Open: ESP32-C3 and PSRAM symbols/footprints in the project library; confirm A-side-on-top for the connector.

### Phase 1: Interface spec sign-off
- Review `docs/v3-architecture.md` with the firmware maintainers. Settle its section 11 questions. The GPIO map, register bits and port list are the contract.
- Chip-down RP2350B decided; power from edge +5 V diode-ORed with USB VBUS.

### Phase 2: Schematic
- Sheets: 2068 interface (fingers, transceivers, gating, open-drain drivers, DMA drivers, reset, buttons, tape divider), local bus and registers, RP2350B core, power (diode-OR, two LDOs, bulk), SD and OLED, WiFi module, audio (PWM filters, mixer, jack), joystick. All drawn 2026-09-16; ERC clean.
- ERC clean; export netlist and a GPIO cross-reference table for the firmware.

### Phase 3: Layout (placement done 2026-09-16; routing pending)
- Keep 130 x 100 mm and the connector position unless the group wants a smaller card; four mounting holes.
- 4 layers. RP2350B and its QSPI flash/PSRAM tightly placed per the RP2350 hardware design guide; crystal and USB per the same; ESP32-C3 antenna at a board edge with keep-out; SD slot and 3.5 mm jack on a side edge; DE-9 and OLED header where they are reachable with the card plugged in; buttons along the right edge; audio section away from the switching regulator.
- JLCPCB PCBA rules: 0603 minimum, one side, fiducials, no parts within 3 mm of the fingers.
- DRC clean, 3D check for USB, SD, DE-9, jack and display access.

### Phase 4: Outputs
- Gerbers, drill, JLC BOM and CPL with LCSC numbers on every SMT part; alternates for the flash (3.3 V versus 5 V fallback), SD socket, and ESP32 module.
- Scripted `kicad-cli` ERC/DRC.

### Phase 5: Prototype and firmware bring-up
- 5 boards, 2 assembled.
- MicroPython board definition for the RP2350B build (flash size, PSRAM CS1 on GP47, pin names), plus a C user module for the AY emulation and any PIO/DMA paths.
- Before layout is final: breadboard proof of emulated memory (Pico 2 plus three 74LVC245s on a 2068 serving a 16 KB ROM, fetch latency on a scope).
- Bring-up order: power rails and reset behaviour; USB boot and REPL; PSRAM; register writes read back through STAT; Z80 memory served from SRAM with the existing ROM images; Z80 I/O port with and without /WAIT; ROM-slot writes with the existing update TAPs; slot map load from QSPI and SD; SD; OLED; Zimodem link; joystick at $1F; AY at $FFFD/$BFFD with audio out; tape out/in; DMA to 2068 memory last.

## 5. Firmware impact

- Every GPIO moves; new map in the architecture doc. `sel_bank` and `set_ctrl` keep their logic with new pin bases and one change: the low-16K-read condition is computed from A14, A15 and /RD in PIO instead of a hardware `/RDROM` input.
- `TS_IO` becomes a port classifier: reads A0 to A7 (plus A14, A15) and responds only to enabled ports; gains /WAIT side-set.
- SD moves to its own SPI; no bus hand-off.
- Reset is a GPIO the firmware releases once ready and can pulse on demand.
- New: Pico-direct flash/SRAM access, PSRAM-backed caching, OLED UI, WiFi via AT commands over UART, Kempston service, AY emulation in C on core 1, tape playback/capture, optional DMA snapshot support.

## 6. Risks

- **Chip-down MCU** adds power, crystal, USB and QSPI layout to get right. Follow the RP2350 hardware design guide layout exactly; JLC assembles QFN-80 routinely.
- **Bank-rule fidelity.** The PIO keeps the rule, but the `/RDROM` condition is now computed. Verify on the prototype with the existing ROM images.
- **Bus contention.** Two masters on the local bus plus a DMA mode onto the 2068 bus. CTL powers up with BUS_OWN and DMA_EN clear; scope the hand-over edges.
- **2068 power.** WiFi transmit bursts (about 350 mA at 3.3 V for the ESP32-C3) on top of a 250 mA card would strain the 2068's 78S40-based 5 V rail. Mitigations in order: bulk capacitance on the card, keep the radio in modem-sleep unless a network feature is in use, and power the card from the expansion bus's own supply or USB when WiFi is used heavily.
- **AY emulation load.** Core 1 in C is required; MicroPython cannot do it. Plan the C user-module build into the existing docker firmware build.
- **Edge connector fit** remains the hard mechanical constraint; verify the footprint against the old Gerbers and test-fit the first prototype.
- **Part stock at JLC**: 3.3 V flash, SD socket, ESP32-C3 module, RP2350B. Keep alternates in the BOM.

## Pending rework before ordering: RP2350B regulator and crystal (JLCPCB review, 2026-09-16)

JLCPCB's RP2350 review flagged the core regulator and crystal circuitry. Checked against
"Hardware design with RP2350" (release 3):

- Crystal parts already match (ABM8-272-T3, 2 x 15 pF, 1 k series on XOUT) but Y1/R20/C35/C36
  sit 10 mm from pins 30/31 with ~18 mm nets, and R20 is on the far side of the crystal.
  Move them within ~3 mm of the pins, R20 between chip and crystal.
- Inductor: use the polarised Abracon AOTA-B201610S3R3-101-T (0806/2016 metric, LCSC C42411119),
  pin 1 (dot) on the +1V1/DVDD side, pin 2 on VREG_LX. Add a silkscreen dot.
- Add the VREG_AVDD RC filter: 33 R + 4.7 uF (guide R3/C9); VREG_AVDD is a separate net, not +3V3.
- Copy the guide's figure 4 layout: L1, output 4.7 uF and input 4.7 uF against the regulator pins,
  VREG_PGND returned directly; VREG_LX net a few mm, not 18 mm.
- Then rip up the two pockets, reroute, DRC, regenerate fab outputs (scripts/gen_fab.py).
