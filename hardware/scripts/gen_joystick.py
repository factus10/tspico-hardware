#!/usr/bin/env python3
"""Generate joystick.kicad_sch: Kempston-style DE-9 joystick port.

  J5 DE-9 socket, Atari pinout: 1 up, 2 down, 3 left, 4 right, 6 fire, 9 fire 2,
  8 GND, 7 +5V through a solder jumper (for autofire sticks), 5 unused.
  Lines are pulled up to +3V3 and read by STAT (pressed = low); the firmware
  inverts when it builds the Kempston byte for port $1F. 100 R series and
  100 pF to ground on each line for ESD and cable ringing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schlib import Sheet  # noqa: E402

R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
DE9_FP = "Connector_Dsub:DSUB-9_Socket_Horizontal_P2.77x2.84mm_EdgePinOffset7.70mm_Housed_MountingHolesOffset9.12mm"
SJ_FP = "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm"

OUT, IN, BI = "output", "input", "bidirectional"


def main():
    s = Sheet("tspico-v3.kicad_sch", "joystick.kicad_sch", "TS-Pico v3: Joystick")
    s.text("Kempston joystick on a DE-9 socket. Inputs pulled up to +3V3, read through STAT; firmware serves port $1F (bit = 1 when pressed).", 20, 285, 2.5)
    s.text("JP10: optional +5V on pin 7 for autofire joysticks (solder jumper, open by default).", 20, 290, 2.0)
    s.power("+3V3", 300, 30, "#PWR18", flag=False)
    s.power("+5V", 330, 30, "#PWR19", flag=False)
    s.power("GND", 360, 40, "#PWR20", flag=False)

    J5 = s.place("Connector:DE9_Socket", "J5", "Joystick", DE9_FP, 80, 120)
    lines = {"1": "JOY_UP", "2": "JOY_DOWN", "3": "JOY_LEFT", "4": "JOY_RIGHT", "6": "JOY_FIRE1", "9": "JOY_FIRE2"}
    for pin, net in lines.items():
        s.label(net + "_J", J5.pin(pin))
    s.label("GND", J5.pin("8")); s.label("JOY_5V", J5.pin("7")); s.nc(J5.pin("5"))
    for k, (pin, net) in enumerate(lines.items()):
        x = 150 + 40 * k
        R = s.place("Device:R", f"R{90 + k}", "100", R0603, x, 80)
        s.label(net + "_J", R.pin("1")); s.glabel(net, R.pin("2"), OUT)
        P = s.place("Device:R", f"R{96 + k}", "10k", R0603, x + 15, 120)
        s.label("+3V3", P.pin("1")); s.glabel(net, P.pin("2"), OUT)
        C = s.place("Device:C", f"C{90 + k}", "100p", C0603, x + 15, 160)
        s.glabel(net, C.pin("1"), OUT); s.label("GND", C.pin("2"))
    JP = s.place("Jumper:SolderJumper_2_Open", "JP10", "JOY +5V", SJ_FP, 80, 200)
    s.label("+5V", JP.pin("1")); s.label("JOY_5V", JP.pin("2"))

    s.write()
    print("wrote joystick.kicad_sch")


if __name__ == "__main__":
    main()
