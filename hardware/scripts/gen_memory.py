#!/usr/bin/env python3
"""Generate memory.kicad_sch: the local bus muxes and the four registers.

  U10/U11 74LVC257  MA0-MA15 byte mux onto MD0-MD7 (S = ASEL, /OE = nAOE)
  U12/U13 74HC574   ALO / AHI: DMA-mode address latches (/OE = nDMA_EN)
  U14     74HC273   CTL register (cleared by power-on RC)
  U15     74LVC245  STAT read buffer (DIR low, B->A; same part as U1-U4)
  Register strobes nWR_ALO, nWR_AHI, nWR_CTL, nRD_STAT come straight from RP2350B GPIOs (the 74LVC139 is gone)
  R4/C9/D1 power-on reset for CTL; C10-C16 decoupling
See docs/v3-architecture.md sections 3 and 4.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

TSSOP16 = "Package_SO:TSSOP-16_4.4x5mm_P0.65mm"
TSSOP20 = "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SOD123 = "Diode_SMD:D_SOD-123"

OUT, IN, BI = "output", "input", "bidirectional"


def main():
    s = Sheet("tspico-v3.kicad_sch", "memory.kicad_sch", "TS-Pico v3: Local Bus and Registers")
    s.text("Local bus MD0-MD7 carries the Z80 address (two bytes through U10/U11), the Z80 data (interface sheet U3) and the registers.", 20, 285, 2.5)
    s.text("No flash or SRAM: the RP2350B serves memory from internal SRAM (PIO + DMA). ALO/AHI drive MA only in DMA mode.", 20, 290, 2.0)

    s.power("+3V3", 300, 30, "#PWR04", flag=False)
    s.power("GND", 330, 40, "#PWR05", flag=False)

    # ---- U10/U11 address byte muxes ---------------------------------------------
    for k, ref in enumerate(("U10", "U11")):
        U = s.place("74xx:74LS257", ref, "74LVC257APW", TSSOP16, 90, 50 + 60 * k)
        for j, ch in enumerate("abcd"):
            bit = 4 * k + j
            s.glabel(f"MA{bit}", U.pin(f"I0{ch}"), BI)
            s.glabel(f"MA{bit + 8}", U.pin(f"I1{ch}"), BI)
            s.glabel(f"MD{bit}", U.pin(f"Z{ch}"), BI)
        s.glabel("ASEL", U.pin("S"), IN)
        s.glabel("nAOE", U.pin("OE"), IN)
        s.label("+3V3", U.pin("VCC")); s.label("GND", U.pin("GND"))

    # ---- U12/U13 DMA address latches (74LS574 pinout: 1 /OE, 2-9 D0-D7, 11 CP, 12-19 Q7-Q0)
    for k, (ref, strobe) in enumerate((("U12", "nWR_ALO"), ("U13", "nWR_AHI"))):
        U = s.place("74xx:74LS574", ref, "74HC574PW", TSSOP20, 190, 50 + 60 * k)
        for bit in range(8):
            s.glabel(f"MD{bit}", U.pin(str(2 + bit)), BI)
            s.glabel(f"MA{8 * k + bit}", U.pin(str(19 - bit)), BI)
        s.glabel(strobe, U.pin("11"), IN)
        s.glabel("nDMA_EN", U.pin("1"), IN)
        s.label("+3V3", U.pin("20")); s.label("GND", U.pin("10"))

    # ---- U14 CTL register --------------------------------------------------------
    U14 = s.place("74xx:74LS273", "U14", "74HC273PW", TSSOP20, 290, 80)
    ctl_bits = ["DMA_EN", "BUSRQ", "NMI_REQ", "nOLED_RST", "WIFI_EN", "WIFI_DL", "LED", None]
    for bit in range(8):
        s.glabel(f"MD{bit}", U14.pin(f"D{bit}"), BI)
        if ctl_bits[bit]:
            s.glabel(ctl_bits[bit], U14.pin(f"Q{bit}"), OUT)
        else:
            s.nc(U14.pin(f"Q{bit}"))
    s.glabel("nWR_CTL", U14.pin("Cp"), IN)
    s.label("nPOR", U14.pin("~{Mr}"))
    s.label("+3V3", U14.pin("VCC")); s.label("GND", U14.pin("GND"))

    # ---- U15 STAT read buffer ------------------------------------------------------
    U15 = s.place("74xx:74LS245", "U15", "74LVC245APW", TSSOP20, 290, 160)
    stat_bits = ["JOY_UP", "JOY_DOWN", "JOY_LEFT", "JOY_RIGHT", "JOY_FIRE1", "JOY_FIRE2", "nBUSAK", "SD_CD"]
    for bit in range(8):
        s.glabel(stat_bits[bit], U15.pin(f"B{bit}"), IN)
        s.glabel(f"MD{bit}", U15.pin(f"A{bit}"), BI)
    s.label("GND", U15.pin("1"))                      # DIR low: B -> A
    s.glabel("nRD_STAT", U15.pin("19"), IN)
    s.label("+3V3", U15.pin("20")); s.label("GND", U15.pin("10"))

    s.text("Register strobes nWR_ALO / nWR_AHI / nWR_CTL / nRD_STAT are RP2350B GPIOs (no decoder).", 190, 170, 1.5)

    # ---- power-on reset for CTL: 10k up, 1u down, Schottky for fast discharge -------
    R4 = s.place("Device:R", "R4", "10k", R0603, 370, 80)
    s.label("+3V3", R4.pin("1")); s.label("nPOR", R4.pin("2"))
    C9 = s.place("Device:C", "C9", "1u", C0603, 370, 100)
    s.label("nPOR", C9.pin("1")); s.label("GND", C9.pin("2"))
    D1 = s.place("Device:D_Schottky", "D1", "B5819W", SOD123, 395, 90, rot=90)
    s.label("nPOR", D1.pin("A")); s.label("+3V3", D1.pin("K"))
    s.text("R4/C9/D1: ~10 ms power-on clear of CTL,", 355, 118, 1.5)
    s.text("so all control bits start at 0.", 355, 121, 1.5)

    # ---- activity LED from CTL bit 6 ---------------------------------------------------
    R5 = s.place("Device:R", "R5", "1k", R0603, 370, 160)
    s.glabel("LED", R5.pin("1"), IN); s.label("LED_K", R5.pin("2"))
    D4 = s.place("Device:LED", "D4", "green", "LED_SMD:LED_0805_2012Metric", 375, 180)
    s.label("LED_K", D4.pin("A")); s.label("GND", D4.pin("K"))
    s.text("R5/D4: activity LED, CTL bit 6.", 355, 195, 1.5)

    # ---- decoupling -----------------------------------------------------------------------
    for k in range(7):
        C = s.place("Device:C", f"C{10 + k}", "100n", C0603, 40 + 9 * k, 255)
        s.label("+3V3", C.pin("1")); s.label("GND", C.pin("2"))

    s.write()
    print("wrote memory.kicad_sch")


if __name__ == "__main__":
    main()
