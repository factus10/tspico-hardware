#!/usr/bin/env python3
"""Tiny KiCad 9/10 schematic writer used by the gen_*.py sheet generators.

Sheets are drawn "netlist style": every symbol pin gets a label at its
connection point (global labels for nets that leave the sheet, local labels
otherwise), so the result is ERC-checkable and editable in KiCad, but not
pretty. Stock symbols are copied verbatim from the KiCad library so the
embedded lib_symbols match the library (DRC/ERC library checks stay clean).
"""
import os
import re
import uuid

KICAD_SYMS = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = "tspico-v3"


def u():
    return str(uuid.uuid4())


def _block(txt, start):
    d = 0
    for j in range(start, len(txt)):
        c = txt[j]
        if c == '(':
            d += 1
        elif c == ')':
            d -= 1
            if d == 0:
                return txt[start:j + 1]
    raise ValueError("unbalanced")


def _find_symbol(txt, name):
    m = re.search(r'\(symbol "%s"' % re.escape(name), txt)
    if not m:
        raise KeyError(name)
    return _block(txt, m.start())


class SymLib:
    """Loads symbol definitions from stock libraries or a project library."""

    def __init__(self):
        self.cache = {}
        self.files = {}

    def _lib_text(self, lib):
        if lib not in self.files:
            path = os.path.join(HW, "lib", lib + ".kicad_sym")
            if not os.path.exists(path):
                path = os.path.join(KICAD_SYMS, lib + ".kicad_sym")
            with open(path) as f:
                self.files[lib] = f.read()
        return self.files[lib]

    def get(self, lib_id):
        """Return (flattened symbol text for lib_symbols, pins) where pins is
        {unit: {number: (x, y, angle, name, type)}} in symbol coordinates."""
        if lib_id in self.cache:
            return self.cache[lib_id]
        lib, name = lib_id.split(":")
        txt = self._lib_text(lib)
        blk = _find_symbol(txt, name)
        # resolve (extends ...) chains: the root ancestor supplies the body,
        # each derived level overrides properties
        chain = [blk]
        cur = blk
        while True:
            m = re.search(r'\(extends "([^"]+)"\)', cur)
            if not m:
                break
            cur = _find_symbol(txt, m.group(1))
            chain.append(cur)
        if len(chain) > 1:
            root_name = re.match(r'\(symbol "([^"]+)"', chain[-1]).group(1)
            body = chain[-1]
            for derived in reversed(chain[:-1]):
                for k, v in re.findall(r'\(property "(\w+)" "([^"]*)"', derived):
                    body = re.sub(r'\(property "%s" "[^"]*"' % re.escape(k), lambda mm: '(property "%s" "%s"' % (k, v), body, count=1)
            body = body.replace('(symbol "%s"' % root_name, '(symbol "%s"' % name, 1)
            body = body.replace('(symbol "%s_' % root_name, '(symbol "%s_' % name)
            blk = body
        blk = blk.replace('(symbol "%s"' % name, '(symbol "%s"' % lib_id, 1)
        pins = {}
        for sub in re.finditer(r'\(symbol "%s_(\d+)_(\d+)"' % re.escape(name), blk):
            unit = int(sub.group(1))
            sblk = _block(blk, sub.start())
            for p in re.finditer(r'\(pin (\w+) \w+\s*\(at ([-\d.]+) ([-\d.]+) (\d+)\).*?\(name "([^"]*)".*?\(number "([^"]*)"', sblk, re.S):
                ptype, x, y, ang, pname, pnum = p.groups()
                pins.setdefault(unit, {})[pnum] = (float(x), float(y), int(ang), pname, ptype)
        self.cache[lib_id] = (blk, pins)
        return self.cache[lib_id]


class Placed:
    def __init__(self, sheet, lib_id, ref, x, y, unit, pins, rot=0):
        self.sheet, self.lib_id, self.ref, self.x, self.y, self.unit, self.rot = sheet, lib_id, ref, x, y, unit, rot
        self._pins = pins  # pins of this unit plus common (unit 0)

    def pin(self, key):
        """key: pin number or pin name. Returns (x, y, angle) in sheet coords."""
        hit = None
        if key in self._pins:
            hit = key
        else:
            for num, (_px, _py, _ang, name, _t) in self._pins.items():
                if key == name:
                    hit = num
                    break
        if hit is not None:
            for num, (px, py, ang, name, _t) in ((hit, self._pins[hit]),):
                # symbol y axis points up; sheet y axis points down
                if self.rot == 0:
                    return (self.x + px, self.y - py, ang)
                if self.rot == 90:
                    return (self.x + py, self.y + px, (ang + 90) % 360)
                if self.rot == 180:
                    return (self.x - px, self.y + py, (ang + 180) % 360)
                if self.rot == 270:
                    return (self.x - py, self.y - px, (ang + 270) % 360)
        raise KeyError(f"{self.ref} pin {key}; have {[(n, p[3]) for n, p in self._pins.items()]}")

    def names(self):
        return {num: p[3] for num, p in self._pins.items()}


class Sheet:
    def __init__(self, root_sch, sheet_file, title):
        self.lib = SymLib()
        self.items = []
        self.symbols = {}
        self.title = title
        self.sheet_file = sheet_file
        with open(os.path.join(HW, root_sch)) as f:
            root = f.read()
        self.root_uuid = re.search(r'\(uuid "([^"]+)"\)', root).group(1)
        self.sheet_uuid = None
        for sm in re.finditer(r'\(sheet\s', root):
            blk = _block(root, sm.start())
            if f'"Sheetfile" "{sheet_file}"' in blk:
                self.sheet_uuid = re.search(r'\(uuid "([^"]+)"\)', blk).group(1)
        if not self.sheet_uuid:
            raise KeyError(sheet_file)
        existing = os.path.join(HW, sheet_file)
        self.file_uuid = None
        if os.path.exists(existing):
            with open(existing) as f:
                self.file_uuid = re.search(r'\(uuid "([^"]+)"\)', f.read()).group(1)
        self.file_uuid = self.file_uuid or u()
        self.path = f"/{self.root_uuid}/{self.sheet_uuid}"

    # ---- placement ---------------------------------------------------------
    def place(self, lib_id, ref, value, footprint, x, y, unit=1, rot=0, fields=None, dnp=False):
        # snap to the 1.27 mm connection grid so pins land on grid
        x = round(round(x / 1.27) * 1.27, 2)
        y = round(round(y / 1.27) * 1.27, 2)
        blk, pins = self.lib.get(lib_id)
        self.symbols[lib_id] = blk
        upins = dict(pins.get(0, {}))
        upins.update(pins.get(unit, {}))
        allpins = {}
        for uu in pins.values():
            allpins.update(uu)
        p = Placed(self, lib_id, ref, x, y, unit, upins, rot)
        # put Reference/Value above the symbol, right of any vertical pin label
        ymax = max([pp[1] for pp in upins.values()] + [2.54])
        xr = round(x + 3.0, 2)
        props = [("Reference", ref, (xr, round(y - ymax - 4.5, 2)), False),
                 ("Value", value, (xr, round(y - ymax - 2.0, 2)), False),
                 ("Footprint", footprint, (x, y), True),
                 ("Datasheet", "", (x, y), True),
                 ("Description", "", (x, y), True)]
        for k, v in (fields or {}).items():
            props.append((k, v, (x, y), True))
        try:
            from parts import lookup
            hit = lookup(value, footprint)
        except ImportError:
            hit = None
        if hit and not any(k == "LCSC" for k, *_ in props):
            mpn, lcsc, note = hit
            props.append(("MPN", mpn, (x, y), True))
            props.append(("LCSC", lcsc, (x, y), True))
        lines = [f'(symbol (lib_id "{lib_id}") (at {x} {y} {rot}) (unit {unit})',
                 f'  (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp {"yes" if dnp else "no"})',
                 f'  (uuid "{u()}")']
        for k, v, (px, py), hide in props:
            h = " (hide yes)" if hide else ""
            lines.append(f'  (property "{k}" "{v}" (at {px} {py} 0) (effects (font (size 1.27 1.27)) (justify left){h}))')
        for num in allpins:
            lines.append(f'  (pin "{num}" (uuid "{u()}"))')
        lines.append(f'  (instances (project "{PROJECT}" (path "{self.path}" (reference "{ref}") (unit {unit}))))')
        lines.append(')')
        self.items.append("\n".join(lines))
        return p

    # ---- connectivity ------------------------------------------------------
    @staticmethod
    def _label_geom(pin_at):
        x, y, ang = pin_at
        la = (ang + 180) % 360
        just = {0: "left", 180: "right", 90: "left", 270: "right"}[la]
        return x, y, la, just

    def label(self, net, pin_at):
        x, y, la, just = self._label_geom(pin_at)
        self.items.append(f'(label "{net}" (at {x:.2f} {y:.2f} {la}) (effects (font (size 1.27 1.27)) (justify {just} bottom)) (uuid "{u()}"))')

    def glabel(self, net, pin_at, shape="bidirectional"):
        x, y, la, just = self._label_geom(pin_at)
        self.items.append(f'(global_label "{net}" (shape {shape}) (at {x:.2f} {y:.2f} {la}) (effects (font (size 1.27 1.27)) (justify {just})) (uuid "{u()}"))')

    def nc(self, pin_at):
        x, y, _ = pin_at
        self.items.append(f'(no_connect (at {x:.2f} {y:.2f}) (uuid "{u()}"))')

    def wire(self, a, b):
        self.items.append(f'(wire (pts (xy {a[0]:.2f} {a[1]:.2f}) (xy {b[0]:.2f} {b[1]:.2f})) (stroke (width 0) (type default)) (uuid "{u()}"))')

    def text(self, s, x, y, size=2.0):
        s = s.replace('"', "'")
        self.items.append(f'(text "{s}" (exclude_from_sim no) (at {x} {y} 0) (effects (font (size {size} {size})) (justify left bottom)) (uuid "{u()}"))')

    def power(self, net, x, y, ref, flag=True):
        """Place a power symbol (+5V, +3V3, GND ...) and, once per project net,
        a PWR_FLAG on it (flag=False on sheets where the net is flagged elsewhere)."""
        lib_id = "power:" + net
        p = self.place(lib_id, ref, net, "", x, y)
        pa = p.pin("1")
        if not flag:
            self.label(net, pa)
            return p
        f = self.place("power:PWR_FLAG", ref.replace("#PWR", "#FLG"), "PWR_FLAG", "", pa[0] + 7.62, pa[1])
        fa = f.pin("1")
        self.wire(pa[:2], fa[:2])
        return p

    # ---- output ------------------------------------------------------------
    def write(self):
        out = ['(kicad_sch (version 20250114) (generator "schlib.py") (generator_version "1")',
               f'  (uuid "{self.file_uuid}")', '  (paper "A3")',
               f'  (title_block (title "{self.title}") (rev "0.1") (company "Timex/Sinclair Online User Group"))',
               '  (lib_symbols']
        for blk in self.symbols.values():
            out.append("    " + blk.replace("\n", "\n    "))
        out.append('  )')
        for it in self.items:
            out.append("  " + it.replace("\n", "\n  "))
        out.append('  (embedded_fonts no)')
        out.append(')')
        with open(os.path.join(HW, self.sheet_file), "w") as f:
            f.write("\n".join(out) + "\n")
