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
    n = 0
    for t in b.GetTracks():
        if t.GetClass() != "PCB_VIA" and T(t.GetWidth()) < 0.127:
            t.SetWidth(MM(0.13)); n += 1
    pcbnew.SaveBoard(PCB, b)
    print("widened", n, "necked segments")
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
    print("final DRC:", kinds or "clean", sorted(open_nets))


if __name__ == "__main__":
    main()
