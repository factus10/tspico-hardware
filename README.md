# TS-Pico hardware

Hardware for the TS-Pico, a mass-storage, ROM, and now WiFi/sound expansion card for the Timex Sinclair 2068.

| Folder | What |
|---|---|
| `hardware/` | TS-Pico v3: KiCad 10 project. RP2350B chip-down, surface mount, JLCPCB assembly. In progress. |
| `hardware-v2.5/` | TS-Pico v2.5: the v2.2 circuit all surface mount on the v3 outline, plus bench programming of the flash from the Pico. KiCad 10. See `hardware-v2.5/README.md`; order files in [v2.5-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v2.5-proto1). |
| `hardware-v2.6/` | TS-Pico v2.6: the v2.2 circuit with the RP2040 on the board, SMT except the DIP-32 flash and SRAM (socketed, hand-soldered). KiCad 10. See `hardware-v2.6/README.md`; order files in [v2.6-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v2.6-proto1). |
| `docs/` | [PLAN.md](PLAN.md) (plan), [docs/v3-architecture.md](docs/v3-architecture.md) (interface spec), part mapping, archived variants. |
| `old/` | TS-Pico v2.2: the shipped through-hole design (CircuitStudio project and full fab package, September 2023). Reference only. |

Firmware lives in [tspico-firmware-build](https://github.com/timex-sinclair-projects/tspico-firmware-build).

## Ordering a board

Ready-to-upload JLCPCB packages (Gerbers, BOM, placement, ordering notes, schematic PDF, renders) are attached to the GitHub releases. None of these boards has been built yet; all are prototype candidates.

| Board | Release |
|---|---|
| v2.6: RP2040 on the board, DIP-32 flash and SRAM in sockets (hand-soldered) | [v2.6-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v2.6-proto1) |
| v2.5: all surface mount, Pico module, bench programming of the flash | [v2.5-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v2.5-proto1) |
| v3: RP2350B, WiFi, audio, joystick | [v3.0-proto1](https://github.com/factus10/tspico-hardware/releases/tag/v3.0-proto1) |

## Working on the v3 hardware

Requirements: KiCad 10 (`kicad-cli` is used for checks), Python 3.

```bash
python3 hardware/scripts/gen_board.py   # regenerate the edge-connector footprint and board skeleton
hardware/scripts/check.sh               # ERC + DRC, fails on any violation
```

See `hardware/README.md` for the project layout and the geometry the edge connector is built from.
