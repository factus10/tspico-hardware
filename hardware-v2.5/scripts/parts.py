"""Orderable part numbers for the TS-Pico v2.5 BOM.

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
    ("4k7 x4", "R_Array_Convex_4x0603"): ("4D03WGJ0472T5E", "C1980", "basic, 4 x 4.7k array"),
    # ---- capacitors ----------------------------------------------------------
    ("100n", C6): ("CC0603KRX7R9BB104", "C14663", "basic, X7R 50V"),
    ("10u", C8): ("CL21A106KAYNNNE", "C15850", "basic, X5R 25V (25 V rating keeps the DC-bias loss small at 5 V, which matters for the 555 timing cap C12)"),
    # ---- semiconductors ------------------------------------------------------
    ("Raspberry Pi Pico", "RaspberryPi_Pico_SMD"): ("SC0915", "C7203002", "extended, castellated module, reflowed by JLCPCB (a Pico 2 fits the same footprint)"),
    ("SST39SF040", "PLCC-32_11.4x14.0mm_P1.27mm"): ("SST39SF040-55-4I-NHE-T", "C632847", "extended, Microchip, 17 in stock 2026-10-11 (C632846, the 0-70 C grade, is the alternate)"),
    ("CY62148ELL-55SXI", "SOP-32_11.305x20.495mm_P1.27mm"): ("CY62148ELL-55SXIT", "C511135", "extended, Infineon 512K x 8 5 V SRAM, 450 mil SOIC, 16 in stock (C2953576 tray: 5); AS6C4008-55SIN is the same footprint and pinout if JLC runs out"),
    ("74LS04", SO14): ("SN74LS04DR", "C6796", "extended, TI"),
    ("74LS09", SO14): ("SN74LS09DR", "C7731", "extended, TI, open-collector (56 in stock)"),
    ("74LS27", SO14): ("XL74LS27", "C707098", "extended, XINLUDA (the only SOIC LS27 at JLC; 108 in stock)"),
    ("74LS32", SO14): ("SN74LS32DR", "C116812", "extended, TI"),
    ("74LS157", SO16): ("XL74LS157", "C707097", "extended, XINLUDA"),
    ("74LVC245APW", T20): ("74LVC245APW,118", "C6082", "extended, Nexperia (same part as v3)"),
    ("74HCT595", SO16): ("74HCT595D,118", "C282339", "extended, Nexperia: HCT for TTL thresholds, the Pico drives SER/SRCLK/RCLK at 3.3 V"),
    ("NE555", "SOIC-8_3.9x4.9mm_P1.27mm"): ("NE555DR", "C7593", "preferred (no loading fee), TI; replaces the TLC555"),
    ("MMBT3904", "SOT-23"): ("MMBT3904", "C20526", "basic, CJ"),
    ("SS14", "D_SMA"): ("SS14", "C2480", "basic, MDD"),
    # ---- electromechanical ---------------------------------------------------
    ("microSD", "microSD_TF-01A"): ("TF-01A", "C91145", "extended, HRO push-push (same socket and footprint as v3)"),
    ("NMI", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("TS Reset", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("Pico Reset", "SW_Push_1P1T_XKB_TS-1187A"): ("TS-1187A-B-A-B", "C318884", "basic, XKB"),
    ("RUN/PROG", "SW_SPDT_Shouhan_MSK12C02"): ("MSK12C02", "C431540", "extended, SHOU HAN SMD slide switch"),
}


def lookup(value, footprint):
    """Return (MPN, LCSC, note) or None."""
    fp = footprint.split(":")[-1] if footprint else ""
    return PARTS.get((value, fp))
