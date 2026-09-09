#!/usr/bin/env python3
"""
space_representation_check.py — is each IfcSpace actually a solid?

An IfcSpace is a legal volume only if it carries a 3D body representation. A space
documented as a 2D FootPrint curve set plus a bounding box counts in every space
tally, imports without error, and yields no volume at all. Counting IfcSpace
instances therefore overstates the number of legal volumes a model can supply.

Usage:
    python3 scripts/space_representation_check.py corpus/routeA --csv corpus/space_reps.csv
"""
from __future__ import annotations
import argparse, collections, csv, os

import ifcopenshell


def check(path):
    f = ifcopenshell.open(path)
    spaces = f.by_type("IfcSpace")
    ids = collections.Counter()
    body_items = collections.Counter()
    with_body = 0
    for sp in spaces:
        rep = getattr(sp, "Representation", None)
        found = False
        if rep:
            for r in rep.Representations:
                rid = r.RepresentationIdentifier or "<unnamed>"
                ids[rid] += 1
                if rid == "Body":
                    found = True
                    for it in r.Items:
                        body_items[it.is_a()] += 1
        with_body += bool(found)
    return dict(
        file=os.path.basename(path),
        n_space=len(spaces),
        n_with_body=with_body,
        n_without_body=len(spaces) - with_body,
        pct_with_body=round(100.0 * with_body / len(spaces), 1) if spaces else 0.0,
        representations=";".join(f"{k}={v}" for k, v in ids.most_common()),
        body_item_types=";".join(f"{k}={v}" for k, v in body_items.most_common()) or "-",
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
    print(f"{'file':34s}{'spaces':>8s}{'w/ Body':>9s}{'no Body':>9s}{'%':>7s}   representations")
    print("-" * 118)
    for p in files:
        r = check(p)
        rows.append(r)
        print(f"{r['file'][:33]:34s}{r['n_space']:8d}{r['n_with_body']:9d}"
              f"{r['n_without_body']:9d}{r['pct_with_body']:7.1f}   {r['representations']}")
    tot = sum(r["n_space"] for r in rows)
    body = sum(r["n_with_body"] for r in rows)
    print("-" * 118)
    print(f"{'TOTAL':34s}{tot:8d}{body:9d}{tot-body:9d}{100.0*body/tot:7.1f}")
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        print(f"\nCSV written: {a.csv}")


if __name__ == "__main__":
    main()
