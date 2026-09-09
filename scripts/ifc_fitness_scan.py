#!/usr/bin/env python3
"""
ifc_fitness_scan.py — screen IFC files for fitness as InfoBhoomi 3D-cadastre input.

Pure-text STEP parsing: no ifcopenshell required, so it runs anywhere and is fast
enough to triage a directory of downloaded models before committing to a full import.

InfoBhoomi's converter (user/services/ifc/ifc2cityjson_cadastral.py) has two hard
requirements and one silent one:

  HARD   at least one IfcBuilding      -> process_ifc() raises "No IfcBuilding found."
  SILENT at least one IfcSpace         -> no error, but zero legal volumes are produced,
                                          which is the failure mode that wastes an
                                          afternoon before anyone notices
  IGNORED IfcMapConversion             -> the converter georeferences manually from an
                                          anchor, so georeferencing presence does not
                                          affect import. It is reported anyway because
                                          its prevalence is a result in its own right.

Usage:
    python3 ifc_fitness_scan.py FILE_OR_DIR [FILE_OR_DIR ...]
    python3 ifc_fitness_scan.py --csv out.csv  models/
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

ENTITIES = [
    "IFCBUILDING", "IFCBUILDINGSTOREY", "IFCSPACE", "IFCZONE",
    "IFCWALL", "IFCWALLSTANDARDCASE", "IFCSLAB", "IFCDOOR", "IFCWINDOW",
    "IFCMAPCONVERSION", "IFCPROJECTEDCRS", "IFCSITE",
    "IFCRELSPACEBOUNDARY", "IFCRELSPACEBOUNDARY2NDLEVEL",
    "IFCPROPERTYSET", "IFCTRIANGULATEDFACESET", "IFCPOLYGONALFACESET",
    "IFCFACETEDBREP", "IFCEXTRUDEDAREASOLID",
]

# "#12=IFCSPACE(" or "#12= IFCSPACE (" — count instantiations, not references
ENTITY_RE = re.compile(r"^\s*#\d+\s*=\s*([A-Z0-9_]+)\s*\(", re.IGNORECASE)


def scan(path: str) -> dict:
    counts = {e: 0 for e in ENTITIES}
    schema = "unknown"
    length_unit = "unknown"
    site_geo = False
    total_entities = 0

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        head = []
        for i, line in enumerate(fh):
            if i < 60:
                head.append(line)
            m = ENTITY_RE.match(line)
            if m:
                total_entities += 1
                name = m.group(1).upper()
                if name in counts:
                    counts[name] += 1
            up = line.upper()
            if "IFCSIUNIT" in up and ".LENGTHUNIT." in up:
                if ".MILLI." in up:
                    length_unit = "millimetre"
                elif ".METRE." in up:
                    length_unit = "metre"
            if "IFCCONVERSIONBASEDUNIT" in up and "LENGTHUNIT" in up:
                length_unit = "imperial/derived"
            if "IFCSITE" in up and ("REFLATITUDE" in up or re.search(r"\(\s*-?\d+\s*,\s*-?\d+\s*,\s*-?\d+", line)):
                site_geo = True

        header = "".join(head)

    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", header, re.IGNORECASE)
    if m:
        schema = m.group(1)

    # verdict
    blockers, warnings = [], []
    if counts["IFCBUILDING"] == 0:
        blockers.append("no IfcBuilding — converter raises RuntimeError")
    if counts["IFCSPACE"] == 0:
        blockers.append("no IfcSpace — imports silently with zero legal volumes")
    if counts["IFCSPACE"] and counts["IFCSPACE"] < 3:
        warnings.append(f"only {counts['IFCSPACE']} space(s) — thin for a corpus member")
    if length_unit == "imperial/derived":
        warnings.append("non-SI length unit — check unit scaling")
    if counts["IFCMAPCONVERSION"] == 0:
        warnings.append("no IfcMapConversion — manual georeferencing required")
    if counts["IFCRELSPACEBOUNDARY"] == 0 and counts["IFCRELSPACEBOUNDARY2NDLEVEL"] == 0:
        warnings.append("no space boundaries — party-wall semantics unavailable")

    return {
        "file": os.path.basename(path),
        "path": path,
        "size_mb": round(os.path.getsize(path) / 1_048_576, 2),
        "schema": schema,
        "length_unit": length_unit,
        "entities": total_entities,
        "buildings": counts["IFCBUILDING"],
        "storeys": counts["IFCBUILDINGSTOREY"],
        "spaces": counts["IFCSPACE"],
        "zones": counts["IFCZONE"],
        "space_boundaries": counts["IFCRELSPACEBOUNDARY"] + counts["IFCRELSPACEBOUNDARY2NDLEVEL"],
        "map_conversion": counts["IFCMAPCONVERSION"],
        "projected_crs": counts["IFCPROJECTEDCRS"],
        "property_sets": counts["IFCPROPERTYSET"],
        "brep": counts["IFCFACETEDBREP"],
        "tessellated": counts["IFCTRIANGULATEDFACESET"] + counts["IFCPOLYGONALFACESET"],
        "extruded": counts["IFCEXTRUDEDAREASOLID"],
        "usable": not blockers,
        "blockers": "; ".join(blockers),
        "warnings": "; ".join(warnings),
    }


def collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                out += [os.path.join(root, f) for f in sorted(files) if f.lower().endswith(".ifc")]
        elif p.lower().endswith(".ifc"):
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--csv", help="also write results to this CSV")
    args = ap.parse_args()

    files = collect(args.paths)
    if not files:
        print("No .ifc files found.", file=sys.stderr)
        return 1

    rows = [scan(f) for f in files]

    hdr = f"{'file':<44}{'schema':<10}{'unit':<12}{'bldg':>5}{'spc':>5}{'bnd':>5}{'psets':>7}{'mapconv':>9}  verdict"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        verdict = "USABLE" if r["usable"] else "UNUSABLE"
        print(f"{r['file'][:43]:<44}{r['schema'][:9]:<10}{r['length_unit'][:11]:<12}"
              f"{r['buildings']:>5}{r['spaces']:>5}{r['space_boundaries']:>5}"
              f"{r['property_sets']:>7}{r['map_conversion']:>9}  {verdict}")
        if r["blockers"]:
            print(f"{'':<44}BLOCKER : {r['blockers']}")
        if r["warnings"]:
            print(f"{'':<44}note    : {r['warnings']}")

    n_ok = sum(1 for r in rows if r["usable"])
    n_geo = sum(1 for r in rows if r["map_conversion"])
    print("-" * len(hdr))
    print(f"{len(rows)} file(s): {n_ok} usable, {len(rows) - n_ok} unusable. "
          f"{n_geo}/{len(rows)} carry an IfcMapConversion.")

    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"CSV written: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
