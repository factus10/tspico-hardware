#!/usr/bin/env python3
"""Generate audio.kicad_sch: PWM stereo from the RP2350B mixed with 2068 SOUND.

  AUDIO_L / AUDIO_R (PWM) -> 2nd-order RC low-pass -> summing node with the
  2068 SOUND line (AC-coupled, attenuated) -> unity-gain buffer (U50 MCP6002,
  single 5 V supply) -> 10 uF coupling -> 100 R -> 3.5 mm stereo jack J4.
  Values are starting points; tune on the prototype.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
JACK_FP = "Connector_Audio:Jack_3.5mm_PJ320D_Horizontal"

OUT, IN, BI = "output", "input", "bidirectional"


def channel(s, ch, y, n):
    """One channel: PWM filter, SOUND mix, buffer input. n = first R/C index.
    Parts stand vertically in a row; labels above and below."""
    pwm = f"AUDIO_{ch}"
    R1 = s.place("Device:R", f"R{n}", "1k", R0603, 60, y)
    s.glabel(pwm, R1.pin("1"), IN); s.label(f"{ch}_F1", R1.pin("2"))
    C1 = s.place("Device:C", f"C{n}", "10n", C0603, 75, y)
    s.label(f"{ch}_F1", C1.pin("1")); s.label("GND", C1.pin("2"))
    R2 = s.place("Device:R", f"R{n + 1}", "1k", R0603, 90, y)
    s.label(f"{ch}_F1", R2.pin("1")); s.label(f"{ch}_F2", R2.pin("2"))
    C2 = s.place("Device:C", f"C{n + 1}", "10n", C0603, 105, y)
    s.label(f"{ch}_F2", C2.pin("1")); s.label("GND", C2.pin("2"))
    R3 = s.place("Device:R", f"R{n + 2}", "10k", R0603, 120, y)
    s.label(f"{ch}_F2", R3.pin("1")); s.label(f"{ch}_MIX", R3.pin("2"))
    R4 = s.place("Device:R", f"R{n + 3}", "22k", R0603, 135, y)
    s.label("SOUND_AC", R4.pin("1")); s.label(f"{ch}_MIX", R4.pin("2"))
    return f"{ch}_MIX"


def main():
    s = Sheet("tspico-v3.kicad_sch", "audio.kicad_sch", "TS-Pico v3: Audio")
    s.text("Emulated AY-3-8910 on RP2350B PWM (AUDIO_L/R), low-passed, mixed with the 2068 SOUND line, buffered to a stereo 3.5 mm jack.", 20, 285, 2.5)
    s.text("Op-amp on the +5V rail (rail-to-rail MCP6002). Component values are starting points; tune on the prototype.", 20, 290, 2.0)
    s.power("+5V", 300, 30, "#PWR16", flag=False)
    s.power("GND", 330, 40, "#PWR17", flag=False)

    # 2068 SOUND: AC couple and attenuate once, shared by both channels
    C70 = s.place("Device:C", "C70", "1u", C0603, 40, 60)
    s.glabel("SOUND_2068", C70.pin("1"), IN); s.label("SOUND_AC", C70.pin("2"))
    R70 = s.place("Device:R", "R70", "100k", R0603, 55, 60)
    s.label("SOUND_AC", R70.pin("1")); s.label("GND", R70.pin("2"))

    mixL = channel(s, "L", 110, 71)
    mixR = channel(s, "R", 170, 75)

    # U50 buffers
    U50a = s.place("Amplifier_Operational:MCP6002-xSN", "U50", "MCP6002", SOIC8, 200, 110, unit=1)
    s.label(mixL, U50a.pin("+")); s.label("L_OUT", U50a.pin("-")); s.label("L_OUT", U50a.pin("1"))
    U50b = s.place("Amplifier_Operational:MCP6002-xSN", "U50", "MCP6002", SOIC8, 200, 170, unit=2)
    s.label(mixR, U50b.pin("+")); s.label("R_OUT", U50b.pin("-")); s.label("R_OUT", U50b.pin("7"))
    U50p = s.place("Amplifier_Operational:MCP6002-xSN", "U50", "MCP6002", SOIC8, 200, 230, unit=3)
    s.label("+5V", U50p.pin("V+")); s.label("GND", U50p.pin("V-"))
    C79 = s.place("Device:C", "C79", "100n", C0603, 230, 230)
    s.label("+5V", C79.pin("1")); s.label("GND", C79.pin("2"))

    # output coupling and jack
    for k, (ch, y) in enumerate((("L", 110), ("R", 170))):
        C = s.place("Device:C_Polarized", f"C{80 + k}", "10u", C0603, 250, y)
        s.label(f"{ch}_OUT", C.pin("1")); s.label(f"{ch}_AC", C.pin("2"))
        R = s.place("Device:R", f"R{80 + k}", "100", R0603, 270, y)
        s.label(f"{ch}_AC", R.pin("1")); s.label(f"{ch}_JACK", R.pin("2"))
    J4 = s.place("Connector_Audio:AudioJack4", "J4", "3.5mm stereo", JACK_FP, 320, 140)   # PJ-320D is 4-pole; a TRS plug shorts R2 to S
    s.label("L_JACK", J4.pin("T")); s.label("R_JACK", J4.pin("R1")); s.label("GND", J4.pin("R2")); s.label("GND", J4.pin("S"))
    s.text("Mix: L = AY A + AY B/2, R = AY C + AY B/2 done in firmware; SOUND_2068 added to both channels here.", 40, 215, 1.5)
    s.text("The PWM branch (0 to 3.3 V, DC about 1.65 V) also biases the buffer input; SOUND is AC-coupled by C70.", 40, 218, 1.5)

    s.write()
    print("wrote audio.kicad_sch")


if __name__ == "__main__":
    main()
