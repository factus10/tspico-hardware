#!/usr/bin/env python3
"""Put the board labels on the silkscreen of a routed board.

Run with KiCad's bundled Python (it has the pcbnew module), from the repo root:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 hardware/scripts/labels.py v3
  ... hardware/scripts/labels.py v2.6

Top: the board name. Bottom: name, the GitHub URL (the Source Location that
CERN-OHL-S-2.0 asks every product to carry), the licence, and the open-source
hardware logo, which OSHWA lets any design released under an open licence use.

Silkscreen only: tracks, pads and zones are not touched, so the board does not
need to be routed again. The labels live in one group, "board_labels", which
is replaced on every run. Before saving, every label is checked against pads,
courtyards and other silk on its side; the script refuses to save if one lands
on something.
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
LOGO_LIB = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Symbol.pretty"
LOGO = "OSHW-Logo2_9.8x8mm_SilkScreen"
URL = "github.com/factus10/tspico-hardware"
LICENCE = "CERN-OHL-S-2.0"
GROUP = "board_labels"

# board -> pcb file, name, top label centre (mm, x right, y down from the body's top-left corner), bottom block centre
BOARDS = {
    "v3": ("hardware/tspico-v3.kicad_pcb", "TS-Pico v3", 2.0, (26.0, 51.0), (65.0, 16.5)),      # top: above the left end of the fingers
    "v2.6": ("hardware-v2.6/tspico-v2.6.kicad_pcb", "TS-Pico v2.6", 2.5, (75.0, 48.5), (65.0, 37.5)),   # top: above the fingers
}


def mm(v):
    return pcbnew.FromMM(v)


def text(board, s, h, bold=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetLayer(pcbnew.F_SilkS)
    t.SetTextSize(pcbnew.VECTOR2I(mm(h), mm(h)))
    t.SetTextThickness(mm(h * (0.18 if bold else 0.13)))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_TOP)
    return t


def bbox(items):
    b = None
    for it in items:
        r = it.GetBoundingBox()
        if b is None:
            b = pcbnew.BOX2I(r.GetPosition(), r.GetSize())
        else:
            b.Merge(r)
    return b


def move_centre(items, cx, cy):
    c = bbox(items).GetCenter()
    d = pcbnew.VECTOR2I(mm(cx) - c.x, mm(cy) - c.y)
    for it in items:
        it.Move(d)


def logo_shapes(board, x, y):
    fp = pcbnew.FootprintLoad(LOGO_LIB, LOGO)
    fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    out = []
    for g in fp.GraphicalItems():
        if g.GetLayer() == pcbnew.F_SilkS and g.GetClass() == "PCB_SHAPE":
            s = g.Duplicate()            # absolute coordinates; becomes a board-level shape once added
            s.SetParent(board)
            out.append(s)
    return out


def bottom_block(board, name):
    """Logo on the left, three lines of text on the right, built as top silk and then flipped."""
    logo = logo_shapes(board, 0, 0)
    lb = bbox(logo)
    x0 = pcbnew.ToMM(lb.GetRight()) + 2.0
    y0 = pcbnew.ToMM(lb.GetTop()) - 0.3
    lines = [text(board, name, 2.0, bold=True), text(board, URL, 1.2), text(board, LICENCE, 1.0)]
    y = y0
    for t, gap in zip(lines, (2.0 + 1.1, 1.2 + 1.0, 0)):
        t.SetPosition(pcbnew.VECTOR2I(mm(x0), mm(y)))
        y += gap
    items = logo + lines
    c = bbox(items).GetCenter()
    for it in items:
        it.Flip(c, pcbnew.FLIP_DIRECTION_LEFT_RIGHT)     # onto B.SilkS, mirrored so it reads from below
    return items


def blocked(board, side, skip):
    cu, silk, crt = ((pcbnew.F_Cu, pcbnew.F_SilkS, pcbnew.F_CrtYd) if side == "top"
                     else (pcbnew.B_Cu, pcbnew.B_SilkS, pcbnew.B_CrtYd))
    boxes = []

    def add(b, m):
        boxes.append((b.GetLeft() - mm(m), b.GetTop() - mm(m), b.GetRight() + mm(m), b.GetBottom() + mm(m)))
    for f in board.GetFootprints():
        c = f.GetCourtyard(crt)
        if c.OutlineCount():
            add(c.BBox(), 0.2)
        for p in f.Pads():
            if p.IsOnLayer(cu) or p.GetDrillSize().x > 0:
                add(p.GetBoundingBox(), 0.3)
        for g in f.GraphicalItems():
            if g.GetLayer() == silk:
                add(g.GetBoundingBox(), 0.2)
        for t in (f.Reference(), f.Value()):
            if t.IsVisible() and t.GetLayer() == silk:
                add(t.GetBoundingBox(), 0.2)
    for d in board.GetDrawings():
        if d.GetLayer() == silk and d.m_Uuid.AsString() not in skip:
            add(d.GetBoundingBox(), 0.2)
    tent = board.GetDesignSettings().m_TentViasFront if side == "top" else board.GetDesignSettings().m_TentViasBack
    if not tent:
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA":
                add(t.GetBoundingBox(), 0.2)
    return boxes


def check(board, items, side):
    skip = {it.m_Uuid.AsString() for it in items}
    boxes = blocked(board, side, skip)
    edge = board.GetBoardEdgesBoundingBox()
    bad = []
    for it in items:
        r = it.GetBoundingBox()
        if r.GetLeft() < edge.GetLeft() + mm(1) or r.GetRight() > edge.GetRight() - mm(1) or r.GetTop() < edge.GetTop() + mm(1) or r.GetBottom() > mm(55):
            bad.append((it, "too close to the board edge or over the fingers"))
        for (x0, y0, x1, y1) in boxes:
            if r.GetLeft() < x1 and r.GetRight() > x0 and r.GetTop() < y1 and r.GetBottom() > y0:
                bad.append((it, f"overlaps something at ({pcbnew.ToMM(x0):.1f}, {pcbnew.ToMM(y0):.1f})"))
                break
    return bad


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "v3"
    pcb, name, top_h, top_c, bot_c = BOARDS[which]
    path = os.path.join(REPO, pcb)
    board = pcbnew.LoadBoard(path)

    for g in list(board.Groups()):
        if g.GetName() == GROUP:
            for it in list(g.GetItems()):
                board.Remove(it)
            board.Remove(g)

    top = [text(board, name, top_h, bold=True)]
    move_centre(top, *top_c)
    bottom = bottom_block(board, name)
    move_centre(bottom, *bot_c)

    group = pcbnew.PCB_GROUP(board)
    group.SetName(GROUP)
    board.Add(group)
    for it in top + bottom:
        board.Add(it)
        group.AddItem(it)

    bad = check(board, top, "top") + check(board, bottom, "bottom")
    for it, why in bad:
        txt = it.GetText() if hasattr(it, "GetText") else it.GetClass()
        print(f"  {txt!r}: {why}")
    if bad:
        sys.exit("labels not saved")
    for side, items in (("top", top), ("bottom", bottom)):
        b = bbox(items)
        print(f"{which} {side}: {pcbnew.ToMM(b.GetWidth()):.1f} x {pcbnew.ToMM(b.GetHeight()):.1f} mm at "
              f"({pcbnew.ToMM(b.GetLeft()):.1f}, {pcbnew.ToMM(b.GetTop()):.1f})")
    pcbnew.SaveBoard(path, board)
    print("saved", pcb)


if __name__ == "__main__":
    main()
