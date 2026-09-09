#!/usr/bin/env python3
"""
verify_against_author_volume.py — check the harness volume against the BIM author's own.

For every IfcSpace that carries an author-supplied GrossVolume, compare it with the
v_src_m3 the harness measured for the same GlobalId. This is the one check that does not
rely on the harness's own arithmetic.

The quantity set is found by structure, not by name — see FINDING_03. Volume quantities
are expressed in the project length unit cubed, so a millimetre model needs 1e-9.

Usage:
    python3 scripts/verify_against_author_volume.py --pairs RA-01=corpus/routeA/AC-20-Smiley-West-10-Bldg.ifc \
        --results results/C0 --csv results/C0/author_volume_check.csv
"""
from __future__ import annotations
import argparse, csv, os, statistics

import ifcopenshell

UNIT_SCALE = {"MILLI": 1e-9, "CENTI": 1e-6, "DECI": 1e-3, None: 1.0, "": 1.0}


def length_scale(f):
    for u in f.by_type("IfcUnitAssignment")[0].Units:
        if getattr(u, "UnitType", None) == "LENGTHUNIT" and u.is_a("IfcSIUnit"):
            return UNIT_SCALE.get(u.Prefix, 1.0)
    return 1.0


def author_volumes(path):
    f = ifcopenshell.open(path)
    scale = length_scale(path and f)
    out = {}
    for rel in f.by_type("IfcRelDefinesByProperties"):
        pd = rel.RelatingPropertyDefinition
        if not pd or not pd.is_a("IfcElementQuantity"):
            continue
        gv = None
        for q in pd.Quantities:
            if q.is_a("IfcQuantityVolume") and q.Name == "GrossVolume":
                gv = q.VolumeValue
        if gv is None:
            continue
        for o in rel.RelatedObjects:
            if o.is_a("IfcSpace"):
                out[o.GlobalId] = gv * scale
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", required=True, help="MODELID=path/to.ifc")
    ap.add_argument("--results", default="results/C0")
    ap.add_argument("--csv")
    a = ap.parse_args()

    rows, per_model = [], []
    for pair in a.pairs:
        mid, path = pair.split("=", 1)
        auth = author_volumes(path)
        rpath = os.path.join(a.results, f"{mid}.csv")
        if not os.path.exists(rpath):
            print(f"{mid}: no results at {rpath}"); continue
        diffs = []
        for r in csv.DictReader(open(rpath)):
            if r.get("status") != "ok":
                continue
            gid = r["id"]
            if gid not in auth:
                continue
            va, vh = auth[gid], float(r["v_src_m3"])
            if va == 0:
                continue
            pct = 100.0 * (vh - va) / va
            diffs.append(pct)
            rows.append(dict(model_id=mid, volume_id=gid, v_author_m3=round(va, 6),
                             v_harness_m3=round(vh, 6), diff_pct=round(pct, 6)))
        if diffs:
            ad = sorted(abs(d) for d in diffs)
            per_model.append((mid, len(diffs), statistics.median(diffs), ad[len(ad)//2], ad[-1]))

    print(f"{'model':8s}{'n':>6s}{'median diff %':>15s}{'median |diff| %':>17s}{'max |diff| %':>14s}")
    print("-" * 60)
    for m, n, med, amed, amax in per_model:
        print(f"{m:8s}{n:6d}{med:15.4f}{amed:17.4f}{amax:14.4f}")
    if rows:
        alld = sorted(abs(r["diff_pct"]) for r in rows)
        print("-" * 60)
        print(f"{'ALL':8s}{len(rows):6d}{'':15s}{alld[len(alld)//2]:17.4f}{alld[-1]:14.4f}")
    if a.csv and rows:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print(f"\nCSV written: {a.csv}")


if __name__ == "__main__":
    main()
