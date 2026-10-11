#!/usr/bin/env python3
"""Build the placed (unrouted) v2.6 board from the schematic netlist.

Run with KiCad's bundled Python (it has the pcbnew module):
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/gen_layout.py

Steps: regenerate the skeleton (outline, edge connector, holes, fiducials) with
gen_board.py, export the netlist with kicad-cli, load every footprint from the
KiCad or project library, assign nets, place parts per P below, add the GND
(In1.Cu) and +5V (In2.Cu) planes, save tspico-v2.6.kicad_pcb.
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
PCB = os.path.join(HW, "tspico-v2.6.kicad_pcb")
NET = "/tmp/tspico-v2.6.net"
BODY_H = 56.0

# ---------------------------------------------------------------------------
# Placement: ref -> (x, y, rot). Anything not listed is parked off-board.
# ---------------------------------------------------------------------------
P = {}

# Pico along the top-left, USB out of the left edge. Rotated 90: pins 1-20 (GP0-GP15: data
# bus and Z80 control inputs) run left to right along the bottom row at y = 28.2, pins
# 21-40 (GP16-GP28, power) right to left along the top row at y = 8.8.
# RP2040 block in the top-left corner (where v2.5's Pico was). Rotated 90: GP0-GP11 face down
# toward the glue logic, QSPI and USB on the left toward the flash and the USB-C socket, the
# crystal on the right, GP18-GP29 along the top.
P["U2"] = (24.0, 19.5, 90)
# IOVDD pins 1, 10 (bottom row) and 33, 42 (top row): each cap stands on its own pin's lane, +3V3 pad
# nearest the chip, so it blocks no neighbour's escape; the pin-to-cap stub is a locked pre-route (below)
P["C21"], P["C22"] = (21.4, 25.4, 270), (25.0, 25.4, 270)
P["C23"], P["C30"] = (29.8, 23.0, 90), (29.8, 16.6, 90)          # IOVDD 22, DVDD 23 (right side)
P["C24"], P["C25"] = (25.0, 13.6, 90), (21.4, 13.6, 90)
P["C26"], P["C27"] = (18.0, 22.6, 90), (18.0, 16.4, 90)          # IOVDD 49 / USB_VDD, ADC_AVDD (left side)
P["C28"], P["C29"], P["C31"] = (16.1, 16.4, 90), (16.1, 19.5, 90), (18.0, 19.5, 90)   # VREG_VIN, VREG_VOUT, DVDD 50
P["Y1"], P["R25"], P["C33"], P["C34"] = (34.6, 19.5, 0), (31.6, 20.2, 90), (34.6, 16.6, 0), (34.6, 22.4, 0)
P["U21"], P["C32"], P["R24"] = (11.0, 24.6, 0), (11.0, 28.9, 0), (6.6, 28.9, 0)
P["J1"] = (3.2, 14.6, 270)                                       # USB-C out of the left edge
P["R26"], P["R27"] = (10.6, 9.6, 0), (10.6, 11.4, 0)                # CC pull-downs
P["R28"], P["R29"] = (12.6, 15.2, 0), (12.6, 17.0, 0)             # USB series
P["D5"], P["R34"] = (31.6, 10.2, 0), (31.6, 12.4, 0)              # GP25 LED
P["R30"], P["R31"], P["R32"], P["R33"] = (35.4, 10.2, 0), (35.4, 12.0, 0), (35.4, 25.4, 0), (35.4, 27.2, 0)
P["TP1"], P["TP2"], P["TP3"] = (24.5, 29.0, 0), (27.0, 29.0, 0), (29.5, 29.0, 0)
# top strip: BOOTSEL, the regulator and power diodes, the 3.3 V pull-ups, then the three buttons
P["SW4"] = (12.5, 4.0, 0)
P["U22"], P["C35"], P["C2"] = (21.8, 5.4, 90), (27.4, 6.2, 0), (27.4, 2.0, 0)
P["D2"], P["D4"] = (33.0, 2.0, 0), (33.0, 5.6, 0)
P["R9"], P["R15"], P["R16"] = (38.0, 2.4, 90), (40.3, 2.4, 90), (42.6, 2.4, 90)
P["SW1"], P["SW2"], P["SW3"] = (58.0, 4.5, 0), (74.0, 4.5, 0), (90.0, 4.5, 0)
P["C15"] = (52.6, 6.6, 0)
P["JP2"], P["JP3"], P["JP5"] = (66.0, 4.5, 90), (82.0, 4.5, 90), (98.0, 4.5, 90)
# memories: DIP-32 sockets lying along the board, SRAM left, flash right, centred on y = 18.7.
# The DIP footprint's origin is pin 1; rotated 90, pins 1-16 run right along y = origin and
# pins 17-32 come back 15.24 mm above, so the origin is the centre less (19.05, -7.62).
def dip(cx, cy):
    return (cx - 19.05, cy + 7.62, 90)


P["U13"], P["C13"] = dip(61.8, 18.7), (61.8, 29.6, 0)
P["U10"], P["C10"] = dip(106.8, 18.7), (106.8, 29.6, 0)
P["R6"], P["P10"] = (88.0, 30.8, 0), (92.0, 30.8, 0)
# micro SD on the left edge below the MCU block (shell flush with the edge)
P["U3"] = (9.58, 39.8, 270)
P["R22"], P["R23"], P["C3"], P["C18"] = (19.8, 34.0, 0), (19.8, 35.8, 0), (19.8, 37.6, 0), (19.8, 39.8, 0)
# glue row, decoupling caps above each package
ROW1 = 38.8
# glue row (prototype 2, 74LVC): port decode U5 and its jumper, the OR gates U4, /MREQ_G U1, the /BE
# driver U9 with its pull-ups and link, the A14/A15 mux U8, then U7 into the Pico; caps above each
P["U5"], P["C5"] = (28.0, ROW1, 0), (28.0, ROW1 - 5.0, 0)
P["JP4"] = (33.6, ROW1, 90)
P["U4"], P["C4"] = (39.5, ROW1, 0), (39.5, ROW1 - 5.0, 0)
P["U1"], P["C1"] = (46.0, ROW1, 0), (46.0, ROW1 - 4.0, 0)
P["U9"], P["C14"] = (51.5, ROW1, 0), (51.5, ROW1 - 4.0, 0)
P["R8"], P["R3"], P["JP1"] = (52.6, ROW1 + 4.6, 90), (55.2, ROW1 + 4.6, 90), (58.4, ROW1 + 4.6, 90)
P["U8"], P["C8"] = (62.0, ROW1, 0), (62.0, ROW1 - 5.0, 0)
P["U7"], P["C6"] = (72.0, ROW1, 0), (72.0, ROW1 - 5.8, 0)
# power-on reset supervisor on the right, below the flash socket
P["U11"] = (108.0, 37.5, 0)
P["R1"], P["R5"], P["C12"], P["C9"] = (103.5, 42.0, 90), (106.0, 42.0, 90), (108.5, 42.0, 90), (111.0, 42.0, 90)
P["C16"] = (120.0, 42.0, 90)
# data path over the data fingers
ROW2 = 49.6
P["U6"], P["C7"] = (44.0, ROW2, 0), (48.8, ROW2 - 3.6, 90)
P["R12"] = (39.0, ROW2 - 4.6, 0)          # D6 pull-down, by U6 pin 8

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
                    os.path.join(HW, "tspico-v2.6.kicad_sch")], check=True)
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

    # RP2040 IOVDD pins on the top and bottom rows: a locked straight stub to the cap on the same lane.
    # Without it the router twice left one of these pins (or a neighbour) sealed in (proto2 attempts 1-3).
    for pin, cap in (("1", "C21"), ("10", "C22"), ("33", "C24"), ("42", "C25")):
        a = [q for q in fps["U2"].Pads() if q.GetNumber() == pin][0]
        c = [q for q in fps[cap].Pads() if q.GetNumber() == "1"][0]
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(a.GetPosition()); t.SetEnd(c.GetPosition())
        t.SetWidth(pcbnew.FromMM(0.2)); t.SetLayer(pcbnew.F_Cu); t.SetNet(a.GetNet()); t.SetLocked(True)
        board.Add(t)

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
