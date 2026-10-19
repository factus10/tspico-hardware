# TS-Pico hardware

Hardware for the TS-Pico, a mass-storage, ROM, and now WiFi/sound expansion card for the Timex Sinclair 2068.

| Folder | What |
|---|---|
| `hardware/` | TS-Pico v3: KiCad 10 project. RP2350B chip-down, surface mount, JLCPCB assembly. See `hardware/README.md`; order files in [v3.0-proto3](https://github.com/factus10/tspico-hardware/releases/tag/v3.0-proto3). |
| `hardware-v2.5/` | TS-Pico v2.5: the v2.2 circuit all surface mount on the v3 outline, plus bench programming of the flash from the Pico. KiCad 10. See `hardware-v2.5/README.md`; order files in [v2.5-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v2.5-proto1). |
| `hardware-v2.6/` | TS-Pico v2.6: the v2.2 circuit with the RP2040 on the board, SMT except the DIP-32 flash and SRAM (socketed, hand-soldered). KiCad 10. See `hardware-v2.6/README.md`; order files in [v2.6-proto2](https://github.com/factus10/tspico-hardware/releases/tag/v2.6-proto2). |
| `docs/` | [PLAN.md](PLAN.md) (plan), [docs/v3-architecture.md](docs/v3-architecture.md) (interface spec), part mapping, archived variants. |
| `old/` | TS-Pico v2.2: the shipped through-hole design (CircuitStudio project and full fab package, September 2023). Reference only. |

![TS-Pico v3, prototype 3](hardware/renders/tspico-v3-iso.png)

The v3 board (prototype 3). Schematic: [hardware/docs/tspico-v3-schematic.pdf](hardware/docs/tspico-v3-schematic.pdf). PCB layers: [hardware/docs/tspico-v3-pcb.pdf](hardware/docs/tspico-v3-pcb.pdf).

| v3 top | v3 bottom |
|---|---|
| ![v3 top](hardware/renders/tspico-v3-top.png) | ![v3 bottom](hardware/renders/tspico-v3-bottom.png) |

| v2.6 | v2.5 |
|---|---|
| ![v2.6 top](hardware-v2.6/renders/tspico-v2.6-top.png) | ![v2.5 top](hardware-v2.5/renders/tspico-v2.5-top.png) |

Firmware lives in [tspico-firmware-build](https://github.com/timex-sinclair-projects/tspico-firmware-build).

## Ordering a board

Ready-to-upload JLCPCB packages (Gerbers, BOM, placement, ordering notes, schematic PDF, renders) are attached to the GitHub releases. All are prototypes. v3 proto1 has been built and brought up (`firmware/bringup/README.md`); proto2 carries its fixes, and proto3 adds a male DE-9 for Atari sticks, a 4-pin header for an I2C SSD1309 OLED and the buttons in a 2x2 block. The others have not been built yet.

| Board | Release |
|---|---|
| v2.6: RP2040 on the board, DIP-32 flash and SRAM in sockets (hand-soldered), 74LVC glue | [v2.6-proto2](https://github.com/factus10/tspico-hardware/releases/tag/v2.6-proto2) (proto1, with 74LS glue: [v2.6-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v2.6-proto1)) |
| v2.5: all surface mount, Pico module, bench programming of the flash | [v2.5-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v2.5-proto1) |
| v3: RP2350B, WiFi, audio, joystick | [v3.0-proto3](https://github.com/factus10/tspico-hardware/releases/tag/v3.0-proto3) (earlier: [v3.0-proto2.1](https://github.com/factus10/tspico-hardware/releases/tag/v3.0-proto2.1), proto2 with L1 fitted by hand; [v3.0-proto2](https://github.com/factus10/tspico-hardware/releases/tag/v3.0-proto2) assembles L1; proto1, built, before the bring-up fixes: [v3.0-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v3.0-proto1)) |

## Working on the v3 hardware

Requirements: KiCad 10 (`kicad-cli` is used for checks), Python 3.

```bash
python3 hardware/scripts/gen_board.py   # regenerate the edge-connector footprint and board skeleton
hardware/scripts/check.sh               # ERC + DRC, fails on any violation
```

See `hardware/README.md` for the project layout and the geometry the edge connector is built from.
