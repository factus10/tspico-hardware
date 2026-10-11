#!/usr/bin/env python3
"""Finish the autorouted board (run with KiCad's Python after autoroute.py):
  1. widen any segment the router necked below the 0.127 mm minimum,
  2. join orphan islands of the supply nets: Freerouting treats +3V3 and GND as
     planes and links RP2350B supply pins to each other under the package
     without always giving the group a via,
  3. join islands of any net still listed as unconnected by DRC,
  4. refill zones, run DRC, print a summary.
All routing is clearance-checked (finish_route.py); nothing is forced.
"""
import collections, math, os, re, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from finish_route import Board, join_islands, seg_dist, pcbnew, MM, T

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(HW, "tspico-v2.5.kicad_pcb")
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"


def drc():
    rpt = os.path.join(HW, "drc.rpt")
    subprocess.run([KICAD_CLI, "pcb", "drc", "--output", rpt, "--severity-error", PCB], capture_output=True)
    txt = open(rpt).read()
    kinds = collections.Counter(l.split("]")[0][1:] for l in txt.splitlines() if l.startswith("["))
    open_nets = set(re.findall(r"@\([^)]*\): (?:Track|Via|Pad [^ ]+) \[([^\]]+)\]", "\n".join(
        blk for blk in txt.split("[unconnected_items]")[1:])))
    return dict(kinds), {n.split("/")[-1] for n in open_nets}


def main():
    b = pcbnew.LoadBoard(PCB)
    # The router necks a track down where it squeezes past something (the board's minimum is 0.1 mm,
    # JLCPCB's is 0.09). Widen such segments back to 0.13 mm only where the clearance allows it.
    chk = Board(PCB, b)
    n = kept = 0
    for t in b.GetTracks():
        if t.GetClass() != "PCB_VIA" and T(t.GetWidth()) < 0.127:
            s_, e_ = t.GetStart(), t.GetEnd()
            if chk.track_ok(T(s_.x), T(s_.y), T(e_.x), T(e_.y), t.GetNetCode(), t.GetLayer(), 0.13):
                t.SetWidth(MM(0.13)); n += 1
            else:
                kept += 1
    pcbnew.SaveBoard(PCB, b)
    print("widened", n, "necked segments;", kept, "left narrow where clearance needs it")
    # hairline clearance misses (the router's arcs round to a few microns under the rule): shave
    # 0.02 mm off the offending wide track instead of moving anything
    txt = open(os.path.join(HW, "drc.rpt")).read() if os.path.exists(os.path.join(HW, "drc.rpt")) else ""
    drc()
    txt = open(os.path.join(HW, "drc.rpt")).read()
    nicks = re.findall(r"\[clearance\][^\n]*actual (0\.12\d+) mm\)\n[^\n]*\n\s+@\(([\d.]+) mm, ([\d.]+) mm\): Track \[([^\]]+)\]", txt)
    if nicks:
        b = pcbnew.LoadBoard(PCB)
        for _, x, y, netname in nicks:
            for t in b.GetTracks():
                if t.GetClass() != "PCB_VIA" and t.GetNetname() == netname and T(t.GetWidth()) >= 0.3 and t.HitTest(pcbnew.VECTOR2I(MM(float(x)), MM(float(y))), MM(0.05)):
                    t.SetWidth(t.GetWidth() - MM(0.02)); print("shaved 0.02 mm off a", netname, "segment at", x, y)
        pcbnew.SaveBoard(PCB, b)
    B = Board(PCB)
    # v2.5: GND (In1) and +5V (In2) are planes; +3V3 is an ordinary routed net
    for net, plane in (("+3V3", False), ("+5V", True), ("GND", True)):
        print(net, join_islands(B, net, plane=plane, reach=12.0, margin=5.0))
    B.save()
    kinds, open_nets = drc()
    print("after supply nets:", kinds, sorted(open_nets))
    todo = sorted(open_nets - {"+5V", "GND"})
    if todo:
        B = Board(PCB)
        for net in todo:
            print(net, join_islands(B, net, reach=90.0, margin=10.0, tries=60))
        B.save()
        kinds, open_nets = drc()
    # still open: the pin is boxed in by a neighbour's via or track. Lift that neighbour's copper
    # around the pin, route the open net, then route the neighbour again; keep it only if DRC agrees.
    # (Each stage in its own interpreter: pcbnew does not survive removals followed by more work.)
    def stage(*a):
        return subprocess.run([sys.executable, os.path.abspath(__file__), *a], capture_output=True, text=True).stdout
    for net in sorted(open_nets - SUPPLY):
        cands = (re.findall(r"VICTIMS (.*)", stage("--victims", net)) or [""])[0].split()
        # one neighbour at a time, then pairs, then the whole neighbourhood
        import itertools
        sets = [(v,) for v in cands[:6]] + list(itertools.combinations(cands[:4], 2)) + [tuple(cands[:6])]
        for vs in sets:
            bak = PCB + ".ripup"; shutil.copy(PCB, bak)
            stage("--rip", net, *vs)
            ok = "JOINED" in stage("--rejoin", net, *vs)
            if ok:
                k2, o2 = drc()
                ok = not (set(k2) - {"unconnected_items"}) and not ({net, *vs} & o2) and len(o2) < len(open_nets)
            if ok:
                print(net, "routed after lifting", *vs); kinds, open_nets = k2, o2; os.remove(bak); break
            shutil.move(bak, PCB)
        else:
            print(net, "still open; tried lifting", cands[:6])
    # pre-routed vias the router did not end up using are just holes: drop them
    full = os.path.join(HW, "drc-all.rpt")
    subprocess.run([KICAD_CLI, "pcb", "drc", "--output", full, PCB], capture_output=True)
    spots = [(float(x), float(y)) for x, y in re.findall(r"\[via_dangling\][^\n]*\n[^\n]*\n\s+@\(([\d.]+) mm, ([\d.]+) mm\)", open(full).read())]
    os.remove(full)
    if spots:
        b = pcbnew.LoadBoard(PCB)
        gone = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and any(abs(T(t.GetPosition().x) - x) < 0.01 and abs(T(t.GetPosition().y) - y) < 0.01 for x, y in spots)]
        zones = b.Zones()                  # before the removals: pcbnew can segfault looking the type up afterwards
        for t in gone: b.Remove(t)
        pcbnew.ZONE_FILLER(b).Fill(zones); pcbnew.SaveBoard(PCB, b)
        print("removed", len(gone), "unused vias")
        kinds, open_nets = drc()
    # ...and the stubs that led to them. In a fresh interpreter: after several board loads in one
    # process pcbnew starts handing back unwrapped SWIG pointers
    peeled = 0
    for _ in range(20):
        out = subprocess.run([sys.executable, os.path.abspath(__file__), "--peel"], capture_output=True, text=True).stdout
        n = int((re.findall(r"peeled (\d+)", out) or ["0"])[-1])
        peeled += n
        if not n:
            break
    if peeled:
        print("removed", peeled, "dangling stub segments")
        kinds, open_nets = drc()
    print("final DRC:", kinds or "clean", sorted(open_nets))
    if kinds or open_nets:
        sys.exit(2)          # flow.py routes the board again; the router does not give the same result twice


SUPPLY = {"GND", "+3V3", "+5V", "VBUS", "VSYS"}


def _orphan_pts(B, netname):
    from finish_route import islands_geo
    net = next(code for code, ni in B.b.GetNetsByNetcode().items() if ni.GetNetname().split("/")[-1] == netname)
    isl = sorted(islands_geo(B, net), key=lambda i: -len(i["pts"]))
    return [pt for i in (isl if len(isl[0]["pts"]) == 1 else isl[1:]) for pt in i["pts"]]


def victims(netname, radius=2.0):
    """Nets whose unlocked copper crowds the unconnected ends of `netname`, nearest first."""
    B = Board(PCB)
    pts = _orphan_pts(B, netname)
    best = {}
    for t in B.b.GetTracks():
        v = t.GetNetname().split("/")[-1]
        if t.IsLocked() or v == netname or v in SUPPLY or not v:
            continue
        a, e = (t.GetPosition(), t.GetPosition()) if t.GetClass() == "PCB_VIA" else (t.GetStart(), t.GetEnd())
        d = min(seg_dist(T(a.x), T(a.y), T(e.x), T(e.y), x, y) for x, y, _ in pts)
        if d < radius:
            best[v] = min(d, best.get(v, 9))
    print("VICTIMS", " ".join(sorted(best, key=best.get)))


def rip(netname, lifted, radius=2.2):
    """Remove the lifted nets' unlocked copper around the unconnected ends of `netname`."""
    B = Board(PCB)
    pts = _orphan_pts(B, netname)
    gone = []
    for t in B.b.GetTracks():
        if t.IsLocked() or t.GetNetname().split("/")[-1] not in lifted:
            continue
        a, e = (t.GetPosition(), t.GetPosition()) if t.GetClass() == "PCB_VIA" else (t.GetStart(), t.GetEnd())
        if any(seg_dist(T(a.x), T(a.y), T(e.x), T(e.y), x, y) < radius for x, y, _ in pts):
            gone.append(t)
    for t in gone: B.b.Remove(t)
    pcbnew.SaveBoard(PCB, B.b)
    print("RIPPED", len(gone))


def rejoin(netname, lifted):
    """Route the open net first, now that there is room, then put the lifted nets back."""
    B = Board(PCB)
    before = len(B.vias)
    res = [join_islands(B, n, reach=90.0, margin=10.0, tries=60) for n in (netname, *lifted)]
    if any(r and r[0] == "FAILED" for rs in res for r in rs):
        print("NOJOIN", res)
    elif len(B.vias) - before > 3 * (1 + len(lifted)):
        print("NOJOIN: would take", len(B.vias) - before, "vias; a detour like that is worse than routing the board again")
    else:
        B.save(); print("JOINED", res)


def peel():
    """Remove the track segments that have a free end. One layer per call: pcbnew's connectivity
    handle does not survive a rebuild in the same interpreter, so main() calls this in a fresh
    process until nothing is left, which walks each stub back to its first junction or pad."""
    b = pcbnew.LoadBoard(PCB)
    b.BuildConnectivity(); conn = b.GetConnectivity()
    gone = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and conn.TestTrackEndpointDangling(t, True)]
    zones = b.Zones()                      # before the removals, as above
    for t in gone: b.Remove(t)
    if gone:
        pcbnew.ZONE_FILLER(b).Fill(zones); pcbnew.SaveBoard(PCB, b)
    print("peeled", len(gone))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: main()
    elif a[0] == "--peel": peel()
    elif a[0] == "--victims": victims(a[1])
    elif a[0] == "--rip": rip(a[1], a[2:])
    elif a[0] == "--rejoin": rejoin(a[1], a[2:])
