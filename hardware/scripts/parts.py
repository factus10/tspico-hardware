"""Orderable part numbers for the TS-Pico v3 BOM.

Keyed by (Value, footprint basename). Each entry: (MPN, LCSC, note).
"basic" in the note means a JLCPCB basic part (no extended-part fee).
LCSC numbers were looked up on 2026-09-16; re-check stock at order time.
An empty LCSC string means "not sourced from LCSC" (edge fingers, pads, jumpers)
or "number not confirmed" (see note).
"""

R = "R_0603_1608Metric"
C6 = "C_0603_1608Metric"
C8 = "C_0805_2012Metric"
T14 = "TSSOP-14_4.4x5mm_P0.65mm"
T16 = "TSSOP-16_4.4x5mm_P0.65mm"
T20 = "TSSOP-20_4.4x6.5mm_P0.65mm"

PARTS = {
    # ---- resistors (0603, 1%) ------------------------------------------------
    ("0", R): ("0603WAF0000T5E", "C21189", "basic"),
    ("33", R): ("0603WAF330JT5E", "C23140", "basic"),
    ("100", R): ("0603WAF1000T5E", "C22775", "basic"),
    ("1k", R): ("0603WAF1001T5E", "C21190", "basic"),
    ("2k2", R): ("0603WAF2201T5E", "C4190", "basic"),
    ("4k7", R): ("0603WAF4701T5E", "C23162", "basic"),
    ("5k1", R): ("0603WAF5101T5E", "C23186", "basic"),
    ("10k", R): ("0603WAF1002T5E", "C25804", "basic"),
    ("15k", R): ("0603WAF1502T5E", "C22809", "basic"),
    ("22k", R): ("0603WAF2202T5E", "C31850", "basic"),
    ("100k", R): ("0603WAF1003T5E", "C25803", "basic"),
    # ---- capacitors ----------------------------------------------------------
    ("15p", C6): ("CL10C150JB8NNNC", "C1644", "basic, C0G"),
    ("100p", C6): ("CL10C101JB8NNNC", "C14858", "basic, C0G"),
    ("10n", C6): ("CL10B103KB8NNNC", "C57112", "basic; verify (C1710 listed as 0805 in some tables)"),
    ("100n", C6): ("CC0603KRX7R9BB104", "C14663", "basic, X7R 50V"),
    ("1u", C6): ("CL10A105KB8NNNC", "C15849", "basic, X5R 25V"),
    ("4.7u", "C_0402_1005Metric"): ("CL05A475MP5NRNC", "C23733", "basic, X5R 10V, 0402 as in the RP2350 design guide"),
    ("10u", C6): ("CL10A106KP8NNNC", "C19702", "basic, X5R 10V (all 10u sit on 5 V or 3.3 V rails)"),
    ("220u", "CP_Elec_6.3x5.4"): ("RVT220UF10V67RV0037", "C2833309", "KNSCHA 220uF 10V SMD aluminium, D6.3xL5.4 (extended; was Panasonic polymer at 26x the price)"),
    # ---- semiconductors ------------------------------------------------------
    ("RP2350B", "QFN-80-1EP_10x10mm_P0.4mm_EP3.4x3.4mm"): ("RP2350B", "C42415655", "extended"),
    ("GD25Q128ESIGR", "SOIC-8_5.3x5.3mm_P1.27mm"): ("GD25Q128ESIGR", "C2928891", "GigaDevice 16 MB QSPI, extended; W25Q128JVSIQ C97521 is basic but $2.22"),
    ("APS6404L-3SQR-SN", "SOIC-8_3.9x4.9mm_P1.27mm"): ("APS6404L-3SQR-SN", "C5333729", "extended, SOP-8 150 mil, $3.97 and 4514 in stock (2026-10-12); DNP. Hand-fit alternative: Adafruit 4677 (ESP-PSRAM64H, $1.75)"),
    ("ESP32-C3-WROOM-02-N4", "ESP32-C3-WROOM-02"): ("ESP32-C3-WROOM-02-N4", "C2934560", "extended, 4 MB"),
    ("TLV1117LV33", "SOT-223-3_TabPin2"): ("TLV1117LV33DCYR", "C15578", "extended, TI"),
    ("MCP6002", "SOIC-8_3.9x4.9mm_P1.27mm"): ("MCP6002T-I/SN", "C7377", "preferred (no loading fee), Microchip"),
    ("74LVC245APW", T20): ("74LVC245APW,118", "C6082", "extended, Nexperia"),
    ("74LVC06AD", "SOIC-14_3.9x8.7mm_P1.27mm"): ("EM74LVC06AD", "C49188178", "extended, EnergyMath SOIC (every TSSOP LVC06 is out of stock or $0.41)"),
    ("74LVC32APW", T14): ("74LVC32APW,118", "C6087", "extended, Nexperia: MEMRD/MEMWR/IORD/IOWR strobes (replaces the 74LVC04 + 74LVC08)"),
    ("74LVC574APW", T20): ("SN74LVC574APWR", "C7672", "extended, TI; DMA option only (DNP). Must be LVC: the outputs sit on the 5 V address bus"),
    ("XL9555", "TSSOP-24_4.4x7.8mm_P0.65mm"): ("XL9555", "C609791", "extended, XINLUDA PCA9555 clone, 16-bit I2C expander (replaces the 74HC273 + STAT buffer)"),
    ("SY6280AAC", "SOT-23-5"): ("SY6280AAC", "C55136", "extended, Silergy current-limited load switch (AAT4610 pinout): SD socket VDD"),
    ("74LVC1G86", "SOT-23-5"): ("SN74LVC1G86DBVR", "C402161", "extended, TI"),
    ("SS34", "D_SMA"): ("SS34", "C8678", "basic, MDD"),
    ("green", "LED_0805_2012Metric"): ("KT-0805G", "C2297", "basic, KENTO (the 0603 basic part had 1 in stock)"),
    ("3.3uH", "L_Abracon_AOTA-B201610"): ("AOTA-B201610S3R3-101-T", "C42411119", "extended, Abracon polarised inductor from the RP2350 design guide; dot = pin 2 = DVDD side. Out of stock 2026-10-12 (proto2.1 and proto3 hand-fitted it); 326 in stock 2026-10-22, assembled again from proto3.1. No substitute: Raspberry Pi found no other polarity-marked 0806 part"),
    ("12MHz", "Crystal_SMD_3225-4Pin_3.2x2.5mm"): ("ABM8-272-T3", "C20625731", "extended, Abracon, CL 10 pF (RP2350 design guide); basic alternative X322512MSB4SI C9002 needs 27 pF loads"),
    # ---- electromechanical ---------------------------------------------------
    ("USB-C", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"): ("TYPE-C-31-M-12", "C165948", "extended, HRO"),
    ("microSD", "microSD_TF-01A"): ("TF-01A", "C91145", "extended, HRO push-push; custom footprint TSPico:microSD_TF-01A to draw from the HRO drawing"),
    ("3.5mm stereo", "Jack_3.5mm_PJ320D_Horizontal"): ("PJ-320D", "C431535", "extended, SHOU HAN 4-pole; TRS plug shorts R2 to S"),
    ("Joystick", "DSUB-9_Pins_Horizontal_P2.77x2.84mm_EdgePinOffset7.70mm_Housed_MountingHolesOffset9.12mm"): ("DS1037-09MNAKT74-0CC", "C75750", "extended, CONNFLY, male (proto3; proto1/2 had the female DS1037-09F, C75749), through-hole, hand-soldered (not in the JLC BOM); verify pin/edge offsets against the KiCad footprint before layout"),
    ("OLED 1.54in 128x64 I2C", "PinHeader_1x04_P2.54mm_Vertical"): ("2.54-1x40P (cut to 4)", "C2337", "extended, through-hole header, hand-soldered (not in the JLC BOM)"),
    ("TS Reset", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("NMI", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("RUN", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("BOOTSEL", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
}


def lookup(value, footprint):
    """Return (MPN, LCSC, note) or None."""
    fp = footprint.split(":")[-1] if footprint else ""
    return PARTS.get((value, fp))
