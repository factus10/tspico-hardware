#!/usr/bin/env python3
"""Write the TS2068 edge-connector symbol into hardware/lib/tspico.kicad_sym.

Pin numbers are A1..A32 / B1..B32 (no A6/B6, the keying slot), names per the
TS2068 Technical Manual table 2.4.1-1. All pins passive so ERC judges the
nets by what is attached on the card side.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_board import SIDE_A, SIDE_B, HW  # noqa: E402

NAME = "TS2068_Edge"
PITCH = 2.54
W = 25.4          # body width
PIN_LEN = 5.08


def main():
    rows = 32
    top = (rows - 1) * PITCH / 2
    lines = ['(kicad_symbol_lib (version 20241209) (generator "gen_edge_symbol.py") (generator_version "1")',
             f'  (symbol "{NAME}" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)',
             f'    (property "Reference" "P" (at 0 {top + 3.81:.2f} 0) (effects (font (size 1.27 1.27))))',
             f'    (property "Value" "{NAME}" (at 0 {-top - 3.81:.2f} 0) (effects (font (size 1.27 1.27))))',
             '    (property "Footprint" "tspico:TS2068_EdgeConnector_2x32" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
             '    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
             '    (property "Description" "TS2068 rear expansion connector, 2x32 card edge, slot at position 6" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
             '    (property "ki_keywords" "TS2068 Timex Sinclair edge connector" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
             f'    (symbol "{NAME}_0_1"',
             f'      (rectangle (start {-W/2:.2f} {top + 1.27:.2f}) (end {W/2:.2f} {-top - 1.27:.2f}) (stroke (width 0.254) (type default)) (fill (type background)))',
             '    )',
             f'    (symbol "{NAME}_1_1"']
    for i in range(rows):
        pos = i + 1
        if pos == 6:
            continue
        y = top - i * PITCH
        na, nb = SIDE_A[i], SIDE_B[i]
        lines.append(f'      (pin passive line (at {-W/2 - PIN_LEN:.2f} {y:.2f} 0) (length {PIN_LEN}) (name "{na}" (effects (font (size 1.27 1.27)))) (number "A{pos}" (effects (font (size 1.27 1.27)))))')
        lines.append(f'      (pin passive line (at {W/2 + PIN_LEN:.2f} {y:.2f} 180) (length {PIN_LEN}) (name "{nb}" (effects (font (size 1.27 1.27)))) (number "B{pos}" (effects (font (size 1.27 1.27)))))')
    lines += ['    )', '  )', ')']
    path = os.path.join(HW, "lib", "tspico.kicad_sym")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
