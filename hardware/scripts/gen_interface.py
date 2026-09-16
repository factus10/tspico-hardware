#!/usr/bin/env python3
"""Generate interface.kicad_sch: the TS2068 side of the TS-Pico v3.

Contents (see docs/v3-architecture.md sections 2, 3, 5):
  P1   TS2068 edge connector
  U1   74LVC245  Z80 A0-A7   <-> MA0-MA7        DIR=DMA_EN, always enabled
  U2   74LVC245  Z80 A8-A15  <-> MA8-MA15
  U3   74LVC245  Z80 D0-D7   <-> MD0-MD7        DIR=DATA_DIR (nRD xor DMA_EN), /OE=nDATA_OE
  U4   74LVC245  Z80 control inputs -> 3.3 V copies for the MCU (fixed B->A)
  U5   74LVC04   inverters for the gating below, one spare
  U6   74LVC08   nMREQ_V = /(MREQ & /RFSH), nIORQ_V = /(IORQ & /M1),
                 nDMA_MREQ = nMRD & nMWR, one spare
  U7   74LVC06   open-drain inverting drivers: BE_REQ, WAIT_REQ, BUSRQ, NMI_REQ, RESET_HOLD -> nBE, nWAIT, nBUSRQ, nNMI, nRESET
  U8   74LVC126  DMA bus drivers for nMREQ, nRD, nWR (OE = DMA_EN)
  U9   74LVC1G86 DATA_DIR = nRD xor DMA_EN
  SW1/SW2 TS reset and NMI buttons; R1 RESET_HOLD pull-up; R2/R3 EAR divider
  C1-C8 decoupling
Net naming: n<NAME> = active low. Signals with suffix _L are 3.3 V copies of
5 V bus signals; *_REQ / BUSRQ / RESET_HOLD are active-high requests that the
open-drain inverting drivers turn into active-low bus signals.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

TSSOP20 = "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"
TSSOP14 = "Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SW_FP = "Button_Switch_SMD:SW_SPST_PTS645Sx43SMTR92"

OUT, IN, BI = "output", "input", "bidirectional"


def main():
    s = Sheet("tspico-v3.kicad_sch", "interface.kicad_sch", "TS-Pico v3: 2068 Interface")
    s.text("TS2068 bus interface. Nets: n = active low, _L = 3.3 V copy of a bus signal, _G = 3.3 V request driven onto the bus through an open-drain buffer.", 20, 285, 2.5)
    s.text("Power: edge +5V (B4) goes to the power sheet as +5V_EDGE and is diode-ORed with USB VBUS. +15V (B3) unused.", 20, 290, 2.0)

    # ---- P1 edge connector -------------------------------------------------
    P1 = s.place("tspico:TS2068_Edge", "P1", "TS2068_Edge", "tspico:TS2068_EdgeConnector_2x32", 60, 120)
    bus_out = {  # pin -> (net, kind) for signals leaving the connector into logic on this sheet
        "A1": ("GND", "pwr"), "B1": ("GND", "pwr"), "A32": ("GND", "pwr"), "B32": ("GND", "pwr"),
        "B7": ("GND", "pwr"), "B8": ("GND", "pwr"), "B4": ("+5V_EDGE", OUT),
        "A2": ("EAR", "loc"), "B2": ("SPKR_TAPE", "loc"),
        "A4": ("D7", "loc"), "A7": ("D0", "loc"), "A8": ("D1", "loc"), "A9": ("D2", "loc"),
        "A10": ("D6", "loc"), "A11": ("D5", "loc"), "A12": ("D3", "loc"), "A13": ("D4", "loc"),
        "A14": ("nINT", "loc"), "A15": ("nNMI", "loc"), "A17": ("nMREQ", "loc"), "A18": ("nIORQ", "loc"),
        "A19": ("nRD", "loc"), "A20": ("nWR", "loc"), "A22": ("nWAIT", "loc"), "A23": ("nBUSRQ", "loc"),
        "A24": ("nRESET", "loc"), "A25": ("nM1", "loc"), "A26": ("nRFSH", "loc"), "A27": ("nEXROM", "loc"),
        "A28": ("nROSCS", "loc"), "A29": ("nBE", "loc"),
        "A21": ("nBUSAK", OUT), "A31": ("SOUND_2068", OUT),
        "B10": ("A0", "loc"), "B11": ("A1", "loc"), "B12": ("A2", "loc"), "B13": ("A3", "loc"),
        "B14": ("A15", "loc"), "B15": ("A14", "loc"), "B16": ("A13", "loc"), "B17": ("A12", "loc"),
        "B18": ("A11", "loc"), "B19": ("A10", "loc"), "B20": ("A9", "loc"), "B21": ("A8", "loc"),
        "B22": ("A7", "loc"), "B23": ("A6", "loc"), "B24": ("A5", "loc"), "B25": ("A4", "loc"),
    }
    nc_pins = ["A3", "A5", "A16", "A30", "B3", "B5", "B9", "B26", "B27", "B28", "B29", "B30", "B31"]
    for pin, (net, kind) in bus_out.items():
        at = P1.pin(pin)
        if kind in ("loc", "pwr"):
            s.label(net, at)
        else:
            s.glabel(net, at, kind)
    for pin in nc_pins:
        s.nc(P1.pin(pin))

    # ---- power symbols -----------------------------------------------------
    s.power("+3V3", 330, 30, "#PWR02", flag=False)
    s.power("GND", 360, 40, "#PWR03", flag=False)

    # ---- U1/U2 address transceivers ------------------------------------------
    def transceiver(ref, x, y, value="74LVC245APW"):
        return s.place("74xx:74LS245", ref, value, TSSOP20, x, y)

    U1 = transceiver("U1", 150, 50)
    for i in range(8):
        s.label(f"A{i}", U1.pin(f"B{i}"))          # Z80 side (B)
        s.glabel(f"MA{i}", U1.pin(f"A{i}"), BI)    # local side (A); driven by ALO in DMA mode
    s.glabel("DMA_EN", U1.pin("1"), IN)
    s.label("GND", U1.pin("19"))
    s.label("+3V3", U1.pin("20"))
    s.label("GND", U1.pin("10"))

    U2 = transceiver("U2", 150, 110)
    for i in range(8):
        s.label(f"A{8 + i}", U2.pin(f"B{i}"))
    for i in range(8):
        s.glabel(f"MA{8 + i}", U2.pin(f"A{i}"), BI)
    s.glabel("DMA_EN", U2.pin("1"), IN)
    s.label("GND", U2.pin("19"))
    s.label("+3V3", U2.pin("20"))
    s.label("GND", U2.pin("10"))

    # ---- U3 data transceiver: A side = Z80, B side = local (DIR = nRD in Z80 mode)
    U3 = transceiver("U3", 150, 170)
    for i in range(8):
        s.label(f"D{i}", U3.pin(f"A{i}"))
        s.glabel(f"MD{i}", U3.pin(f"B{i}"), BI)
    s.label("DATA_DIR", U3.pin("1"))
    s.glabel("nDATA_OE", U3.pin("19"), IN)
    s.label("+3V3", U3.pin("20"))
    s.label("GND", U3.pin("10"))

    # ---- U4 control inputs, fixed B (Z80) -> A (MCU) -------------------------
    U4 = transceiver("U4", 150, 230)
    ctl = [("nRD", "nRD_L"), ("nWR", "nWR_L"), ("nROSCS", "nROSCS_L"), ("nEXROM", "nEXROM_L"),
           ("nINT", "nINT_L"), ("A14", "Z80_A14"), ("A15", "Z80_A15"), ("SPKR_TAPE", "TAPE_IN")]
    for i, (src, dst) in enumerate(ctl):
        s.label(src, U4.pin(f"B{i}"))
        s.glabel(dst, U4.pin(f"A{i}"), OUT)
    s.label("GND", U4.pin("1"))     # DIR low: B -> A
    s.label("GND", U4.pin("19"))    # always enabled
    s.label("+3V3", U4.pin("20"))
    s.label("GND", U4.pin("10"))

    # ---- U5 inverters, U6 AND gates ------------------------------------------
    inv_x, inv_y = 250, 40
    inv = [s.place("74xx:74LS04", "U5", "74LVC04APW", TSSOP14, inv_x, inv_y + 15 * k, unit=k + 1) for k in range(6)]
    pw5 = s.place("74xx:74LS04", "U5", "74LVC04APW", TSSOP14, inv_x, inv_y + 100, unit=7)
    s.label("+3V3", pw5.pin("14")); s.label("GND", pw5.pin("7"))
    and_x, and_y = 250, 160
    ands = [s.place("74xx:74LS08", "U6", "74LVC08APW", TSSOP14, and_x, and_y + 15 * k, unit=k + 1) for k in range(4)]
    pw6 = s.place("74xx:74LS08", "U6", "74LVC08APW", TSSOP14, and_x, and_y + 70, unit=5)
    s.label("+3V3", pw6.pin("14")); s.label("GND", pw6.pin("7"))

    # inverter a: nMREQ -> MREQ_H ; b: nIORQ -> IORQ_H ; c: MREQ_RFSH -> nMREQ_V
    # d: IORQ_M1 -> nIORQ_V ; e: DMA_EN -> nDMA_EN ; f: WIFI_DL -> nWIFI_BOOT (ESP32 IO9)
    s.label("nMREQ", inv[0].pin("1"));   s.label("MREQ_H", inv[0].pin("2"))
    s.label("nIORQ", inv[1].pin("3"));   s.label("IORQ_H", inv[1].pin("4"))
    s.label("MREQ_RFSH", inv[2].pin("5")); s.glabel("nMREQ_V", inv[2].pin("6"), OUT)
    s.label("IORQ_M1", inv[3].pin("9"));   s.glabel("nIORQ_V", inv[3].pin("8"), OUT)
    s.glabel("DMA_EN", inv[4].pin("11"), IN); s.glabel("nDMA_EN", inv[4].pin("10"), OUT)
    s.glabel("WIFI_DL", inv[5].pin("13"), IN); s.glabel("nWIFI_BOOT", inv[5].pin("12"), OUT)

    # AND a: MREQ_H & nRFSH ; b: IORQ_H & nM1 ; c: nMRD & nMWR ; d: spare
    s.label("MREQ_H", ands[0].pin("1")); s.label("nRFSH", ands[0].pin("2")); s.label("MREQ_RFSH", ands[0].pin("3"))
    s.label("IORQ_H", ands[1].pin("4")); s.label("nM1", ands[1].pin("5"));   s.label("IORQ_M1", ands[1].pin("6"))
    s.glabel("nMRD", ands[2].pin("9"), IN); s.glabel("nMWR", ands[2].pin("10"), IN); s.label("nDMA_MREQ", ands[2].pin("8"))
    s.label("GND", ands[3].pin("12")); s.label("GND", ands[3].pin("13")); s.nc(ands[3].pin("11"))

    # ---- U7 open-drain drivers -------------------------------------------------
    od_x, od_y = 330, 60
    od = [s.place("74xx:74LS06", "U7", "74LVC06APW", TSSOP14, od_x, od_y + 15 * k, unit=k + 1) for k in range(6)]
    pw7 = s.place("74xx:74LS06", "U7", "74LVC06APW", TSSOP14, od_x, od_y + 100, unit=7)
    s.label("+3V3", pw7.pin("14")); s.label("GND", pw7.pin("7"))
    od_map = [("BE_REQ", "nBE", "1", "2"), ("WAIT_REQ", "nWAIT", "3", "4"), ("BUSRQ", "nBUSRQ", "5", "6"),
              ("NMI_REQ", "nNMI", "9", "8"), ("RESET_HOLD", "nRESET", "11", "10")]
    for k, (src, dst, pi, po) in enumerate(od_map):
        s.glabel(src, od[k].pin(pi), IN)
        s.label(dst, od[k].pin(po))
    s.label("GND", od[5].pin("13")); s.nc(od[5].pin("12"))    # spare inverter: input low, output off

    # ---- U8 DMA bus drivers (74LVC126, OE active high = DMA_EN) -----------------
    dma_x, dma_y = 330, 185
    dr = [s.place("74xx:74LS126", "U8", "74LVC126APW", TSSOP14, dma_x, dma_y + 18 * k, unit=k + 1) for k in range(4)]
    pw8 = s.place("74xx:74LS126", "U8", "74LVC126APW", TSSOP14, dma_x + 35, dma_y + 45, unit=5)
    s.label("+3V3", pw8.pin("14")); s.label("GND", pw8.pin("7"))
    dr_map = [("nDMA_MREQ", "nMREQ", "2", "3", "1"), ("nMRD", "nRD", "5", "6", "4"), ("nMWR", "nWR", "9", "8", "10")]
    for k, (src, dst, pi, po, oe) in enumerate(dr_map):
        if src.startswith("nM") and src != "nDMA_MREQ":
            s.glabel(src, dr[k].pin(pi), IN)
        else:
            s.label(src, dr[k].pin(pi))
        s.label(dst, dr[k].pin(po))
        s.glabel("DMA_EN", dr[k].pin(oe), IN)
    s.label("GND", dr[3].pin("12")); s.label("GND", dr[3].pin("13")); s.nc(dr[3].pin("11"))

    # ---- U9 XOR: DATA_DIR = nRD xor DMA_EN -------------------------------------
    U9 = s.place("74xGxx:74LVC1G86", "U9", "74LVC1G86", SOT23_5, 260, 250)
    s.label("nRD", U9.pin("1")); s.glabel("DMA_EN", U9.pin("2"), IN); s.label("DATA_DIR", U9.pin("4"))
    s.label("+3V3", U9.pin("5")); s.label("GND", U9.pin("3"))

    # ---- reset / NMI buttons, pull-down, tape divider --------------------------
    SW1 = s.place("Switch:SW_Push", "SW1", "TS Reset", SW_FP, 385, 150)
    s.label("nRESET", SW1.pin("1")); s.label("GND", SW1.pin("2"))
    SW2 = s.place("Switch:SW_Push", "SW2", "NMI", SW_FP, 385, 165)
    s.label("nNMI", SW2.pin("1")); s.label("GND", SW2.pin("2"))
    R1 = s.place("Device:R", "R1", "4k7", R0603, 380, 50)
    s.label("+3V3", R1.pin("1")); s.glabel("RESET_HOLD", R1.pin("2"), IN)
    R2 = s.place("Device:R", "R2", "4k7", R0603, 395, 90)
    s.glabel("TAPE_OUT", R2.pin("1"), IN); s.label("EAR", R2.pin("2"))
    R3 = s.place("Device:R", "R3", "1k", R0603, 395, 110)
    s.label("EAR", R3.pin("1")); s.label("GND", R3.pin("2"))
    s.text("R2/R3: TAPE_OUT divided to ~0.6 V for the 2068 EAR input.", 355, 125, 1.5)
    s.text("Values to be confirmed on the prototype.", 355, 128, 1.5)

    # ---- decoupling ------------------------------------------------------------
    for k in range(8):
        C = s.place("Device:C", f"C{k + 1}", "100n", C0603, 40 + 9 * k, 255)
        s.label("+3V3", C.pin("1")); s.label("GND", C.pin("2"))

    s.write()
    print("wrote interface.kicad_sch")


if __name__ == "__main__":
    main()
