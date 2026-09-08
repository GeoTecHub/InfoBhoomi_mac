#!/usr/bin/env python3
"""
space_quantity_check.py — does each IfcSpace carry an author-supplied volume?

Paper 1 needs a BIM-authored GrossVolume per IfcSpace as an independent check on the
harness volume. IFC4 names that quantity set 'Qto_SpaceBaseQuantities', but ArchiCAD
and several other authoring tools name it plainly 'BaseQuantities'. A scan that greps
only for the IFC4 spelling reports zero and is wrong.

Pure stdlib STEP text parse — no ifcopenshell. Usage:
    python3 scripts/space_quantity_check.py corpus/routeA --csv corpus/space_quantities.csv
"""
from __future__ import annotations
import argparse, csv, os, re, sys

ENT = re.compile(r"^#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)$", re.I | re.S)

def parse(path):
    """Return {id: (TYPE, argstring)} for every entity instance in the file."""
    ents = {}
    buf = ""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        indata = False
        for line in fh:
            s = line.strip()
            if not indata:
                if s.upper().startswith("DATA"):
                    indata = True
                continue
            if s.upper().startswith("ENDSEC"):
                break
            buf += s
            while ";" in buf:
                stmt, buf = buf.split(";", 1)
                m = ENT.match(stmt.strip())
                if m:
                    ents[int(m.group(1))] = (m.group(2).upper(), m.group(3))
    return ents

def refs(arg):
    return [int(x) for x in re.findall(r"#(\d+)", arg)]

def check(path):
    ents = parse(path)
    spaces = {i for i, (t, _) in ents.items() if t == "IFCSPACE"}

    # quantity sets carrying a GrossVolume, and their names
    qsets = {}
    for i, (t, a) in ents.items():
        if t == "IFCELEMENTQUANTITY":
            nm = re.findall(r"'([^']*)'", a)
            qsets[i] = (nm[2] if len(nm) > 2 else "", a)
    volq = {i for i, (t, a) in ents.items()
            if t == "IFCQUANTITYVOLUME" and re.match(r"^\s*'GrossVolume'", a, re.I)}
    qsets_with_vol = {i for i, (nm, a) in qsets.items() if set(refs(a)) & volq}

    # IfcRelDefinesByProperties: (…, RelatedObjects, RelatingPropertyDefinition)
    hit, names = set(), {}
    for i, (t, a) in ents.items():
        if t != "IFCRELDEFINESBYPROPERTIES":
            continue
        r = refs(a)
        if not r:
            continue
        relating = r[-1]
        if relating in qsets_with_vol:
            for o in r[:-1]:
                if o in spaces:
                    hit.add(o)
                    names[qsets[relating][0]] = names.get(qsets[relating][0], 0) + 1
    return dict(
        file=os.path.basename(path),
        n_space=len(spaces),
        n_space_with_grossvolume=len(hit),
        pct=round(100.0 * len(hit) / len(spaces), 1) if spaces else 0.0,
        qset_names=";".join(f"{k}={v}" for k, v in sorted(names.items())) or "-",
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--csv")
    a = ap.parse_args()
    files = ([a.path] if os.path.isfile(a.path) else
             sorted(os.path.join(a.path, f) for f in os.listdir(a.path)
                    if f.lower().endswith(".ifc")))
    rows = []
    print(f"{'file':46s} {'spaces':>7s} {'w/GrossVolume':>14s} {'%':>6s}  quantity-set name")
    print("-" * 110)
    for f in files:
        r = check(f)
        rows.append(r)
        print(f"{r['file']:46s} {r['n_space']:7d} {r['n_space_with_grossvolume']:14d} "
              f"{r['pct']:6.1f}  {r['qset_names']}")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nCSV written: {a.csv}")

if __name__ == "__main__":
    main()
