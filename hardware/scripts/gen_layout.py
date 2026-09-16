#!/usr/bin/env python3
"""Build the placed (unrouted) board from the schematic netlist.

Run with KiCad's bundled Python (it has the pcbnew module):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/gen_layout.py

Steps: regenerate the skeleton (outline, edge connector, holes, fiducials) with
gen_board.py, export the netlist with kicad-cli, load every footprint from the
KiCad or project library, assign nets, place parts per PLACEMENT below, add
GND (In1.Cu) and +3V3 (In2.Cu) zones, save tspico-v3.kicad_pcb.

Coordinates: mm, board origin at the top-left corner of the body, y down.
Body 130 x 64; tongue below y = 64 between x = 18.48 and 102.14.
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


# Body is 130 x 64 mm (tongue below y = 64). Rows above the fingers at 8 mm pitch.
# Left edge: ESP32 antenna (top corner), USB-C, micro SD. Right edge: audio jack, DE-9.
# Row 3 (y 58.5): transceivers in finger order: data (fingers x 29-52), address low
# (44-62), address high (64-82), control (54-92). Bit order inside each is set in the schematic.
P["U3"], P["C3"] = (40, 58.5, 270), (48, 58.5, 90)
P["U1"], P["C1"] = (56, 58.5, 270), (64, 58.5, 90)
P["U2"], P["C2"] = (74, 58.5, 270), (82, 58.5, 90)
P["U4"], P["C4"] = (92, 58.5, 270), (100, 58.5, 90)
# Row 2 (y 50.5): XOR, DMA drivers, inverters, ANDs, open-drain drivers
P["U9"] = (30, 50.5, 0)
row(["U8", "U5", "U6", "U7"], 42, 50.5, 12, 270)
row(["C8", "C5", "C6", "C7"], 48, 50.5, 12, 90)
# Row 1 (y 42.5): address muxes and the registers, the MD bus block
row(["U10", "U11", "U12", "U13", "U14", "U15", "U16"], 26, 42.5, 12, 270)
row(["C10", "C11", "C12", "C13", "C14", "C15", "C16"], 32.5, 42.5, 12, 90)
P["R4"], P["C9"], P["D1"] = (98, 62, 0), (101.5, 62, 0), (105.5, 62, 0)
P["JP10"] = (85, 62.5, 0)
# RP2350B core, rotated so GPIO0-7 (MD bus) sit at the bottom-left corner, the
# control GPIOs along the bottom, QSPI/USB on the left, crystal on the right
P["U20"] = (62, 26, 90)
for i, r in enumerate(["C23", "C24", "C25"]):
    P[r] = (51.5, 20 + 4 * i, 0)          # thinner left column: room for the QSPI/USB/MD escapes
P["C26"], P["C27"] = (57, 33.5, 90), (67, 33.5, 90)   # under the bottom edge, where IOVDD pins 5 and 15 are
for i, r in enumerate(["C28", "C29", "C30", "C31", "C32"]):
    P[r] = (71.5, 19 + 3.5 * i, 0)
P["C33"], P["C34"] = (58, 17, 90), (66, 17, 90)
row(["L1", "C20", "C21", "C22"], 52, 37, 4.5, 0)
P["Y1"], P["C35"], P["C36"], P["R20"] = (77, 26, 0), (77, 21.5, 0), (77, 30.5, 0), (81, 26, 90)
P["U21"], P["C37"], P["R21"] = (44, 20, 0), (38, 20, 90), (38, 25, 0)
P["U22"], P["C38"] = (44, 30, 0), (38, 30, 90)
P["TP1"], P["TP2"], P["TP3"] = (6, 46, 0), (9.5, 46, 0), (13, 46, 0)
# top edge: ESP32-C3 (antenna over the edge), LED, buttons on 0.5 in centres, OLED header
P["U40"] = (20, 8, 0)
P["C60"], P["C61"], P["R40"] = (34, 19, 0), (34, 23, 0), (34, 27, 0)
P["D4"], P["R5"] = (37, 8, 0), (37, 12, 0)
row(["SW1", "SW2", "SW3", "SW4"], 50, 4, 12.7, 0)
P["R22"], P["R23"] = (72, 9.5, 0), (92, 9, 0)
P["J3"] = (95, 4, 90)
# left edge: USB-C below the ESP32, micro SD below that (both open to the left)
P["J1"] = (3.2, 21, 270)
row(["R24", "R25", "R26", "R27"], 12, 21, 3, 0)
P["J2"] = (8.75, 35, 270)      # shell 0.35 mm inside the edge: its front shield tabs need 0.3 mm copper-to-edge (fab outline includes the card)
for i, r in enumerate(["R30", "R31", "R32", "R33", "R34"]):
    P[r] = (23.5, 27 + 2.5 * i, 0)
for i, r in enumerate(["R35", "R36", "R37", "R38", "R39"]):
    P[r] = (27, 27 + 2.5 * i, 0)
P["C50"], P["C51"] = (30.5, 30, 0), (30.5, 34, 0)
# power block, top right, below the OLED header; LDOs right of the crystal
P["D2"], P["D3"] = (98, 12, 0), (98, 17, 0)
P["C40"], P["C41"] = (106.5, 14, 0), (117, 14, 0)
P["U30"], P["C42"], P["C43"] = (86.5, 23, 0), (82, 15, 0), (91, 15, 0)
P["U31"], P["C44"], P["C45"], P["C46"] = (86.5, 31, 0), (82, 36, 0), (91, 36, 0), (107.5, 23, 0)
# right edge: audio jack, then the DE-9 (face 7.7 mm beyond the pin-1 row)
P["J4"] = (121.9, 24, 270)
P["J5"] = (122.3, 41, 90)
# audio: op-amp below the power caps, passives in signal order in three rows of six
P["U50"], P["C79"] = (99.5, 27, 0), (105, 28, 0)
for i, r in enumerate(["R71", "C71", "R72", "C72", "R73", "R74"]):
    P[r] = (97 + 3.4 * i, 32, 0)
for i, r in enumerate(["R75", "C75", "R76", "C76", "R77", "R78"]):
    P[r] = (97 + 3.4 * i, 35, 0)
for i, r in enumerate(["C70", "R70", "C80", "R80", "C81"]):
    P[r] = (103 + 3.4 * i, 38, 0)
P["R81"] = (92, 38.5, 0)
# joystick: one row per line beside the DE-9 pins
for i, (rs, rp, c) in enumerate(zip(["R90", "R91", "R92", "R93", "R94", "R95"],
                                    ["R96", "R97", "R98", "R99", "R100", "R101"],
                                    ["C90", "C91", "C92", "C93", "C94", "C95"])):
    P[rs], P[rp], P[c] = (108, 45.5 + 2.5 * i, 0), (112, 45.5 + 2.5 * i, 0), (116, 45.5 + 2.5 * i, 0)
# misc interface passives in the left margin below the SD
P["R1"], P["R2"], P["R3"] = (10, 59, 0), (10, 55, 0), (10, 51, 0)

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

    # keepout: no tracks or vias on B.Cu under the RP2350B, as four rectangles
    # around a 4 x 4 mm centre window that leaves the thermal-pad via legal
    # (Freerouting crashes on KiCad's tracks-only "wire_keepout", so this is a full keepout)
    ux, uy = P["U20"][0], P["U20"][1]
    # only the chip body (10 x 10 mm): the 0.4 mm QFN needs vias in its fanout ring
    for name, (x0, y0, x1, y1) in {"L": (-5.3, -5.3, -2.0, 5.3), "R": (2.0, -5.3, 5.3, 5.3),
                                   "T": (-2.0, -5.3, 2.0, -2.0), "B": (-2.0, 2.0, 2.0, 5.3)}.items():
        ko = pcbnew.ZONE(board)
        ko.SetIsRuleArea(True)
        ko.SetDoNotAllowTracks(True)
        ko.SetDoNotAllowVias(True)
        ko.SetLayer(pcbnew.B_Cu)
        ko.SetZoneName("U20_keepout_B_" + name)
        kop = ko.Outline()
        kop.NewOutline()
        for x, y in ((ux + x0, uy + y0), (ux + x1, uy + y0), (ux + x1, uy + y1), (ux + x0, uy + y1)):
            kop.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        board.Add(ko)

    # zones: GND on In1.Cu, +3V3 on In2.Cu, covering the body and the tongue
    body_h = 64.0
    for layer, netname in ((pcbnew.In1_Cu, "GND"), (pcbnew.In2_Cu, "+3V3")):
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
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    pcbnew.SaveBoard(PCB, board)
    print("saved", PCB, "footprints:", len(board.GetFootprints()), "nets:", board.GetNetCount())


if __name__ == "__main__":
    main()
