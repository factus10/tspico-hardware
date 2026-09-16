#!/usr/bin/env python3
"""Generate power.kicad_sch.

  +5V_EDGE (edge pin B4) and VBUS (USB-C) are diode-ORed into the card's
  +5V rail (D2, D3 Schottky), so the card runs from the 2068 or the
  expansion bus, from USB alone on the bench, or both at once without
  back-feeding either source.
  U30 TLV1117-33  +3V3 for the RP2350B, logic, SD, OLED
  U31 TLV1117-33  +3V3_WIFI for the ESP32-C3 module
  C40/C41 220 uF bulk on +5V, 10 uF at each LDO in/out, 100 uF at the module
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
CP_FP = "Capacitor_SMD:CP_Elec_6.3x5.9"
D_SMA = "Diode_SMD:D_SMA"
SOT223 = "Package_TO_SOT_SMD:SOT-223-3_TabPin2"

OUT, IN, BI = "output", "input", "bidirectional"


def main():
    s = Sheet("tspico-v3.kicad_sch", "power.kicad_sch", "TS-Pico v3: Power")
    s.text("+5V rail = diode-OR of the edge connector +5V (B4) and USB VBUS. Card runs from the 2068/expansion bus, from USB alone, or both.", 20, 285, 2.5)
    s.text("Two LDOs: +3V3 (RP2350B, logic, SD, OLED) and +3V3_WIFI (ESP32-C3 module, 350 mA transmit bursts).", 20, 290, 2.0)

    # power symbols with the project's PWR_FLAGs
    s.power("+5V", 60, 40, "#PWR10")
    s.power("+3V3", 120, 40, "#PWR11", flag=False)   # driven by U30
    s.power("GND", 180, 50, "#PWR12")

    # ---- inputs -----------------------------------------------------------------
    D2 = s.place("Device:D_Schottky", "D2", "SS34", D_SMA, 80, 90, rot=0)
    s.glabel("+5V_EDGE", D2.pin("A"), IN); s.label("+5V", D2.pin("K"))
    D3 = s.place("Device:D_Schottky", "D3", "SS34", D_SMA, 80, 110, rot=0)
    s.glabel("VBUS", D3.pin("A"), IN); s.label("+5V", D3.pin("K"))
    F1 = s.place("power:PWR_FLAG", "#FLG10", "PWR_FLAG", "", 50, 90)
    s.glabel("+5V_EDGE", F1.pin("1"), IN)
    F2 = s.place("power:PWR_FLAG", "#FLG11", "PWR_FLAG", "", 50, 110)
    s.glabel("VBUS", F2.pin("1"), IN)
    s.text("D2/D3: SS34 (3 A, SMA). About 0.35 V drop at 0.5 A; the 1117-LV LDOs need only 0.35 V headroom.", 40, 125, 1.5)

    for k, ref in enumerate(("C40", "C41")):
        C = s.place("Device:C_Polarized", ref, "220u", CP_FP, 130 + 15 * k, 90)
        s.label("+5V", C.pin("1")); s.label("GND", C.pin("2"))
    s.text("C40/C41: bulk for WiFi transmit bursts, low-ESR polymer.", 120, 105, 1.5)

    # ---- U30 logic LDO -----------------------------------------------------------
    U30 = s.place("Regulator_Linear:TLV1117-33", "U30", "TLV1117LV33", SOT223, 230, 90)
    s.label("+5V", U30.pin("VI")); s.label("+3V3", U30.pin("VO")); s.label("GND", U30.pin("GND"))
    for k, (ref, net) in enumerate((("C42", "+5V"), ("C43", "+3V3"))):
        C = s.place("Device:C", ref, "10u", C0805, 210 + 40 * k, 110)
        s.label(net, C.pin("1")); s.label("GND", C.pin("2"))

    # ---- U31 WiFi LDO ------------------------------------------------------------
    U31 = s.place("Regulator_Linear:TLV1117-33", "U31", "TLV1117LV33", SOT223, 230, 160)
    s.label("+5V", U31.pin("VI")); s.glabel("+3V3_WIFI", U31.pin("VO"), OUT); s.label("GND", U31.pin("GND"))
    for k, (ref, net, val, fp) in enumerate((("C44", "+5V", "10u", C0805), ("C45", "+3V3_WIFI", "10u", C0805), ("C46", "+3V3_WIFI", "220u", CP_FP))):
        C = s.place("Device:C" if val != "220u" else "Device:C_Polarized", ref, val, fp, 210 + 30 * k, 180)
        (s.glabel(net, C.pin("1"), IN) if net == "+3V3_WIFI" else s.label(net, C.pin("1"))); s.label("GND", C.pin("2"))
    s.text("U30/U31: TLV1117LV33 (SOT-223, 1 A, 0.35 V dropout, 1117 pinout). Alternate: AMS1117-3.3 (1.1 V dropout, marginal).", 195, 200, 1.5)
    s.text("Input current budget: about 250 mA average, 600 mA peak with WiFi transmit. Do not exceed 1 A from the 2068's own rail.", 195, 204, 1.5)

    s.write()
    print("wrote power.kicad_sch")


if __name__ == "__main__":
    main()
