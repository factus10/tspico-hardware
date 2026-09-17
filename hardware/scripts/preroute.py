#!/usr/bin/env python3
"""Hand routes that must not be left to the autorouter, added (locked) to the
freshly placed board: the RP2350B core regulator and the crystal, laid out as in
"Hardware design with RP2350" figure 4 (rotated: the regulator pins 61-65 are at
the top of the chip's left side). Run with KiCad's Python after gen_layout.py.

Regulator: VIN cap C22 and output cap C20 (0402) straddle the VREG_LX pin, so LX
runs under both to L1 (3.7 mm); VIN and PGND go straight into C22; FB senses at
C20; the cap grounds return to PGND with one via beside them; AVDD goes up to
its RC filter. USB D-/D+ get their first jog so they clear the FB track.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from finish_route import Board, pcbnew

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = pcbnew.F_Cu


def main():
    B = Board(os.path.join(HW, "tspico-v3.kicad_pcb"))
    B.lock = True
    net = lambda n: next(c for name, c in ((ni.GetNetname(), code) for code, ni in B.b.GetNetsByNetcode().items()) if name.split("/")[-1] == n)
    fails = []

    def route(name, pts, w):
        if not B.polyline(pts, net(name), F, w):
            fails.append((name, pts[0]))

    def via(name, x, y, d=0.6):      # 0.6/0.3: JLCPCB's no-surcharge via
        if B.via_ok(x, y, net(name), d):
            B.add_via(x, y, net(name), d)
        else:
            fails.append((name + " via", (x, y)))

    # ---- core regulator (pins 61 AVDD, 62 PGND, 63 LX, 64 VIN, 65 FB) ----------
    route("VREG_LX", [(57.05, 23.0), (56.35, 23.0), (56.15, 22.8), (53.55, 22.8), (53.0, 22.25), (52.6, 22.0)], 0.13)
    route("+3V3", [(57.05, 23.4), (55.4, 23.4)], 0.2)
    via("+3V3", 56.0, 23.4)
    route("GND", [(57.05, 22.6), (56.55, 22.6), (56.3, 22.35), (54.05, 22.35)], 0.15)
    route("GND", [(54.05, 22.32), (54.05, 21.45)], 0.25)
    route("GND", [(54.62, 21.2), (54.05, 21.45)], 0.25)
    via("GND", 54.05, 21.45)
    route("DVDD", [(52.9, 23.65), (53.85, 23.4)], 0.3)
    route("DVDD", [(57.05, 23.8), (56.45, 23.8), (56.25, 24.0), (54.75, 24.0), (54.3, 23.55)], 0.15)
    route("VREG_AVDD", [(57.05, 22.2), (56.6, 22.2), (56.2, 21.8), (55.75, 21.35)], 0.15)
    route("VREG_AVDD", [(55.6, 20.025), (55.6, 21.0)], 0.2)
    route("USB_DM", [(57.05, 24.2), (56.5, 24.2), (56.25, 24.45), (55.6, 24.45)], 0.2)
    route("USB_DP", [(57.05, 24.6), (56.6, 24.6), (56.35, 24.85), (55.6, 24.85)], 0.2)
    # ---- crystal ----------------------------------------------------------------
    # XIN and XOUT drop one pad lane (0.4 mm) right after the pads: that leaves room for DVDD pin 32's via above them
    route("XIN", [(66.95, 26.2), (67.45, 26.2), (67.85, 26.6), (72.6, 26.6), (72.85, 26.85), (73.8, 26.85)], 0.2)
    route("XIN", [(74.4, 27.3), (74.4, 28.3)], 0.2)
    route("XOUT", [(66.95, 25.8), (67.75, 25.8), (68.15, 26.2), (70.0, 26.2), (70.6, 25.6), (70.9, 25.4)], 0.2)
    route("DVDD", [(66.95, 25.4), (68.2, 25.4), (68.5, 25.5)], 0.15)
    via("DVDD", 68.6, 25.55)
    route("XOUT_R", [(72.525, 25.2), (72.9, 25.6), (73.3, 26.0), (76.6, 26.0), (76.6, 25.5)], 0.2)
    route("XOUT_R", [(76.6, 23.7), (76.6, 24.7)], 0.2)
    # ---- corner supply pins: via on the corner side, so the neighbours' lanes stay open ----
    route("+3V3", [(58.6, 21.05), (58.2, 21.05), (58.2, 20.5), (57.55, 19.85)], 0.15)
    via("+3V3", 57.45, 19.75)
    route("+3V3", [(65.8, 21.05), (65.8, 20.5), (66.4, 19.9)], 0.15)
    via("+3V3", 66.5, 19.8)
    B.save()
    print("pre-routes added:", len(B.tracks), "tracks,", len(B.vias), "vias; failed:", fails or "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
