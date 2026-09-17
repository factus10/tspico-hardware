#!/usr/bin/env python3
"""Generate wifi.kicad_sch: ESP32-C3-WROOM-02 running Zimodem.

  U40 ESP32-C3-WROOM-02 (4 MB, PCB antenna). UART0 (IO20 RXD / IO21 TXD) to the
  RP2350B (WIFI_TX / WIFI_RX). EN from CTL WIFI_EN, IO9 (boot) from the inverted
  CTL WIFI_DL bit, IO8 pulled up (required high for download mode). Power from
  the +3V3_WIFI LDO with 100 nF + 10 uF at the module.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
ESP_FP = "RF_Module:ESP32-C3-WROOM-02"

OUT, IN, BI = "output", "input", "bidirectional"


def main():
    s = Sheet("tspico-v3.kicad_sch", "wifi.kicad_sch", "TS-Pico v3: WiFi")
    s.text("ESP32-C3-WROOM-02 running Zimodem (Hayes modem over UART). Antenna end over the board edge, copper keep-out per the module datasheet.", 20, 285, 2.5)
    s.text("Flashing: RP2350B acts as USB-UART bridge; firmware sets WIFI_DL=1 then pulses WIFI_EN for download mode.", 20, 290, 2.0)
    s.power("GND", 330, 40, "#PWR15", flag=False)

    U40 = s.place("RF_Module:ESP32-C3-WROOM-02", "U40", "ESP32-C3-WROOM-02-N4", ESP_FP, 150, 120)
    s.glabel("+3V3_WIFI", U40.pin("3V3"), IN)
    s.label("GND", U40.pin("9")); s.label("GND", U40.pin("19"))
    s.glabel("WIFI_EN", U40.pin("EN"), IN)
    s.glabel("nWIFI_BOOT", U40.pin("IO9"), IN)
    s.label("ESP_IO8", U40.pin("IO8"))
    s.glabel("WIFI_TX", U40.pin("IO20/RXD"), IN)     # RP2350 TX -> ESP RXD
    s.glabel("WIFI_RX", U40.pin("IO21/TXD"), OUT)    # ESP TXD -> RP2350 RX
    for pin in ("IO4", "IO5", "IO6", "IO7", "IO10", "IO18", "IO19", "IO3", "IO2", "IO1", "IO0"):
        s.nc(U40.pin(pin))
    R40 = s.place("Device:R", "R40", "10k", R0603, 230, 90)
    s.glabel("+3V3_WIFI", R40.pin("1"), IN); s.label("ESP_IO8", R40.pin("2"))
    R41 = s.place("Device:R", "R41", "10k", R0603, 245, 90)
    s.glabel("+3V3_WIFI", R41.pin("1"), IN); s.glabel("nWIFI_BOOT", R41.pin("2"), IN)
    for k, (ref, val, fp) in enumerate((("C60", "10u", C0603), ("C61", "100n", C0603))):
        C = s.place("Device:C", ref, val, fp, 230 + 15 * k, 130)
        s.glabel("+3V3_WIFI", C.pin("1"), IN); s.label("GND", C.pin("2"))
    s.text("R40: IO8 must be high during a download-mode boot. IO9 low = download mode: R41 pulls it up, the open-drain gate in U7 pulls it down when WIFI_DL is set.", 130, 180, 1.5)
    s.text("Zimodem's modem-status pins (DCD, RI, DSR, DTR, RTS/CTS) are not routed; XON/XOFF flow control.", 130, 183, 1.5)

    s.write()
    print("wrote wifi.kicad_sch")


if __name__ == "__main__":
    main()
