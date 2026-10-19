#!/usr/bin/env python3
"""Generate memory.kicad_sch: slow I/O on a 16-bit I2C expander.

  U15  XL9555 (PCA9555 pinout, TSSOP-24, address 0x20) on I2C0 (GP24 SDA, GP25 SCL), /INT to GP35
       port 0 (outputs): BUSRQ, NMI_REQ, spare (OLED reset until proto3), WIFI_EN, WIFI_DL, nLED, SD_PWR_EN
       port 1 (inputs):  joystick x6, nBUSAK_L, SD_CD
  The expander powers up with every pin an input (100 k internal pull-ups), so the
  active-high outputs have 10 k pull-downs: nothing asserts until the firmware sets it.
  This replaces the 74HC273 CTL register, its power-on clear, and the STAT buffer.
  The address byte mux is now the two address 74LVC245s on the interface sheet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

TSSOP16 = "Package_SO:TSSOP-16_4.4x5mm_P0.65mm"
TSSOP24 = "Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SOD123 = "Diode_SMD:D_SOD-123"

OUT, IN, BI = "output", "input", "bidirectional"


def main():
    s = Sheet("tspico-v3.kicad_sch", "memory.kicad_sch", "TS-Pico v3: I/O Expander")
    s.text("Slow control and status on one I2C expander. The fast local bus MD0-MD7 (address groups, Z80 data) is on the interface sheet.", 20, 285, 2.5)
    s.text("No flash or SRAM: the RP2350B serves memory from internal SRAM (PIO + DMA).", 20, 290, 2.0)

    s.power("+3V3", 300, 30, "#PWR04", flag=False)
    s.power("GND", 330, 40, "#PWR05", flag=False)

    U15 = s.place("Interface_Expansion:PCA9555PW", "U15", "XL9555", TSSOP24, 150, 110)
    port0 = ["BUSRQ", "NMI_REQ", None, "WIFI_EN", "WIFI_DL", "nLED", "SD_PWR_EN", None]           # pins 4-11
    port1 = ["JOY_UP", "JOY_DOWN", "JOY_LEFT", "JOY_RIGHT", "JOY_FIRE1", "JOY_FIRE2", "nBUSAK_L", "SD_CD"]   # pins 13-20
    for bit, net in enumerate(port0):
        pin = U15.pin(str(4 + bit))
        if net is None:
            s.nc(pin)
        elif net == "nLED":
            s.label(net, pin)
        else:
            s.glabel(net, pin, OUT)
    for bit, net in enumerate(port1):
        s.glabel(net, U15.pin(str(13 + bit)), IN)
    for pin in ("21", "2", "3"):                       # A0-A2 low: address 0x20
        s.label("GND", U15.pin(pin))
    s.glabel("I2C_SCL", U15.pin("22"), IN); s.glabel("I2C_SDA", U15.pin("23"), BI)
    s.glabel("nIOX_INT", U15.pin("1"), OUT)
    s.label("+3V3", U15.pin("24")); s.label("GND", U15.pin("12"))

    # I2C and /INT pull-ups
    for k, (ref, net, val) in enumerate((("R6", "I2C_SDA", "4k7"), ("R7", "I2C_SCL", "4k7"), ("R8", "nIOX_INT", "10k"))):
        R = s.place("Device:R", ref, val, R0603, 250 + 15 * k, 60)
        s.label("+3V3", R.pin("1")); s.glabel(net, R.pin("2"), BI)
    # power-up defaults for the active-high outputs (R11 held the SPI OLED in reset until proto3)
    for k, (ref, net) in enumerate((("R9", "BUSRQ"), ("R10", "NMI_REQ"), ("R12", "WIFI_EN"), ("R13", "WIFI_DL"))):
        R = s.place("Device:R", ref, "10k", R0603, 250 + 15 * k, 110)
        s.glabel(net, R.pin("1"), BI); s.label("GND", R.pin("2"))
    s.text("R9, R10, R12, R13: 10 k pull-downs beat the expander's 100 k pull-ups until the firmware configures the port.", 245, 125, 1.5)

    # activity LED, active low (the expander sinks better than it sources)
    R5 = s.place("Device:R", "R5", "100", R0603, 250, 160)
    s.label("+3V3", R5.pin("1")); s.label("LED_A", R5.pin("2"))
    D4 = s.place("Device:LED", "D4", "green", "LED_SMD:LED_0805_2012Metric", 270, 160)
    s.label("LED_A", D4.pin("A")); s.label("nLED", D4.pin("K"))
    s.text("R5/D4: activity LED, on when nLED is driven low.", 245, 175, 1.5)

    C = s.place("Device:C", "C10", "100n", C0603, 40, 255)
    s.label("+3V3", C.pin("1")); s.label("GND", C.pin("2"))

    s.write()
    print("wrote memory.kicad_sch")


if __name__ == "__main__":
    main()
