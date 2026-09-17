#!/usr/bin/env python3
"""Generate mcu.kicad_sch: RP2350B core.

  U20 RP2350B (QFN-80) with the RP2350 hardware-design-guide support parts:
      internal 1.1 V regulator (L1 3.3 uH, 4.7 uF caps), 100 nF on every IOVDD,
      12 MHz crystal with 15 pF loads and 1 k series, RUN pull-up and button,
      BOOTSEL button on QSPI_SS through 1 k, USB D+/D- 27 R series.
  U21 GD25Q128E (W25Q128 pinout) 16 MB QSPI flash on the QSPI bus (XIP, CS0)
  U22 APS6404L 8 MB PSRAM on the QSPI bus, CS1 = GPIO47
  J1  USB-C receptacle, data only: VBUS unconnected, 5.1 k Rd on CC1/CC2
  SW3 RUN, SW4 BOOTSEL, TP1-TP3 SWD pads
GPIO nets follow docs/v3-architecture.md section 7.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402
from config import DMA_OPTION  # noqa: E402

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
L_FP = "tspico:L_Abracon_AOTA-B201610"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
SW_FP = "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A"
TP_FP = "TestPoint:TestPoint_Pad_1.5x1.5mm"

OUT, IN, BI = "output", "input", "bidirectional"

# GPIO number -> (net, shape)
GPIO = {
    **{i: (f"MD{i}", BI) for i in range(8)},
    8: ("nAEN_LO", OUT), 9: ("nAEN_HI", OUT), 10: ("nDATA_OE", OUT), 11: ("BE_REQ", OUT), 12: ("WAIT_REQ", OUT),
    13: ("Z80_A14", IN), 14: ("Z80_A15", IN), 15: ("nMEMRD", IN), 16: ("nMEMWR", IN),
    17: ("nIORD", IN), 18: ("nIOWR", IN), 19: ("nROSCS_L", IN), 20: ("nEXROM_L", IN),
    21: ("nINT_L", IN), 22: ("TAPE_IN", IN), 23: ("TAPE_OUT", OUT),
    24: ("I2C_SDA", BI), 25: ("I2C_SCL", OUT),
    29: ("RESET_HOLD", OUT), 30: ("AUDIO_R", OUT),
    32: ("SD_MISO", IN), 35: ("nIOX_INT", IN), 37: ("SD_CS", OUT), 38: ("SD_SCK", OUT), 39: ("SD_MOSI", OUT),
    34: ("OLED_DC", OUT), 41: ("OLED_CS", OUT), 42: ("OLED_SCK", OUT), 43: ("OLED_MOSI", OUT),      # DC is a plain GPIO: GP34 sits in the open corner of the fan-out, GP40 is boxed in
    44: ("WIFI_TX", OUT), 45: ("WIFI_RX", IN), 46: ("AUDIO_L", OUT),
}
DMA_GPIO = {26: ("nWR_ALO", OUT), 27: ("nMRD", OUT), 28: ("nMWR", OUT), 31: ("nWR_AHI", OUT), 33: ("nDMA_EN", OUT), 34: ("nDMA_MREQ", OUT)}
if DMA_OPTION:
    GPIO.update(DMA_GPIO)
SPARE = ([36] if DMA_OPTION else [36] + sorted(DMA_GPIO)) + [40]
SPARE = [g for g in SPARE if g not in GPIO]


def main():
    s = Sheet("tspico-v3.kicad_sch", "mcu.kicad_sch", "TS-Pico v3: RP2350B Core")
    s.text("RP2350B core per the RP2350 hardware design guide. GPIO map: docs/v3-architecture.md section 7. GP36 spare (plus the six DMA pins when the DMA option is off).", 20, 285, 2.5)
    s.text("USB-C: data, and VBUS to the power sheet (diode-ORed with the edge +5V) so the card runs from USB alone on the bench.", 20, 290, 2.0)

    s.power("+3V3", 300, 30, "#PWR06", flag=False)
    s.power("GND", 330, 40, "#PWR07", flag=False)

    # ---- U20 RP2350B ---------------------------------------------------------------
    U = s.place("MCU_RaspberryPi:RP2350B", "U20", "RP2350B", "Package_DFN_QFN:QFN-80-1EP_10x10mm_P0.4mm_EP3.4x3.4mm", 130, 150)
    names = U.names()
    by_name = {}
    for num, nm in names.items():
        by_name.setdefault(nm.split("/")[0], num)
    for g, (net, shape) in GPIO.items():
        s.glabel(net, U.pin(by_name[f"GPIO{g}"]), shape)
    for g in SPARE:
        s.nc(U.pin(by_name[f"GPIO{g}"]))
    s.label("PSRAM_CS", U.pin(by_name["GPIO47"]))
    for num, nm in names.items():
        if nm in ("IOVDD", "QSPI_IOVDD", "USB_OTP_VDD", "ADC_AVDD", "VREG_VIN"):
            s.label("+3V3", U.pin(num))
        elif nm == "VREG_AVDD":
            s.label("VREG_AVDD", U.pin(num))
        elif nm in ("GND", "VREG_PGND"):
            s.label("GND", U.pin(num))
        elif nm == "DVDD":
            s.label("DVDD", U.pin(num))
    s.label("VREG_LX", U.pin(by_name["VREG_LX"]))
    s.label("DVDD", U.pin(by_name["VREG_FB"]))
    s.label("XIN", U.pin(by_name["XIN"])); s.label("XOUT", U.pin(by_name["XOUT"]))
    s.label("SWCLK", U.pin(by_name["SWCLK"])); s.label("SWDIO", U.pin(by_name["SWDIO"]))
    s.label("RUN", U.pin(by_name["RUN"]))
    s.label("USB_DM", U.pin(by_name["USB_DM"])); s.label("USB_DP", U.pin(by_name["USB_DP"]))
    for nm in ("QSPI_SD0", "QSPI_SD1", "QSPI_SD2", "QSPI_SD3", "QSPI_SCLK"):
        s.label(nm, U.pin(by_name[nm]))
    s.label("nQSPI_SS", U.pin(by_name["~{QSPI_SS}"]))

    # ---- core regulator: VREG_LX -> L1 -> DVDD, 4.7 uF x2, 4.7 uF on VREG_VIN --------
    L1 = s.place("Device:L", "L1", "3.3uH", L_FP, 250, 60)
    s.label("VREG_LX", L1.pin("1")); s.label("DVDD", L1.pin("2"))   # LCSC numbering: dot-marked terminal = pad 2 = DVDD (1.1 V) side
    for k, (ref, net, val, fp) in enumerate([("C20", "DVDD", "4.7u", C0402), ("C22", "+3V3", "4.7u", C0402), ("C21", "DVDD", "100n", C0603), ("C47", "DVDD", "100n", C0603), ("C48", "DVDD", "100n", C0603)]):
        C = s.place("Device:C", ref, val, fp, 265 + 10 * k, 60)
        s.label(net, C.pin("1")); s.label("GND", C.pin("2"))
    s.text("L1 (Abracon AOTA-B201610S3R3-101-T, polarised: dot = pad 2 to DVDD), C20 output, C22 at VREG_VIN (0402 as in the design guide). C21/C47/C48: 100 nF at DVDD pins 51, 32, 10.", 245, 75, 1.5)
    R28 = s.place("Device:R", "R28", "33", R0603, 300, 85)
    s.label("+3V3", R28.pin("1")); s.label("VREG_AVDD", R28.pin("2"))
    C39 = s.place("Device:C", "C39", "4.7u", C0402, 315, 85)
    s.label("VREG_AVDD", C39.pin("1")); s.label("GND", C39.pin("2"))
    s.text("R28/C39: 33 R + 4.7 uF filter on VREG_AVDD (design guide R3/C9).", 245, 95, 1.5)
    FL2 = s.place("power:PWR_FLAG", "#FLG08", "PWR_FLAG", "", 330, 85)
    s.label("VREG_AVDD", FL2.pin("1"))
    FL = s.place("power:PWR_FLAG", "#FLG06", "PWR_FLAG", "", 300, 60)
    s.label("DVDD", FL.pin("1"))

    # ---- IOVDD and analog decoupling: 12 x 100 nF ----------------------------------
    for k in range(9):
        C = s.place("Device:C", f"C{23 + k}", "100n", C0603, 250 + 9 * k, 100)
        s.label("+3V3", C.pin("1")); s.label("GND", C.pin("2"))
    s.text("C23-C31: one per 3.3 V supply pin or adjacent pair (5, 15, 24, 29, 41, 50, 59/60, 68/69, 76); pin 64 has C22.", 245, 115, 1.5)

    # ---- crystal ---------------------------------------------------------------------
    Y1 = s.place("Device:Crystal_GND24", "Y1", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", 270, 150)
    s.label("XIN", Y1.pin("1")); s.label("XOUT_R", Y1.pin("3")); s.label("GND", Y1.pin("2")); s.label("GND", Y1.pin("4"))
    R20 = s.place("Device:R", "R20", "1k", R0603, 295, 150)
    s.label("XOUT", R20.pin("1")); s.label("XOUT_R", R20.pin("2"))
    C35 = s.place("Device:C", "C35", "15p", C0603, 255, 165)
    s.label("XIN", C35.pin("1")); s.label("GND", C35.pin("2"))
    C36 = s.place("Device:C", "C36", "15p", C0603, 285, 165)
    s.label("XOUT_R", C36.pin("1")); s.label("GND", C36.pin("2"))
    s.text("Y1: 12 MHz, e.g. ABM8-272-T3 (CL 10 pF). C35/C36 15 pF, R20 1 k in series with XOUT.", 245, 180, 1.5)

    # ---- QSPI flash and PSRAM ---------------------------------------------------------
    F = s.place("Memory_Flash:W25Q128JVS", "U21", "GD25Q128ESIGR", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm", 340, 150)
    s.label("nQSPI_SS", F.pin("1")); s.label("QSPI_SD1", F.pin("2")); s.label("QSPI_SD2", F.pin("3")); s.label("GND", F.pin("4"))
    s.label("QSPI_SD0", F.pin("5")); s.label("QSPI_SCLK", F.pin("6")); s.label("QSPI_SD3", F.pin("7")); s.label("+3V3", F.pin("8"))
    P = s.place("Memory_RAM:APS6404L-3SQRx-SN", "U22", "APS6404L-3SQR-SN", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm", 340, 200, dnp=True)
    # APS6404L SOP-8: 1 CE#, 2 SO/SIO1, 3 SIO2, 4 VSS, 5 SI/SIO0, 6 SCLK, 7 SIO3, 8 VCC
    s.label("PSRAM_CS", P.pin("1")); s.label("QSPI_SD1", P.pin("2")); s.label("QSPI_SD2", P.pin("3")); s.label("GND", P.pin("4"))
    s.label("QSPI_SD0", P.pin("5")); s.label("QSPI_SCLK", P.pin("6")); s.label("QSPI_SD3", P.pin("7")); s.label("+3V3", P.pin("8"))
    for k, (ref, net) in enumerate([("C37", "+3V3"), ("C38", "+3V3")]):
        C = s.place("Device:C", ref, "100n", C0603, 375 + 10 * k, 175)
        s.label(net, C.pin("1")); s.label("GND", C.pin("2"))
    R21 = s.place("Device:R", "R21", "10k", R0603, 395, 150)
    s.label("+3V3", R21.pin("1")); s.label("nQSPI_SS", R21.pin("2"))
    s.text("U21 boot flash (XIP CS0). U22 PSRAM on the same QSPI bus, DNP on the prototype ($5 part, SD-image cache only),", 320, 225, 1.5)
    s.text("CS1 = GPIO47 (QMI CS1n). C37/C38 at U21/U22.", 320, 228, 1.5)

    # ---- RUN and BOOTSEL -------------------------------------------------------------
    R22 = s.place("Device:R", "R22", "10k", R0603, 250, 210)
    s.label("+3V3", R22.pin("1")); s.label("RUN", R22.pin("2"))
    SW3 = s.place("Switch:SW_Push", "SW3", "RUN", SW_FP, 270, 225)
    s.label("RUN", SW3.pin("1")); s.label("GND", SW3.pin("2"))
    R23 = s.place("Device:R", "R23", "1k", R0603, 250, 245)
    s.label("nQSPI_SS", R23.pin("1")); s.label("BOOTSEL_SW", R23.pin("2"))
    SW4 = s.place("Switch:SW_Push", "SW4", "BOOTSEL", SW_FP, 270, 260)
    s.label("BOOTSEL_SW", SW4.pin("1")); s.label("GND", SW4.pin("2"))

    # ---- USB-C, data only -----------------------------------------------------------
    J1 = s.place("Connector:USB_C_Receptacle_USB2.0_16P", "J1", "USB-C", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", 40, 60)
    for pin in ("A4", "A9", "B4", "B9"):
        s.glabel("VBUS", J1.pin(pin), OUT)
    for pin in ("A8", "B8"):
        s.nc(J1.pin(pin))
    for pin in ("A1", "A12", "B1", "B12", "SH"):
        s.label("GND", J1.pin(pin))
    s.label("USB_DP_C", J1.pin("A6")); s.label("USB_DP_C", J1.pin("B6"))
    s.label("USB_DM_C", J1.pin("A7")); s.label("USB_DM_C", J1.pin("B7"))
    s.label("CC1", J1.pin("A5")); s.label("CC2", J1.pin("B5"))
    R24 = s.place("Device:R", "R24", "5k1", R0603, 80, 40)
    s.label("CC1", R24.pin("1")); s.label("GND", R24.pin("2"))
    R25 = s.place("Device:R", "R25", "5k1", R0603, 95, 40)
    s.label("CC2", R25.pin("1")); s.label("GND", R25.pin("2"))
    R26 = s.place("Device:R", "R26", "33", R0603, 80, 85)
    s.label("USB_DP_C", R26.pin("1")); s.label("USB_DP", R26.pin("2"))
    R27 = s.place("Device:R", "R27", "33", R0603, 95, 85)
    s.label("USB_DM_C", R27.pin("1")); s.label("USB_DM", R27.pin("2"))
    s.text("J1: USB 2.0. VBUS -> power sheet. SBU unconnected.", 20, 100, 1.5)
    s.text("R24/R25 5.1 k Rd. R26/R27 33 R series (JLC basic; 27 R is not).", 20, 103, 1.5)

    # ---- SWD pads ---------------------------------------------------------------------
    for k, (ref, net) in enumerate([("TP1", "SWCLK"), ("TP2", "SWDIO"), ("TP3", "GND")]):
        T = s.place("Connector:TestPoint", ref, net, TP_FP, 40 + 15 * k, 250)
        s.label(net, T.pin("1"))
    s.text("TP1-TP3: SWD debug pads.", 30, 262, 1.5)

    s.write()
    print("wrote mcu.kicad_sch")


if __name__ == "__main__":
    main()
