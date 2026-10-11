#!/usr/bin/env python3
"""Generate the TS-Pico v2.6 schematic: the v2.2 circuit with the RP2040 on the board.

  python3 hardware-v2.6/scripts/gen_schematic.py

Writes tspico-v2.6.kicad_sch (root) and four sheets. Netlist style, as in v3: every pin
gets a label (global, so board net names carry no sheet prefix) or a no-connect.
The bus circuit and designators are v2.2's (old/tsPico2_2Fab/tsPico.PDF), and the RP2040's
GPIOs carry exactly the signals the Pico's did, so the standard Pico MicroPython build and
the shipped firmware run unchanged. Differences from v2.2:

  - RP2040 chip-down after "Hardware design with RP2040" (minimal design): W25Q16JV 2 MB
    QSPI flash (as on the Pico), 12 MHz ABM8-272-T3 with 15 pF and 1 k, USB-C (5.1 k Rd,
    27 R series), BOOTSEL on QSPI_SS through 1 k. GP23 to a test pad, GP24 VBUS sense
    (5.6 k / 10 k), GP25 LED (the firmware drives it), GP29 VSYS/3 (200 k / 100 k), as on the Pico.
  - 3.3 V from an AMS1117 on VSYS; VSYS = diode-OR of the edge +5V (D2, as v2.2) and USB
    VBUS (D4, the Pico's own Schottky). USB powers only the 3.3 V side, as with the Pico.
  - U10 flash and U13 SRAM: through-hole DIP-32 in sockets, hand-soldered (program the
    flash in a ROM programmer, as v2.2 boards are built)
  - prototype 2: the glue logic in 74LVC at 3.3 V (U5 LVC138 port decode, U4 LVC32, U1 LVC1G97,
    U9 LVC2G07 open-drain /BE, U8 LVC157) instead of 74LS04/27/32/09/157, same logic at every
    Pico pin; TPS3808 reset supervisor instead of the 555 and Q1
  - as v2.5: on-board micro SD (TF-01A), solder jumpers JP1/P10 (closed) and JP4 (1-2), DNP pads
    for JP2/JP3/JP5, R12 4.7 k D6 pull-down, R15/R16 10 k on the memory /CE lines
"""
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schlib  # noqa: E402
from schlib import Sheet, HW  # noqa: E402

ROOT = "tspico-v2.6.kicad_sch"
ROOT_UUID = "5b3c1d2e-25a0-4c6e-9f1a-2068026a0001"
SHEETS = [  # file, name, sheet uuid
    ("interface.kicad_sch", "2068 Interface and Reset", "5b3c1d2e-25a0-4c6e-9f1a-2068026a0002"),
    ("logic.kicad_sch", "Bus Logic", "5b3c1d2e-25a0-4c6e-9f1a-2068026a0003"),
    ("memory.kicad_sch", "Memory and SD", "5b3c1d2e-25a0-4c6e-9f1a-2068026a0004"),
    ("mcu.kicad_sch", "RP2040", "5b3c1d2e-25a0-4c6e-9f1a-2068026a0005"),
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
DIP32 = "Package_DIP:DIP-32_W15.24mm_Socket"
SOIC8W = "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm"
TP_FP = "TestPoint:TestPoint_Pad_D1.0mm"
SOT23_6 = "Package_TO_SOT_SMD:SOT-23-6"
TSSOP14 = "Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
TSSOP16 = "Package_SO:TSSOP-16_4.4x5mm_P0.65mm"

POWER = {"+5V", "+3V3", "GND"}
NC = None

schlib.PROJECT = "tspico-v2.6"


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
            "B4": "+5V",
            "A4": "D7", "A7": "D0", "A8": "D1", "A9": "D2", "A10": "D6", "A11": "D5", "A12": "D3", "A13": "D4",
            "A15": "nNMI", "A17": "nMREQ", "A18": "nIORQ", "A19": "nRD", "A20": "nWR", "A24": "nRESET",
            "A25": "nM1", "A27": "nEXROM", "A28": "nROSCS", "A29": "nBE_OUT", "B30": "nBE_IN",
            "B10": "A0", "B11": "A1", "B12": "A2", "B13": "A3", "B14": "A15", "B15": "A14", "B16": "A13",
            "B17": "A12", "B18": "A11", "B19": "A10", "B20": "A9", "B21": "A8", "B22": "A7", "B23": "A6",
            "B24": "A5", "B25": "A4"}
    for p in ("B3", "A2", "A3", "A5", "A14", "A16", "A21", "A22", "A23", "A26", "A30", "A31",
              "B2", "B5", "B9", "B26", "B27", "B28", "B29", "B31"):
        edge[p] = NC
    return [
        part("tspico:TS2068_Edge", "P1", "TS2068_Edge", "tspico:TS2068_EdgeConnector_2x32", edge),
        # power-on reset (proto2): TPS3808G01 supervisor holds /RESET low while +5V is under 4.09 V
        # (R1/R5 divider into SENSE, 0.405 V threshold) and for CT/175 nF s = 2.7 s after (C12 470 nF),
        # so the Pico is running before the Z80 starts, as the v2.2 555 did. Open-drain output.
        part("Power_Supervisor:TPS3808DBV", "U11", "TPS3808G01", SOT23_6,
             {"1": "nRESET", "2": "GND", "3": NC, "4": "RST_CT", "5": "RST_SENSE", "6": "+5V"}),
        R("R1", "100k", "+5V", "RST_SENSE"), R("R5", "11k", "RST_SENSE", "GND"),
        C("C12", "470n", "RST_CT"), C("C9", "100n", "+5V"),
        # buttons; JP2/JP3 are DNP pads for external buttons in parallel
        part("Switch:SW_Push", "SW1", "NMI", SW_FP, {"1": "nNMI", "2": "GND"}),
        C("C15", "100n", "nNMI"),
        part("Connector_Generic:Conn_01x02", "JP2", "Ext NMI", HDR2_SMD, {"1": "GND", "2": "nNMI"}, dnp=True),
        part("Switch:SW_Push", "SW2", "TS Reset", SW_FP, {"1": "nRESET", "2": "GND"}),
        part("Connector_Generic:Conn_01x02", "JP3", "Ext Reset", HDR2_SMD, {"1": "GND", "2": "nRESET"}, dnp=True),
        # /BE link (v2.2 JP1), closed
        part("Jumper:SolderJumper_2_Bridged", "JP1", "BE link", SJ2_BR, {"1": "nBE_OUT", "2": "nBE_DRV"}),
        C("C16", "10u", "+5V"),
    ]


def logic():
    # proto2: the v2.2 gates rebuilt in 74LVC at 3.3 V (inputs take the 2068's 5 V directly). The logic
    # at every Pico pin is v2.2's; only the gate delays shrink. Every signal still reaches the Pico
    # through U7, and /+W and /+RW leave U4 after the same number of gates, as their order matters
    # to the TS_IO PIO program (it reads /+W one cycle after /+RW falls).
    return [
        # U8: A14/A15 to the memories, Z80's in DOCK (/ROSCS low), the Pico's otherwise (3.3 V out, TTL-level memory inputs)
        part("74xx:74LS157", "U8", "74LVC157A", TSSOP16, {"1": "nROSCS_L", "2": "A14", "3": "A14_B", "4": "A14_I",
                                                          "5": "A15", "6": "A15_B", "7": "A15_I", "8": "GND", "16": "+3V3",
                                                          "15": "GND", "10": "GND", "11": "GND", "13": "GND", "14": "GND",
                                                          "9": NC, "12": NC}),
        # U7: control signals to the Pico (A to B always). Channel 5 now carries /BE_IN as /BE_STAT
        # (v2.2 looped the Pico's own /BE_L through it and used an LS09 gate for /BE_STAT).
        part("tspico:74LVC245_AtoB", "U7", "74LVC245APW", TSSOP20, {"1": "+3V3", "2": "A0", "3": "nPW", "4": "nMREQ_G",
                                                                    "5": "nEXROM", "6": "nBE_IN", "7": "nRDROM", "8": "nROSCS",
                                                                    "9": "nPRW", "10": "GND", "20": "+3V3", "19": "GND",
                                                                    "18": "A0_L", "17": "nPW_L", "16": "nMREQ_L", "15": "nEXR_L",
                                                                    "14": "nBE_STAT", "13": "nRDROM_L", "12": "nROSCS_L", "11": "nPRW_L"}),
        # U6: Z80 data bus <-> Pico, DIR from /+W (B to A only for an I/O read of the card's port)
        part("74xx:74LS245", "U6", "74LVC245APW", TSSOP20, {"1": "nPW", "2": "D0", "3": "D1", "4": "D2", "5": "D3",
                                                            "6": "D4", "7": "D5", "8": "D6", "9": "D7", "10": "GND",
                                                            "20": "+3V3", "19": "nU6_EN", "18": "D0_L", "17": "D1_L",
                                                            "16": "D2_L", "15": "D3_L", "14": "D4_L", "13": "D5_L",
                                                            "12": "D6_L", "11": "D7_L"}),
        # R12: 4.7k from U6 pin 8 (D6) to pin 10 (GND), a later rework on v2.2 boards that is not in the
        # 2023 schematic; carried into v2.5 as a part
        R("R12", "4k7", "D6", "GND"),
        # U5: port decode. O0 is low for an I/O cycle to $x0-$xF with A7-A5 = 0, A4 = 0 (port pair $00-$0F),
        # O1 the same with A4 = 1 ($10-$1F); E3 = /M1 keeps interrupt-acknowledge cycles out, exactly as
        # v2.2's /+RW = NOT(M1 + /IORQ + PX). JP4 picks the pair (1-2 = O0 = $00-$0F as shipped).
        part("74xx:74LS138", "U5", "74LVC138A", TSSOP16, {"1": "A4", "2": "A5", "3": "A6", "4": "nIORQ", "5": "A7",
                                                          "6": "nM1", "15": "DEC_00", "14": "DEC_10", "13": NC, "12": NC,
                                                          "11": NC, "10": NC, "9": NC, "7": NC, "8": "GND", "16": "+3V3"}),
        part("Jumper:SolderJumper_3_Bridged12", "JP4", "Port $00/$10", SJ3_BR12, {"1": "DEC_00", "2": "PORT_SEL", "3": "DEC_10"}),
        # U4: /+RW = PORT_SEL (through a gate so it keeps step with /+W); /+W = PORT_SEL + /RD, which equals
        # v2.2's NOT(/RD + /IORQ + PX) except when /M1, /IORQ and /RD are all low, which a Z80 never does;
        # /RDROM = A14 + A15 + /RD as v2.2
        part("74xx:74LS32", "U4", "74LVC32A", TSSOP14, {"1": "PORT_SEL", "2": "GND", "3": "nPRW"}, unit=1),
        part("74xx:74LS32", "U4", "74LVC32A", TSSOP14, {"4": "PORT_SEL", "5": "nRD", "6": "nPW"}, unit=2),
        part("74xx:74LS32", "U4", "74LVC32A", TSSOP14, {"9": "A14", "10": "A15", "8": "A14_OR_A15"}, unit=3),
        part("74xx:74LS32", "U4", "74LVC32A", TSSOP14, {"12": "A14_OR_A15", "13": "nRD", "11": "nRDROM"}, unit=4),
        part("74xx:74LS32", "U4", "74LVC32A", TSSOP14, {"14": "+3V3", "7": "GND"}, unit=5),
        # U1: /MREQ_G = /MREQ + NOT /BE_IN, as v2.2. The 1G97 is a 2:1 mux (Y = IN0 when IN2 high, IN1 when
        # IN2 low), so IN2 = /BE_IN, IN0 = /MREQ, IN1 tied high.
        part("74xGxx:74LVC1G97", "U1", "74LVC1G97", SOT23_6, {"1": "+3V3", "2": "GND", "3": "nMREQ", "4": "nMREQ_G",
                                                             "5": "+3V3", "6": "nBE_IN"}),
        # U9: open-drain /BE driver: /BE_DRV low when the Pico asks (nBE_L) or a card further out does (/BE_IN),
        # the wired-AND v2.2's LS09 made. Outputs tolerate 5 V (R3 pull-up to +5V).
        part("74xGxx:74LVC2G07", "U9", "74LVC2G07", SOT23_6, {"1": "nBE_L", "6": "nBE_DRV"}, unit=1),
        part("74xGxx:74LVC2G07", "U9", "74LVC2G07", SOT23_6, {"3": "nBE_IN", "4": "nBE_DRV"}, unit=2),
        part("74xGxx:74LVC2G07", "U9", "74LVC2G07", SOT23_6, {"2": "GND", "5": "+3V3"}, unit=3),
        R("R3", "2k7", "+5V", "nBE_DRV"), R("R8", "4k7", "+5V", "nBE_IN"),
        C("C1", "100n", "+3V3"), C("C4", "100n", "+3V3"), C("C5", "100n", "+3V3"), C("C8", "100n", "+3V3"),
        C("C14", "100n", "+3V3"), C("C6", "100n", "+3V3"), C("C7", "100n", "+3V3"),
    ]


def memory():
    flash = {"1": "A18", "2": "A16", "3": "A15_I", "4": "A12", "5": "A7", "6": "A6", "7": "A5", "8": "A4", "9": "A3",
             "10": "A2", "11": "A1", "12": "A0", "13": "D0", "14": "D1", "15": "D2", "16": "GND", "17": "D3",
             "18": "D4", "19": "D5", "20": "D6", "21": "D7", "22": "nU10_ENA", "23": "A10", "24": "nRD", "25": "A11",
             "26": "A9", "27": "A8", "28": "A13", "29": "A14_I", "30": "A17", "31": "FLASH_nWE", "32": "+5V"}
    sram = dict(flash)
    sram.update({"3": "A14_I", "22": "nU13_ENA", "29": "nWR", "31": "A15_I"})
    return [
        part("Memory_Flash:SST39SF040", "U10", "SST39SF040-70-4C-PHE", DIP32, flash),
        R("R6", "4k7", "+5V", "FLASH_nWE"),
        part("Jumper:SolderJumper_2_Bridged", "P10", "Flash WE", SJ2_BR, {"1": "FLASH_nWE", "2": "nWR"}),
        part("Memory_RAM:AS6C4008-55PCN", "U13", "AS6C4008-55PCN", DIP32, sram),
        # micro SD in SPI mode on the Pico's D0_L-D2_L (shared with the data bus, as v2.2)
        part("Connector:Micro_SD_Card_Det_Hirose_DM3AT", "U3", "microSD", "tspico:microSD_TF-01A",
             {"1": "SD_DAT2", "2": "SD_CS", "3": "D1_L", "4": "+3V3", "5": "D0_L", "6": "GND", "7": "D2_L",
              "8": "SD_DAT1", "9": NC, "10": "GND", "SH": "GND"}),
        R("R22", "10k", "+3V3", "SD_DAT1"), R("R23", "10k", "+3V3", "SD_DAT2"),
        C("C3", "100n", "+3V3"), C("C18", "10u", "+3V3"),
        C("C10", "100n", "+5V"), C("C13", "100n", "+5V"),
    ]


def mcu():
    gp = ["nEXR_L", "nRDROM_L", "D0_L", "D1_L", "D2_L", "D3_L", "D4_L", "D5_L", "D6_L", "D7_L",      # GP0-GP9
          "A0_L", "nPW_L", "nU6_EN", "nMREQ_L", "nPRW_L", "A15_B", "A16", "A17", "A18", "nU10_ENA",   # GP10-GP19
          "nU13_ENA", "nBE_L", "A14_B", "GP23", "VBUS_SENSE", "LED", "nROSCS_L", "nBE_STAT", "SD_CS",  # GP20-GP28
          "VSYS_SENSE"]                                                                                 # GP29
    gpio_pin = list(range(2, 10)) + list(range(11, 19)) + list(range(27, 33)) + list(range(34, 42))
    u = {str(p): gp[i] for i, p in enumerate(gpio_pin)}
    for p in (1, 10, 22, 33, 42, 49, 48, 43, 44):          # IOVDD, USB_VDD, ADC_AVDD, VREG_VIN
        u[str(p)] = "+3V3"
    u.update({"45": "DVDD", "23": "DVDD", "50": "DVDD", "19": "GND", "57": "GND", "20": "XIN", "21": "XOUT",
              "24": "SWCLK", "25": "SWDIO", "26": "PICO_RUN", "46": "USB_DM", "47": "USB_DP",
              "51": "QSPI_SD3", "52": "QSPI_SCLK", "53": "QSPI_SD0", "54": "QSPI_SD2", "55": "QSPI_SD1", "56": "QSPI_SS"})
    usb = {p: "VBUS" for p in ("A4", "A9", "B4", "B9")}
    usb.update({p: "GND" for p in ("A1", "A12", "B1", "B12", "SH")})
    usb.update({"A8": NC, "B8": NC, "A5": "CC1", "B5": "CC2", "A6": "USB_DP_C", "B6": "USB_DP_C",
                "A7": "USB_DM_C", "B7": "USB_DM_C"})
    return [
        part("MCU_RaspberryPi:RP2040", "U2", "RP2040", "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", u),
        # decoupling as the minimal design: 100 n per IOVDD/DVDD/ADC pin, 1 u on VREG_VIN and VREG_VOUT
        *[C(f"C{21 + k}", "100n", "+3V3") for k in range(7)],          # C21-C26 IOVDD x6 (one shared with USB_VDD), C27 ADC_AVDD
        C("C28", "1u", "+3V3"), C("C29", "1u", "DVDD"), C("C30", "100n", "DVDD"), C("C31", "100n", "DVDD"),
        part("Memory_Flash:W25Q16JVSS", "U21", "W25Q16JVSSIQ", SOIC8W,
             {"1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "4": "GND", "5": "QSPI_SD0", "6": "QSPI_SCLK",
              "7": "QSPI_SD3", "8": "+3V3"}),
        C("C32", "100n", "+3V3"),
        R("R24", "1k", "QSPI_SS", "BOOT_SW"),
        part("Switch:SW_Push", "SW4", "BOOTSEL", SW_FP, {"1": "BOOT_SW", "2": "GND"}),
        part("Device:Crystal_GND24", "Y1", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
             {"1": "XIN", "3": "XTAL_OUT", "2": "GND", "4": "GND"}),
        R("R25", "1k", "XOUT", "XTAL_OUT"), C("C33", "15p", "XIN"), C("C34", "15p", "XTAL_OUT"),
        part("Connector:USB_C_Receptacle_USB2.0_16P", "J1", "USB-C", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", usb),
        R("R26", "5k1", "CC1", "GND"), R("R27", "5k1", "CC2", "GND"),
        R("R28", "27", "USB_DP_C", "USB_DP"), R("R29", "27", "USB_DM_C", "USB_DM"),
        # power: VSYS = edge +5V (D2) or USB VBUS (D4); AMS1117 to +3V3
        part("Device:D_Schottky", "D2", "SS14", D_SMA, {"1": "VSYS", "2": "+5V"}),
        part("Device:D_Schottky", "D4", "SS14", D_SMA, {"1": "VSYS", "2": "VBUS"}),
        C("C2", "10u", "VSYS"),
        part("Regulator_Linear:AMS1117-3.3", "U22", "AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
             {"1": "GND", "2": "+3V3", "3": "VSYS"}),
        C("C35", "10u", "+3V3"),
        # Pico-compatible extras: VBUS sense on GP24, VSYS/3 on GP29, LED on GP25, GP23 and SWD to pads
        R("R30", "5k6", "VBUS", "VBUS_SENSE"), R("R31", "10k", "VBUS_SENSE", "GND"),
        R("R32", "200k", "VSYS", "VSYS_SENSE"), R("R33", "100k", "VSYS_SENSE", "GND"),
        R("R34", "470", "LED", "LED_A"),
        part("Device:LED", "D5", "green", "LED_SMD:LED_0805_2012Metric", {"1": "GND", "2": "LED_A"}),
        part("Connector:TestPoint", "TP1", "SWCLK", TP_FP, {"1": "SWCLK"}),
        part("Connector:TestPoint", "TP2", "SWDIO", TP_FP, {"1": "SWDIO"}),
        part("Connector:TestPoint", "TP3", "GP23", TP_FP, {"1": "GP23"}),
        # as v2.2: RUN pull-up and the Pico reset button; memory /CE pull-ups (v2.5)
        R("R9", "4k7", "+3V3", "PICO_RUN"),
        part("Switch:SW_Push", "SW3", "Pico Reset", SW_FP, {"1": "PICO_RUN", "2": "GND"}),
        part("Connector_Generic:Conn_01x02", "JP5", "Ext Pico Reset", HDR2_SMD, {"1": "GND", "2": "PICO_RUN"}, dnp=True),
        R("R15", "10k", "+3V3", "nU10_ENA"), R("R16", "10k", "+3V3", "nU13_ENA"),
    ]


NOTES = {
    "interface.kicad_sch": [
        "TS2068 rear connector (pin names per the TS2068 Technical Manual table 2.4.1-1). Side A on top, confirmed by the v3 bring-up.",
        "U11 TPS3808G01: /RESET held while +5V < 4.09 V (R1/R5) and 2.7 s after (C12 470 nF), so the Pico is running before the Z80 starts. Open-drain, like v2.2's Q1.",
        "SW1 NMI, SW2 TS reset. JP2/JP3: DNP pads for external buttons. JP1 (/BE link) is a solder jumper, closed.",
    ],
    "logic.kicad_sch": [
        "The v2.2 bus logic (Logic.schdoc) rebuilt in 74LVC at 3.3 V: same logic at every Pico pin. /+W = I/O read of the card's port; /+RW = any I/O to it (not INTA).",
        "U5 decodes the port (A7-A4, /IORQ, /M1); U4 makes /+RW, /+W, /RDROM; U1 /MREQ_G; U9 the open-drain /BE. U7 channel 5 = /BE_IN -> /BE_STAT.",
        "R12: 4.7k pull-down on D6 at U6 (pins 8 to 10), a post-2023 rework on v2.2 boards, now a fitted part.",
        "JP4: 1-2 (as shipped) answers $00-$0F, 2-3 answers $10-$1F. U8 C/D sections unused (inputs grounded).",
    ],
    "memory.kicad_sch": [
        "U10 SST39SF040 and U13 AS6C4008, DIP-32 in sockets (hand-soldered), both on the 5 V bus as v2.2. Program the flash in a ROM programmer.",
        "P10 (flash write enable from the Z80's /WR) is a solder jumper, closed: the romupdate TAP needs it.",
        "U3 micro SD in SPI mode on D0_L (SCK), D1_L (MOSI), D2_L (MISO), SD_CS (GP28), as v2.2. R22/R23 pull up the unused DAT1/DAT2.",
    ],
    "mcu.kicad_sch": [
        "RP2040 after the minimal design in 'Hardware design with RP2040'. GPIO map identical to the v2.2 Pico (Pico.SchDoc): GP0-GP22, GP26-GP28 carry the same signals.",
        "GP23 test pad, GP24 VBUS sense, GP25 LED, GP29 VSYS/3: as on the Pico, so the Pico MicroPython build sees the same board.",
        "VSYS = edge +5V through D2 (as v2.2) or USB VBUS through D4; U22 AMS1117-3.3. The card's 5 V logic and memories run from the edge only.",
        "SW4 BOOTSEL, SW3 RUN (Pico reset). R15/R16 hold the memories deselected until the firmware drives GP19/GP20.",
    ],
}


def project_symbols():
    """Rewrite lib/tspico.kicad_sym: the edge connector plus a flattened copy of a stock
    symbol, adjusted so ERC judges this circuit correctly:
      74LVC245_AtoB 74LS245 with A pins as inputs and B pins as outputs (U7 is fixed A to B)
"""
    import gen_edge_symbol
    gen_edge_symbol.main()
    path = os.path.join(HW, "lib", "tspico.kicad_sym")
    lib = schlib.SymLib()
    out = []
    for stock, name, types in (("74xx:74LS245", "74LVC245_AtoB", {**{str(n): "input" for n in range(2, 10)},
                                                                  **{str(n): "output" for n in range(11, 19)}}),):
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
           '  (title_block (title "TS-Pico v2.6") (rev "0.1") (company "Timex/Sinclair Online User Group") (comment 1 "v2.2 circuit with the RP2040 on the board"))',
           '  (lib_symbols)']
    for i, (fname, name, su) in enumerate(SHEETS):
        x, y = 30.0 + 80 * (i % 4), 30.0 + 60 * (i // 4)
        out.append(f'  (sheet (at {x} {y}) (size 60 30) (fields_autoplaced yes) (stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000)) (uuid "{su}")')
        out.append(f'    (property "Sheetname" "{name}" (at {x} {y - 0.7:.1f} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))')
        out.append(f'    (property "Sheetfile" "{fname}" (at {x} {y + 30.6:.1f} 0) (effects (font (size 1.27 1.27)) (justify left top)))')
        out.append(f'    (instances (project "tspico-v2.6" (path "/{ROOT_UUID}" (page "{i + 2}"))))')
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
               "mcu.kicad_sch": mcu()}
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
        s = Sheet(ROOT, fname, f"TS-Pico v2.6: {name}")
        parts = content[fname]
        used = {n for p in parts for n in p["pins"].values() if n}
        # power symbols: +5V and GND get a PWR_FLAG once; +3V3 is driven by the AMS1117
        px = 330
        for net in ("+5V", "+3V3", "GND"):
            if net in used:
                flag = net in ("+5V", "GND") and net not in flagged
                flagged.add(net) if flag else None
                s.power(net, px, 25, f"#PWR{pwr_ref[0]:02d}", flag=flag)
                pwr_ref[0] += 1
                px += 25
        if "VSYS" in used:          # VSYS: diode cathodes + the regulator's power_in pin; flag it
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
