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
import collections, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from finish_route import Board, join_islands, pcbnew, MM, T

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(HW, "tspico-v3.kicad_pcb")
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
    # DVDD first: the +3V3 links the joiner adds under the package can fence in the regulator's feedback pin
    for net, plane in (("DVDD", False), ("+3V3", True), ("GND", True)):
        print(net, join_islands(B, net, plane=plane, reach=12.0, margin=5.0))
    B.save()
    kinds, open_nets = drc()
    print("after supply nets:", kinds, sorted(open_nets))
    todo = sorted(open_nets - {"+3V3", "GND", "DVDD"})
    if todo:
        B = Board(PCB)
        for net in todo:
            print(net, join_islands(B, net, reach=90.0, margin=10.0, tries=60))
        B.save()
        kinds, open_nets = drc()
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
    peel() if "--peel" in sys.argv else main()
