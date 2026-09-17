#!/usr/bin/env python3
"""Autoroute the placed board with Freerouting, headless.

Run with KiCad's bundled Python:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 scripts/autoroute.py [--passes N] [--jar PATH]

Steps: export a Specctra DSN from tspico-v3.kicad_pcb, run Freerouting
(needs a Java runtime; jar path via --jar or FREEROUTING_JAR), import the
session file back into the board, save, and run kicad-cli DRC.
Existing tracks and vias are kept unless --fresh is given, which strips
them first so the router starts from the bare placement.
"""
import argparse
import os
import subprocess
import sys

import pcbnew

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(HW, "tspico-v3.kicad_pcb")
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
JAVA = "/opt/homebrew/opt/openjdk/bin/java"


PLANE_NETS = {"GND": pcbnew.In1_Cu, "+3V3": pcbnew.In2_Cu}


def _seg_dist(a, b, p):
    """Distance from point p to segment a-b (all VECTOR2I), in internal units."""
    ax, ay, bx, by, px, py = a.x, a.y, b.x, b.y, p.x, p.y
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    qx, qy = ax + t * dx, ay + t * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


def plane_fanout(board):
    """Freerouting treats the GND/+3V3 zones as planes and leaves their SMD pads
    alone. Give every such pad that is not already wired a short stub to a via,
    clearance-checked against pads, tracks, vias and keepouts (finish_route.Board).
    Pads with no legal spot are left for the router or the hand finish."""
    from finish_route import Board
    B = Board(PCB, board)
    added, skipped = 0, []
    for fp in board.GetFootprints():
        fc = fp.GetPosition()
        pads = list(fp.Pads())
        if len(pads) > 60:        # the 0.4 mm pitch QFN: a via 0.9 mm out of a supply pin blocks both neighbours' lanes; leave
            # those to the pre-routes and the router. Its exposed pad still gets its ground vias (five, inside the keepout's centre window).
            for pad in pads:
                bb = pad.GetBoundingBox()
                if pad.GetNetname() == "GND" and min(bb.GetWidth(), bb.GetHeight()) >= pcbnew.FromMM(3.0):
                    cx, cy = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
                    for dx, dy in ((0, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
                        if B.via_ok(cx + dx, cy + dy, pad.GetNetCode()):
                            B.add_via(cx + dx, cy + dy, pad.GetNetCode()); added += 1
            continue
        for pad in pads:
            name = pad.GetNetname()
            if name not in PLANE_NETS or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or not pad.GetLayerSet().Contains(pcbnew.F_Cu):
                continue
            net = pad.GetNetCode()
            bb = pad.GetBoundingBox()
            x0, y0, x1, y1 = (pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
            if any(tn == net and tl == pcbnew.F_Cu and any(x0 - 0.05 <= px <= x1 + 0.05 and y0 - 0.05 <= py <= y1 + 0.05 for px, py in ((ax, ay), (bx, by)))
                   for ax, ay, bx, by, hw, tn, tl in B.tracks):
                continue                                  # already wired (pre-route or an earlier pass)
            px, py = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
            if min(x1 - x0, y1 - y0) >= 1.4:              # big pad (thermal pad): via inside it,
                if not any(q.GetNumber() == pad.GetNumber() and q.GetDrillSize().x > 0 for q in pads):     # unless the footprint brings its own thermal vias
                    B.add_via(px, py, net); added += 1
                continue
            dx, dy = px - pcbnew.ToMM(fc.x), py - pcbnew.ToMM(fc.y)
            if len(pads) == 2:                            # R, C, D, L: sideways first, then outward along the axis
                other = [q for q in pads if q is not pad][0].GetPosition()
                ax, ay = px - pcbnew.ToMM(other.x), py - pcbnew.ToMM(other.y)
                n = (ax * ax + ay * ay) ** 0.5 or 1.0
                dirs = [(-ay / n, ax / n), (ay / n, -ax / n), (ax / n, ay / n)]
            elif abs(dx) >= abs(dy):
                dirs = [(1 if dx > 0 else -1, 0)]
            else:
                dirs = [(0, 1 if dy > 0 else -1)]
            spot = None
            for step in (0.9, 1.3, 1.7):
                for ux, uy in dirs:
                    cx, cy = px + ux * step, py + uy * step
                    if B.via_ok(cx, cy, net) and B.track_ok(px, py, cx, cy, net, pcbnew.F_Cu, 0.25):
                        spot = (cx, cy); break
                if spot:
                    break
            if spot is None:
                skipped.append(fp.GetReference() + "." + pad.GetNumber())
                continue
            B.add_track(px, py, spot[0], spot[1], net, pcbnew.F_Cu, 0.25)
            B.add_via(spot[0], spot[1], net)
            added += 1
    print("plane fanout vias added:", added, "; no spot for:", " ".join(skipped) or "none")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=40)
    ap.add_argument("--threads", type=int, default=1, help="Freerouting warns that >1 breaks optimizer clearances")
    ap.add_argument("--jar", default=os.environ.get("FREEROUTING_JAR", ""))
    ap.add_argument("--workdir", default=os.path.join(HW, "fab", "route"))
    ap.add_argument("--fresh", action="store_true", help="remove existing tracks/vias before routing")
    ap.add_argument("--import-only", default="", help="skip routing, import this .ses")
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    dsn = os.path.join(a.workdir, "tspico-v3.dsn")
    ses = a.import_only or os.path.join(a.workdir, "tspico-v3.ses")

    board = pcbnew.LoadBoard(PCB)
    if a.fresh:
        for t in list(board.GetTracks()):
            board.Remove(t)
        print("stripped existing tracks and vias")
    if not a.import_only:
        plane_fanout(board)          # stitch GND/+3V3 pads to the planes before routing
        if not a.jar:
            sys.exit("need --jar or FREEROUTING_JAR")
        pcbnew.ExportSpecctraDSN(board, dsn)
        print("exported", dsn)
        log = os.path.join(a.workdir, "freerouting.log")
        with open(log, "w") as f:
            r = subprocess.run([JAVA, "-jar", a.jar, "-de", dsn, "-do", ses, "-mp", str(a.passes), "-mt", str(a.threads)],
                               stdout=f, stderr=subprocess.STDOUT)
        print("freerouting exit", r.returncode, "log", log)
        if not os.path.exists(ses):
            sys.exit("no session file produced; see the log")
    ok = pcbnew.ImportSpecctraSES(board, ses)
    print("session import:", ok)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    print("saved", PCB, "tracks:", len(board.GetTracks()))
    rpt = os.path.join(HW, "drc.rpt")
    subprocess.run([KICAD_CLI, "pcb", "drc", "--output", rpt, "--severity-error", PCB])
    with open(rpt) as f:
        txt = f.read()
    import collections
    kinds = collections.Counter(line.split("]")[0][1:] for line in txt.splitlines() if line.startswith("["))
    print("DRC:", dict(kinds) or "clean")


if __name__ == "__main__":
    main()
