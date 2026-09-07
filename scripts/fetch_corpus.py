#!/usr/bin/env python3
"""
Paper 1 — Route A corpus fetcher.

Downloads the open, publicly available IFC models that were verified on 2026-09-07 to
contain IfcSpace entities, into corpus/routeA/ , and checks each file against a recorded
SHA-256 so the corpus is reproducible by anyone reading the paper.

    python3 scripts/fetch_corpus.py                 # download into corpus/routeA
    python3 scripts/fetch_corpus.py --out somewhere # download elsewhere
    python3 scripts/fetch_corpus.py --verify        # re-check hashes, download nothing

Every entry records where the file came from and under what licence. Read LICENCE NOTES
in PAPER1_CORPUS_FRESH_START.md before redistributing any model or any derived data.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

UA = "Mozilla/5.0 (compatible; InfoBhoomi-Paper1-corpus-fetcher/1.0)"

# name, url, sha256 of the .ifc AFTER any unzip, licence, note
MODELS = [
    dict(
        name="AC20-FZK-Haus.ifc",
        url="https://www.ifcwiki.org/images/e/e3/AC20-FZK-Haus.ifc",
        sha256="70cc8ff245fc0894201d96496c031005a5cbd7a96b22d8a1b87c5a883fb77994",
        licence="KIT/IAI — unrestricted use, credit requested",
        note="Small detached house. 7 spaces, 81 space boundaries. The easiest first run.",
    ),
    dict(
        name="AC20-Institute-Var-2.ifc",
        url="https://www.ifcwiki.org/images/9/98/AC20-Institute-Var-2.ifc",
        sha256="cfb2124497b25d9a72101075e84be0feb44ff669cb1bd3251be11efebeea945c",
        licence="KIT/IAI — unrestricted use, credit requested",
        note="Five-storey office building. 82 spaces, 1000 space boundaries.",
    ),
    dict(
        name="AC-20-Smiley-West-10-Bldg.ifc",
        url="https://www.ifcwiki.org/images/c/c8/AC-20-Smiley-West-10-Bldg.zip",
        zip_member="AC-20-Smiley-West-10-Bldg.ifc",
        sha256="26734e67bdc0fd2ab30cb560bddc279a0a4f23eb4d28861509524e4bbe201c48",
        licence="KIT/IAI — unrestricted use, credit requested",
        note="Residential block, 140 spaces, 1689 space boundaries. The closest thing "
             "to a strata building in the open set.",
    ),
    dict(
        name="Schependomlaan.ifc",
        url="https://raw.githubusercontent.com/openBIMstandards/Archive-DataSetSchependomlaan/"
            "master/Design%20model%20IFC/IFC%20Schependomlaan.ifc",
        sha256="2c3565ca1904f2aa61adab92024cf3755b2c5b21a498144d3094d7cb58cebec7",
        licence="CC BY 4.0",
        note="Dutch residential building, widely cited in GeoBIM research. 100 spaces, "
             "1675 space boundaries. Units are MILLIMETRES — exercises the unit-scale path.",
    ),
    dict(
        name="Duplex_Architecture_IFC2x3.ifc",
        url="https://raw.githubusercontent.com/youshengCode/IfcSampleFiles/master/"
            "Ifc2x3_Duplex_Architecture.ifc",
        sha256="b347a2c8aa8fff6db896a4417a9c50c22ac0ccd7c5cfc22b99b8d29336c606ed",
        licence="NOT STATED in the hosting repository — originally a Common BIM File "
                "(Duplex Apartment). Use freely for measurement; clear redistribution first.",
        note="Two-unit residential. 21 spaces, 265 space boundaries. A genuine multi-unit "
             "case, which is what strata registration looks like.",
    ),
    dict(
        name="SampleHouse_IFC4.ifc",
        url="https://raw.githubusercontent.com/youshengCode/IfcSampleFiles/master/"
            "Ifc4_SampleHouse.ifc",
        sha256="7606dc4e96b538d6fe7f2fa76655f26186d64d0226f8a10fbc141b9f2cd6cbfe",
        licence="NOT STATED in the hosting repository.",
        note="4 spaces, NO space boundaries — keep it as the negative control for the "
             "semantic axis.",
    ),
]

# Downloaded, scanned, and rejected — kept here so the rejection is on the record.
REJECTED = [
    dict(
        name="Ifc4_Revit_ARC.ifc",
        url="https://raw.githubusercontent.com/youshengCode/IfcSampleFiles/master/Ifc4_Revit_ARC.ifc",
        reason="0 IfcSpace — imports cleanly and yields zero legal volumes (silent failure).",
    ),
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, dest.open("wb") as out:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="corpus/routeA", help="output folder")
    ap.add_argument("--verify", action="store_true", help="only check existing files")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    ok = bad = 0
    for m in MODELS:
        target = out / m["name"]

        if not args.verify and not target.exists():
            print(f"downloading {m['name']} ...", flush=True)
            try:
                if "zip_member" in m:
                    tmp = out / (m["name"] + ".zip")
                    download(m["url"], tmp)
                    with zipfile.ZipFile(tmp) as z:
                        with z.open(m["zip_member"]) as src, target.open("wb") as dst:
                            dst.write(src.read())
                    tmp.unlink()
                else:
                    download(m["url"], target)
            except Exception as exc:                       # noqa: BLE001
                print(f"  FAILED: {exc}")
                bad += 1
                continue

        if not target.exists():
            print(f"{m['name']:34s} MISSING")
            bad += 1
            continue

        digest = sha256_of(target)
        if digest == m["sha256"]:
            print(f"{m['name']:34s} OK    {target.stat().st_size/1048576:6.2f} MB   {m['licence']}")
            ok += 1
        else:
            print(f"{m['name']:34s} HASH MISMATCH — the upstream file changed.")
            print(f"    expected {m['sha256']}")
            print(f"    got      {digest}")
            print("    Record the new hash in this script and say so in the paper.")
            bad += 1

    print(f"\n{ok} verified, {bad} problem(s). Files in {out.resolve()}")
    print("\nRejected on the first pass (kept on the record, not downloaded):")
    for r in REJECTED:
        print(f"  {r['name']}: {r['reason']}")
    print("\nNext: python3 scripts/ifc_fitness_scan.py "
          f"{out} --csv corpus/scan_routeA.csv")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
