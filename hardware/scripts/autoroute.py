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
    """Freerouting treats the GND/+3V3 zones as planes and leaves their SMD
    pads alone. Give every such pad that has no track a via next to it so the
    zone fill picks it up: a short stub from the pad centre outward (away
    from the footprint centre) to a 0.6/0.3 via."""
    tracks = list(board.GetTracks())
    def has_track(pad):
        net = pad.GetNetCode()
        for t in tracks:
            if t.GetNetCode() == net and t.HitTest(pad.GetPosition(), pcbnew.FromMM(0.05)):
                return True
        return False
    added = 0
    placed = []
    other_pads = [(p.GetPosition(), p.GetNetCode()) for f in board.GetFootprints() for p in f.Pads()]
    for fp in board.GetFootprints():
        fc = fp.GetPosition()
        for pad in fp.Pads():
            name = pad.GetNetname()
            if name not in PLANE_NETS or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            if pad.GetLayerSet().Contains(pcbnew.F_Cu) is False:
                continue
            if has_track(pad):
                continue
            pp = pad.GetPosition()
            net = pad.GetNetCode()
            dx, dy = pp.x - fc.x, pp.y - fc.y
            sz = pad.GetSize()
            if min(sz.x, sz.y) >= pcbnew.FromMM(1.4):
                vp = pp                      # big pad (thermal pad): via inside it
            else:
                pads = list(fp.Pads())
                if len(pads) == 2:
                    # two-pad part (R, C, D, L): go sideways, perpendicular to the
                    # pad axis, so rows and columns of passives do not collide
                    ax, ay = pads[1].GetPosition().x - pads[0].GetPosition().x, pads[1].GetPosition().y - pads[0].GetPosition().y
                    if abs(ax) >= abs(ay):
                        ux, uy = 0, 1
                    else:
                        ux, uy = 1, 0
                elif abs(dx) >= abs(dy):
                    ux, uy = (1 if dx > 0 else -1), 0
                else:
                    ux, uy = 0, (1 if dy > 0 else -1)
                vp = None
                # candidate stubs: straight out 0.9 mm, else 1.7 mm; reject any
                # whose via/stub comes within 0.8 mm of a placed via or within
                # 0.55 mm of a pad on another net; otherwise leave the pad to the router
                for step_mm in (0.9, 1.7):
                    step = pcbnew.FromMM(step_mm)
                    cand = pcbnew.VECTOR2I(int(pp.x + ux * step), int(pp.y + uy * step))
                    if not all(_seg_dist(pp, cand, v) >= pcbnew.FromMM(0.8) for v in placed):
                        continue
                    if any(_seg_dist(pp, cand, op) < pcbnew.FromMM(0.5) for op, onet in other_pads if onet != net):
                        continue
                    vp = cand
                    break
                if vp is None:
                    print("no via spot for", fp.GetReference(), pad.GetNumber())
                    continue
            tr = pcbnew.PCB_TRACK(board)
            tr.SetStart(pp); tr.SetEnd(vp); tr.SetWidth(pcbnew.FromMM(0.25)); tr.SetLayer(pcbnew.F_Cu); tr.SetNet(pad.GetNet())
            board.Add(tr)
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(vp); via.SetDrill(pcbnew.FromMM(0.3)); via.SetWidth(pcbnew.FromMM(0.6))
            via.SetViaType(pcbnew.VIATYPE_THROUGH); via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); via.SetNet(pad.GetNet())
            board.Add(via)
            placed.append(vp)
            added += 1
    print("plane fanout vias added:", added)


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
