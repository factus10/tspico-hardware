#!/usr/bin/env python3
"""Generate the TS-Pico v2.5 schematic: the v2.2 circuit in surface mount, plus bench
programming of the flash from the Pico.

  python3 hardware-v2.5/scripts/gen_schematic.py

Writes tspico-v2.5.kicad_sch (root) and five sheets. Netlist style, as in v3: every pin
gets a label (global, so board net names carry no sheet prefix) or a no-connect.
The circuit, designators and Pico pin map are v2.2's (old/tsPico2_2Fab/tsPico.PDF), so the
shipped firmware runs unchanged. Differences from v2.2:

  - every part surface mount; flash in PLCC-32, SRAM in 450 mil SOIC-32, LVC245s in TSSOP
  - NE555 for the TLC555 (JLC preferred part); 10 uF 25 V ceramics for the electrolytics
  - micro SD socket on the board (HRO TF-01A, as v3) instead of the SD breakout module;
    10 k pull-ups on the unused DAT1/DAT2 pins
  - JP1 (/BE link) and P10 (flash write enable) are solder jumpers, closed as shipped
    (the v2.2 manual says keep both fitted); JP4 port select is a 3-pad solder jumper,
    $00-$0F as shipped. Cut a trace to change any of them.
  - JP2/JP3/JP5 (external NMI, TS reset and Pico reset buttons in parallel with SW1-SW3)
    are DNP SMD header footprints
  - 10 k pull-ups: /ROSCS and /IORQ at the edge (bench mode), flash and SRAM /CE at the Pico
    (deselected while the Pico boots)
  - new sheet "Bench Programming": three 74HCT595s drive A0-A13, /RD, flash /WE and (through
    4.7 k) D0-D7 so the Pico can write the flash with the card out of the 2068, powered from
    USB. Enabled only with SW4 in PROG, USB present and no +15 V on the edge connector.
"""
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schlib  # noqa: E402
from schlib import Sheet, HW  # noqa: E402

ROOT = "tspico-v2.5.kicad_sch"
ROOT_UUID = "5b3c1d2e-25a0-4c6e-9f1a-2068025a0001"
SHEETS = [  # file, name, sheet uuid
    ("interface.kicad_sch", "2068 Interface and Reset", "5b3c1d2e-25a0-4c6e-9f1a-2068025a0002"),
    ("logic.kicad_sch", "Bus Logic", "5b3c1d2e-25a0-4c6e-9f1a-2068025a0003"),
    ("memory.kicad_sch", "Memory and SD", "5b3c1d2e-25a0-4c6e-9f1a-2068025a0004"),
    ("pico.kicad_sch", "Raspberry Pi Pico", "5b3c1d2e-25a0-4c6e-9f1a-2068025a0005"),
    ("benchprog.kicad_sch", "Bench Programming", "5b3c1d2e-25a0-4c6e-9f1a-2068025a0006"),
]

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SO8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
SO14 = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
SO16 = "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
TSSOP20 = "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
D_SMA = "Diode_SMD:D_SMA"
SW_FP = "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A"
HDR2_SMD = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical_SMD_Pin1Left"
SJ2_BR = "Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm"
SJ3_BR12 = "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm_NumberLabels"
RN4 = "Resistor_SMD:R_Array_Convex_4x0603"

POWER = {"+5V", "+3V3", "GND"}
NC = None

schlib.PROJECT = "tspico-v2.5"


# ---------------------------------------------------------------------------
# The netlist, sheet by sheet: (lib_id, ref, value, footprint, unit, {pin: net}, opts)
# ---------------------------------------------------------------------------
def part(lib, ref, value, fp, pins, unit=1, dnp=False):
    return dict(lib=lib, ref=ref, value=value, fp=fp, pins=pins, unit=unit, dnp=dnp)


def R(ref, val, a, b):
    return part("Device:R", ref, val, R0603, {"1": a, "2": b})


def C(ref, val, a, b="GND"):
    return part("Device:C", ref, val, C0805 if val == "10u" else C0603, {"1": a, "2": b})


def interface():
    edge = {"A1": "GND", "A32": "GND", "B1": "GND", "B32": "GND", "B7": "GND", "B8": "GND",
            "B3": "+15V", "B4": "+5V",
            "A4": "D7", "A7": "D0", "A8": "D1", "A9": "D2", "A10": "D6", "A11": "D5", "A12": "D3", "A13": "D4",
            "A15": "nNMI", "A17": "nMREQ", "A18": "nIORQ", "A19": "nRD", "A20": "nWR", "A24": "nRESET",
            "A25": "nM1", "A27": "nEXROM", "A28": "nROSCS", "A29": "nBE_OUT", "B30": "nBE_IN",
            "B10": "A0", "B11": "A1", "B12": "A2", "B13": "A3", "B14": "A15", "B15": "A14", "B16": "A13",
            "B17": "A12", "B18": "A11", "B19": "A10", "B20": "A9", "B21": "A8", "B22": "A7", "B23": "A6",
            "B24": "A5", "B25": "A4"}
    for p in ("A2", "A3", "A5", "A14", "A16", "A21", "A22", "A23", "A26", "A30", "A31",
              "B2", "B5", "B9", "B26", "B27", "B28", "B29", "B31"):
        edge[p] = NC
    return [
        part("tspico:TS2068_Edge", "P1", "TS2068_Edge", "tspico:TS2068_EdgeConnector_2x32", edge),
        # power-on reset: 555 monostable holds the 2068 in reset ~2.4 s while the Pico boots (as v2.2)
        part("Timer:NE555D", "U11", "NE555", SO8, {"1": "GND", "8": "+5V", "4": "+5V", "2": "RST_TRIG",
                                                   "6": "RST_TIM", "7": "RST_TIM", "5": "RST_CONT", "3": "RST_OUT"}),
        R("R1", "1M", "+5V", "RST_TRIG"), C("C9", "100n", "RST_TRIG"),
        R("R5", "220k", "+5V", "RST_TIM"), C("C12", "10u", "RST_TIM"),
        C("C11", "100n", "RST_CONT"),
        R("R10", "4k7", "RST_OUT", "RST_B"), R("R11", "2k2", "RST_B", "GND"),
        part("tspico:MMBT3904", "Q1", "MMBT3904", SOT23, {"1": "RST_B", "2": "GND", "3": "nRESET"}),
        # buttons; JP2/JP3 are DNP pads for external buttons in parallel
        part("Switch:SW_Push", "SW1", "NMI", SW_FP, {"1": "nNMI", "2": "GND"}),
        C("C15", "100n", "nNMI"),
        part("Connector_Generic:Conn_01x02", "JP2", "Ext NMI", HDR2_SMD, {"1": "GND", "2": "nNMI"}, dnp=True),
        part("Switch:SW_Push", "SW2", "TS Reset", SW_FP, {"1": "nRESET", "2": "GND"}),
        part("Connector_Generic:Conn_01x02", "JP3", "Ext Reset", HDR2_SMD, {"1": "GND", "2": "nRESET"}, dnp=True),
        # /BE link (v2.2 JP1), closed
        part("Jumper:SolderJumper_2_Bridged", "JP1", "BE link", SJ2_BR, {"1": "nBE_OUT", "2": "nBE_DRV"}),
        # bench-mode pull-ups: U8 must select the Pico's A14/A15 and U6 must point at the Pico
        R("R13", "10k", "+5V", "nROSCS"), R("R14", "10k", "+5V", "nIORQ"),
        C("C16", "10u", "+5V"),
    ]


def logic():
    return [
        # U8: A14/A15 to the memories, Z80's in DOCK (/ROSCS low), the Pico's otherwise
        part("74xx:74LS157", "U8", "74LS157", SO16, {"1": "nROSCS_L", "2": "A14", "3": "A14_B", "4": "A14_I",
                                                     "5": "A15", "6": "A15_B", "7": "A15_I", "8": "GND", "16": "+5V",
                                                     "15": "GND", "10": "GND", "11": "GND", "13": "GND", "14": "GND",
                                                     "9": NC, "12": NC}),
        # U7: 5 V control signals to the Pico (A to B always)
        part("tspico:74LVC245_AtoB", "U7", "74LVC245APW", TSSOP20, {"1": "U7_DIR", "2": "A0", "3": "nPW", "4": "nMREQ_G",
                                                            "5": "nEXROM", "6": "nBE_L", "7": "nRDROM", "8": "nROSCS",
                                                            "9": "nPRW", "10": "GND", "20": "+3V3", "19": "GND",
                                                            "18": "A0_L", "17": "nPW_L", "16": "nMREQ_L", "15": "nEXR_L",
                                                            "14": "BE_L_BUF", "13": "nRDROM_L", "12": "nROSCS_L", "11": "nPRW_L"}),
        R("R2", "4k7", "+3V3", "U7_DIR"),
        R("R7", "4k7", "+3V3", "BE_L_BUF"),
        # U6: Z80 data bus <-> Pico, DIR from /+W (B to A only for an I/O read of the card's port)
        part("74xx:74LS245", "U6", "74LVC245APW", TSSOP20, {"1": "nPW", "2": "D0", "3": "D1", "4": "D2", "5": "D3",
                                                            "6": "D4", "7": "D5", "8": "D6", "9": "D7", "10": "GND",
                                                            "20": "+3V3", "19": "nU6_EN", "18": "D0_L", "17": "D1_L",
                                                            "16": "D2_L", "15": "D3_L", "14": "D4_L", "13": "D5_L",
                                                            "12": "D6_L", "11": "D7_L"}),
        # R12: 4.7k from U6 pin 8 (D6) to pin 10 (GND), a later rework on v2.2 boards that is not in the
        # 2023 schematic; carried into v2.5 as a part
        R("R12", "4k7", "D6", "GND"),
        # U9: open-collector /BE driver and /BE_IN status
        part("74xx:74LS09", "U9", "74LS09", SO14, {"1": "BE_L_BUF", "2": "nBE_IN", "3": "nBE_DRV"}, unit=1),
        part("74xx:74LS09", "U9", "74LS09", SO14, {"4": "GND", "5": "GND", "6": NC}, unit=2),
        part("74xx:74LS09", "U9", "74LS09", SO14, {"9": "GND", "10": "GND", "8": NC}, unit=3),
        part("74xx:74LS09", "U9", "74LS09", SO14, {"12": "nBE_IN", "13": "nBE_IN", "11": "nBE_STAT"}, unit=4),
        part("74xx:74LS09", "U9", "74LS09", SO14, {"14": "+5V", "7": "GND"}, unit=5),
        R("R3", "2k7", "+5V", "nBE_DRV"), R("R8", "4k7", "+5V", "nBE_IN"),
        # U1 inverters
        part("74xx:74LS04", "U1", "74LS04", SO14, {"1": "nM1", "2": "M1"}, unit=1),
        part("74xx:74LS04", "U1", "74LS04", SO14, {"3": "NOR567", "4": "OR567"}, unit=2),
        part("74xx:74LS04", "U1", "74LS04", SO14, {"5": "NRW", "6": "nPRW"}, unit=3),
        part("74xx:74LS04", "U1", "74LS04", SO14, {"9": "NW", "8": "nPW"}, unit=4),
        part("74xx:74LS04", "U1", "74LS04", SO14, {"11": "nBE_IN", "10": "BE_IN"}, unit=5),
        part("74xx:74LS04", "U1", "74LS04", SO14, {"13": "A4", "12": "nA4"}, unit=6),
        part("74xx:74LS04", "U1", "74LS04", SO14, {"14": "+5V", "7": "GND"}, unit=7),
        # U4 OR gates
        part("74xx:74LS32", "U4", "74LS32", SO14, {"1": "A14", "2": "A15", "3": "A14_OR_A15"}, unit=1),
        part("74xx:74LS32", "U4", "74LS32", SO14, {"4": "A14_OR_A15", "5": "nRD", "6": "nRDROM"}, unit=2),
        part("74xx:74LS32", "U4", "74LS32", SO14, {"9": "OR567", "10": "PORT_A4", "8": "PX"}, unit=3),
        part("74xx:74LS32", "U4", "74LS32", SO14, {"12": "nMREQ", "13": "BE_IN", "11": "nMREQ_G"}, unit=4),
        part("74xx:74LS32", "U4", "74LS32", SO14, {"14": "+5V", "7": "GND"}, unit=5),
        # U5 NOR gates: port decode
        part("74xx:74LS27", "U5", "74LS27", SO14, {"1": "A5", "2": "A6", "13": "A7", "12": "NOR567"}, unit=1),
        part("74xx:74LS27", "U5", "74LS27", SO14, {"3": "M1", "4": "nIORQ", "5": "PX", "6": "NRW"}, unit=2),
        part("74xx:74LS27", "U5", "74LS27", SO14, {"9": "nRD", "10": "nIORQ", "11": "PX", "8": "NW"}, unit=3),
        part("74xx:74LS27", "U5", "74LS27", SO14, {"14": "+5V", "7": "GND"}, unit=4),
        # JP4: port pair, 1-2 = $00-$0F (as shipped), 2-3 = $10-$1F
        part("Jumper:SolderJumper_3_Bridged12", "JP4", "Port $00/$10", SJ3_BR12, {"1": "A4", "2": "PORT_A4", "3": "nA4"}),
        C("C1", "100n", "+5V"), C("C4", "100n", "+5V"), C("C5", "100n", "+5V"), C("C8", "100n", "+5V"),
        C("C14", "100n", "+5V"), C("C6", "100n", "+3V3"), C("C7", "100n", "+3V3"),
    ]


def memory():
    flash = {"1": "A18", "2": "A16", "3": "A15_I", "4": "A12", "5": "A7", "6": "A6", "7": "A5", "8": "A4", "9": "A3",
             "10": "A2", "11": "A1", "12": "A0", "13": "D0", "14": "D1", "15": "D2", "16": "GND", "17": "D3",
             "18": "D4", "19": "D5", "20": "D6", "21": "D7", "22": "nU10_ENA", "23": "A10", "24": "nRD", "25": "A11",
             "26": "A9", "27": "A8", "28": "A13", "29": "A14_I", "30": "A17", "31": "FLASH_nWE", "32": "+5V"}
    sram = dict(flash)
    sram.update({"3": "A14_I", "22": "nU13_ENA", "29": "nWR", "31": "A15_I"})
    return [
        part("Memory_Flash:SST39SF040", "U10", "SST39SF040", "Package_LCC:PLCC-32_11.4x14.0mm_P1.27mm", flash),
        R("R6", "4k7", "+5V", "FLASH_nWE"),
        part("Jumper:SolderJumper_2_Bridged", "P10", "Flash WE", SJ2_BR, {"1": "FLASH_nWE", "2": "nWR"}),
        part("Memory_RAM:AS6C4008-55PCN", "U13", "CY62148ELL-55SXI", "Package_SO:SOP-32_11.305x20.495mm_P1.27mm", sram),
        # micro SD in SPI mode on the Pico's D0_L-D2_L (shared with the data bus, as v2.2)
        part("Connector:Micro_SD_Card_Det_Hirose_DM3AT", "U3", "microSD", "tspico:microSD_TF-01A",
             {"1": "SD_DAT2", "2": "SD_CS", "3": "D1_L", "4": "+3V3", "5": "D0_L", "6": "GND", "7": "D2_L",
              "8": "SD_DAT1", "9": NC, "10": "GND", "SH": "GND"}),
        R("R22", "10k", "+3V3", "SD_DAT1"), R("R23", "10k", "+3V3", "SD_DAT2"),
        C("C3", "100n", "+3V3"), C("C18", "10u", "+3V3"),
        C("C10", "100n", "+5V"), C("C13", "100n", "+5V"),
    ]


def pico():
    gp = {"1": "nEXR_L", "2": "nRDROM_L", "4": "D0_L", "5": "D1_L", "6": "D2_L", "7": "D3_L", "9": "D4_L",
          "10": "D5_L", "11": "D6_L", "12": "D7_L", "14": "A0_L", "15": "nPW_L", "16": "nU6_EN", "17": "nMREQ_L",
          "19": "nPRW_L", "20": "A15_B", "21": "A16", "22": "A17", "24": "A18", "25": "nU10_ENA", "26": "nU13_ENA",
          "27": "nBE_L", "29": "A14_B", "30": "PICO_RUN", "31": "nROSCS_L", "32": "nBE_STAT", "34": "SD_CS",
          "35": NC, "36": "+3V3", "37": NC, "39": "VSYS", "40": "VBUS"}
    for g in ("3", "8", "13", "18", "23", "28", "33", "38"):
        gp[g] = "GND"
    return [
        part("tspico:Pico_AGND", "U2", "Raspberry Pi Pico", "Module:RaspberryPi_Pico_SMD", gp),
        part("Device:D_Schottky", "D2", "SS14", D_SMA, {"1": "VSYS", "2": "+5V"}),
        C("C2", "10u", "VSYS"),
        R("R4", "4k7", "+3V3", "nBE_STAT"),
        R("R9", "4k7", "+3V3", "PICO_RUN"),
        part("Switch:SW_Push", "SW3", "Pico Reset", SW_FP, {"1": "PICO_RUN", "2": "GND"}),
        part("Connector_Generic:Conn_01x02", "JP5", "Ext Pico Reset", HDR2_SMD, {"1": "GND", "2": "PICO_RUN"}, dnp=True),
        R("R15", "10k", "+3V3", "nU10_ENA"), R("R16", "10k", "+3V3", "nU13_ENA"),
    ]


def benchprog():
    def sr(ref, ser, outs, qh2):
        pins = {"14": ser, "11": "D0_L", "12": "SD_CS", "13": "nPROG", "10": "+5V", "16": "+5V", "8": "GND", "9": qh2}
        for pin, net in zip(("15", "1", "2", "3", "4", "5", "6", "7"), outs):
            pins[pin] = net
        return part("74xx:74HC595", ref, "74HCT595", SO16, pins)

    def rn(ref, k):
        pins = {}
        for i in range(4):
            pins[str(1 + i)] = f"PD{k + i}"
            pins[str(8 - i)] = f"D{k + i}"
        return part("Device:R_Pack04", ref, "4k7 x4", RN4, pins)

    return [
        # chain: SER = D1_L (SPI0 TX), SRCLK = D0_L (SPI0 SCK), RCLK = SD_CS (GP28), /OE = nPROG
        sr("U12", "D1_L", [f"A{i}" for i in range(8)], "SR1"),
        sr("U14", "SR1", [f"A{i}" for i in range(8, 14)] + ["nRD", "FLASH_nWE"], "SR2"),
        sr("U15", "SR2", [f"PD{i}" for i in range(8)], NC),
        rn("RN1", 0), rn("RN2", 4),
        # program enable: SW4 in PROG puts USB VBUS on the card's +5V (through D3) and turns Q2 on;
        # Q3 holds Q2 off whenever the 2068's +15 V (edge B3) is present
        part("Switch:SW_SPDT", "SW4", "RUN/PROG", "Button_Switch_SMD:SW_SPDT_Shouhan_MSK12C02",
             {"2": "VBUS", "1": "VBUS_PROG", "3": NC}),
        part("Device:D_Schottky", "D3", "SS14", D_SMA, {"1": "+5V", "2": "VBUS_PROG"}),
        R("R17", "10k", "VBUS_PROG", "PROG_B"), R("R18", "47k", "PROG_B", "GND"),
        part("tspico:MMBT3904", "Q2", "MMBT3904", SOT23, {"1": "PROG_B", "2": "GND", "3": "nPROG"}),
        R("R19", "10k", "+5V", "nPROG"),
        R("R20", "47k", "+15V", "LOCK_B"), R("R21", "10k", "LOCK_B", "GND"),
        part("tspico:MMBT3904", "Q3", "MMBT3904", SOT23, {"1": "LOCK_B", "2": "GND", "3": "PROG_B"}),
        C("C17", "100n", "+5V"), C("C19", "100n", "+5V"), C("C20", "100n", "+5V"),
    ]


NOTES = {
    "interface.kicad_sch": [
        "TS2068 rear connector (pin names per the TS2068 Technical Manual table 2.4.1-1). Side A on top, confirmed by the v3 bring-up.",
        "U11/Q1: power-on reset, 1.1 x 220k x 10u = 2.4 s, so the Pico is running before the Z80 starts. C12 is a 25 V ceramic to keep DC-bias loss small.",
        "SW1 NMI, SW2 TS reset. JP2/JP3: DNP pads for external buttons. JP1 (/BE link) is a solder jumper, closed.",
        "R13/R14 only matter out of the 2068 (bench programming): /ROSCS high makes U8 pass the Pico's A14/A15, /IORQ high keeps U6 pointing at the Pico.",
    ],
    "logic.kicad_sch": [
        "The v2.2 bus logic, gate for gate (Logic.schdoc). /+W = I/O read of the card's port; /+RW = any I/O to it; +X = port address match.",
        "R12: 4.7k pull-down on D6 at U6 (pins 8 to 10), a post-2023 rework on v2.2 boards, now a fitted part.",
        "JP4: 1-2 (as shipped) answers $00-$0F, 2-3 answers $10-$1F. U9B/U9C unused (inputs grounded). U8 C/D sections unused.",
    ],
    "memory.kicad_sch": [
        "U10 SST39SF040 (PLCC-32) and U13 512K x 8 SRAM (450 mil SOIC-32; CY62148E or AS6C4008), both on the 5 V bus as v2.2.",
        "P10 (flash write enable from the Z80's /WR) is a solder jumper, closed: the romupdate TAP needs it. The bench programmer drives FLASH_nWE directly, so P10 does not matter there.",
        "U3 micro SD in SPI mode on D0_L (SCK), D1_L (MOSI), D2_L (MISO), SD_CS (GP28), as v2.2. R22/R23 pull up the unused DAT1/DAT2.",
    ],
    "pico.kicad_sch": [
        "Raspberry Pi Pico, castellated SMD. Pin map identical to v2.2 (Pico.SchDoc): shipped firmware runs unchanged.",
        "R15/R16 hold the flash and SRAM deselected until the firmware drives GP19/GP20. SW3 = Pico RUN (reset); JP5 DNP pads for an external button.",
    ],
    "benchprog.kicad_sch": [
        "Bench programming: writes the 512K flash image from the Pico with the card OUT of the 2068, powered from the Pico's USB.",
        "Chain: SER = D1_L (GP3, SPI0 TX), SRCLK = D0_L (GP2, SPI0 SCK), RCLK = SD_CS (GP28). 24 bits: U12 = A0-A7, U14 = A8-A13, /RD, flash /WE; U15 = D0-D7 through RN1/RN2 4.7k.",
        "Read-back: U15 outputs high, /RD low, then U6 (/U6_EN low, DIR from /IORQ high) carries the flash byte to GP2-GP9. The 4.7k lets the flash win.",
        "Enable (nPROG low) needs SW4 in PROG and USB VBUS present and no +15 V on edge pin B3. In the 2068 the outputs stay off; RCLK and SRCLK toggling there is harmless.",
        "Pico GP19 (flash /CE) high while SD_CS toggles for SD traffic, so garbage latched into the chain never reaches the flash.",
    ],
}


def project_symbols():
    """Rewrite lib/tspico.kicad_sym: the edge connector plus flattened copies of three stock
    symbols, adjusted so ERC judges this circuit correctly:
      Pico_AGND     RaspberryPi_Pico with AGND (pin 33) passive; the stock symbol makes both
                    GND pin 3 and AGND power outputs, which ERC calls a short
      74LVC245_AtoB 74LS245 with A pins as inputs and B pins as outputs (U7 is fixed A to B)
      MMBT3904      the stock symbol extends Q_NPN_BEC; a flat copy avoids a library mismatch"""
    import gen_edge_symbol
    gen_edge_symbol.main()
    path = os.path.join(HW, "lib", "tspico.kicad_sym")
    lib = schlib.SymLib()
    out = []
    for stock, name, types in (("MCU_Module:RaspberryPi_Pico", "Pico_AGND", {"33": "passive"}),
                               ("74xx:74LS245", "74LVC245_AtoB", {**{str(n): "input" for n in range(2, 10)},
                                                                  **{str(n): "output" for n in range(11, 19)}}),
                               ("Transistor_BJT:MMBT3904", "MMBT3904", {})):
        blk, _ = lib.get(stock)
        old = stock.split(":")[1]
        blk = blk.replace(f'(symbol "{stock}"', f'(symbol "{name}"', 1).replace(f'(symbol "{old}_', f'(symbol "{name}_')

        def retype(m):
            num = re.search(r'\(number "([^"]+)"', m.group(0)).group(1)
            return m.group(0).replace(m.group(1), types[num], 1) if num in types else m.group(0)
        blk = re.sub(r'\(pin (\w+) \w+\s*\(at[^\n]*?(?:\n[^\n]*?)*?\(number "[^"]+"', retype, blk)
        out.append("  " + blk.replace("\n", "\n  "))
    txt = open(path).read().rstrip()
    assert txt.endswith(")")
    open(path, "w").write(txt[:-1] + "\n".join(out) + "\n)\n")


def write_root():
    out = ['(kicad_sch (version 20250114) (generator "gen_schematic.py") (generator_version "1")',
           f'  (uuid "{ROOT_UUID}")', '  (paper "A3")',
           '  (title_block (title "TS-Pico v2.5") (rev "0.1") (company "Timex/Sinclair Online User Group") (comment 1 "v2.2 circuit in surface mount, plus bench flash programming"))',
           '  (lib_symbols)']
    for i, (fname, name, su) in enumerate(SHEETS):
        x, y = 30.0 + 80 * (i % 4), 30.0 + 60 * (i // 4)
        out.append(f'  (sheet (at {x} {y}) (size 60 30) (fields_autoplaced yes) (stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000)) (uuid "{su}")')
        out.append(f'    (property "Sheetname" "{name}" (at {x} {y - 0.7:.1f} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))')
        out.append(f'    (property "Sheetfile" "{fname}" (at {x} {y + 30.6:.1f} 0) (effects (font (size 1.27 1.27)) (justify left top)))')
        out.append(f'    (instances (project "tspico-v2.5" (path "/{ROOT_UUID}" (page "{i + 2}"))))')
        out.append('  )')
    out.append('  (sheet_instances (path "/" (page "1")))')
    out.append('  (embedded_fonts no)')
    out.append(')')
    with open(os.path.join(HW, ROOT), "w") as f:
        f.write("\n".join(out) + "\n")


def size_of(lib, unit, sheet):
    _, pins = sheet.lib.get(lib)
    pp = dict(pins.get(0, {}))
    pp.update(pins.get(unit, {}))
    xs = [p[0] for p in pp.values()] or [0]
    ys = [p[1] for p in pp.values()] or [0]
    return max(xs) - min(xs), max(ys) - min(ys)


def build():
    project_symbols()
    write_root()
    content = {"interface.kicad_sch": interface(), "logic.kicad_sch": logic(), "memory.kicad_sch": memory(),
               "pico.kicad_sch": pico(), "benchprog.kicad_sch": benchprog()}
    # nets on more than one sheet get global labels
    where = {}
    for fname, parts in content.items():
        for p in parts:
            for net in p["pins"].values():
                if net and net not in POWER:
                    where.setdefault(net, set()).add(fname)
    # every signal net gets global labels: plain net names (no /Sheet/ prefix) keep the
    # board-side scripts simple, and ERC's single-global-label check is off in this project
    glob = set(where)
    flagged = set()
    pwr_ref = [1]
    for fname, name, _ in SHEETS:
        s = Sheet(ROOT, fname, f"TS-Pico v2.5: {name}")
        parts = content[fname]
        used = {n for p in parts for n in p["pins"].values() if n}
        # power symbols (+5V gets the one PWR_FLAG; GND and +3V3 are driven by the Pico's power_out pins)
        px = 330
        for net in ("+5V", "+3V3", "GND"):
            if net in used:
                flag = net == "+5V" and net not in flagged
                flagged.add(net) if flag else None
                s.power(net, px, 25, f"#PWR{pwr_ref[0]:02d}", flag=flag)
                pwr_ref[0] += 1
                px += 25
        if "VSYS" in used:          # VSYS: diode cathode + the Pico's power_in pin; flag it
            f = s.place("power:PWR_FLAG", "#FLG90", "PWR_FLAG", "", 300, 40)
            s.glabel("VSYS", f.pin("1"))
        # layout: big parts in columns on the left, small two- and three-pin parts in a grid on the right
        big = [p for p in parts if len(p["pins"]) > 3 or p["lib"].startswith("74xx")]
        small = [p for p in parts if p not in big]
        x, y, colw = 40.0, 45.0, 0.0
        for p in big:
            w, h = size_of(p["lib"], p["unit"], s)
            if y + h + 15 > 270:
                x += colw + 55
                y, colw = 45.0, 0.0
            yc = y + h / 2 + 5
            P = s.place(p["lib"], p["ref"], p["value"], p["fp"], x + w / 2, yc, unit=p["unit"], dnp=p["dnp"])
            emit(s, P, p["pins"], glob)
            y += h + 22
            colw = max(colw, w)
        gx0 = max(x + colw + 60, 250)
        for i, p in enumerate(small):
            gx = gx0 + 32 * (i % 4)
            gy = 75 + 24 * (i // 4)
            P = s.place(p["lib"], p["ref"], p["value"], p["fp"], gx, gy, unit=p["unit"], dnp=p["dnp"])
            emit(s, P, p["pins"], glob)
        for k, line in enumerate(NOTES[fname]):
            s.text(line, 20, 278 + 4 * k, 1.8)
        s.write()
        print("wrote", fname, len(parts), "parts")


def emit(s, P, pins, glob):
    for pin, net in pins.items():
        at = P.pin(pin)
        if net is None:
            s.nc(at)
        elif net in glob:
            s.glabel(net, at)
        else:
            s.label(net, at)


if __name__ == "__main__":
    build()
