#!/usr/bin/env python3
"""The whole board flow in one go (run with KiCad's Python):

    flow.py [--jar <freerouting-2.4.1.jar>] [--passes 100] [--attempts 3]

--jar defaults to $FREEROUTING_JAR.

placement -> locked pre-routes -> Freerouting -> finish -> silkscreen -> board labels. Freerouting does not
give the same result twice from the same input, and now and then it leaves a signal pin
sealed in behind its neighbours' vias where finish.py cannot free it without a silly detour.
Then the board is routed again from the placement; a board that fails is kept as
fab/route/attempt-N.kicad_pcb for a look.
"""
import argparse, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)
PCB = os.path.join(HW, "tspico-v3.kicad_pcb")


def step(name, *args):
    t = time.time()
    rc = subprocess.run([sys.executable, os.path.join(HERE, name), *args]).returncode
    print(f"== {name}: exit {rc}, {time.time() - t:.0f} s", flush=True)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", default=os.environ.get("FREEROUTING_JAR", ""))
    ap.add_argument("--passes", default="100")
    ap.add_argument("--attempts", type=int, default=3)
    a = ap.parse_args()
    a.jar = os.path.expanduser(a.jar)
    if not os.path.isfile(a.jar):
        sys.exit(f"Freerouting jar not found: {a.jar or '(none)'}; pass --jar or set FREEROUTING_JAR")
    for n in range(1, a.attempts + 1):
        print(f"==== attempt {n}", flush=True)
        if step("gen_layout.py") or step("preroute.py") or step("autoroute.py", "--jar", a.jar, "--passes", a.passes):
            sys.exit("flow stopped: a step before finish.py failed")
        if step("finish.py") == 0:
            break
        os.makedirs(os.path.join(HW, "fab", "route"), exist_ok=True)
        shutil.copy(PCB, os.path.join(HW, "fab", "route", f"attempt-{n}.kicad_pcb"))
    else:
        sys.exit(f"not closed after {a.attempts} attempts")
    if step("silk.py"):
        sys.exit("silk.py failed")
    # board name, URL, licence and OSHW logo (gen_layout.py rebuilt the board without them)
    if subprocess.run([sys.executable, os.path.join(HERE, "labels.py"), "v3"]).returncode:
        sys.exit("labels.py failed")
    print(f"==== closed on attempt {n}")


if __name__ == "__main__":
    main()
