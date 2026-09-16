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
    ("4k7", R): ("0603WAF4701T5E", "C23162", "basic"),
    ("5k1", R): ("0603WAF5101T5E", "C23186", "basic"),
    ("10k", R): ("0603WAF1002T5E", "C25804", "basic"),
    ("22k", R): ("0603WAF2202T5E", "C31850", "basic"),
    ("100k", R): ("0603WAF1003T5E", "C25803", "basic"),
    # ---- capacitors ----------------------------------------------------------
    ("15p", C6): ("CL10C150JB8NNNC", "C1644", "basic, C0G"),
    ("100p", C6): ("CL10C101JB8NNNC", "C14858", "basic, C0G"),
    ("10n", C6): ("CL10B103KB8NNNC", "C57112", "basic; verify (C1710 listed as 0805 in some tables)"),
    ("100n", C6): ("CC0603KRX7R9BB104", "C14663", "basic, X7R 50V"),
    ("1u", C6): ("CL10A105KB8NNNC", "C15849", "basic, X5R 25V"),
    ("4.7u", C8): ("CL21A475KAQNNNE", "C1779", "basic, X5R 25V"),
    ("10u", C8): ("CL21A106KAYNNNE", "C15850", "basic, X5R 25V"),
    ("220u", "CP_Elec_6.3x5.9"): ("6SVPC220MV", "C128504", "Panasonic polymer 6.3V 15mOhm, D6.3xL6 (extended)"),
    # ---- semiconductors ------------------------------------------------------
    ("RP2350B", "QFN-80-1EP_10x10mm_P0.4mm_EP3.4x3.4mm"): ("RP2350B", "C42415655", "extended"),
    ("W25Q128JVSIQ", "SOIC-8_5.3x5.3mm_P1.27mm"): ("W25Q128JVSIQ", "C97521", "extended"),
    ("APS6404L-3SQR-SN", "SOIC-8_5.3x5.3mm_P1.27mm"): ("APS6404L-3SQR-SN", "C5333729", "extended"),
    ("ESP32-C3-WROOM-02-N4", "ESP32-C3-WROOM-02"): ("ESP32-C3-WROOM-02-N4", "C2934560", "extended, 4 MB"),
    ("TLV1117LV33", "SOT-223-3_TabPin2"): ("TLV1117LV33DCYR", "C15578", "extended, TI"),
    ("MCP6002", "SOIC-8_3.9x4.9mm_P1.27mm"): ("MCP6002T-E/SN", "C125816", "extended, Microchip"),
    ("74LVC245APW", T20): ("74LVC245APW,118", "C6082", "extended, Nexperia"),
    ("74LVC04APW", T14): ("SN74LVC04APWRG4", "C7806", "extended, TI (Nexperia 74LVC04APW not listed)"),
    ("74LVC06APW", T14): ("74LVC06APW,118", "C131311", "extended, Nexperia"),
    ("74LVC08APW", T14): ("SN74LVC08APWR", "C465737", "extended, TI; low stock seen, alternate 74LVC08AD (SOIC) C6052"),
    ("74LVC126APW", T14): ("SN74LVC126APWR", "C7815", "extended, TI"),
    ("74LVC257APW", T16): ("74LVC257APW,118", "C6083", "extended, Nexperia"),
    ("74LVC139PW", T16): ("74LVC139PW,118", "C6064", "extended, Nexperia (non-A part, same function)"),
    ("74LVC574APW", T20): ("SN74LVC574APWR", "C7672", "extended, TI"),
    ("74HC273PW", T20): ("74HC273PW,118", "C131680", "extended, Nexperia; HC used because LVC273 is not stocked, fine at 3.3 V"),
    ("74LVC541APW", T20): ("74LVC541APW,118", "C6093", "extended, Nexperia"),
    ("74LVC1G86", "SOT-23-5"): ("SN74LVC1G86DBVR", "C402161", "extended, TI"),
    ("SS34", "D_SMA"): ("SS34", "C8678", "basic, MDD"),
    ("B5819W", "D_SOD-123"): ("B5819W SL", "C8598", "basic, CJ"),
    ("green", "LED_0603_1608Metric"): ("19-217/GHC-YR1S2/3T", "C72043", "basic, Everlight"),
    ("3.3uH", "L_1008_2520Metric"): ("SWPA252012S3R3MT", "", "Sunlord 3.3uH 1.04A 2520; LCSC number not confirmed, pick at order time"),
    ("12MHz", "Crystal_SMD_3225-4Pin_3.2x2.5mm"): ("ABM8-272-T3", "C20625731", "extended, Abracon, CL 10 pF (RP2350 design guide); basic alternative X322512MSB4SI C9002 needs 27 pF loads"),
    # ---- electromechanical ---------------------------------------------------
    ("USB-C", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"): ("TYPE-C-31-M-12", "C165948", "extended, HRO"),
    ("microSD", "microSD_HC_Hirose_DM3AT-SF-PEJM5"): ("DM3AT-SF-PEJM5", "C114218", "extended, Hirose"),
    ("3.5mm stereo", "Jack_3.5mm_CUI_SJ-3523-SMT_Horizontal"): ("SJ-3523-SMT-TR", "C4991872", "extended, CUI"),
    ("Joystick", "DSUB-9_Socket_Horizontal_P2.77x2.84mm_EdgePinOffset7.70mm_Housed_MountingHolesOffset9.12mm"): ("DS1037-09FNAKT74-0CC", "C75749", "extended, CONNFLY, through-hole; verify pin/edge offsets against the KiCad footprint before layout"),
    ("OLED 1.27in 128x96", "PinHeader_1x07_P2.54mm_Vertical"): ("2.54-1x40P (cut to 7)", "C2337", "basic, through-hole header"),
    ("TS Reset", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("NMI", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("RUN", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("BOOTSEL", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
}


def lookup(value, footprint):
    """Return (MPN, LCSC, note) or None."""
    fp = footprint.split(":")[-1] if footprint else ""
    return PARTS.get((value, fp))
