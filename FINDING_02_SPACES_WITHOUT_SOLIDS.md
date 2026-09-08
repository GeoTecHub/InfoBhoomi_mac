# Finding 2 — a quarter of the corpus's "legal volumes" are not volumes at all

Measured 2026-09-07 with `scripts/space_representation_check.py` and
`scripts/roundtrip_metrics.py` on the six-model Route A corpus.

---

## Result

The corpus contains **354 `IfcSpace` instances but only 260 legal volumes**. The other 94 —
**26.6%** — carry no 3D body representation. They are documented as a 2D footprint curve and a
bounding box, nothing more.

| Model | `IfcSpace` | with `Body` | without | Representations present |
|---|---|---|---|---|
| AC-20-Smiley-West-10-Bldg | 140 | 140 | 0 | Body, Box, FootPrint |
| AC20-Institute-Var-2 | 82 | 82 | 0 | Body, Box, FootPrint |
| Duplex Architecture | 21 | 21 | 0 | Body |
| AC20-FZK-Haus | 7 | 7 | 0 | Body, Box, FootPrint |
| SampleHouse IFC4 | 4 | 4 | 0 | Body |
| **IFC Schependomlaan** | **100** | **6** | **94** | Box ×100, FootPrint ×94, Body ×6 |
| **Total** | **354** | **260** | **94** | |

The whole deficit is in one model, and it is the model most heavily cited in the GeoBIM
literature. Of Schependomlaan's 100 spaces, 94 have `Box` + `FootPrint` and no `Body`; the six
that do have one carry an `IfcExtrudedAreaSolid`. `ifcopenshell.geom.create_shape` raises
"Failed to process shape" on all 94 and succeeds on the 6.

## Why this matters more than a missing-data note

This is a loss that happens **before any encoding**. No CRS, no geometry type, no tolerance and
no database is involved. The building was modelled in a way that never contained the legal
volume, so no conversion chain can preserve it.

It is also silent in exactly the way `Ifc4_Revit_ARC.ifc` was silent — the file that was rejected
from the corpus for having zero `IfcSpace`. Schependomlaan is the same failure at 94%
instead of 100%, and it passes the fitness scan cleanly because the scan counts `IfcSpace`
instances. **Counting spaces overstates the number of legal volumes a model can supply**, and the
overstatement is invisible unless representations are inspected.

That deserves its own row in the loss taxonomy: a *source-side* loss, distinct from the geometric
and semantic losses the encoding chain introduces. It is not correctable by an encoding profile.
The only remedy is a modelling requirement upstream — which is precisely the kind of clause a
cadastral data specification would have to state.

## Consequences for the paper

- **The corpus figure is 260, not 354.** Every count in §3 and the corpus table must say so.
  Schependomlaan contributes 6 measurable volumes, not 100.
- **`ifc_fitness_scan.py` needs a `spaces_with_body` column.** As it stands, the scanner reports
  Schependomlaan as fully usable and it is 6% usable. The scan is the gate that decides what
  enters the corpus, so a gate that cannot see this is the wrong gate.
- **The n for the real arm is unchanged** — six independent buildings — but the per-model weight
  is not what the space counts suggested.
- Keep Schependomlaan. It is the only non-metre model, it exercises the unit-scale path, and this
  finding is more useful than the 100 volumes would have been.

## What was recorded

Every space now appears in the results, measured or not. `roundtrip_metrics.py` previously wrote
only rows with `status = ok` to its CSV, so the 94 failures existed in the JSON and vanished on
the way to the workbook — a loss of loss data. The CSV writer now emits every space, with the
measurement columns blank and the status carried through. The **Volumes** sheet holds 354 rows:
260 `ok`, 94 `no_geometry`.
