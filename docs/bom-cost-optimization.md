# BOM cost optimisation against the JLCPCB catalog (2026-09-17)

Prices and stock come from JLCPCB's parts API (`hardware/scripts/jlc_price.py`), priced for a
10-board prototype run. JLCPCB charges a one-off $3 loading fee per *extended* part number;
basic and preferred parts have none. TSSOP logic is never basic, so the levers were unit price,
out-of-stock parts, and the number of distinct part numbers.

|  | first v3 BOM | part substitutions | logic consolidation | DMA dropped |
|---|---|---|---|---|
| parts per board | $25.75 | $11.79 | $10.43 | $10.28 |
| extended part numbers (fee) | 24 ($72) | 18 ($54) | 15 ($45) | 14 ($42) |
| parts + fees per board, 10 boards | $32.95 | $17.19 | $14.93 | $14.48 |
| fitted logic packages | 16 | 15 | 8 | 7 |

Rerun `python3 scripts/gen_fab.py --bom-only && python3 scripts/jlc_price.py --boards 10` from
`hardware/` to refresh the numbers.

## Changes, largest saving first (per 10 boards)

| Change | Was | Now | Saves | Layout impact |
|---|---|---|---|---|
| PSRAM U22 not fitted | APS6404L-3SQR-SN $5.18, 143 in stock (2026-10-12: $3.97, 4514) | footprint kept, DNP | $55 | none |
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
| DMA dropped (`DMA_OPTION = False` in `hardware/scripts/config.py`) | 2 x 574, DMA-driver 245, the direction XOR (74LVC1G86, one extended part number) and three caps | nothing; the data transceiver's DIR is /RD |

Each address buffer delivers one plain byte (A0-A7, A8-A15); the connector's split finger order is handled in the board routing.

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

Surveyed 2026-10-12 (JLCPCB parts API, unit prices at quantity 1). The PSRAM only caches SD-card
images (1 ms load instead of 30-50 ms); images in QSPI flash already load in about 2 ms.

| Part | LCSC | Price | Stock | Notes |
|---|---|---|---|---|
| APS6404L-3SQR-SN, 8 MB, 3.3 V, SOP-8 150 mil | C5333729 | $3.97 | 4514 | The reference part (Pico Plus 2, Adafruit Feather RP2350). Was $5.18 with 143 left in September. |
| APS6404L-3SQR-ZR, USON-8 2x3 | C3040877 | $4.96 | 1793 | Needs a different footprint; no saving. |
| APS1604M-3SQR-SN, 2 MB, 3.3 V, SOP-8 | C18214056 | $2.57 | 868 | Same pinout and commands at a quarter of the size. |
| VTI7064MSME, 8 MB, SOIC-8 | C139966 | $4.68 | 154 | Rated 2.7-3.3 V, no margin on the 3.3 V rail. |
| LY68L6400SLIT (Lyontek) | C261881 | $1.86 | 0 | Listed, not stocked. |
| ESP-PSRAM64H, IPS6404, CSS6404 | - | - | 0 | Only as consigned-part entries. |
| APS6404L-SQN-SN / -SQR-ZR | C5360304 / C43758152 | $1.92 / $3.03 | | 1.8 V parts: unusable, the QSPI bank is 3.3 V. |

Adafruit's product 4677 ($1.75, $1.58 for 10+) is a sanded generic 8 MB PSRAM sold with the
Espressif ESP-PSRAM64H datasheet: same pinout as the APS6404L (1 CE#, 2 SIO1, 3 SIO2, 4 VSS,
5 SIO0, 6 SCLK, 7 SIO3, 8 VCC), 133 MHz, SPI/QPI, SOP-8 150 mil. It fits U22 by hand.

So: leave U22 DNP in the JLCPCB order and hand-fit Adafruit 4677 on boards that need it, or
remove `dnp=True` on U22 in `gen_mcu.py` to have JLCPCB fit the APS6404L-3SQR-SN (about $43 on a
10-board run: 10 x $3.97 plus the $3 extended-part fee). Hand-fitting ten 4677s is about $16.

**Footprint fix (proto2):** proto1's U22 was SOIC-8 5.3 x 5.3 mm (208 mil). AP Memory's package code
SN is SOP-8L(150): body 3.90 mm, 6.00 mm across the leads (MS-012 AA), so proto2 uses
`SOIC-8_3.9x4.9mm_P1.27mm`. Proto1 boards can't take a PSRAM without bending leads.
