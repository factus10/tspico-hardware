#!/usr/bin/env python3
"""Fabrication outputs for JLCPCB: Gerbers + drill (zipped), BOM and CPL.

  python3 scripts/gen_fab.py        (plain python3; calls kicad-cli)

Writes hardware/fab/jlcpcb/: tspico-v2.6-gerbers.zip, tspico-v2.6-bom.csv,
tspico-v2.6-cpl.csv, and fab/NOTES.md with what to check on upload.
"""
import csv, os, re, shutil, subprocess, sys, zipfile

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KC = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
PCB = os.path.join(HW, "tspico-v2.6.kicad_pcb")
SCH = os.path.join(HW, "tspico-v2.6.kicad_sch")
OUT = os.path.join(HW, "fab", "jlcpcb")
GERB = os.path.join(OUT, "gerbers")
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
NOT_ASSEMBLED = re.compile(r"^(P\d+|JP\d+|FID\d+|H\d+|TP\d+|U10|U13)$")   # edge fingers and P10, solder jumpers, DNP pads, fiducials, holes, test pads; U10/U13 DIP sockets, hand-soldered


def expand_refs(field):
    """'C1-C8,C10,R5' -> ['C1', ..., 'C8', 'C10', 'R5']"""
    out = []
    for tok in re.split(r"[,;]", field):
        tok = tok.strip()
        if not tok:
            continue
        m = re.match(r"^([A-Za-z]+)(\d+)-([A-Za-z]+)(\d+)$", tok)
        if m and m.group(1) == m.group(3):
            out += [f"{m.group(1)}{i}" for i in range(int(m.group(2)), int(m.group(4)) + 1)]
        else:
            out.append(tok)
    return out


def run(*args):
    r = subprocess.run([KC, *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"kicad-cli failed: {' '.join(args)}\n{r.stdout}{r.stderr}")
    return r.stdout


def main():
    bom_only = "--bom-only" in sys.argv
    if not bom_only:
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(GERB, exist_ok=True)
    # --- Gerbers + drill -------------------------------------------------
    if not bom_only: run("pcb", "export", "gerbers", "--output", GERB, "--layers", LAYERS, "--subtract-soldermask",
        "--no-x2", "--no-netlist", "--disable-aperture-macros", PCB)
    if not bom_only: run("pcb", "export", "drill", "--output", GERB, "--format", "excellon", "--excellon-units", "mm",
        "--excellon-zeros-format", "decimal", "--drill-origin", "absolute", "--generate-map", "--map-format", "gerberx2", PCB)
    zpath = os.path.join(OUT, "tspico-v2.6-gerbers.zip")
    if not bom_only:
      with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(GERB)):
            z.write(os.path.join(GERB, f), f)
      print("gerbers:", zpath, len(os.listdir(GERB)), "files")
    # --- BOM (JLC format) --------------------------------------------------
    bom_src = os.path.join(HW, "bom", "tspico-v2.6-jlcpcb-bom.csv")
    run("sch", "export", "bom", "--output", bom_src, "--fields", "Value,Reference,Footprint,LCSC",
        "--labels", "Comment,Designator,Footprint,LCSC Part #", "--group-by", "Value,Footprint", "--exclude-dnp", SCH)
    run("sch", "export", "bom", "--output", os.path.join(HW, "bom", "tspico-v2.6-bom-full.csv"),
        "--fields", "Value,Reference,Footprint,MPN,LCSC,${QUANTITY}", "--labels", "Value,Reference,Footprint,MPN,LCSC,Qty",
        "--group-by", "Value,Footprint", "--exclude-dnp", SCH)
    rows, assembled, missing = [], set(), []
    with open(bom_src, newline="") as f:
        for r in csv.DictReader(f):
            refs = expand_refs(r["Designator"])
            refs = [x for x in refs if not NOT_ASSEMBLED.match(x)]
            if not refs:
                continue
            if not r["LCSC Part #"]:
                missing.append((r["Comment"], ", ".join(refs)))
            rows.append({"Comment": r["Comment"], "Designator": ",".join(refs), "Footprint": r["Footprint"].split(":")[-1], "LCSC Part #": r["LCSC Part #"]})
            assembled.update(refs)
    with open(os.path.join(OUT, "tspico-v2.6-bom.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Comment", "Designator", "Footprint", "LCSC Part #"]); w.writeheader(); w.writerows(rows)
    print("bom:", len(rows), "lines,", len(assembled), "parts; missing LCSC:", missing)
    # --- CPL -------------------------------------------------------------
    if bom_only:
        print("bom only; gerbers/CPL not regenerated"); return
    pos = os.path.join(OUT, "pos.csv")
    run("pcb", "export", "pos", "--output", pos, "--format", "csv", "--units", "mm", "--side", "both", "--exclude-dnp", PCB)
    cpl, skipped, th = [], [], []
    with open(pos, newline="") as f:
        for r in csv.DictReader(f):
            ref = r["Ref"]
            if ref not in assembled:
                skipped.append(ref); continue
            cpl.append({"Designator": ref, "Mid X": f"{float(r['PosX']):.4f}mm", "Mid Y": f"{float(r['PosY']):.4f}mm",
                        "Layer": r["Side"].capitalize(), "Rotation": f"{float(r['Rot']):.1f}"})
    os.remove(pos)
    with open(os.path.join(OUT, "tspico-v2.6-cpl.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]); w.writeheader(); w.writerows(cpl)
    print("cpl:", len(cpl), "placements; skipped:", skipped)
    with open(os.path.join(HW, "fab", "NOTES.md"), "w") as f:
        f.write("# Fab outputs (generated by scripts/gen_fab.py)\n\n")
        f.write("- `jlcpcb/tspico-v2.6-gerbers.zip`: 4-layer Gerbers (F, In1 = GND, In2 = +5V, B; paste, silk, mask, edge) and Excellon drill + map.\n")
        f.write("- `jlcpcb/tspico-v2.6-bom.csv`, `jlcpcb/tspico-v2.6-cpl.csv`: JLCPCB assembly BOM and placement (top side; all mm, KiCad rotations).\n")
        f.write(f"- Not in the BOM/CPL (not assembled): {', '.join(sorted(skipped))}.\n")
        f.write("- BOM lines with no LCSC number (pick at upload): " + ("; ".join(f"{c} ({r})" for c, r in missing) or "none") + ".\n")
        f.write("- Everything JLCPCB assembles is SMT on the top side. U10 (SST39SF040, program it first) and U13 (AS6C4008) go in DIP-32 sockets you solder yourself; they are not in the BOM or CPL.\n")
        f.write("- JP1, JP4 and P10 are solder jumpers (closed / 1-2 as shipped); JP2, JP3, JP5 are DNP pads for external buttons; TP1-TP3 are SWCLK, SWDIO, GP23 test pads.\n")
        f.write("- U2 is the RP2040 (QFN-56, 0.4 mm pitch); check its pin-1 orientation and the crystal, USB-C and SOT-223 rotations in the placement preview.\n")
        f.write("- All drills are 0.3 mm or larger; all vias 0.6/0.3 mm.\n")
        f.write("- Check rotations in JLCPCB's placement preview: JLC's part orientation differs from KiCad's for many footprints (QFN, SOT-223, SOIC, connectors); fix there, not here.\n")
        f.write("- Upload order: PCB first (4 layers, 1.6 mm, ENIG recommended for the edge fingers, chamfered gold fingers optional), then assembly with the BOM and CPL.\n")
    print("wrote fab/NOTES.md")


if __name__ == "__main__":
    main()
