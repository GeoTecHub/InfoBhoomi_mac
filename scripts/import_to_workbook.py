#!/usr/bin/env python3
"""
Load roundtrip_metrics.py output into Paper1_RawData_Template.xlsx (Volumes sheet).

    python3 scripts/import_to_workbook.py results/C0/RA-05.csv \
            --model RA-05 --condition C0 --run RUN-001

    # several files at once
    python3 scripts/import_to_workbook.py results/C0/*.csv --condition C0

Model id is taken from --model, or from the CSV file name if not given.
Existing rows for the same (model, condition) are replaced, so re-running is safe.
Calculated columns are left alone — they are formulas and fill themselves.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

WORKBOOK = "Paper1_RawData_Template.xlsx"
SHEET = "Volumes"
HEADER_ROW = 2
FIRST_DATA_ROW = 4          # row 3 is the example row

# harness column -> workbook column. Anything not listed is ignored.
MAP = {
    "id": "volume_id (IFC GlobalId)",
    "name": "volume_name",
    "status": "status",
    "v_src_m3": "v_src_m3",
    "v_out_m3": "v_out_m3",
    "v_proj_m3": "v_proj_m3",
    "v_naive_stored_units": "v_naive_stored_units",
    "proj_disp_mm": "proj_disp_mm",
    "max_vertex_disp_mm": "max_vertex_disp_mm",
    "src_tris": "src_tris",
    "out_tris": "out_tris",
    "src_verts": "src_verts",
    "out_verts": "out_verts",
    "src_watertight": "src_watertight",
    "out_watertight": "out_watertight",
    "src_unpaired_edges": "src_unpaired_edges",
    "out_unpaired_edges": "out_unpaired_edges",
}

BOOLS = {"true": "Y", "false": "N", "1": "Y", "0": "N", "yes": "Y", "no": "N"}


def clean(col: str, raw: str):
    """Turn a harness string into what the workbook wants."""
    if raw is None or raw == "":
        return None
    s = str(raw).strip()
    if col.endswith(("watertight", "orientation_ok")):
        return BOOLS.get(s.lower(), s)
    try:
        return int(s) if s.lstrip("-").isdigit() else float(s)
    except ValueError:
        return s


def read_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            for key in ("volumes", "spaces", "rows", "results"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise SystemExit(f"{path}: cannot find a list of per-volume records")
        return data
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="metrics CSV or JSON from roundtrip_metrics.py")
    ap.add_argument("--workbook", default=WORKBOOK)
    ap.add_argument("--model", help="model_id (default: the file's stem)")
    ap.add_argument("--condition", required=True, help="C0 … C5")
    ap.add_argument("--run", help="run_id to stamp on every row")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    wb = load_workbook(args.workbook)
    ws = wb[SHEET]
    col = {c.value: c.column for c in ws[HEADER_ROW] if c.value}

    missing = [v for v in MAP.values() if v not in col]
    if missing:
        raise SystemExit(f"workbook is missing columns: {missing}")

    c_model, c_cond, c_run = col["model_id"], col["condition"], col["run_id"]
    written = 0

    for f in args.files:
        path = Path(f)
        model = args.model or path.stem
        rows = read_rows(path)

        # drop any existing rows for this model+condition
        kill = [r for r in range(FIRST_DATA_ROW, ws.max_row + 1)
                if ws.cell(r, c_model).value == model
                and ws.cell(r, c_cond).value == args.condition]
        # only the columns this script owns — never the formula columns
        owned = [c_model, c_cond, c_run] + [col[v] for v in MAP.values()]
        for r in kill:
            for c in owned:
                ws.cell(r, c).value = None

        # first free row
        target = FIRST_DATA_ROW
        while ws.cell(target, c_model).value not in (None, ""):
            target += 1

        for rec in rows:
            ws.cell(target, c_model).value = model
            ws.cell(target, c_cond).value = args.condition
            if args.run:
                ws.cell(target, c_run).value = args.run
            for src, dst in MAP.items():
                if src in rec:
                    ws.cell(target, col[dst]).value = clean(src, rec[src])
            target += 1
            written += 1

        print(f"{path.name:34s} -> {model} / {args.condition}   "
              f"{len(rows)} rows"
              + (f", replaced {len(kill)}" if kill else ""))

    if args.dry_run:
        print(f"\ndry run — {written} rows NOT written")
        return 0

    wb.save(args.workbook)
    print(f"\n{written} rows written to {args.workbook} ({SHEET})")
    print("Open it in Excel once so the calculated columns and Survival_Summary refresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
