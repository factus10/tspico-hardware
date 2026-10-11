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
    ("2k7", R): ("0603WAF2701T5E", "C13167", "basic"),
    ("4k7", R): ("0603WAF4701T5E", "C23162", "basic"),
    ("10k", R): ("0603WAF1002T5E", "C25804", "basic"),
    ("11k", R): ("0603WAF1102T5E", "C25950", "preferred (no loading fee)"),
    ("47k", R): ("0603WAF4702T5E", "C25819", "basic"),
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
    ("470n", C6): ("CL10B474KA8NNNC", "C1623", "basic, X7R 25V; TPS3808 delay = 470/175 = 2.7 s"),
    ("1u", C6): ("CL10A105KB8NNNC", "C15849", "basic, X5R 25V"),
    ("10u", C8): ("CL21A106KAYNNNE", "C15850", "basic, X5R 25V"),
    # ---- semiconductors ------------------------------------------------------
    ("RP2040", "QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm"): ("RP2040", "C2040", "extended, Raspberry Pi"),
    ("W25Q16JVSSIQ", "SOIC-8_5.3x5.3mm_P1.27mm"): ("W25Q16JVSSIQ", "C82317", "extended, Winbond 2 MB QSPI (the Pico's flash size); the basic W25Q128JVSIQ C97521 costs more than the fee saves"),
    ("12MHz", "Crystal_SMD_3225-4Pin_3.2x2.5mm"): ("ABM8-272-T3", "C20625731", "extended, Abracon, the RP2040 design guide's crystal (also on v3); basic X322512MSB4SI C9002 is untried with the RP2040"),
    ("AMS1117-3.3", "SOT-223-3_TabPin2"): ("AMS1117-3.3", "C6186", "basic, AMS"),
    ("green", "LED_0805_2012Metric"): ("KT-0805G", "C2297", "basic, KENTO"),
    ("USB-C", "USB_C_Receptacle_HRO_TYPE-C-31-M-12"): ("TYPE-C-31-M-12", "C165948", "extended, HRO (same as v3)"),
    # U10 SST39SF040-70-4C-PHE and U13 AS6C4008-55PCN are through-hole DIP-32 in sockets, hand-soldered: no LCSC number
    ("74LVC138A", "TSSOP-16_4.4x5mm_P0.65mm"): ("SN74LVC138APWR", "C485077", "extended, TI, port decode (6617 in stock 2026-10-11; SSOP C2674435 is cheaper but a different footprint)"),
    ("74LVC32A", "TSSOP-14_4.4x5mm_P0.65mm"): ("74LVC32APW,118", "C6087", "extended, Nexperia (same part as v3)"),
    ("74LVC157A", "TSSOP-16_4.4x5mm_P0.65mm"): ("SN74LVC157APWR", "C406871", "extended, TI"),
    ("74LVC1G97", "SOT-23-6"): ("SN74LVC1G97DBVR", "C128411", "extended, TI configurable gate, wired as OR with one inverted input"),
    ("74LVC2G07", "SOT-23-6"): ("74LVC2G07GV", "C19829597", "extended, Nexperia dual open-drain buffer (EM74LVC2G07GV C49188101 is the alternate)"),
    ("TPS3808G01", "SOT-23-6"): ("TPS3808G01DBVR", "C19653", "extended, TI reset supervisor, adjustable threshold and delay"),
    ("74LVC245APW", T20): ("74LVC245APW,118", "C6082", "extended, Nexperia (same part as v3)"),
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
