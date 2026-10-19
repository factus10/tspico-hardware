#!/usr/bin/env python3
"""Generate storage_display.kicad_sch: micro SD socket and OLED header.

  J2  HRO TF-01A push-push micro SD (was Hirose DM3AT, 8x the price), SPI mode on SPI0, card detect to STAT
  U32 SY6280AAC current-limited load switch: the socket's VDD (+3V3_SD), on from expander P0.6 (SD_PWR_EN).
      Added for proto2 after issue #21: a card that latches up hits the switch's limit instead of pulling
      +3V3 down (which reset the RP2350B), and the firmware can power-cycle a wedged card. The card-side
      pull-ups are on +3V3_SD so they cannot power a switched-off card; the detect pull-up stays on +3V3.
  J3  4-pin header for a 1.54" 128x64 SSD1309 I2C OLED module (GND VCC SCL SDA) on I2C1, R44/R45 4k7 pull-ups.
      Proto3; proto1/2 had a 7-pin header for the Waveshare 1.27" 128x96 SSD1351 on SPI1.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SD_FP = "tspico:microSD_TF-01A"   # custom footprint for the HRO TF-01A push-push socket (pads 1-8, 9 = CD switch, 10 = CD common, SH)
HDR4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"

OUT, IN, BI = "output", "input", "bidirectional"


def main():
    s = Sheet("tspico-v3.kicad_sch", "storage_display.kicad_sch", "TS-Pico v3: SD and Display")
    s.text("Micro SD in SPI mode on the RP2350B SPI0 (GP36-GP39); card detect (switch to GND) into STAT bit 7.", 20, 285, 2.5)
    s.text("OLED: 4-pin header for a 1.54in 128x64 SSD1309 I2C module on I2C1 (GP42 SDA, GP43 SCL), its own bus so display updates never delay joystick reads.", 20, 290, 2.0)
    s.power("+3V3", 300, 30, "#PWR13", flag=False)
    s.power("GND", 330, 40, "#PWR14", flag=False)

    # ---- J2 micro SD ----------------------------------------------------------------
    J2 = s.place("Connector:Micro_SD_Card_Det_Hirose_DM3AT", "J2", "microSD", SD_FP, 100, 100)
    # SPI mode: DAT3 = CS, CMD = MOSI, CLK = SCK, DAT0 = MISO; DAT1/DAT2 pulled up and unused
    s.label("SD_DAT2", J2.pin("1")); s.label("SD_CS_J", J2.pin("2")); s.label("SD_MOSI_J", J2.pin("3"))
    s.glabel("+3V3_SD", J2.pin("4"), IN); s.label("SD_SCK_J", J2.pin("5")); s.label("GND", J2.pin("6"))
    s.label("SD_MISO_J", J2.pin("7")); s.label("SD_DAT1", J2.pin("8"))
    s.label("SD_CD_SW", J2.pin("9")); s.label("GND", J2.pin("10")); s.label("GND", J2.pin("SH"))
    # series resistors on the SPI lines (ringing on a long card trace), pull-ups per the SD spec
    for k, (ref, a, b) in enumerate((("R30", "SD_CS", "SD_CS_J"), ("R31", "SD_MOSI", "SD_MOSI_J"),
                                     ("R32", "SD_SCK", "SD_SCK_J"), ("R33", "SD_MISO", "SD_MISO_J"))):
        R = s.place("Device:R", ref, "33", R0603, 150 + 15 * k, 70)
        s.glabel(a, R.pin("1"), IN if a != "SD_MISO" else OUT); s.label(b, R.pin("2"))
    for k, (ref, net) in enumerate((("R34", "SD_CS_J"), ("R35", "SD_MISO_J"), ("R36", "SD_DAT1"), ("R37", "SD_DAT2"), ("R38", "SD_CD_SW"))):
        R = s.place("Device:R", ref, "10k", R0603, 150 + 15 * k, 130)
        if ref == "R38":                               # the detect switch must read with the card unpowered
            s.label("+3V3", R.pin("1"))
        else:
            s.glabel("+3V3_SD", R.pin("1"), IN)
        s.label(net, R.pin("2"))
    R39 = s.place("Device:R", "R39", "0", R0603, 230, 130)
    s.label("SD_CD_SW", R39.pin("1")); s.glabel("SD_CD", R39.pin("2"), OUT)
    for k, (ref, val, fp) in enumerate((("C50", "10u", C0603), ("C51", "100n", C0603))):
        C = s.place("Device:C", ref, val, fp, 100, 150 + 15 * k)
        s.glabel("+3V3_SD", C.pin("1"), IN); s.label("GND", C.pin("2"))

    # ---- U32 socket power switch -----------------------------------------------------
    # SY6280AAC (pin-compatible with the AAT4610-1: 1 OUT, 2 GND, 3 ISET, 4 EN active high, 5 IN).
    # I_LIM = 6800 / R_SET: 15k gives 0.45 A typ (0.34-0.57 A over the datasheet's +-25 %), above a
    # card's 200 mA peak, under what the TLV1117LV33 can give on top of the RP2350B.
    U32 = s.place("Power_Management:AAT4610BIGV-1-T1", "U32", "SY6280AAC", "Package_TO_SOT_SMD:SOT-23-5", 60, 200)
    s.label("+3V3", U32.pin("5")); s.glabel("+3V3_SD", U32.pin("1"), OUT); s.label("GND", U32.pin("2"))
    s.label("SD_ISET", U32.pin("3")); s.glabel("SD_PWR_EN", U32.pin("4"), IN)
    R42 = s.place("Device:R", "R42", "15k", R0603, 90, 215)
    s.label("SD_ISET", R42.pin("1")); s.label("GND", R42.pin("2"))
    R43 = s.place("Device:R", "R43", "10k", R0603, 105, 215)          # off until the firmware sets P0.6 (beats the expander's 100 k pull-up)
    s.glabel("SD_PWR_EN", R43.pin("1"), IN); s.label("GND", R43.pin("2"))
    C52 = s.place("Device:C", "C52", "1u", C0603, 40, 215)
    s.label("+3V3", C52.pin("1")); s.label("GND", C52.pin("2"))

    s.text("R30-R33 33 R series; R34-R37 10 k pull-ups (CS, MISO, DAT1, DAT2) on +3V3_SD; R38 pull-up on the detect switch (+3V3), R39 0 R link to SD_CD.", 90, 185, 1.5)
    s.text("Card present = SD_CD low (the TF-01A switch closes to GND; confirmed on proto1). U32: SD VDD switch, R42 sets 0.45 A, R43 holds it off.", 90, 188, 1.5)
    s.text("Firmware order: card detected, settle, SD_PWR_EN on, then SPI. SPI lines released (inputs) before SD_PWR_EN goes off.", 90, 191, 1.5)

    # ---- J3 OLED header --------------------------------------------------------------
    J3 = s.place("Connector_Generic:Conn_01x04", "J3", "OLED 1.54in 128x64 I2C", HDR4, 300, 110)
    nets = [("GND", "loc"), ("+3V3", "loc"), ("OLED_SCL", IN), ("OLED_SDA", BI)]
    for k, (net, kind) in enumerate(nets):
        at = J3.pin(str(k + 1))
        if kind == "loc":
            s.label(net, at)
        else:
            s.glabel(net, at, kind)
    # bus pull-ups on the card, so the bus idles high with no module or one without its own
    for k, (ref, net) in enumerate((("R44", "OLED_SCL"), ("R45", "OLED_SDA"))):
        R = s.place("Device:R", ref, "4k7", R0603, 330 + 15 * k, 150)
        s.label("+3V3", R.pin("1")); s.glabel(net, R.pin("2"), BI)
    s.text("J3 pin order matches the module: GND VCC SCL SDA. VCC is +3V3, so the module's own pull-ups stay at 3.3 V.", 280, 135, 1.5)

    s.write()
    print("wrote storage_display.kicad_sch")


if __name__ == "__main__":
    main()
