# Paper 1 — Where the models come from, what is recorded, and how it is verified

Companion to `PAPER1_CORPUS_PLAN.md`. Written 2026-08-30; all availability checks and all
verification results below were produced on that date against files in this repository.

---

## A. Where to find IFC models

### A1. Sources checked and reachable

| Source | What it holds | Use for this study |
|---|---|---|
| **buildingSMART Sample-Test-Files** (github.com/buildingSMART/Sample-Test-Files) | Official sample and test files, IFC 4.0.2.1 and IFC 4.3.2.0. Carries a LICENSE file — read it before redistributing | Schema-conformance edge cases; authoritative provenance |
| **Open IFC Model Repository**, University of Auckland (openifcmodel.cs.auckland.ac.nz) | A curated academic collection of complete building models | The main pool of production-style models |
| **STEP Tools sample IFC files** (steptools.com/docs/stpfiles/ifc/) | IFC2x3 and IFC4 samples; the page is copyright STEP Tools, terms not stated openly | Useful, but check terms before publishing derived data |
| **BIMData curated list** (github.com/bimdata/BIMData-Research-and-Development) | An index pointing at model collections rather than a collection itself | Discovery |
| **Duplex Apartment** (github.com/MadsHolten/BOT-Duplex-house) | The widely used two-unit residential model | A genuine multi-unit case — directly relevant to strata |
| **Schependomlaan** (github.com/ibpsa/project1-wp-2-2-bim) | A well-known Dutch residential building used in research | Production-authored, frequently cited |

### A2. Screen before you commit

Run every candidate through the screening tool before spending time on it:

```
python3 scripts/ifc_fitness_scan.py <folder> --csv candidates.csv
```

Reject anything with no `IfcBuilding` (hard failure) or no `IfcSpace` (silent failure —
imports cleanly and yields zero legal volumes). Prefer models that also carry
`Qto_SpaceBaseQuantities`, for the reason set out in §C2.

### A3. What these models cannot give you

None of them carries a registered condominium plan. They support the round-trip, validity
and detection analyses; they cannot support a claim of legal materiality. That still
requires Route C of the corpus plan.

---

## B. What is recorded

`scripts/roundtrip_metrics.py` writes one row per legal volume, plus a run-level summary.

### B1. Per legal volume

| Field | Unit | Meaning | How obtained |
|---|---|---|---|
| `id` | — | IFC GlobalId | read from the source file |
| `name` | — | space name or long name | read from the source file |
| `status` | — | `ok`, `no_geometry`, `no_solid_emitted` | outcome of extraction |
| `v_src_m3` | m³ | volume of the source mesh in the local metric frame | divergence theorem over the triangle set |
| `v_out_m3` | m³ | volume recovered from the emitted geometry | inverse of the converter's own projection |
| `dv_m3`, `dv_pct` | m³, % | signed difference and percentage | `v_out − v_src` |
| `v_proj_m3` | m³ | volume recovered by an **independent** geodetic reprojection to EPSG:5235 | pyproj |
| `dv_proj_pct` | % | signed difference under that independent reprojection | — |
| `proj_disp_mm` | mm | worst horizontal displacement under that reprojection | per-vertex |
| `v_naive_stored_units` | degree²·m | volume as a naive computation on the stored coordinates would return | shows what the stored units actually mean |
| `max_vertex_disp_mm` | mm | worst vertex displacement under self-inversion | — |
| `src_tris`, `out_tris` | count | triangles in and out | — |
| `src_verts`, `out_verts` | count | vertices in and out | — |
| `src_watertight`, `out_watertight` | bool | every undirected edge used exactly twice | edge-pairing test |
| `src_unpaired_edges`, `out_unpaired_edges` | count | edges failing that test | — |

### B2. Per run

File name and size, IFC load seconds, geometry seconds, spaces total / measured / without
geometry, counts of watertight source and output, total vertices lost, and the median and
maximum of the absolute percentage deltas under both the self-inversion and the independent
reprojection.

### B3. Why two volume comparisons are recorded rather than one

`dv_pct` inverts the converter's own equirectangular formula, and therefore returns zero to
floating-point precision. It measures nothing about fidelity and is retained only as a
control: a non-zero value would indicate a coding fault in the encoder or the harness.
`dv_proj_pct` reprojects the stored coordinates with an independent geodetic
transformation, which is what any real consumer of an EPSG:4326 geometry does, and it is the
number that carries meaning.

---

## C. Manual verification

Every quantity in this study can be checked by hand or by an independent tool. Five levels,
from arithmetic to instrument.

### C1. Analytic check — arithmetic on a known solid

For a synthetic member with stated dimensions, the volume is a hand calculation: a
3 m × 4 m × 10 m box is 120 m³, and `v_src_m3` must return it. This verifies the volume
integration, the unit scaling and the mesh extraction in one step, with a pocket
calculator. It is the reason the synthetic arm exists.

### C2. Cross-check against quantities authored inside the file — **already performed**

Many IFC files carry `Qto_SpaceBaseQuantities` or an equivalent, in which the authoring BIM
application records its own `GrossVolume` for each space. That number is produced by a
different program, from the parametric definition rather than from the tessellation, and is
therefore genuinely independent of everything measured here.

Both models in this repository carry these quantities on **every** space. Comparing them
against the volume computed by our harness:

| Model | Spaces compared | Authored unit | Maximum relative difference |
|---|---|---|---|
| `IFC_01.ifc` | 129 | m³ | 3.4 × 10⁻¹² % |
| `simple-model-spaces01.ifc` | 5 | ft³ | 3.2 × 10⁻¹¹ % |

Agreement is at floating-point identity. The harness's volume computation is therefore
verified against an independent source, not merely self-consistent.

Two observations from this check are worth carrying into the paper. First, the second model
declares space heights in millimetres while stating volumes in cubic feet — a unit
inconsistency inside the authored quantities themselves, which had to be resolved before the
comparison could be made (1 m³ = 35.3146667215 ft³). Unit declaration is not a formality.
Second, this check is free wherever the quantities exist, so `Qto_SpaceBaseQuantities` should
be a preference criterion when selecting corpus models.

### C3. Geodetic check — pencil and paper

The scale error underlying Finding 1 is verifiable from first principles, with no software:

- metres per degree of latitude used by the converter: π·a/180 = 111 319.49 m, taking the
  WGS84 semi-major axis as a sphere radius;
- true meridian arc per degree at φ = 6.9°: π·M/180 = 110 590.30 m, with
  M = a(1−e²)/(1−e² sin²φ)^{3/2};
- ratio 1.006594, so a north–south distance is over-stated by 0.6594%;
- volume is scaled in one dimension only, so the predicted volume error is −0.655%.

Measured: −0.6505%. Agreement to within 0.005 percentage points. Any surveyor can reproduce
this in a few lines, which is precisely what makes it a finding rather than an anomaly.

### C4. Independent software check

Load the same model in a third-party tool — the FZK Viewer, Bonsai/BlenderBIM, or any
IFC-capable BIM application — and read the space volume from its own quantity take-off.
This checks the geometry extraction path rather than the arithmetic, and catches errors in
tessellation settings that C1 and C2 would not.

### C5. Database check, once PostGIS is running

With the geometry actually stored, compare `ST_Area`, `ST_3DArea` and the closure of the
stored geometry against the harness's figures. This is the check that closes the gap between
what has been measured so far — the geometry emitted for storage — and what the database
holds. It is outstanding.

### C6. Field check, for the real arm

For a real building, the ultimate reference is a tape or a disto: measure a room, compare
with the registered plan area and with the value the pipeline produces. This is the only
check that also tests the area-measurement convention, and it is the one a cadastral
audience will find most persuasive.

---

## D. What verification has and has not established

| Claim | Verified how | Status |
|---|---|---|
| Volume computation is correct | Against `GrossVolume` authored by the BIM application, 134 spaces, agreement at floating-point identity | **Verified** |
| A systematic −0.65% bias exists | Analytically from geodetic first principles, and empirically on 136 spaces, agreeing to 0.005 pp | **Verified** |
| The bias is legally material | Arithmetic on a 100 m² unit gives 0.65 m² | **Verified**, pending a stated registration threshold |
| Stored geometry is watertight in coordinates | Edge-pairing on exact coordinates, 136 of 136 | **Verified** |
| The stored *type* guarantees nothing | `MULTIPOLYGON Z` is a surface collection by definition | **True by the standard**, no measurement needed |
| The database preserves any of this | — | **Not yet tested.** Requires C5 |
| Real buildings behave as these models do | — | **Not yet tested.** Requires the real arm |
