#!/usr/bin/env python3
"""Fabrication outputs for JLCPCB: Gerbers + drill (zipped), BOM and CPL.

  python3 scripts/gen_fab.py        (plain python3; calls kicad-cli)

Writes hardware/fab/jlcpcb/: tspico-v3-gerbers.zip, tspico-v3-bom.csv,
tspico-v3-cpl.csv, and fab/NOTES.md with what to check on upload.
"""
import csv, os, re, shutil, subprocess, sys, zipfile

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KC = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
PCB = os.path.join(HW, "tspico-v3.kicad_pcb")
SCH = os.path.join(HW, "tspico-v3.kicad_sch")
OUT = os.path.join(HW, "fab", "jlcpcb")
GERB = os.path.join(OUT, "gerbers")
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"
NOT_ASSEMBLED = re.compile(r"^(P\d+|TP\d+|JP\d+|FID\d+|H\d+|J3|J5)$")   # edge fingers, test points, solder jumpers, fiducials, holes; J3/J5 through-hole, hand-soldered


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
    zpath = os.path.join(OUT, "tspico-v3-gerbers.zip")
    if not bom_only:
      with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(GERB)):
            z.write(os.path.join(GERB, f), f)
      print("gerbers:", zpath, len(os.listdir(GERB)), "files")
    # --- BOM (JLC format) --------------------------------------------------
    bom_src = os.path.join(HW, "bom", "tspico-v3-jlcpcb-bom.csv")
    run("sch", "export", "bom", "--output", bom_src, "--fields", "Value,Reference,Footprint,LCSC",
        "--labels", "Comment,Designator,Footprint,LCSC Part #", "--group-by", "Value,Footprint", "--exclude-dnp", SCH)
    run("sch", "export", "bom", "--output", os.path.join(HW, "bom", "tspico-v3-bom-full.csv"),
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
    with open(os.path.join(OUT, "tspico-v3-bom.csv"), "w", newline="") as f:
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
    with open(os.path.join(OUT, "tspico-v3-cpl.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]); w.writeheader(); w.writerows(cpl)
    print("cpl:", len(cpl), "placements; skipped:", skipped)
    with open(os.path.join(HW, "fab", "NOTES.md"), "w") as f:
        f.write("# Fab outputs (generated by scripts/gen_fab.py)\n\n")
        f.write("- `jlcpcb/tspico-v3-gerbers.zip`: 4-layer Gerbers (F, In1 = GND, In2 = +3V3, B; paste, silk, mask, edge) and Excellon drill + map.\n")
        f.write("- `jlcpcb/tspico-v3-bom.csv`, `jlcpcb/tspico-v3-cpl.csv`: JLCPCB assembly BOM and placement (top side; all mm, KiCad rotations).\n")
        f.write(f"- Not in the BOM/CPL (not assembled): {', '.join(sorted(skipped))}.\n")
        f.write("- BOM lines with no LCSC number (pick at upload): " + ("; ".join(f"{c} ({r})" for c, r in missing) or "none") + ".\n")
        f.write("- J3 (OLED header) and J5 (DE-9) are through-hole and hand-soldered: they are not in the BOM or CPL.\n")
        f.write("- L1 is polarised. The footprint copies LCSC's land pattern and pad numbering, so no rotation offset should be needed, but check the preview: the dot on L1 must be at the end away from the top edge of the board (pad 2, net DVDD).\n")
        f.write("- DNP (footprints only): U22 PSRAM, and the DMA option U8, U12, U13, C7-C9. Two DMA-option nets (nMRD, nWR_ALO) are not routed; see hardware/README.md.\n")
        f.write("- All drills are 0.3 mm or larger; all vias 0.6/0.3 mm.\n")
        f.write("- Check rotations in JLCPCB's placement preview: JLC's part orientation differs from KiCad's for many footprints (QFN, SOT-223, SOIC, connectors); fix there, not here.\n")
        f.write("- Upload order: PCB first (4 layers, 1.6 mm, ENIG recommended for the edge fingers, chamfered gold fingers optional), then assembly with the BOM and CPL.\n")
    print("wrote fab/NOTES.md")


if __name__ == "__main__":
    main()
