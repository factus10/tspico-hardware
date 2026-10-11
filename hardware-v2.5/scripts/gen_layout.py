#!/usr/bin/env python3
"""Build the placed (unrouted) v2.5 board from the schematic netlist.

Run with KiCad's bundled Python (it has the pcbnew module):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/gen_layout.py

Steps: regenerate the skeleton (outline, edge connector, holes, fiducials) with
gen_board.py, export the netlist with kicad-cli, load every footprint from the
KiCad or project library, assign nets, place parts per P below, add the GND
(In1.Cu) and +5V (In2.Cu) planes, save tspico-v2.5.kicad_pcb.
It overwrites the board: once routing is done, stop running it.

Coordinates: mm, board origin at the top-left corner of the body, y down.
Body 130 x 56; tongue below y = 56 between x = 18.48 and 102.14.
Fingers (x of each position = 21.00 + 2.54 (n - 1)): data D0-D7 top side x 28.6-51.5,
address A0-A15 bottom side x 43.9-82.0, control top side x 56.6-92.1.
Rotation: degrees counter-clockwise as in KiCad.
"""
import os
import re
import subprocess
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
KICAD_FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
PCB = os.path.join(HW, "tspico-v2.5.kicad_pcb")
NET = "/tmp/tspico-v2.5.net"
BODY_H = 56.0

# ---------------------------------------------------------------------------
# Placement: ref -> (x, y, rot). Anything not listed is parked off-board.
# ---------------------------------------------------------------------------
P = {}

# Pico along the top-left, USB out of the left edge. Rotated 90: pins 1-20 (GP0-GP15: data
# bus and Z80 control inputs) run left to right along the bottom row at y = 28.2, pins
# 21-40 (GP16-GP28, power) right to left along the top row at y = 8.8.
P["U2"] = (26.0, 19.5, 90)
# top strip, left to right: SW4 (bench programming) and D3 next to VBUS (pin 40), D2/C2 for VSYS (pin 39),
# the Pico-side pull-ups, then the three buttons with their DNP external-button pads
P["SW4"], P["D3"] = (14.5, 3.2, 0), (23.0, 3.0, 0)
P["D2"], P["C2"] = (30.0, 3.0, 0), (35.0, 3.0, 90)
P["R9"], P["R15"], P["R16"], P["R4"] = (38.0, 2.4, 90), (40.3, 2.4, 90), (42.6, 2.4, 90), (44.9, 2.4, 90)
P["SW1"], P["SW2"], P["SW3"] = (58.0, 4.5, 0), (74.0, 4.5, 0), (90.0, 4.5, 0)
P["C15"] = (58.0, 9.6, 0)
P["JP2"], P["JP3"], P["JP5"] = (66.0, 4.5, 90), (82.0, 4.5, 90), (98.0, 4.5, 90)
# memories in the middle band, right of the Pico
P["U13"], P["C13"] = (67.5, 21.0, 90), (75.5, 30.6, 0)
P["U10"], P["C10"] = (89.0, 21.5, 0), (89.0, 30.6, 0)
P["R6"], P["P10"] = (97.4, 14.0, 90), (97.4, 18.0, 90)
# power-on reset (555) in the top-right corner
P["U11"] = (108.0, 13.0, 0)
P["R1"], P["C9"] = (103.0, 18.5, 90), (105.5, 18.5, 90)
P["R5"], P["C12"] = (108.0, 18.5, 90), (111.0, 18.5, 90)
P["C11"], P["R10"], P["R11"], P["Q1"] = (113.8, 18.5, 90), (113.5, 10.5, 90), (116.0, 10.5, 90), (114.5, 14.5, 0)
P["C16"] = (120.0, 18.5, 90)
# micro SD on the left edge below the Pico (shell flush with the edge), near GP2-GP4 and GP28
P["U3"] = (9.58, 39.8, 270)
P["R22"], P["R23"], P["C3"], P["C18"] = (19.8, 34.0, 0), (19.8, 35.8, 0), (19.8, 37.6, 0), (19.8, 39.8, 0)
# glue row, decoupling caps above each package
ROW1 = 38.8
for ref, cap, x in (("U1", "C1", 26.0), ("U5", "C5", 35.5), ("U4", "C4", 45.0), ("U9", "C14", 54.5)):
    P[ref], P[cap] = (x, ROW1, 0), (x, ROW1 - 5.8, 0)
P["U8"], P["C8"] = (64.0, ROW1 + 0.3, 0), (64.0, ROW1 - 5.8, 0)
P["U7"], P["C6"] = (73.0, ROW1, 0), (73.0, ROW1 - 5.8, 0)
P["R7"], P["R2"] = (71.5, ROW1 + 6.0, 90), (74.5, ROW1 + 6.0, 90)
P["R8"], P["R3"], P["JP1"] = (52.5, ROW1 + 6.6, 90), (55.0, ROW1 + 6.6, 90), (58.4, ROW1 + 6.6, 90)
P["JP4"] = (31.0, ROW1 + 7.0, 0)
# bench-programming chain: address registers over the address fingers, data register last
P["U12"], P["C17"] = (82.0, ROW1 + 0.3, 0), (82.0, ROW1 - 5.8, 0)
P["U14"], P["C19"] = (91.0, ROW1 + 0.3, 0), (91.0, ROW1 - 5.8, 0)
# program-enable interlock right of the chain
P["Q2"], P["Q3"] = (108.0, 34.0, 0), (108.0, 39.0, 0)
P["R17"], P["R18"], P["R19"] = (112.0, 32.4, 0), (112.0, 34.2, 0), (112.0, 36.0, 0)
P["R20"], P["R21"] = (112.0, 38.4, 0), (112.0, 40.2, 0)
# data path next to the data fingers
ROW2 = 49.6
P["U6"], P["C7"] = (44.0, ROW2, 0), (48.8, ROW2 - 3.6, 90)
# data register U15 with its 4.7k packs at the left end of the data fingers (D7 is the leftmost finger)
P["U15"], P["C20"] = (22.5, ROW2 + 0.4, 90), (16.4, ROW2 + 0.4, 90)
P["RN1"], P["RN2"] = (31.0, ROW2 + 0.9, 0), (35.6, ROW2 + 0.9, 0)
P["R12"] = (39.0, ROW2 - 4.6, 0)          # D6 pull-down, by U6 pin 8
P["R13"], P["R14"] = (88.6, ROW2 + 1.0, 90), (66.0, ROW2 + 1.0, 90)
# right side of the board is spare

# ---------------------------------------------------------------------------


def sexpr(text):
    """Minimal s-expression parser: returns nested lists of str."""
    tokens = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+', text)
    stack = [[]]
    for t in tokens:
        if t == '(':
            stack.append([])
        elif t == ')':
            top = stack.pop()
            stack[-1].append(top)
        else:
            stack[-1].append(t[1:-1] if t.startswith('"') else t)
    return stack[0]


def find(node, key):
    return [n for n in node if isinstance(n, list) and n and n[0] == key]


def first(node, key):
    f = find(node, key)
    return f[0] if f else None


def load_netlist(path):
    root = sexpr(open(path).read())[0]
    comps = {}
    for c in find(first(root, "components"), "comp"):
        ref = first(c, "ref")[1]
        dnp = any(len(pr) > 1 and isinstance(pr[1], list) and pr[1][:2] == ["name", "dnp"] for pr in find(c, "property"))
        comps[ref] = {"value": first(c, "value")[1], "footprint": (first(c, "footprint") or ["", ""])[1], "dnp": dnp}
    nets = []
    for n in find(first(root, "nets"), "net"):
        name = first(n, "name")[1]
        nodes = [(first(nd, "ref")[1], first(nd, "pin")[1]) for nd in find(n, "node")]
        nets.append((name, nodes))
    return comps, nets


def load_footprint(fpid):
    lib, name = fpid.split(":")
    path = os.path.join(HW, "lib", lib + ".pretty") if lib == "tspico" else os.path.join(KICAD_FP, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f"footprint not found: {fpid}")
    return fp


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def main():
    subprocess.run(["python3", os.path.join(HERE, "gen_board.py")], check=True)
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", NET,
                    os.path.join(HW, "tspico-v2.5.kicad_sch")], check=True)
    comps, nets = load_netlist(NET)
    board = pcbnew.LoadBoard(PCB)

    netinfo = {}
    for name, _ in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni

    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    park_x = 140.0
    for i, (ref, c) in enumerate(sorted(comps.items())):
        if ref.startswith("#") or ref in fps:
            continue
        fp = load_footprint(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        if c.get("dnp"):
            fp.SetDNP(True)
        if ref in P:
            x, y, rot = P[ref]
        else:
            x, y, rot = park_x, 5 + (i % 40) * 2.5, 0
            print("unplaced (parked):", ref)
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)
        board.Add(fp)
        fps[ref] = fp

    pad_index = {}
    for ref, fp in fps.items():
        for pad in fp.Pads():
            pad_index.setdefault((ref, pad.GetNumber()), []).append(pad)
    missing = 0
    for name, nodes in nets:
        for ref, pin in nodes:
            pads = pad_index.get((ref, pin))
            if not pads:
                missing += 1
                print("no pad for", ref, pin)
                continue
            for pad in pads:
                pad.SetNet(netinfo[name])
    print("nets assigned; missing pads:", missing)

    # bottom-side fingers (B.Cu): a locked stub straight up into the body and a via, so no finger
    # can be sealed off by its neighbours' tracks (attempt 1 left B4 (+5V) and B13 (A3) unconnected).
    # +5V gets a wide stub and two vias into the In2 plane; GND fingers drop straight into In1.
    finger_top = BODY_H - 0.325
    for pad in fps["P1"].Pads():
        if not pad.GetNumber().startswith("B") or not pad.GetNetname() or pad.GetNetname().startswith("unconnected"):
            continue
        x = pcbnew.ToMM(pad.GetPosition().x)
        net = pad.GetNet()
        power = pad.GetNetname() == "+5V"
        vias = [(x - 0.5, 54.0), (x + 0.5, 53.0)] if power else [(x, 54.3)]
        for vx, vy in vias:
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(mm(x, finger_top + 0.5)); t.SetEnd(mm(vx, vy))
            t.SetWidth(pcbnew.FromMM(0.5 if power else 0.25)); t.SetLayer(pcbnew.B_Cu); t.SetNet(net); t.SetLocked(True)
            board.Add(t)
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(mm(vx, vy)); v.SetWidth(pcbnew.FromMM(0.6)); v.SetDrill(pcbnew.FromMM(0.3)); v.SetNet(net); v.SetLocked(True)
            board.Add(v)

    # fiducials: the router does not see their 0.6 mm pad clearance, so give each a keepout square
    for fp in board.GetFootprints():
        if not fp.GetReference().startswith("FID"):
            continue
        cx, cy = pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)
        ko = pcbnew.ZONE(board)
        ko.SetIsRuleArea(True); ko.SetDoNotAllowTracks(True); ko.SetDoNotAllowVias(True)
        ko.SetDoNotAllowPads(False); ko.SetDoNotAllowFootprints(False); ko.SetDoNotAllowZoneFills(False)
        ko.SetLayer(pcbnew.F_Cu); ko.SetZoneName(fp.GetReference() + "_keepout")
        kop = ko.Outline(); kop.NewOutline()
        for x, y in ((cx - 1.3, cy - 1.3), (cx + 1.3, cy - 1.3), (cx + 1.3, cy + 1.3), (cx - 1.3, cy + 1.3)):
            kop.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        board.Add(ko)

    # planes: GND on In1.Cu, +5V on In2.Cu (almost every IC is on 5 V; +3V3 is a handful of tracks)
    body_h = BODY_H
    for layer, netname in ((pcbnew.In1_Cu, "GND"), (pcbnew.In2_Cu, "+5V")):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(netinfo[netname])
        z.SetZoneName(netname + "_plane")
        outline = z.Outline()
        outline.NewOutline()
        for x, y in ((0.5, 0.5), (129.5, 0.5), (129.5, body_h - 0.5), (101.6, body_h - 0.5), (101.6, body_h + 7.5),
                     (35.2, body_h + 7.5), (35.2, body_h - 0.5), (32.2, body_h - 0.5), (32.2, body_h + 7.5),
                     (19.0, body_h + 7.5), (19.0, body_h - 0.5), (0.5, body_h - 0.5)):
            outline.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        z.SetLocalClearance(pcbnew.FromMM(0.25))
        z.SetMinThickness(pcbnew.FromMM(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        board.Add(z)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

    pcbnew.SaveBoard(PCB, board)
    print("saved", PCB, "footprints:", len(board.GetFootprints()), "nets:", board.GetNetCount())


if __name__ == "__main__":
    main()
