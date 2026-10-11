#!/usr/bin/env python3
"""Silkscreen pass (run with KiCad's Python, any time after gen_layout.py; routing is not touched).

  * every reference designator: 0.8 x 0.8 mm, 0.15 mm stroke (JLCPCB prints this cleanly)
  * each one is moved to the first spot around its part that touches no pad, no other
    silkscreen, no other part's body and stays 0.6 mm inside the board; big parts may
    fall back to the middle of their own body; if nothing fits the designator is
    hidden on silk (it stays on F.Fab for the assembly drawing)
  * silkscreen graphics that cross or hug the board edge (connector and antenna
    outlines) are removed
"""
import os, sys
import pcbnew

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(HW, "tspico-v2.6.kicad_pcb")
MM, T = pcbnew.FromMM, pcbnew.ToMM
SIZE, STROKE, EDGE = 0.8, 0.15, 0.6
BODY_H = 56.0


def box(bb, grow=0.0):
    return (T(bb.GetLeft()) - grow, T(bb.GetTop()) - grow, T(bb.GetRight()) + grow, T(bb.GetBottom()) + grow)


def hit(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def main():
    b = pcbnew.LoadBoard(PCB)
    ebb = b.GetBoardEdgesBoundingBox()
    W = T(ebb.GetRight())
    fps = list(b.GetFootprints())
    pads, silk, bodies = [], [], {}
    doomed = []
    for f in fps:
        for p in f.Pads():
            if p.GetLayerSet().Contains(pcbnew.F_Cu) or p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                pads.append(box(p.GetBoundingBox(), 0.2))
        for g in list(f.GraphicalItems()):
            if g.GetLayer() != pcbnew.F_SilkS:
                continue
            bx = box(g.GetBoundingBox())
            if bx[0] < EDGE / 2 or bx[1] < EDGE / 2 or bx[2] > W - EDGE / 2 or bx[3] > BODY_H - EDGE / 2:
                doomed.append((f, g))              # outline running off or along the board edge; removed at the end
                continue
            silk.append((f.GetReference(), box(g.GetBoundingBox(), 0.12)))
        cys = [box(g.GetBoundingBox()) for g in f.GraphicalItems() if g.GetLayer() == pcbnew.F_CrtYd]
        if cys:
            bodies[f.GetReference()] = (min(c[0] for c in cys), min(c[1] for c in cys), max(c[2] for c in cys), max(c[3] for c in cys))
        else:
            bodies[f.GetReference()] = box(f.GetBoundingBox(False), 0.05)

    placed, hidden = {}, []

    def try_place(f):
        """Put f's designator at the first candidate spot that is clear; returns its ink box or None."""
        ref = f.Reference()
        name = f.GetReference()
        ref.SetVisible(True)
        ref.SetLayer(pcbnew.F_SilkS)
        ref.SetTextSize(pcbnew.VECTOR2I(MM(SIZE), MM(SIZE)))
        ref.SetTextThickness(MM(STROKE))
        ref.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER); ref.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        ref.SetKeepUpright(True)
        x0, y0, x1, y1 = bodies[name]
        cx, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
        tw, th = len(name) * SIZE * 0.87 + 0.13, SIZE + STROKE + 0.08      # the ink box below

        def ink(px, py, ang, n=len(name)):
            # the glyphs themselves (capitals and digits, centred): KiCad's text bounding box adds
            # a line-spacing allowance that would waste half the room between parts
            hw, hh = (n * SIZE * 0.87 + 0.05) / 2 + 0.04, (SIZE + STROKE) / 2 + 0.04
            return (px - hw, py - hh, px + hw, py + hh) if ang == 0 else (px - hh, py - hw, px + hh, py + hw)
        cands = []
        for g in (0.02, 0.3, 0.6, 1.0, 1.5, 2.0):
            for ang, w, h in ((0, tw, th), (90, th, tw)):
                centred = [(cx, y0 - h / 2 - g), (cx, y1 + h / 2 + g), (x1 + w / 2 + g, cy_), (x0 - w / 2 - g, cy_)]
                if y1 - y0 > x1 - x0:                # upright part: beside it reads better than above it
                    centred = centred[2:] + centred[:2]
                for px, py in (*centred,
                               (x0 + w / 2, y0 - h / 2 - g), (x1 - w / 2, y0 - h / 2 - g), (x0 + w / 2, y1 + h / 2 + g), (x1 - w / 2, y1 + h / 2 + g),
                               (x0 - w / 2 - g, y0 + h / 2), (x0 - w / 2 - g, y1 - h / 2), (x1 + w / 2 + g, y0 + h / 2), (x1 + w / 2 + g, y1 - h / 2)):
                    cands.append((px, py, ang, False))
        if (x1 - x0) * (y1 - y0) > 14:              # ICs, connectors, the module: inside the body as a fallback
            cands += [(cx, cy_, 0, True), (cx, cy_, 90, True)]
        for px, py, ang, inside in cands:
            tb = ink(px, py, ang)
            if tb[0] < EDGE or tb[1] < EDGE or tb[2] > W - EDGE or tb[3] > BODY_H - EDGE:
                continue
            if any(hit(tb, p) for p in pads):
                continue
            if any(hit(tb, s) for owner, s in silk if not (inside and owner == name)):
                continue
            if any(hit(tb, o) for o in placed.values()):
                continue
            if any(hit(tb, bd) for other, bd in bodies.items() if other != name):
                continue
            if inside and not (tb[0] > x0 and tb[2] < x1 and tb[1] > y0 and tb[3] < y1):
                continue
            ref.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
            ref.SetPosition(pcbnew.VECTOR2I(MM(px), MM(py)))
            return tb
        ref.SetVisible(False)
        return None

    byname = {f.GetReference(): f for f in fps}
    # big parts first: their designators have the fewest good spots relative to their size
    # (ties in reading order, so a row or column of equal parts all get the same side)
    for f in sorted(fps, key=lambda f: (-round((bodies[f.GetReference()][2] - bodies[f.GetReference()][0]) * (bodies[f.GetReference()][3] - bodies[f.GetReference()][1]), 1), bodies[f.GetReference()][0], bodies[f.GetReference()][1])):
        name = f.GetReference()
        if name.startswith(("FID", "H")):
            f.Reference().SetVisible(False)
            continue
        tb = try_place(f)
        if tb: placed[name] = tb
        else: hidden.append(name)
    # second chance: lift a neighbour's designator, place the hidden one, then put the neighbour somewhere else
    for name in list(hidden):
        x0, y0, x1, y1 = bodies[name]
        near = [n for n, tb in placed.items() if hit(tb, (x0 - 3.5, y0 - 3.5, x1 + 3.5, y1 + 3.5))]
        for n in near:
            old_tb = placed.pop(n)
            ref_n = byname[n].Reference(); keep = (ref_n.GetPosition(), ref_n.GetTextAngle())
            tb = try_place(byname[name])
            if tb:
                placed[name] = tb
                tb_n = try_place(byname[n])
                if tb_n:
                    placed[n] = tb_n; hidden.remove(name); break
                del placed[name]; byname[name].Reference().SetVisible(False)
            ref_n.SetVisible(True); ref_n.SetPosition(keep[0]); ref_n.SetTextAngle(keep[1]); placed[n] = old_tb
    moved = len(placed)
    # clusters of parts too dense for individual designators get one legend, e.g. "R90-101 C90-95"
    import re
    def ranges(names):
        out = []
        for pre in sorted({re.match(r"[A-Z]+", n).group(0) for n in names}):
            nums = sorted(int(re.search(r"\d+", n).group(0)) for n in names if re.match(r"[A-Z]+", n).group(0) == pre)
            runs, start, prev = [], nums[0], nums[0]
            for v in nums[1:] + [None]:
                if v is None or v != prev + 1:
                    runs.append(f"{start}" if start == prev else f"{start}-{prev}"); start = v
                prev = v if v is not None else prev
            out.append(pre + ",".join(runs))
        return " ".join(out)
    left = list(hidden); clusters = []
    while left:
        cl = [left.pop()]
        grew = True
        while grew:
            grew = False
            for n in list(left):
                if any(abs((bodies[n][0] + bodies[n][2]) - (bodies[m][0] + bodies[m][2])) / 2 < 4.2 and abs((bodies[n][1] + bodies[n][3]) - (bodies[m][1] + bodies[m][3])) / 2 < 4.2 for m in cl):
                    cl.append(n); left.remove(n); grew = True
        clusters.append(cl)
    legends = []
    for cl in clusters:
        if len(cl) < 4:
            continue
        label = ranges(cl)
        x0 = min(bodies[n][0] for n in cl); y0 = min(bodies[n][1] for n in cl); x1 = max(bodies[n][2] for n in cl); y1 = max(bodies[n][3] for n in cl)
        txt = pcbnew.PCB_TEXT(b)
        txt.SetText(label); txt.SetLayer(pcbnew.F_SilkS)
        txt.SetTextSize(pcbnew.VECTOR2I(MM(SIZE), MM(SIZE))); txt.SetTextThickness(MM(STROKE))
        txt.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER); txt.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        tw, th = len(label) * SIZE * 0.92 + 0.1, SIZE + 0.1
        ok = False
        for g in (0.1, 0.4, 0.8, 1.3, 2.0, 3.0):
            for ang, w, h in ((0, tw, th), (90, th, tw)):
                for px, py in (((x0 + x1) / 2, y1 + h / 2 + g), ((x0 + x1) / 2, y0 - h / 2 - g), (x0 - w / 2 - g, (y0 + y1) / 2), (x1 + w / 2 + g, (y0 + y1) / 2),
                               (x0 + w / 2, y1 + h / 2 + g), (x1 - w / 2, y1 + h / 2 + g), (x0 + w / 2, y0 - h / 2 - g), (x1 - w / 2, y0 - h / 2 - g)):
                    txt.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T)); txt.SetPosition(pcbnew.VECTOR2I(MM(px), MM(py)))
                    tb = box(txt.GetBoundingBox(), 0.04)
                    if tb[0] < EDGE or tb[1] < EDGE or tb[2] > W - EDGE or tb[3] > BODY_H - EDGE: continue
                    if any(hit(tb, p_) for p_ in pads) or any(hit(tb, s_) for _, s_ in silk) or any(hit(tb, o) for o in placed.values()) or any(hit(tb, bd) for bd in bodies.values()): continue
                    ok = True; break
                if ok: break
            if ok: break
        if ok:
            b.Add(txt); placed[label] = tb; legends.append(label)
    print("group legends:", legends)
    for f, g in doomed:                # last: pcbnew's item lists do not survive a Remove
        f.Remove(g)
    removed = len(doomed)
    pcbnew.SaveBoard(PCB, b)
    print(f"designators placed: {moved}; hidden for lack of room: {len(hidden)} {sorted(hidden)}; edge outline segments removed: {removed}")


if __name__ == "__main__":
    main()
