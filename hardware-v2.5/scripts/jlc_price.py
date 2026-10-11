#!/usr/bin/env python3
"""Price the JLCPCB BOM against JLCPCB's parts catalog (public search API).

  python3 scripts/jlc_price.py [--boards 10] [--bom fab/jlcpcb/tspico-v2.5-bom.csv]

Prints per line: library type (basic / preferred / extended), stock, unit price
at the order quantity, line cost per board, and the extended-part loading fee.
Also usable as a module: search(keyword, ...) and lookup(code).
"""
import argparse, csv, json, os, re, sys, time, urllib.request

API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
EXT_FEE = 3.0          # USD loading fee per extended part number (waived for preferred parts)
_cache = {}


def search(keyword, page_size=30, library="", in_stock=True):
    key = (keyword, page_size, library, in_stock)
    if key in _cache:
        return _cache[key]
    body = json.dumps({"currentPage": 1, "pageSize": page_size, "keyword": keyword,
                       "componentLibraryType": library, "stockFlag": in_stock}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)["data"]["componentPageInfo"]["list"] or []
            break
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)
    out = [slim(c) for c in data]
    _cache[key] = out
    return out


def slim(c):
    lib = "basic" if c.get("componentLibraryType") == "base" else ("preferred" if c.get("preferredComponentFlag") else "extended")
    return {"code": c["componentCode"], "mpn": c.get("componentModelEn"), "brand": c.get("componentBrandEn"),
            "package": c.get("componentSpecificationEn"), "lib": lib, "stock": c.get("stockCount", 0),
            "prices": [(p["startNumber"], p["productPrice"]) for p in c.get("componentPrices") or []],
            "describe": c.get("describe", "")}


def lookup(code):
    for c in search(code, page_size=5, in_stock=False):
        if c["code"] == code:
            return c
    return None


def unit_price(part, qty):
    tiers = sorted(part["prices"])
    price = tiers[0][1] if tiers else float("nan")
    for start, p in tiers:
        if qty >= start:
            price = p
    return price


def fee(part):
    return EXT_FEE if part["lib"] == "extended" else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boards", type=int, default=10)
    ap.add_argument("--bom", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fab", "jlcpcb", "tspico-v2.5-bom.csv"))
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    lines = []
    with open(a.bom, newline="") as f:
        for r in csv.DictReader(f):
            n = len([x for x in r["Designator"].split(",") if x])
            code = r["LCSC Part #"]
            part = lookup(code) if code else None
            lines.append({"comment": r["Comment"], "refs": r["Designator"], "n": n, "code": code, "part": part})
    total_parts = total_fees = 0.0
    rows = []
    for l in lines:
        p = l["part"]
        if not p:
            rows.append((0, 0, f"{l['comment']:<22} {l['refs'][:28]:<28} x{l['n']:<3} {l['code']:<11} NOT FOUND"))
            continue
        qty = l["n"] * a.boards
        up = unit_price(p, qty)
        line = up * l["n"]
        total_parts += line; total_fees += fee(p)
        rows.append((line * a.boards + fee(p), line, f"{l['comment']:<22} {l['refs'][:28]:<28} x{l['n']:<3} {p['code']:<11} {p['lib']:<9} stock {p['stock']:<8} ${up:<7.4f} ${line:<7.3f}/board  fee ${fee(p):.0f}  {p['mpn']}"))
    print(f"{'value':<22} {'refs':<28} {'qty':<4} {'LCSC':<11} {'library':<9} {'':<15} {'unit':<8} {'per board':<15}")
    for _, _, s in sorted(rows, key=lambda r: -r[0]):
        print(s)
    print(f"\n{a.boards} boards: parts ${total_parts:.2f}/board (${total_parts * a.boards:.2f}), extended-part fees ${total_fees:.0f} once, "
          f"parts+fees per board ${total_parts + total_fees / a.boards:.2f}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(lines, f, indent=1)


if __name__ == "__main__":
    main()
