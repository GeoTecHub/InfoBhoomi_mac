# Finding 3 — the author-supplied volume is there, under a name the standard does not use

Measured 2026-09-07 with `scripts/space_quantity_check.py` on the six-model Route A corpus.

---

## Result

Grepping the corpus for `Qto_SpaceBaseQuantities`, the IFC4 standard name for a space's base
quantity set, returns **zero hits in all six models**. The quantity set is nevertheless present in
five of the six, under vendor names:

| Model | Spaces | with author `GrossVolume` | Quantity set name as written |
|---|---|---|---|
| AC-20-Smiley-West-10-Bldg | 140 | 140 (100%) | `ARCHICAD BIM Base Quantities` |
| IFC Schependomlaan | 100 | 100 (100%) | `ArchiCAD BIM Base Quantities` |
| AC20-Institute-Var-2 | 82 | 82 (100%) | `ARCHICAD BIM Base Quantities` |
| AC20-FZK-Haus | 7 | 7 (100%) | `ARCHICAD BIM Base Quantities` |
| SampleHouse IFC4 | 4 | 4 (100%) | *(unnamed)* |
| Duplex Architecture | 21 | **0** | — |

**333 of 354 spaces (94%) carry an author-supplied `GrossVolume`.** Note that even the casing
differs between two files from the same authoring tool.

## Why it matters

The author-supplied `GrossVolume` is the independent check on the harness. Without it, the
measured volume is compared only against the harness's own arithmetic; with it, the harness is
checked against a number the BIM author computed by a different route. Losing that check to a
string comparison would be a poor trade.

A check that looks for the standard name alone concludes the corpus has no ground truth and is
wrong by 333 spaces. The quantity set has to be found by **structure** — an `IfcElementQuantity`
containing an `IfcQuantityVolume` named `GrossVolume`, related to the space through
`IfcRelDefinesByProperties` — not by its name.

This is worth one sentence in the paper on its own account. The property- and quantity-set naming
in real IFC files is a vendor convention, not a standard one, and a cadastral consumer that
matches on `Qto_` prefixes will silently find nothing in files that plainly contain the data.
That is the same class of silent failure as Finding 2: not a wrong answer, an empty one.

## Consequences

- `has_qto_spacebasequantities` in the **Models** sheet is recorded `Y` for RA-01, 02, 03, 05, 06
  and `N` for RA-04, on structural grounds. The column name keeps the IFC4 spelling; the meaning
  is "an author-supplied `GrossVolume` is attached to the space".
- **Duplex (RA-04) is the one model with no author volume**, so it has no independent check. Say so
  rather than treating its numbers as equally supported.
- The cross-check itself — harness volume against author `GrossVolume` on 333 spaces — has not been
  run yet. `space_quantity_check.py` establishes that the data exists; comparing the numbers is
  the next step, and it is what would let Finding 1's verification be repeated on this corpus.
