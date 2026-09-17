#!/usr/bin/env python3
"""Build the placed (unrouted) board from the schematic netlist.

Run with KiCad's bundled Python (it has the pcbnew module):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/gen_layout.py

Steps: regenerate the skeleton (outline, edge connector, holes, fiducials) with
gen_board.py, export the netlist with kicad-cli, load every footprint from the
KiCad or project library, assign nets, place parts per PLACEMENT below, add
GND (In1.Cu) and +3V3 (In2.Cu) zones, save tspico-v3.kicad_pcb.

Coordinates: mm, board origin at the top-left corner of the body, y down.
Body 130 x 56; tongue below y = 56 between x = 18.48 and 102.14.
Rotation: degrees counter-clockwise as in KiCad.
"""
import os
import re
import subprocess
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DMA_OPTION  # noqa: E402

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


BODY_H = 56.0
R3Y, R2Y = BODY_H - 5.5, BODY_H - 13.5      # transceiver row, glue/DMA row

# Body is 130 x 56 mm (tongue below). Left edge: ESP32 antenna (top corner), USB-C,
# micro SD (shell flush with the edge). Right edge: audio jack, DE-9.
# Row 3, nearest the fingers: data U3 (fingers x 29-52, top copper), high address byte U2
# directly over its fingers A15-A8 (x 54-72, bottom copper), control U4 (x 54-92).
# Row 2: low address byte U1 above U2; its fingers are split (A0-A3 at x 44-52, A7-A4 at
# x 74-82) and come in from both sides on the bottom layer. Then strobes U6, drivers U7.
P["U3"], P["C3"] = (40, R3Y, 270 if DMA_OPTION else 90), (48, R3Y, 90)      # without the DMA option U3's A side is the Z80 side
P["U2"], P["C2"] = (63, R3Y, 270), (69, R3Y, 90)
P["U4"], P["C4"] = (92, R3Y, 270), (100, R3Y, 90)
P["U1"], P["C1"] = (63, R2Y, 270), (68.4, R2Y, 90)
P["U6"], P["C5"] = (76, R2Y, 270), (80.1, R2Y, 90)
P["U7"], P["C6"] = (87, R2Y, 270), (93.8, R2Y - 1.5, 90)
P["R1"] = (93.8, R2Y + 3.2, 0)
P["U9"], P["R4"] = (32, R2Y + 4, 0), (32, R2Y + 1, 0)
P["R9"], P["R10"] = (94.6, 37.2, 0), (94.6, 34.6, 0)          # BUSRQ / NMI_REQ pull-downs by U7 and the expander
# I2C expander and the joystick network beside the DE-9
P["U15"], P["C10"] = (101, 41.5, 0), (106.4, 35.8, 0)
P["R6"], P["R7"], P["R8"] = (109.8, 35.8, 0), (113.2, 35.8, 0), (101, 35.8, 0)
for i, (rs, rp, c) in enumerate(zip(["R90", "R91", "R92", "R93", "R94", "R95"],
                                    ["R96", "R97", "R98", "R99", "R100", "R101"],
                                    ["C90", "C91", "C92", "C93", "C94", "C95"])):
    x = 106.6 + 2.0 * i
    P[rs], P[rp], P[c] = (x, 38.7, 90), (x, 41.7, 90), (x, 44.7, 90)
P["JP10"] = (105.5, 50.2, 0)
# RP2350B core, rotated so GPIO0-7 (MD bus) sit at the bottom-left corner, the
# control GPIOs along the bottom, QSPI/USB/regulator on the left, crystal on the right
P["U20"] = (62, 26, 90)
# core regulator, copied from the design guide's figure 4 (rotated): VIN cap C22 and
# output cap C20 straddle the VREG_LX pin so LX runs under them to L1; AVDD filter above
P["C22"], P["C20"], P["L1"] = (55.25, 22.8, 90), (54.05, 22.8, 90), (52.25, 22.8, 270)
P["C39"], P["R28"] = (55.1, 21.2, 180), (55.6, 19.2, 270)
# crystal 6.5 mm from XIN/XOUT (leaving a via ring for the neighbouring pins), series resistor between chip and crystal, load caps at the pads
P["Y1"], P["R20"], P["C35"], P["C36"] = (75.5, 26.0, 0), (71.7, 25.2, 0), (74.4, 29.3, 270), (76.6, 22.7, 90)
# decoupling: left 68/69, 76; bottom 5, DVDD 10, 15; right 29, 24, DVDD 32; top 41, 50, DVDD 51, 59/60
P["C23"], P["C24"] = (51.2, 26.4, 0), (51.2, 29.4, 0)
P["C25"], P["C48"], P["C26"] = (57.6, 37.0, 270), (61.35, 37.0, 270), (66.0, 37.0, 270)      # under the fan vias of pins 5, 10 (DVDD) and 15
P["C28"], P["C29"], P["C47"] = (69.4, 30.6, 0), (72.6, 33.0, 0), (70.6, 19.8, 0)
P["C27"], P["C30"], P["C21"], P["C31"] = (67.4, 17.4, 90), (64.2, 14.0, 0), (62.3, 18.2, 90), (57.4, 16.4, 0)     # C21 straight above DVDD pin 51 (pin 50 beside it connects under the package, so its lane is free)
P["U21"], P["C37"], P["R21"] = (44, 20, 0), (38, 20, 90), (38, 25, 0)
P["U22"], P["C38"] = (44, 30, 0), (38, 30, 90)
P["R27"], P["R26"] = (47.6, 24.0, 0), (47.6, 26.0, 0)          # USB series resistors on the way out to J1
P["TP1"], P["TP2"], P["TP3"] = (6, 45.8, 0), (9.5, 45.8, 0), (13, 45.8, 0)
P["R2"], P["R3"] = (20, 47.5, 0), (23.5, 47.5, 0)
# top edge: ESP32-C3 (antenna over the edge), WiFi bulk cap, LED, buttons on 0.5 in centres, OLED header
P["U40"] = (20, 8, 0)
P["C46"] = (35.5, 9, 0)
P["C60"], P["C61"], P["R40"], P["R41"], P["R12"], P["R13"] = (34, 19, 0), (34, 22, 0), (34, 25, 0), (34, 28, 0), (34, 31, 0), (34, 34, 0)
P["D4"], P["R5"] = (43.5, 8, 0), (43.5, 11, 0)
row(["SW1", "SW2", "SW3", "SW4"], 47, 4, 12.7, 0)
P["R22"], P["R23"] = (72, 9.5, 0), (78.5, 9.5, 0)
P["J3"], P["R11"] = (93, 4, 90), (112.6, 9.5, 90)
# left edge: USB-C below the ESP32, micro SD below that (both open to the left)
P["J1"] = (3.2, 21, 270)
P["R24"], P["R25"] = (12, 21, 0), (15, 21, 0)
P["J2"] = (9.58, 35.5, 270)    # TF-01A: shell front 9.576 mm from the origin, so the shell is flush with the board edge
for i, r in enumerate(["R30", "R31", "R32", "R33", "R34"]):
    P[r] = (23.5, 27 + 2.5 * i, 0)
for i, r in enumerate(["R35", "R36", "R37", "R38", "R39"]):
    P[r] = (27, 27 + 2.5 * i, 0)
P["C50"], P["C51"] = (30.5, 30, 0), (30.5, 34, 0)
# power block, top right below the OLED header
P["D2"], P["D3"] = (84, 11, 0), (84, 15.5, 0)
P["C40"], P["C41"] = (93.5, 13.5, 0), (104, 13.5, 0)
P["U30"], P["C42"], P["C43"] = (88, 23.5, 0), (81.6, 21, 90), (81.6, 25.5, 90)
P["U31"], P["C44"], P["C45"] = (88, 32.5, 0), (81.6, 30, 90), (81.6, 34.5, 90)
# right edge: audio jack in the corner (opening to the right), DE-9 below it
P["J4"] = (123.7, 7, 180)
P["J5"] = (122.3, 34, 90)
# audio: op-amp, passives in signal order in three rows
P["U50"], P["C79"] = (99, 22.5, 0), (104.6, 21, 0)
for i, r in enumerate(["R71", "C71", "R72", "C72", "R73", "R74"]):
    P[r] = (94 + 3.4 * i, 27.4, 0)
for i, r in enumerate(["R75", "C75", "R76", "C76", "R77", "R78"]):
    P[r] = (94 + 3.4 * i, 30.1, 0)
for i, r in enumerate(["C70", "R70", "C80", "R80", "C81", "R81"]):
    P[r] = (94 + 3.4 * i, 32.8, 0)

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

    # the stock ESP32-C3-WROOM-02 footprint has 0.2 mm thermal vias; 0.3 mm keeps the board on JLCPCB's standard drill list
    for pad in fps["U40"].Pads():
        if 0 < pad.GetDrillSize().x < pcbnew.FromMM(0.3):
            pad.SetDrillSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.3), pcbnew.FromMM(0.3)))
            if pad.GetSize().x < pcbnew.FromMM(0.6):
                pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.6), pcbnew.FromMM(0.6)))

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

    # zones: GND on In1.Cu, +3V3 on In2.Cu, covering the body and the tongue
    body_h = BODY_H
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
