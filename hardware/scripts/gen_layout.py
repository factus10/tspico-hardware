#!/usr/bin/env python3
"""Build the placed (unrouted) board from the schematic netlist.

Run with KiCad's bundled Python (it has the pcbnew module):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/gen_layout.py

Steps: regenerate the skeleton (outline, edge connector, holes, fiducials) with
gen_board.py, export the netlist with kicad-cli, load every footprint from the
KiCad or project library, assign nets, place parts per PLACEMENT below, add
GND (In1.Cu) and +3V3 (In2.Cu) zones, save tspico-v3.kicad_pcb.

Coordinates: mm, board origin at the top-left corner of the body, y down.
Body 130 x 91.75; tongue below y = 91.75 between x = 18.48 and 102.14.
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
PCB = os.path.join(HW, "tspico-v3.kicad_pcb")
NET = "/tmp/tspico-v3.net"

# ---------------------------------------------------------------------------
# Placement: ref -> (x, y, rot). Anything not listed is parked off-board.
# ---------------------------------------------------------------------------
P = {}


def row(refs, x0, y, dx, rot=0):
    for i, r in enumerate(refs):
        P[r] = (x0 + i * dx, y, rot)


# Z80 transceivers above the fingers, B side (Z80) facing the connector
row(["U1", "U2", "U3", "U4"], 30, 83, 18, 270)
row(["C1", "C2", "C3", "C4"], 38, 83, 18, 90)
# gating, open-drain, DMA drivers, XOR, address muxes
row(["U5", "U6", "U7", "U8"], 25, 73, 12, 270)
P["U9"] = (73, 73, 0)
row(["C5", "C6", "C7", "C8"], 31, 73, 12, 90)
row(["U10", "U11"], 84, 73, 12, 270)
row(["C10", "C11"], 90, 73, 12, 90)
# registers, power-on-reset parts to the right of them
row(["U12", "U13", "U14", "U15", "U16"], 24, 63, 16, 270)
row(["C12", "C13", "C14", "C15", "C16"], 31, 63, 16, 90)
P["R4"], P["C9"], P["D1"] = (96, 78, 0), (99.5, 78, 0), (104, 78, 0)
# RP2350B core
P["U20"] = (62, 38, 0)
for i, r in enumerate(["C23", "C24", "C25", "C26", "C27"]):
    P[r] = (52.5, 31 + 3.5 * i, 0)
for i, r in enumerate(["C28", "C29", "C30", "C31", "C32"]):
    P[r] = (71.5, 31 + 3.5 * i, 0)
P["C33"], P["C34"] = (58, 29, 90), (66, 29, 90)
row(["L1", "C20", "C21", "C22"], 54, 48, 4.5, 0)
P["Y1"], P["C35"], P["C36"], P["R20"] = (76, 45, 0), (72.5, 49, 0), (79.5, 49, 0), (76, 41, 90)
P["U21"], P["C37"], P["R21"] = (46, 24, 0), (46, 19, 90), (39, 24, 0)
P["U22"], P["C38"] = (80, 24, 0), (80, 19, 90)
row(["TP1", "TP2", "TP3"], 74, 52, 3.5, 0)
# switches along the top edge on 0.5 in centres: TS Reset, NMI, RUN, BOOTSEL
row(["SW1", "SW2", "SW3", "SW4"], 45, 4, 12.7, 0)
P["R22"], P["R23"] = (70.4, 9.5, 0), (83.1, 9.5, 0)
# ESP32-C3 module top-left, antenna over the edge; its caps below it
P["U40"] = (20, 8, 0)
P["C60"], P["C61"], P["R40"] = (12, 19, 0), (16, 19, 0), (20, 19, 0)
# OLED header at the top edge, right of the switches; LED beside it
P["J3"] = (93, 4, 90)
P["D4"], P["R5"] = (112, 9, 0), (116, 9, 0)
# power block below the header
P["D2"], P["D3"] = (96, 12, 0), (96, 17, 0)
P["C40"], P["C41"] = (105.5, 14, 0), (115.5, 14, 0)
P["U30"], P["C42"], P["C43"] = (95, 23, 0), (88.5, 23, 0), (101.5, 23, 0)
P["U31"], P["C44"], P["C45"], P["C46"] = (95, 31, 0), (88.5, 31, 0), (101.5, 31, 0), (92, 39.5, 0)
# right edge, top to bottom: USB-C, micro SD, 3.5 mm jack, DE-9
P["J1"] = (126.8, 15, 90)
row(["R24", "R25", "R26", "R27"], 112, 22, 3, 0)
P["J2"] = (117.2, 33, 90)
for i, r in enumerate(["R30", "R31", "R32", "R33", "R34"]):
    P[r] = (98 + 3 * i, 43, 0)
for i, r in enumerate(["R35", "R36", "R37", "R38", "R39"]):
    P[r] = (98 + 3 * i, 45.5, 0)
P["C50"], P["C51"] = (98, 48, 0), (101.5, 48, 0)
P["J4"] = (121.9, 48, 270)
P["J5"] = (122.3, 66, 90)
# audio in signal order: row L, row R, then common/output parts; op-amp to their left
P["U50"], P["C79"] = (88, 55, 0), (86, 51, 0)
for i, r in enumerate(["R71", "C71", "R72", "C72", "R73", "R74"]):
    P[r] = (94 + 3.4 * i, 52, 0)
for i, r in enumerate(["R75", "C75", "R76", "C76", "R77", "R78"]):
    P[r] = (94 + 3.4 * i, 55.5, 0)
for i, r in enumerate(["C70", "R70", "C80", "R80", "C81", "R81"]):
    P[r] = (94 + 3.4 * i, 59, 0)
# joystick: one row per line (series R, pull-up, cap) beside the DE-9 pins
for i, (rs, rp, c) in enumerate(zip(["R90", "R91", "R92", "R93", "R94", "R95"],
                                    ["R96", "R97", "R98", "R99", "R100", "R101"],
                                    ["C90", "C91", "C92", "C93", "C94", "C95"])):
    P[rs], P[rp], P[c] = (106, 62 + 2.5 * i, 0), (110, 62 + 2.5 * i, 0), (114, 62 + 2.5 * i, 0)
P["JP10"] = (110, 78, 0)
# misc interface passives in the left margin
P["R1"], P["R2"], P["R3"] = (10, 84, 0), (10, 79, 0), (10, 74, 0)

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
        comps[ref] = {"value": first(c, "value")[1], "footprint": (first(c, "footprint") or ["", ""])[1]}
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
    subprocess.run([sys.executable if "KiCad" not in sys.executable else "python3", os.path.join(HERE, "gen_board.py")], check=True)
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "--output", NET,
                    os.path.join(HW, "tspico-v3.kicad_sch")], check=True)
    comps, nets = load_netlist(NET)
    board = pcbnew.LoadBoard(PCB)

    # nets
    netinfo = {}
    for name, _ in nets:
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni

    # footprints (P1 already exists in the skeleton)
    fps = {}
    for fp in board.GetFootprints():
        fps[fp.GetReference()] = fp
    park_x = 140.0
    for i, (ref, c) in enumerate(sorted(comps.items())):
        if ref.startswith("#"):
            continue
        if ref in fps:
            continue
        fp = load_footprint(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        if ref in P:
            x, y, rot = P[ref]
        else:
            x, y, rot = park_x, 5 + (i % 40) * 2.5, 0
            print("unplaced (parked):", ref)
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)
        board.Add(fp)
        fps[ref] = fp

    # pad nets
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

    # zones: GND on In1.Cu, +3V3 on In2.Cu, covering the body
    body_h = 91.75
    for layer, netname in ((pcbnew.In1_Cu, "GND"), (pcbnew.In2_Cu, "+3V3")):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(netinfo[netname])
        z.SetZoneName(netname + "_plane")
        outline = z.Outline()
        outline.NewOutline()
        for x, y in ((0.5, 0.5), (129.5, 0.5), (129.5, body_h - 0.5), (0.5, body_h - 0.5)):
            outline.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        z.SetLocalClearance(pcbnew.FromMM(0.25))
        z.SetMinThickness(pcbnew.FromMM(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        board.Add(z)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    pcbnew.SaveBoard(PCB, board)
    print("saved", PCB, "footprints:", len(board.GetFootprints()), "nets:", board.GetNetCount())


if __name__ == "__main__":
    main()
