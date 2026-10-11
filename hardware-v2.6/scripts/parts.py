"""Orderable part numbers for the TS-Pico v2.6 BOM.

Keyed by (Value, footprint basename). Each entry: (MPN, LCSC, note).
"basic" in the note means a JLCPCB basic part (no extended-part fee).
LCSC numbers and stock were looked up on 2026-10-11 with jlc_price.py; re-check at order time.
An empty LCSC string means "not sourced from LCSC" (edge fingers, solder jumpers, DNP pads).
"""

R = "R_0603_1608Metric"
C6 = "C_0603_1608Metric"
C8 = "C_0805_2012Metric"
SO14 = "SOIC-14_3.9x8.7mm_P1.27mm"
SO16 = "SOIC-16_3.9x9.9mm_P1.27mm"
T20 = "TSSOP-20_4.4x6.5mm_P0.65mm"

PARTS = {
    # ---- resistors (0603, 1%) ------------------------------------------------
    ("2k2", R): ("0603WAF2201T5E", "C4190", "basic"),
    ("2k7", R): ("0603WAF2701T5E", "C13167", "basic"),
    ("4k7", R): ("0603WAF4701T5E", "C23162", "basic"),
    ("10k", R): ("0603WAF1002T5E", "C25804", "basic"),
    ("47k", R): ("0603WAF4702T5E", "C25819", "basic"),
    ("220k", R): ("0603WAF2203T5E", "C22961", "basic"),
    ("1M", R): ("0603WAF1004T5E", "C22935", "basic"),
    ("27", R): ("0603WAF270JT5E", "C25190", "preferred, USB series (RP2040 design guide value)"),
    ("1k", R): ("0603WAF1001T5E", "C21190", "basic"),
    ("5k1", R): ("0603WAF5101T5E", "C23186", "basic"),
    ("5k6", R): ("0603WAF5601T5E", "C23189", "basic"),
    ("100k", R): ("0603WAF1003T5E", "C25803", "basic"),
    ("200k", R): ("0603WAF2003T5E", "C25811", "basic"),
    ("470", R): ("0603WAF4700T5E", "C23179", "basic"),
    # ---- capacitors ----------------------------------------------------------
    ("100n", C6): ("CC0603KRX7R9BB104", "C14663", "basic, X7R 50V"),
    ("15p", C6): ("CL10C150JB8NNNC", "C1644", "basic, C0G"),
    ("1u", C6): ("CL10A105KB8NNNC", "C15849", "basic, X5R 25V"),
    ("10u", C8): ("CL21A106KAYNNNE", "C15850", "basic, X5R 25V (25 V rating keeps the DC-bias loss small at 5 V, which matters for the 555 timing cap C12)"),
    # ---- semiconductors ------------------------------------------------------
    ("RP2040", "QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm"): ("RP2040", "C2040", "extended, Raspberry Pi"),
    ("W25Q16JVSSIQ", "SOIC-8_5.3x5.3mm_P1.27mm"): ("W25Q16JVSSIQ", "C82317", "extended, Winbond 2 MB QSPI (the Pico's flash size); the basic W25Q128JVSIQ C97521 costs more than the fee saves"),
    ("12MHz", "Crystal_SMD_3225-4Pin_3.2x2.5mm"): ("ABM8-272-T3", "C20625731", "extended, Abracon, the RP2040 design guide's crystal (also on v3); basic X322512MSB4SI C9002 is untried with the RP2040"),
    ("AMS1117-3.3", "SOT-223-3_TabPin2"): ("AMS1117-3.3", "C6186", "basic, AMS"),
    ("green", "LED_0805_2012Metric"): ("KT-0805G", "C2297", "basic, KENTO"),
    ("USB-C", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"): ("TYPE-C-31-M-12", "C165948", "extended, HRO (same as v3)"),
    # U10 SST39SF040-70-4C-PHE and U13 AS6C4008-55PCN are through-hole DIP-32 in sockets, hand-soldered: no LCSC number
    ("74LS04", SO14): ("SN74LS04DR", "C6796", "extended, TI"),
    ("74LS09", SO14): ("SN74LS09DR", "C7731", "extended, TI, open-collector (56 in stock)"),
    ("74LS27", SO14): ("XL74LS27", "C707098", "extended, XINLUDA (the only SOIC LS27 at JLC; 108 in stock)"),
    ("74LS32", SO14): ("SN74LS32DR", "C116812", "extended, TI"),
    ("74LS157", SO16): ("XL74LS157", "C707097", "extended, XINLUDA"),
    ("74LVC245APW", T20): ("74LVC245APW,118", "C6082", "extended, Nexperia (same part as v3)"),
    ("NE555", "SOIC-8_3.9x4.9mm_P1.27mm"): ("NE555DR", "C7593", "preferred (no loading fee), TI; replaces the TLC555"),
    ("MMBT3904", "SOT-23"): ("MMBT3904", "C20526", "basic, CJ"),
    ("SS14", "D_SMA"): ("SS14", "C2480", "basic, MDD"),
    # ---- electromechanical ---------------------------------------------------
    ("microSD", "microSD_TF-01A"): ("TF-01A", "C91145", "extended, HRO push-push (same socket and footprint as v3)"),
    ("NMI", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("TS Reset", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("Pico Reset", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("BOOTSEL", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
}


def lookup(value, footprint):
    """Return (MPN, LCSC, note) or None."""
    fp = footprint.split(":")[-1] if footprint else ""
    return PARTS.get((value, fp))
