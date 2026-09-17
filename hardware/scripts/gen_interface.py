#!/usr/bin/env python3
"""Generate interface.kicad_sch: the TS2068 side of the TS-Pico v3.

Contents (see docs/v3-architecture.md sections 2, 3, 5):
  P1   TS2068 edge connector
  U1   74LVC245  Z80 A0-A3, A12-A15 -> MD   address group X, /OE = nAEN_X (fixed B->A)
  U2   74LVC245  Z80 A4-A11         -> MD   address group Y, /OE = nAEN_Y
       The two output enables are the byte mux: the PIO enables X, reads MD, enables Y, reads MD.
  U3   74LVC245  Z80 D0-D7 <-> MD0-MD7      DIR from U9 (or straight from /RD without the DMA option), /OE = nDATA_OE
  U4   74LVC245  Z80 control inputs -> 3.3 V copies for the MCU (fixed B->A)
  U6   74LVC32   bus strobes: nMEMRD, nMEMWR, nIORD, nIOWR (refresh and INTACK never assert /RD or /WR,
                 so no /RFSH or /M1 qualification is needed)
  U7   74LVC06   (SOIC-14) open-drain inverting drivers: BE_REQ, WAIT_REQ, BUSRQ, NMI_REQ, RESET_HOLD -> nBE, nWAIT,
                 nBUSRQ, nNMI, nRESET; sixth gate WIFI_DL -> nWIFI_BOOT (ESP32 IO9)
  DMA stuffing option (config.DMA_OPTION), all DNP except U9:
  U8   74LVC245  DMA bus drivers for nMREQ, nRD, nWR (DIR fixed A->B, /OE = nDMA_EN)
  U9   74LVC1G86 DATA_DIR = nRD xor nDMA_EN (fitted; nDMA_EN is pulled high by R4)
  U12/U13 74LVC574 ALO / AHI address latches, outputs straight onto Z80 A0-A15 (/OE = nDMA_EN)
  SW1/SW2 TS reset and NMI buttons; R1 RESET_HOLD pull-up; R2/R3 EAR divider
Net naming: n<NAME> = active low. Signals with suffix _L are 3.3 V copies of
5 V bus signals; *_REQ / BUSRQ / RESET_HOLD are active-high requests that the
open-drain inverting drivers turn into active-low bus signals.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402
from config import DMA_OPTION  # noqa: E402

TSSOP20 = "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"
TSSOP14 = "Package_SO:TSSOP-14_4.4x5mm_P0.65mm"
SOIC14 = "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SW_FP = "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A"

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
        "A24": ("nRESET", "loc"), "A27": ("nEXROM", "loc"),
        "A28": ("nROSCS", "loc"), "A29": ("nBE", "loc"),
        "A21": ("nBUSAK", OUT), "A31": ("SOUND_2068", OUT),
        "B10": ("A0", "loc"), "B11": ("A1", "loc"), "B12": ("A2", "loc"), "B13": ("A3", "loc"),
        "B14": ("A15", "loc"), "B15": ("A14", "loc"), "B16": ("A13", "loc"), "B17": ("A12", "loc"),
        "B18": ("A11", "loc"), "B19": ("A10", "loc"), "B20": ("A9", "loc"), "B21": ("A8", "loc"),
        "B22": ("A7", "loc"), "B23": ("A6", "loc"), "B24": ("A5", "loc"), "B25": ("A4", "loc"),
    }
    nc_pins = ["A25", "A26",    # /M1, /RFSH: not needed with the /RD-/WR qualified strobes
               "A3", "A5", "A16", "A30", "B3", "B5", "B9", "B26", "B27", "B28", "B29", "B30", "B31"]
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

    # ---- U1/U2 address buffers; their output enables are the byte mux ------------
    def transceiver(ref, x, y, value="74LVC245APW", dnp=False):
        return s.place("74xx:74LS245", ref, value, TSSOP20, x, y, dnp=dnp)

    # The B side follows the connector's finger order so the tracks from the
    # fingers do not cross (at rot 270 on the board B7 is the leftmost pin).
    # Finger order, left to right: A0 A1 A2 A3 A15 A14 A13 A12 | A11 ... A4.
    # Each chip puts two address nibbles on MD:
    #   group X (U1): MD3-0 = A3-A0,  MD7-4 = A15-A12
    #   group Y (U2): MD3-0 = A7-A4,  MD7-4 = A11-A8
    # so the PIO's 16-bit word {X, Y} is the address with its nibbles in the
    # order 3,0,2,1. The firmware stores images indexed by that word.
    U1 = transceiver("U1", 150, 50)
    for b_, idx in zip(range(7, -1, -1), [0, 1, 2, 3, 15, 14, 13, 12]):
        s.label(f"A{idx}", U1.pin(f"B{b_}"))
        s.glabel(f"MD{idx if idx < 4 else idx - 8}", U1.pin(f"A{b_}"), BI)
    s.label("GND", U1.pin("1"))                      # DIR low: B -> A
    s.glabel("nAEN_X", U1.pin("19"), IN)
    s.label("+3V3", U1.pin("20")); s.label("GND", U1.pin("10"))

    U2 = transceiver("U2", 150, 110)
    for b_, idx in zip(range(7, -1, -1), [11, 10, 9, 8, 7, 6, 5, 4]):
        s.label(f"A{idx}", U2.pin(f"B{b_}"))
        s.glabel(f"MD{idx - 4}", U2.pin(f"A{b_}"), BI)
    s.label("GND", U2.pin("1"))
    s.glabel("nAEN_Y", U2.pin("19"), IN)
    s.label("+3V3", U2.pin("20")); s.label("GND", U2.pin("10"))

    # ---- U3 data transceiver ---------------------------------------------------------
    U3 = transceiver("U3", 150, 170)
    z80_side, md_side = ("B", "A") if DMA_OPTION else ("A", "B")
    # The Z80 side faces the fingers. With B facing them (rot 270) B7 is the leftmost pin; with A
    # facing them (rot 90, no DMA option) A0 is, so the pin order runs the other way.
    for b_, idx in zip(range(7, -1, -1) if DMA_OPTION else range(8), [7, 0, 1, 2, 6, 5, 3, 4]):
        s.label(f"D{idx}", U3.pin(f"{z80_side}{b_}"))
        s.glabel(f"MD{idx}", U3.pin(f"{md_side}{b_}"), BI)
    if DMA_OPTION:
        # B = Z80, A = MD. DIR high = A->B (local -> Z80): a Z80 read in Z80 mode,
        # a write in DMA mode: DATA_DIR = nRD xor nDMA_EN (U9).
        s.label("DATA_DIR", U3.pin("1"))
    else:
        # A = Z80, B = MD. DIR = /RD: low on a Z80 read = B->A (local -> Z80).
        s.label("nRD", U3.pin("1"))
    s.glabel("nDATA_OE", U3.pin("19"), IN)
    s.label("+3V3", U3.pin("20")); s.label("GND", U3.pin("10"))

    # ---- U4 control inputs, fixed B (Z80) -> A (MCU), in finger order ----------
    U4 = transceiver("U4", 150, 230)
    ctl = [("SPKR_TAPE", "TAPE_IN"), ("nINT", "nINT_L"), ("A15", "Z80_A15"), ("A14", "Z80_A14"),
           ("nBUSAK", "nBUSAK_L"), (None, None), ("nEXROM", "nEXROM_L"), ("nROSCS", "nROSCS_L")]
    for b_, (src, dst) in zip(range(7, -1, -1), ctl):
        if src is None:
            s.label("GND", U4.pin(f"B{b_}")); s.nc(U4.pin(f"A{b_}"))
            continue
        if src == "nBUSAK":
            s.glabel(src, U4.pin(f"B{b_}"), IN)
        else:
            s.label(src, U4.pin(f"B{b_}"))
        s.glabel(dst, U4.pin(f"A{b_}"), OUT)
    s.label("GND", U4.pin("1"))     # DIR low: B -> A
    s.label("GND", U4.pin("19"))    # always enabled
    s.label("+3V3", U4.pin("20")); s.label("GND", U4.pin("10"))

    # ---- U6 bus strobes (74LVC32, inputs straight from the 5 V bus) ---------------
    or_x, or_y = 250, 160
    ors = [s.place("74xx:74LS32", "U6", "74LVC32APW", TSSOP14, or_x, or_y + 15 * k, unit=k + 1) for k in range(4)]
    pw6 = s.place("74xx:74LS32", "U6", "74LVC32APW", TSSOP14, or_x, or_y + 70, unit=5)
    s.label("+3V3", pw6.pin("14")); s.label("GND", pw6.pin("7"))
    for k, (a_, b_, out, (pa, pb, po)) in enumerate([("nMREQ", "nRD", "nMEMRD", ("1", "2", "3")), ("nMREQ", "nWR", "nMEMWR", ("4", "5", "6")),
                                                     ("nIORQ", "nRD", "nIORD", ("9", "10", "8")), ("nIORQ", "nWR", "nIOWR", ("12", "13", "11"))]):
        s.label(a_, ors[k].pin(pa)); s.label(b_, ors[k].pin(pb)); s.glabel(out, ors[k].pin(po), OUT)

    # ---- U7 open-drain drivers -------------------------------------------------
    od_x, od_y = 330, 60
    od = [s.place("74xx:74LS06", "U7", "74LVC06AD", SOIC14, od_x, od_y + 15 * k, unit=k + 1) for k in range(6)]
    pw7 = s.place("74xx:74LS06", "U7", "74LVC06AD", SOIC14, od_x, od_y + 100, unit=7)
    s.label("+3V3", pw7.pin("14")); s.label("GND", pw7.pin("7"))
    od_map = [("BE_REQ", "nBE", "1", "2"), ("WAIT_REQ", "nWAIT", "3", "4"), ("BUSRQ", "nBUSRQ", "5", "6"),
              ("NMI_REQ", "nNMI", "9", "8"), ("RESET_HOLD", "nRESET", "11", "10")]
    for k, (src, dst, pi, po) in enumerate(od_map):
        s.glabel(src, od[k].pin(pi), IN)
        s.label(dst, od[k].pin(po))
    s.glabel("WIFI_DL", od[5].pin("13"), IN); s.glabel("nWIFI_BOOT", od[5].pin("12"), OUT)   # ESP32 IO9, pulled up on the WiFi sheet

    if DMA_OPTION:
        # ---- U8 DMA bus drivers: 74LVC245, DIR high (A->B), /OE = nDMA_EN. DNP. ------
        U8 = transceiver("U8", 330, 200, dnp=True)
        for k, (src, dst) in enumerate([("nDMA_MREQ", "nMREQ"), ("nMRD", "nRD"), ("nMWR", "nWR")]):
            s.glabel(src, U8.pin(f"A{k}"), IN)
            s.label(dst, U8.pin(f"B{k}"))
        for k in range(3, 8):
            s.label("GND", U8.pin(f"A{k}")); s.nc(U8.pin(f"B{k}"))
        s.label("+3V3", U8.pin("1"))                      # DIR: A -> B
        s.glabel("nDMA_EN", U8.pin("19"), IN)
        s.label("+3V3", U8.pin("20")); s.label("GND", U8.pin("10"))

        # ---- U9 XOR: DATA_DIR = nRD xor nDMA_EN (fitted; nDMA_EN idles high) ---------
        U9 = s.place("74xGxx:74LVC1G86", "U9", "74LVC1G86", SOT23_5, 260, 250)
        s.label("nRD", U9.pin("1")); s.glabel("nDMA_EN", U9.pin("2"), IN); s.label("DATA_DIR", U9.pin("4"))
        s.label("+3V3", U9.pin("5")); s.label("GND", U9.pin("3"))
        R4 = s.place("Device:R", "R4", "10k", R0603, 290, 250)
        s.label("+3V3", R4.pin("1")); s.glabel("nDMA_EN", R4.pin("2"), IN)

        # ---- U12/U13 DMA address latches, outputs on the Z80 address bus. DNP. -------
        # 74LS574 pinout: 1 /OE, 2-9 D0-D7, 11 CP, 19-12 Q0-Q7. LVC: 5 V tolerant when disabled.
        for k, (ref, strobe) in enumerate((("U12", "nWR_ALO"), ("U13", "nWR_AHI"))):
            U = s.place("74xx:74LS574", ref, "74LVC574APW", TSSOP20, 250, 45 + 60 * k, dnp=True)
            for bit in range(8):
                s.glabel(f"MD{bit}", U.pin(str(2 + bit)), BI)
                s.label(f"A{8 * k + bit}", U.pin(str(19 - bit)))
            s.glabel(strobe, U.pin("11"), IN)
            s.glabel("nDMA_EN", U.pin("1"), IN)
            s.label("+3V3", U.pin("20")); s.label("GND", U.pin("10"))

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
    for k in range(9 if DMA_OPTION else 6):          # C1-C6: U1-U4, U6, U7 (U9 shares); C7-C9: U8, U12, U13 (DNP)
        C = s.place("Device:C", f"C{k + 1}", "100n", C0603, 40 + 9 * k, 255, dnp=k >= 6)
        s.label("+3V3", C.pin("1")); s.label("GND", C.pin("2"))

    s.write()
    print("wrote interface.kicad_sch")


if __name__ == "__main__":
    main()
