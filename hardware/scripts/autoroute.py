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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=20)
    ap.add_argument("--threads", type=int, default=6)
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
