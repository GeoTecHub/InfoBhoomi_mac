# Paper 1 — Results table skeletons

Draft tables for the Results section of *"How Much of a Legal Volume Survives?"*

> **WARNING — READ BEFORE USE.** Every number in Tables 3–8 is a **placeholder**,
> written only to show the shape of the table. They are marked `‹…›`. Nothing here is a
> measurement. Delete or overwrite every `‹…›` cell before the draft goes to anyone.
> The only real values in this file are marked **†** and come from `corpus/scan_routeA.csv`
> and `FINDING_01_MERIDIAN_SCALE.md`.

Table numbering continues from Tables 1–2 (corpus and trait coverage).

---

## Table 3. Corpus as measured — inputs to the harness

One row per model. This is the "what went in" table; it is filled from the fitness scan
and needs no pipeline run.

| Model | Schema | Unit | Legal volumes (`IfcSpace`) | Space boundaries | Faces (S0) | Watertight at S0 (n / %) | Total source volume (m³) |
|---|---|---|---|---|---|---|---|
| Schependomlaan | IFC2X3 † | mm † | 100 † | 1675 † | ‹…› | ‹…› | ‹…› |
| AC-20-Smiley-West-10-Bldg | IFC4 † | m † | 140 † | 1689 † | ‹…› | ‹…› | ‹…› |
| AC20-Institute-Var-2 | IFC4 † | m † | 82 † | 1000 † | ‹…› | ‹…› | ‹…› |
| Duplex Architecture | IFC2X3 † | m † | 21 † | 265 † | ‹…› | ‹…› | ‹…› |
| AC20-FZK-Haus | IFC4 † | m † | 7 † | 81 † | ‹…› | ‹…› | ‹…› |
| SampleHouse IFC4 | IFC4 † | m † | 4 † | 0 † | ‹…› | ‹…› | ‹…› |
| **Total** | | | **354** † | **4710** † | ‹…› | ‹…› | ‹…› |

*Note.* A volume that is not watertight at S0 has no defined source volume; it is counted
in the sample but its `v_in_m3` is blank (§6.1, Type-3 asymmetry).

---

## Table 4. Survival matrix — the paper's main table

Rows = property class. Columns = pipeline transition. Cells = **% of the 354 volumes
surviving at tolerance ε**. One table per condition; this one is **C0 (baseline)**.
Repeat as Table 4a–4f for C1–C5, or move C1–C5 to an appendix and keep only C0 and C5
in the body.

| Property class | ε | S0→S1 | S1→S2 | S2→S3 | End-to-end S0→S3 |
|---|---|---|---|---|---|
| **Coordinate** | 1 mm | ‹…› | ‹…› | ‹…› | ‹…› |
| | 10 mm | ‹…› | ‹…› | ‹…› | ‹…› |
| | 100 mm | ‹…› | ‹…› | ‹…› | ‹…› |
| **Topology** (closure, manifold) | n/a ‡ | ‹…› | ‹…› | ‹…› | ‹…› |
| **Semantics** (face type, party wall) | n/a ‡ | ‹…› | ‹…› | ‹…› | ‹…› |
| **Identity** (M1↔M2, parent link) | n/a ‡ | ‹…› | ‹…› | ‹…› | ‹…› |
| **Attribute** (Pset, CRS, unit, storey) | n/a ‡ | ‹…› | ‹…› | ‹…› | ‹…› |
| *Volumes undefined (closure failed)* | | ‹…› | ‹…› | ‹…› | ‹…› |

‡ tolerance-independent — binary pass rate (§6.3).
No aggregate "overall survival" row is reported, by design.

---

## Table 5. Continuous error, by transition — C0

Signed, so bias is visible separately from spread. Volumes whose closure failed are
excluded from this table only, and their count is stated in the caption.

| Metric | Unit | S0→S1 | S1→S2 | S2→S3 | S0→S3 |
|---|---|---|---|---|---|
| Volume delta ΔV — median (IQR) | % | **−0.650** † ‹IQR› | ‹…› | ‹…› | ‹…› |
| Volume delta ΔV — signed mean (bias) | % | **−0.65** † | ‹…› | ‹…› | ‹…› |
| Floor area delta ΔA — median (IQR) | % | ‹…› | ‹…› | ‹…› | ‹…› |
| Vertex displacement — mean | mm | ‹…› | ‹…› | ‹…› | ‹…› |
| Vertex displacement — 95th pct | mm | ‹…› | ‹…› | ‹…› | ‹…› |
| Vertex displacement — max | mm | ‹…› | ‹…› | ‹…› | ‹…› |
| Symmetric Hausdorff distance — median | mm | ‹…› | ‹…› | ‹…› | ‹…› |
| Planarity RMS residual — median | mm | ‹…› | ‹…› | ‹…› | ‹…› |
| Footprint centroid displacement — median | m | ‹…› | ‹…› | ‹…› | ‹…› |
| Vertex count delta | count | ‹…› | ‹…› | ‹…› | ‹…› |
| Face count delta | count | ‹…› | ‹…› | ‹…› | ‹…› |

† Analytically predicted −0.655%, measured −0.6505% against `Qto_SpaceBaseQuantities` on
134 spaces (Finding 1 — equirectangular metres-per-degree constant).

---

## Table 6. Synthetic arm — accuracy against known truth

The only arm with an exact reference volume. This table carries the accuracy claim;
Tables 4–5 carry only self-consistency.

| Member | Tests | True V (m³) | V at S1 | ΔV (%) | V at S3 | ΔV (%) | Closure S3 | Detected as invalid? |
|---|---|---|---|---|---|---|---|---|
| Rectangular box (control) | baseline | 120.000 | ‹…› | ‹…› | ‹…› | ‹…› | ‹Y/N› | n/a |
| Sloped-top prism (attic) | non-axis-aligned faces | 160.000 | ‹…› | ‹…› | ‹…› | ‹…› | ‹Y/N› | n/a |
| Multi-storey stack | vertical adjacency | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› | ‹Y/N› | n/a |
| L-shaped unit | non-convexity | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› | ‹Y/N› | n/a |
| Two units, shared party wall | semantics, sum-of-parts | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› | ‹Y/N› | n/a |
| Near-coplanar faces | detection | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› | ‹Y/N› | ‹Y/N› |
| Sliver face | detection | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› | ‹Y/N› | ‹Y/N› |
| Unclosed shell | detection | undefined | undefined | — | undefined | — | N | ‹Y/N› |

*Last column is the point of the degenerate members: silent propagation is the failure,
not the error magnitude.*

---

## Table 7. Ablation ladder — attributing the loss

One row per condition, so the reader can see which single change does the work.
`Δ from C0` is the improvement over baseline.

| Id | Change from baseline | Coordinate survival @10 mm (%) | Topology pass (%) | Semantics retention (%) | Identity retention (%) | Median \|ΔV\| (%) |
|---|---|---|---|---|---|---|
| C0 | baseline (as-is) | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› |
| C1 | + projected CRS (EPSG:5235) | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› |
| C2 | + closed `POLYHEDRALSURFACE Z` | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› |
| C3 | + semantic carrier | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› |
| C4 | + explicit 1 mm tolerance | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› |
| C5 | full profile | ‹…› | ‹…› | ‹…› | ‹…› | ‹…› |
| | **Σ(C1..C4) − C0 vs C5 − C0** | ‹interaction› | ‹interaction› | ‹interaction› | ‹interaction› | ‹interaction› |

The last row is where the interaction is reported rather than suppressed (§4).

---

## Table 8. n-cycle drift, CityJSON→PostGIS→CityJSON sub-loop

Pre-registered prediction: fixed point after 1–2 cycles under C0. Monotonic growth would
indicate a non-idempotent per-cycle reprojection.

| Cycle n | Median vertex displacement from n=0 (mm) | Max (mm) | Volumes still watertight (%) |
|---|---|---|---|
| 1 | ‹…› | ‹…› | ‹…› |
| 2 | ‹…› | ‹…› | ‹…› |
| 3 | ‹…› | ‹…› | ‹…› |
| 5 | ‹…› | ‹…› | ‹…› |
| 10 | ‹…› | ‹…› | ‹…› |
| | **Fixed point reached at n = ‹…›** *(or: drift monotonic, slope ‹…› mm/cycle)* | | |

---

## Table 9. Legally material error (RQ2)

Ties the geometry to the legal outcome. Cannot be completed until the Sri Lankan
registration thresholds are settled (open item) and Route C data arrives.

| Legal outcome | Threshold | Volumes exceeding it, C0 (n / %) | Volumes exceeding it, C5 (n / %) |
|---|---|---|---|
| Registered floor area | ‹from SL practice› | ‹…› | ‹…› |
| Registered volume | ‹from SL practice› | ‹…› | ‹…› |
| Condominium share fraction | any error changing a rounded share | ‹…› | ‹…› |
| Overlap / double registration | any error flipping an intersection test | ‹…› | ‹…› |
| Parcel assignment | footprint inside correct parcel (binary) | ‹…› | ‹…› |

---

## Notes on which tables go in the body

Suggested split, to keep the body readable:

- **Body:** Tables 1, 2, 4 (C0), 5, 6, 7, 9.
- **Appendix:** Table 3, survival matrices for C1–C5, Table 8, per-volume outlier list.

Table 6 is the one a reviewer will read first — it is the only one with a known truth.
