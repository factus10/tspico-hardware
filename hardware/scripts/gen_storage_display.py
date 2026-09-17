#!/usr/bin/env python3
"""Generate storage_display.kicad_sch: micro SD socket and OLED header.

  J2  HRO TF-01A push-push micro SD (was Hirose DM3AT, 8x the price), SPI mode on SPI0, card detect to STAT
  J3  7-pin header for the Waveshare 1.27" 128x96 SSD1351 RGB OLED (VCC GND DIN CLK CS DC RST)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SD_FP = "tspico:microSD_TF-01A"   # custom footprint for the HRO TF-01A push-push socket (pads 1-8, 9 = CD switch, 10 = CD common, SH)
HDR7 = "Connector_PinHeader_2.54mm:PinHeader_1x07_P2.54mm_Vertical"

OUT, IN, BI = "output", "input", "bidirectional"


def main():
    s = Sheet("tspico-v3.kicad_sch", "storage_display.kicad_sch", "TS-Pico v3: SD and Display")
    s.text("Micro SD in SPI mode on the RP2350B SPI0 (GP36-GP39); card detect (switch to GND) into STAT bit 7.", 20, 285, 2.5)
    s.text("OLED: 7-pin header for the Waveshare 1.27in 128x96 SSD1351 module on SPI1 (GP40-GP43), reset from CTL.", 20, 290, 2.0)
    s.power("+3V3", 300, 30, "#PWR13", flag=False)
    s.power("GND", 330, 40, "#PWR14", flag=False)

    # ---- J2 micro SD ----------------------------------------------------------------
    J2 = s.place("Connector:Micro_SD_Card_Det_Hirose_DM3AT", "J2", "microSD", SD_FP, 100, 100)
    # SPI mode: DAT3 = CS, CMD = MOSI, CLK = SCK, DAT0 = MISO; DAT1/DAT2 pulled up and unused
    s.label("SD_DAT2", J2.pin("1")); s.label("SD_CS_J", J2.pin("2")); s.label("SD_MOSI_J", J2.pin("3"))
    s.label("+3V3", J2.pin("4")); s.label("SD_SCK_J", J2.pin("5")); s.label("GND", J2.pin("6"))
    s.label("SD_MISO_J", J2.pin("7")); s.label("SD_DAT1", J2.pin("8"))
    s.label("SD_CD_SW", J2.pin("9")); s.label("GND", J2.pin("10")); s.label("GND", J2.pin("SH"))
    # series resistors on the SPI lines (ringing on a long card trace), pull-ups per the SD spec
    for k, (ref, a, b) in enumerate((("R30", "SD_CS", "SD_CS_J"), ("R31", "SD_MOSI", "SD_MOSI_J"),
                                     ("R32", "SD_SCK", "SD_SCK_J"), ("R33", "SD_MISO", "SD_MISO_J"))):
        R = s.place("Device:R", ref, "33", R0603, 150 + 15 * k, 70)
        s.glabel(a, R.pin("1"), IN if a != "SD_MISO" else OUT); s.label(b, R.pin("2"))
    for k, (ref, net) in enumerate((("R34", "SD_CS_J"), ("R35", "SD_MISO_J"), ("R36", "SD_DAT1"), ("R37", "SD_DAT2"), ("R38", "SD_CD_SW"))):
        R = s.place("Device:R", ref, "10k", R0603, 150 + 15 * k, 130)
        s.label("+3V3", R.pin("1")); s.label(net, R.pin("2"))
    R39 = s.place("Device:R", "R39", "0", R0603, 230, 130)
    s.label("SD_CD_SW", R39.pin("1")); s.glabel("SD_CD", R39.pin("2"), OUT)
    for k, (ref, val, fp) in enumerate((("C50", "10u", C0603), ("C51", "100n", C0603))):
        C = s.place("Device:C", ref, val, fp, 100, 150 + 15 * k)
        s.label("+3V3", C.pin("1")); s.label("GND", C.pin("2"))
    s.text("R30-R33 33 R series; R34-R37 10 k pull-ups (CS, MISO, DAT1, DAT2); R38 pull-up on the detect switch, R39 0 R link to SD_CD.", 90, 185, 1.5)
    s.text("Card present = SD_CD low (TF-01A detect switch closes to GND; verify polarity on the HRO drawing).", 90, 188, 1.5)

    # ---- J3 OLED header --------------------------------------------------------------
    J3 = s.place("Connector_Generic:Conn_01x07", "J3", "OLED 1.27in 128x96", HDR7, 300, 110)
    nets = [("+3V3", "loc"), ("GND", "loc"), ("OLED_MOSI", IN), ("OLED_SCK", IN), ("OLED_CS", IN), ("OLED_DC", IN), ("nOLED_RST", IN)]
    for k, (net, kind) in enumerate(nets):
        at = J3.pin(str(k + 1))
        if kind == "loc":
            s.label(net, at)
        else:
            s.glabel(net, at, kind)
    s.text("J3 pin order matches the Waveshare module: VCC GND DIN CLK CS DC RST.", 280, 135, 1.5)

    s.write()
    print("wrote storage_display.kicad_sch")


if __name__ == "__main__":
    main()
