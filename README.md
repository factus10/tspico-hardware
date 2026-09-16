# TS-Pico hardware

Hardware for the TS-Pico, a mass-storage, ROM, and now WiFi/sound expansion card for the Timex Sinclair 2068.

| Folder | What |
|---|---|
| `hardware/` | TS-Pico v3: KiCad 10 project. RP2350B chip-down, surface mount, JLCPCB assembly. In progress. |
| `docs/` | [PLAN.md](PLAN.md) (plan), [docs/v3-architecture.md](docs/v3-architecture.md) (interface spec), part mapping, archived variants. |
| `old/` | TS-Pico v2.2: the shipped through-hole design (CircuitStudio project and full fab package, September 2023). Reference only. |

Firmware lives in [tspico-firmware-build](https://github.com/timex-sinclair-projects/tspico-firmware-build).

## Working on the v3 hardware

Requirements: KiCad 10 (`kicad-cli` is used for checks), Python 3.

```bash
python3 hardware/scripts/gen_board.py   # regenerate the edge-connector footprint and board skeleton
hardware/scripts/check.sh               # ERC + DRC, fails on any violation
```

See `hardware/README.md` for the project layout and the geometry the edge connector is built from.
