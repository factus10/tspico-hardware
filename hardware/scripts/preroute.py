#!/usr/bin/env python3
"""Hand routes that must not be left to the autorouter, added (locked) to the
freshly placed board: the RP2350B core regulator and the crystal, laid out as in
"Hardware design with RP2350" figure 4 (rotated: the regulator pins 61-65 are at
the top of the chip's left side). Run with KiCad's Python after gen_layout.py.

Regulator: VIN cap C22 and output cap C20 (0402) straddle the VREG_LX pin, so LX
runs under both to L1 (3.7 mm); VIN and PGND go straight into C22; FB senses at
C20; the cap grounds return to PGND with one via beside them; AVDD goes up to
its RC filter. USB D-/D+ get their first jog so they clear the FB track.

Also fixed here: the DVDD spine and supply links under the RP2350B, the fan of its
bottom pad row, and the via fan of U1's Z80-side address pins.
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
    route("DVDD", [(57.05, 23.8), (56.45, 23.8), (56.25, 24.0), (55.8, 24.0)], 0.15)      # 0.15 past the USB jogs, 0.2 after
    route("DVDD", [(55.8, 24.0), (54.75, 24.0), (54.3, 23.55)], 0.2)
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
    # supply pins linked under the package, in the first band inside the pad row, so the router
    # does not fence in their neighbours with links across the outside of the chip:
    # pin 50 to the corner pins 59/60 (which have the corner via), pins 68/69 to pin 76
    # pin 50 east to corner pin 41, pins 68/69 to pin 76, pin 24 to pin 29 (each group has a via)
    route("+3V3", [(62.2, 21.05), (62.2, 21.72), (65.8, 21.72), (65.8, 21.05)], 0.15)
    route("+3V3", [(57.05, 25.0), (57.05, 25.4), (57.75, 25.4), (57.75, 28.2), (57.05, 28.2)], 0.15)
    route("+3V3", [(66.95, 28.6), (66.3, 28.6), (66.3, 26.6), (66.95, 26.6)], 0.15)
    route("+3V3", [(57.75, 28.2), (57.75, 29.6), (58.3, 30.15), (59.8, 30.15), (59.8, 30.95)], 0.15)      # ...and on to pin 5, whose fan via feeds the 68/69/76 group
    # ---- DVDD spine: the 1.1 V core rail from the regulator's pin 65 to DVDD pins 51, 10 and 32,
    # 0.25 mm under the package (0.2 mm where it enters a 0.2 mm pad)
    route("DVDD", [(57.05, 23.8), (57.9, 23.8)], 0.2)
    route("DVDD", [(57.9, 23.8), (58.6, 23.8), (60.0, 22.4), (61.8, 22.4)], 0.25)
    route("DVDD", [(61.8, 22.4), (61.8, 21.05)], 0.2)
    route("DVDD", [(58.6, 23.8), (58.6, 28.9), (59.4, 29.7), (61.8, 29.7)], 0.25)
    route("DVDD", [(61.8, 29.7), (61.8, 30.95)], 0.2)
    route("DVDD", [(61.8, 29.7), (64.0, 29.7), (65.85, 27.85), (65.85, 25.4), (66.4, 25.4)], 0.25)
    route("DVDD", [(66.4, 25.4), (66.95, 25.4)], 0.2)
    route("DVDD", [(61.8, 21.05), (61.8, 19.9), (62.3, 19.4), (62.3, 19.0)], 0.2)      # pin 51 to its 100 nF, 2 mm
    # ---- bottom pad row (pins 1-20, all in use): a deterministic fan ----------------------
    # Every pin runs straight out to a staggered depth, turns 45 degrees away from the centre and
    # ends in a via on the line y = YV. Adjacent diagonals are (0.4 + STEP) / sqrt(2) = 0.53 mm
    # apart and the vias 0.75 mm apart: the tightest legal pattern for 0.6 mm vias at 0.4 mm pitch.
    u20 = B.b.FindFootprintByReference("U20")
    bottom = sorted((p for p in u20.Pads() if p.GetNumber().isdigit() and 1 <= int(p.GetNumber()) <= 20), key=lambda p: p.GetPosition().x)
    Y0, STEP, YV = 31.6, 0.35, 35.2
    for k, pad in enumerate(bottom):
        x, y = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
        left = k < 10
        yb = Y0 + STEP * (k if left else 19 - k)
        xe = x - (YV - yb) if left else x + (YV - yb)
        name = pad.GetNetname().split("/")[-1]
        route(name, [(x, y), (x, yb), (xe, YV)], 0.15)
        via(name, xe, YV)
        if name in ("+3V3", "DVDD"):                  # their decoupling cap sits just below the via
            route(name, [(xe, YV), (xe, YV + 1.0)], 0.25)
    # supply pin 29 shares its lane with the XIN track; pads 27/28 below it are spare, so it
    # drops into their lanes to a via (clear of XIN above and I2C_SCL below)
    route("+3V3", [(66.95, 26.6), (67.35, 26.6), (67.85, 27.1), (68.7, 27.2)], 0.15)
    via("+3V3", 68.7, 27.2)
    # ---- U1's Z80-side pins (A0-A7): a via fan under its own body ---------------------------
    # U1's bottom pad row faces U2's top row across a 0.8 mm gap, so these pins can only leave
    # under U1, and all of them have to change layer (their fingers are bottom copper). Left to
    # itself the router puts the first few vias right at the pads and now and then seals a
    # neighbour in behind them (A5 one run, A3 another). Two staggered rows: neighbours are
    # 1.03 mm apart centre to centre, and a track (top or bottom) still passes between two vias
    # of the near row, so every via can be left downwards on the bottom layer.
    u1 = B.b.FindFootprintByReference("U1")
    cy = pcbnew.ToMM(u1.GetPosition().y)
    zside = sorted((p for p in u1.Pads() if p.GetNumber().isdigit() and 11 <= int(p.GetNumber()) <= 18), key=lambda p: p.GetPosition().x)
    for k, pad in enumerate(zside):
        x, y = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
        inward = -1 if cy < y else 1
        yv = round(y + inward * (1.26 if k % 2 == 0 else 2.06), 3)
        name = pad.GetNetname().split("/")[-1]
        route(name, [(x, y), (x, yv)], 0.15)
        via(name, x, yv)
    B.save()
    print("pre-routes added:", len(B.tracks), "tracks,", len(B.vias), "vias; failed:", fails or "none")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
