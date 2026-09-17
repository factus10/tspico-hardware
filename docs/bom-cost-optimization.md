# BOM cost optimisation against the JLCPCB catalog (2026-09-17)

Prices and stock come from JLCPCB's parts API (`hardware/scripts/jlc_price.py`), priced for a
10-board prototype run. JLCPCB charges a one-off $3 loading fee per *extended* part number;
basic and preferred parts have none. TSSOP logic is never basic, so the levers were unit price,
out-of-stock parts, and the number of distinct part numbers.

|  | first v3 BOM | part substitutions | logic consolidation |
|---|---|---|---|
| parts per board | $25.75 | $11.79 | $10.43 |
| extended part numbers (fee) | 24 ($72) | 18 ($54) | 15 ($45) |
| parts + fees per board, 10 boards | $32.95 | $17.19 | $14.93 |
| fitted logic packages | 16 | 15 | 8 |

Rerun `python3 scripts/gen_fab.py --bom-only && python3 scripts/jlc_price.py --boards 10` from
`hardware/` to refresh the numbers.

## Changes, largest saving first (per 10 boards)

| Change | Was | Now | Saves | Layout impact |
|---|---|---|---|---|
| PSRAM U22 not fitted | APS6404L-3SQR-SN $5.18, 143 in stock | footprint kept, DNP | $55 | none |
| Bulk capacitors C40/C41/C46 | Panasonic polymer 220 uF $1.02 | KNSCHA 220 uF 10 V SMD electrolytic C2833309 $0.04 | $29 | CP_Elec 6.3x5.4 |
| micro SD socket J2 | Hirose DM3AT $1.54 | HRO TF-01A C91145 $0.19 | $14 | new footprint to draw |
| 3.5 mm jack J4 | CUI SJ-3523 $1.05, 26 in stock | PJ-320D C431535 $0.05 | $10 | PJ320D footprint |
| ALO/AHI latches U12/U13 | TI SN74LVC574 $0.69 | MDD 74HC574PW C54796860 $0.17 | $10 | none |
| Flash U21 | W25Q128JVSIQ basic $2.22 | GD25Q128ESIGR C2928891 $1.34 (+$3 fee) | $6 | none |
| Register decoder U16 | 74LVC139 (out of stock) | deleted: four strobes on GP24/25/26/31 | $6 | one package fewer |
| STAT buffer U15 | 74LVC541 $0.43 | sixth 74LVC245 (DIR low) | $6 | none |
| DMA drivers U8 | TI 74LVC126 $0.37 | fifth 74LVC245 (DIR high, /OE = nDMA_EN) | $5 | TSSOP-20 instead of TSSOP-14 |
| Through-hole J3, J5 | in the JLC BOM ($3 fee each plus TH assembly) | hand-soldered, out of the JLC BOM/CPL | $6+ | none |
| 10 uF x8 | 0805 25 V $0.084 | 0603 10 V C19702 $0.032 | $4 | 0603 |
| Op-amp U50 | MCP6002T-E/SN extended | MCP6002T-I/SN C7377 preferred, no fee | $3 | none |
| LED D4 | 0603, 1 in stock, extended | KENTO KT-0805G C2297 basic | $3 | 0805 |
| AND gates U6 | TI SN74LVC08APWR $0.37 | Nexperia 74LVC08APW C6053 $0.14 | $2 | none |
| CTL register U14 | Nexperia 74HC273PW $0.26 | JSMSEMI SN74HC273PWR C44512760 $0.18 | $1 | none |

Forced by stock rather than price: 74LVC257 (Nexperia TSSOP at zero, now TI SN74LVC257APWR
C205921), 74LVC04 (TECH PUBLIC SN74LVC04APWR-TP C54561939), 74LVC06 (every TSSOP option is out
of stock or $0.41, now EnergyMath EM74LVC06AD in SOIC-14, C49188178).

Added by the RP2350 regulator rework: Abracon AOTA-B201610S3R3-101-T C42411119 ($0.28, replaces
the unsourced Sunlord part), 33 R + 4.7 uF VREG_AVDD filter (both basic).

## Logic consolidation (2026-09-17, second pass)

| Change | Removes | Adds |
|---|---|---|
| The two address 74LVC245s go straight onto MD; their output enables are the byte mux | 2 x 74LVC257, the 16-line MA bus | nothing (GP8/GP9 change role) |
| Strobes nMEMRD, nMEMWR, nIORD, nIOWR from one OR package; refresh and INTACK never assert /RD or /WR, so /RFSH and /M1 qualification is unnecessary | 74LVC04, 74LVC08 | 74LVC32 C6087 $0.14 |
| XL9555 I2C expander for the slow I/O | 74HC273, STAT 74LVC245, power-on clear (R, C, Schottky) | XL9555 C609791 $0.41, three pull-ups, five 10 k pull-downs |
| DMA becomes a stuffing option (`DMA_OPTION` in `hardware/scripts/config.py`) | 2 x 574, DMA-driver 245 and three caps from the BOM | footprints stay; the latches must be 74LVC574 if fitted because they drive the 5 V address bus |

The address groups follow the connector's finger order, so the firmware stores images indexed by
the PIO's address word (nibble order 3, 0, 2, 1); see docs/v3-architecture.md section 2.

## Kept on purpose

- **74LVC everywhere in the logic**: every remaining package touches the 5 V bus and needs 5 V
  tolerant inputs and 24 mA drive.
- **TI TLV1117LV33** ($0.29): the $0.11 clones list 1.2 V dropout, which would not hold 3.3 V
  from USB power after the OR-ing diode. A cheap alternative if the rails are split further:
  ME6211C33 (C82942, $0.06, 500 mA).
- **ABM8-272-T3 crystal and the AOTA inductor**: Raspberry Pi's required parts.
- **ESP32-C3-WROOM-02-N4** ($2.90): the MINI-1 is only $0.30 less.
- **W25Q128 pinout, 16 MB**: an 8 MB GD25Q64E (C2831359, $0.97) saves another $4 per 10 boards.
- **0603 100 nF** (basic, $0.012): 0402 (C1525, $0.0045) would save $2.50 per 10 boards.

## If the PSRAM is wanted

JLCPCB stocks no cheap 3.3 V 8 MB PSRAM: APS6404L-3SQR-SN is $5.18 (143 left), the USON-8
version APS6404L-3SQR-ZR C3040877 is $4.18 (about 1000), the $1.76 APS6404L-SQN is the 1.8 V part,
and ESP-PSRAM64H / LY68L6400 / IPS6404 are not stocked. The PSRAM only caches SD-card images
(1 ms load instead of 30-50 ms); images in QSPI flash already load in about 2 ms. Remove
`dnp=True` on U22 in `gen_mcu.py` to fit it (adds about $8 on a 10-board run with the fee).
