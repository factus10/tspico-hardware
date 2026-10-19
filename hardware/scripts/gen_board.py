#!/usr/bin/env python3
"""Generate the TS2068 edge-connector footprint and the v3 board skeleton.

Geometry is taken from the v2.2 fab Gerbers (old/tsPico2_2Fab/Gerber):
  board 130.00 x 100.00 mm; tongue 83.66 mm wide x 8.25 mm deep, its left
  edge 18.48 mm from the board's left edge; 32 positions at 2.54 mm pitch,
  31 fingers per side (position 6 is the keying slot, 2.03 mm wide, 8.26 mm
  deep); fingers 1.651 x 8.255 mm (65 x 325 mil), first finger centre
  2.52 mm from the tongue's left edge; corner chamfers 1.0 mm at the tongue.

Run from anywhere: python3 hardware/scripts/gen_board.py
Writes hardware/lib/tspico.pretty/TS2068_EdgeConnector_2x32.kicad_mod
and    hardware/tspico-v3.kicad_pcb (outline + connector + holes + fiducials).
"""
import os
import re
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.dirname(HERE)

# ---- measured geometry (mm) -------------------------------------------------
BOARD_W = 130.00
BOARD_H = 64.25           # including tongue (body 56.00); v2.2 was 100.00
TONGUE_W = 83.66
TONGUE_H = 8.25
TONGUE_X0 = 18.48         # tongue left edge from board left edge
PITCH = 2.54
POSITIONS = 32
SLOT_POS = 6              # 1-based position of the keying slot
SLOT_W = 2.03
SLOT_D = 8.26
FINGER_W = 1.651
FINGER_H = 8.255
FIRST_FINGER_X = 2.52     # centre of position 1 from the tongue's left edge
FINGER_Y_OFFSET = 0.32    # finger bottom edge above the tongue's bottom edge
CHAMFER = 1.0

# Pin names per the TS2068 Technical Manual table 2.4.1-1. Side A is the
# component (top) side, B the solder (bottom) side: confirmed by v3 proto1 in a
# 2068 (2026-10-07), which read addresses from side B and served ROM bytes onto side A.
SIDE_A = ["GND", "EAR", "A7RB", "D7", "DZIN", "SLOT", "D0", "D1", "D2", "D6",
          "D5", "D3", "D4", "~{INT}", "~{NMI}", "~{HALT}", "~{MREQ}", "~{IORQ}",
          "~{RD}", "~{WR}", "~{BUSAK}", "~{WAIT}", "~{BUSRQ}", "~{RESET}",
          "~{M1}", "~{RFSH}", "~{EXROM}", "~{ROSCS}", "~{BE}", "IOA5", "SOUND",
          "GND"]
SIDE_B = ["GND", "SPKR_TAPE", "+15V", "+5V", "NC", "SLOT", "PGND", "PGND",
          "~{CLK}", "A0", "A1", "A2", "A3", "A15", "A14", "A13", "A12", "A11",
          "A10", "A9", "A8", "A7", "A6", "A5", "A4", "DZOUT", "R", "G", "B",
          "BUSISO", "VIDEO", "GND"]


def u():
    return str(uuid.uuid4())


def edge_connector_footprint(embedded=False, at=None):
    """Footprint origin: centre of the tongue's top edge (where it meets the
    board body). Fingers hang below (positive y in KiCad = down)."""
    lines = []
    name = "TS2068_EdgeConnector_2x32"
    hdr = f'(footprint "tspico:{name}"' if embedded else f'(footprint "{name}"'
    lines.append(hdr)
    lines.append('  (version 20241229) (generator "gen_board.py") (generator_version "1")')
    lines.append('  (layer "F.Cu")')
    if embedded:
        lines.append(f'  (uuid "{u()}")')
        lines.append(f'  (at {at[0]:.4f} {at[1]:.4f})')
    lines.append('  (descr "TS2068 rear expansion edge connector, 2x32 positions, 0.100in pitch, slot at position 6. Geometry from TS-Pico v2.2 Gerbers.")')
    lines.append('  (tags "edge connector TS2068 Timex Sinclair")')
    lines.append('  (property "Reference" "P1" (at 0 -2 0) (layer "F.SilkS") (uuid "%s") (effects (font (size 1 1) (thickness 0.15))))' % u())
    lines.append('  (property "Value" "TS2068_Edge" (at 0 -4 0) (layer "F.Fab") (uuid "%s") (effects (font (size 1 1) (thickness 0.15))))' % u())
    lines.append('  (property "Footprint" "" (at 0 0 0) (layer "F.Fab") hide (uuid "%s") (effects (font (size 1.27 1.27) (thickness 0.15))))' % u())
    lines.append('  (property "Datasheet" "" (at 0 0 0) (layer "F.Fab") hide (uuid "%s") (effects (font (size 1.27 1.27) (thickness 0.15))))' % u())
    lines.append('  (property "Description" "" (at 0 0 0) (layer "F.Fab") hide (uuid "%s") (effects (font (size 1.27 1.27) (thickness 0.15))))' % u())
    lines.append('  (attr smd exclude_from_pos_files)')

    half = TONGUE_W / 2
    # tongue outline on Edge.Cuts (the body edge itself is drawn in the PCB)
    # bottom edge with slot cut-out; sides; chamfers
    slot_cx = -half + FIRST_FINGER_X + (SLOT_POS - 1) * PITCH
    sx0, sx1 = slot_cx - SLOT_W / 2, slot_cx + SLOT_W / 2
    yb = TONGUE_H
    pts = [
        ((-half, 0), (-half, yb - CHAMFER)),
        ((-half, yb - CHAMFER), (-half + CHAMFER, yb)),
        ((-half + CHAMFER, yb), (sx0, yb)),
        ((sx0, yb), (sx0, yb - SLOT_D)),
        ((sx0, yb - SLOT_D), (sx1, yb - SLOT_D)),
        ((sx1, yb - SLOT_D), (sx1, yb)),
        ((sx1, yb), (half - CHAMFER, yb)),
        ((half - CHAMFER, yb), (half, yb - CHAMFER)),
        ((half, yb - CHAMFER), (half, 0)),
    ]
    for (x0, y0), (x1, y1) in pts:
        lines.append(f'  (fp_line (start {x0:.4f} {y0:.4f}) (end {x1:.4f} {y1:.4f}) (stroke (width 0.05) (type solid)) (layer "Edge.Cuts") (uuid "{u()}"))')
    # fab outline of the tongue and a courtyard
    lines.append(f'  (fp_rect (start {-half:.4f} 0) (end {half:.4f} {yb:.4f}) (stroke (width 0.1) (type solid)) (fill no) (layer "F.Fab") (uuid "{u()}"))')
    lines.append(f'  (fp_rect (start {-half-0.25:.4f} -0.25) (end {half+0.25:.4f} {yb+0.25:.4f}) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd") (uuid "{u()}"))')
    lines.append(f'  (fp_rect (start {-half-0.25:.4f} -0.25) (end {half+0.25:.4f} {yb+0.25:.4f}) (stroke (width 0.05) (type solid)) (fill no) (layer "B.CrtYd") (uuid "{u()}"))')
    # pin-1 marker
    x1 = -half + FIRST_FINGER_X
    lines.append(f'  (fp_text user "1" (at {x1:.4f} -1 0) (layer "F.SilkS") (uuid "{u()}") (effects (font (size 0.8 0.8) (thickness 0.12))))')
    lines.append(f'  (fp_text user "32" (at {x1 + 31*PITCH:.4f} -1 0) (layer "F.SilkS") (uuid "{u()}") (effects (font (size 0.8 0.8) (thickness 0.12))))')
    lines.append(f'  (fp_text user "A side (top)" (at 0 -1 0) (layer "F.Fab") (uuid "{u()}") (effects (font (size 0.8 0.8) (thickness 0.12))))')
    lines.append(f'  (fp_text user "B side (bottom)" (at 0 -1 0) (layer "B.Fab") (uuid "{u()}") (effects (font (size 0.8 0.8) (thickness 0.12)) (justify mirror)))')

    fy = yb - FINGER_Y_OFFSET - FINGER_H / 2
    for pos in range(1, POSITIONS + 1):
        if pos == SLOT_POS:
            continue
        x = -half + FIRST_FINGER_X + (pos - 1) * PITCH
        for side, layers in (("A", '"F.Cu" "F.Mask"'), ("B", '"B.Cu" "B.Mask"')):
            lines.append(f'  (pad "{side}{pos}" smd rect (at {x:.4f} {fy:.4f}) (size {FINGER_W} {FINGER_H}) (layers {layers}) (solder_mask_margin 0.05) (uuid "{u()}"))')
    lines.append(')')
    return "\n".join(lines)


KICAD_FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"


def stock_footprint(lib, name, ref, at):
    """Embed a copy of a stock KiCad footprint so DRC's library check passes."""
    path = os.path.join(KICAD_FP, lib + ".pretty", name + ".kicad_mod")
    with open(path) as f:
        txt = f.read()
    txt = txt.replace(f'(footprint "{name}"', f'(footprint "{lib}:{name}"', 1)
    txt = txt.replace('(layer "F.Cu")', f'(layer "F.Cu")\n\t(uuid "{u()}")\n\t(at {at[0]} {at[1]})', 1)
    txt = txt.replace('"REF**"', f'"{ref}"', 1)
    # give every graphic/pad its own uuid so multiple copies do not clash
    txt = re.sub(r'\(uuid "[0-9a-f-]{36}"\)', lambda m: f'(uuid "{u()}")', txt)
    return txt.strip()


def mounting_hole(ref, at):
    return stock_footprint("MountingHole", "MountingHole_3.2mm_M3", ref, at)


def fiducial(ref, at):
    return stock_footprint("Fiducial", "Fiducial_1mm_Mask2mm", ref, at)


def board():
    # Board origin: top-left corner of the body at (0,0); body is 130 x 91.75,
    # tongue below it. KiCad y grows downward.
    body_h = BOARD_H - TONGUE_H
    tx0 = TONGUE_X0
    tx1 = TONGUE_X0 + TONGUE_W
    edge = [
        ((0, 0), (BOARD_W, 0)),
        ((BOARD_W, 0), (BOARD_W, body_h)),
        ((BOARD_W, body_h), (tx1, body_h)),
        ((tx0, body_h), (0, body_h)),
        ((0, body_h), (0, 0)),
    ]
    out = []
    out.append('(kicad_pcb (version 20241229) (generator "gen_board.py") (generator_version "1")')
    out.append('  (general (thickness 1.6) (legacy_teardrops no))')
    out.append('  (paper "A3")')
    out.append('  (title_block (title "TS-Pico v3") (rev "0.1") (company "Timex/Sinclair Online User Group") (comment 1 "RP2350B mass storage / ROM / WiFi / sound card for the TS2068") (comment 2 "Board skeleton generated by hardware/scripts/gen_board.py"))')
    out.append('''  (layers
    (0 "F.Cu" signal)
    (1 "In1.Cu" power "GND")
    (2 "In2.Cu" power "PWR")
    (3 "B.Cu" signal)
    (4 "B.Adhes" user "B.Adhesive") (5 "F.Adhes" user "F.Adhesive")
    (6 "B.Paste" user) (7 "F.Paste" user)
    (8 "B.SilkS" user "B.Silkscreen") (9 "F.SilkS" user "F.Silkscreen")
    (10 "B.Mask" user) (11 "F.Mask" user)
    (12 "Dwgs.User" user "User.Drawings") (13 "Cmts.User" user "User.Comments")
    (14 "Eco1.User" user "User.Eco1") (15 "Eco2.User" user "User.Eco2")
    (16 "Edge.Cuts" user) (17 "Margin" user)
    (18 "B.CrtYd" user "B.Courtyard") (19 "F.CrtYd" user "F.Courtyard")
    (20 "B.Fab" user) (21 "F.Fab" user)
  )''')
    # JLCPCB 4-layer (JLC04161H-7628) capable rules, kept conservative
    out.append('''  (setup
    (stackup
      (layer "F.SilkS" (type "Top Silk Screen"))
      (layer "F.Paste" (type "Top Solder Paste"))
      (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "prepreg") (thickness 0.1) (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02))
      (layer "In1.Cu" (type "copper") (thickness 0.0152))
      (layer "dielectric 2" (type "core") (thickness 1.065) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
      (layer "In2.Cu" (type "copper") (thickness 0.0152))
      (layer "dielectric 3" (type "prepreg") (thickness 0.1) (material "FR4") (epsilon_r 4.4) (loss_tangent 0.02))
      (layer "B.Cu" (type "copper") (thickness 0.035))
      (layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))
      (layer "B.Paste" (type "Bottom Solder Paste"))
      (layer "B.SilkS" (type "Bottom Silk Screen"))
      (copper_finish "ENIG")
      (dielectric_constraints no)
    )
    (pad_to_mask_clearance 0)
    (allow_soldermask_bridges_in_footprints no)
    (pcbplotparams (layerselection 0x00000000_00000000_55555555_5755f5ff) (plot_on_all_layers_selection 0x00000000_00000000_00000000_00000000) (disableapertmacros no) (usegerberextensions yes) (usegerberattributes yes) (usegerberadvancedattributes yes) (creategerberjobfile yes) (dashed_line_dash_ratio 12.000000) (dashed_line_gap_ratio 3.000000) (svgprecision 4) (plotframeref no) (mode 1) (useauxorigin no) (hpglpennumber 1) (hpglpenspeed 20) (hpglpendiameter 15.000000) (pdf_front_fp_property_popups yes) (pdf_back_fp_property_popups yes) (pdf_metadata yes) (pdf_single_document no) (dxfpolygonmode yes) (dxfimperialunits yes) (dxfusepcbnewfont yes) (psnegative no) (psa4output no) (plot_black_and_white yes) (sketchpadsonfab no) (plotpadnumbers no) (hidednponfab no) (sketchdnponfab yes) (crossoutdnponfab yes) (subtractmaskfromsilk no) (outputformat 1) (mirror no) (drillshape 1) (scaleselection 1) (outputdirectory "fab/"))
  )''')
    out.append('  (net 0 "")')
    for (x0, y0), (x1, y1) in edge:
        out.append(f'  (gr_line (start {x0:.4f} {y0:.4f}) (end {x1:.4f} {y1:.4f}) (stroke (width 0.05) (type solid)) (layer "Edge.Cuts") (uuid "{u()}"))')
    out.append('  ' + edge_connector_footprint(embedded=True, at=(tx0 + TONGUE_W / 2, body_h)).replace("\n", "\n  "))
    for i, at in enumerate([(5, 5), (113.6, 4.2), (5, body_h - 5), (112, body_h - 4.5)], 1):
        out.append('  ' + mounting_hole(f"H{i}", at).replace("\n", "\n  "))
    for i, at in enumerate([(14, body_h - 2.5), (42, 3.5), (104, body_h - 2.5)], 1):
        out.append('  ' + fiducial(f"FID{i}", at).replace("\n", "\n  "))
    out.append(f'  (gr_text "TS-Pico v3 skeleton: outline and edge connector from v2.2 Gerbers" (at 65 45 0) (layer "Cmts.User") (uuid "{u()}") (effects (font (size 2 2) (thickness 0.3))))')
    out.append(')')
    return "\n".join(out) + "\n"


def main():
    lib = os.path.join(HW, "lib", "tspico.pretty")
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, "TS2068_EdgeConnector_2x32.kicad_mod"), "w") as f:
        f.write(edge_connector_footprint() + "\n")
    with open(os.path.join(HW, "tspico-v3.kicad_pcb"), "w") as f:
        f.write(board())
    print("wrote footprint and board skeleton")


if __name__ == "__main__":
    main()
