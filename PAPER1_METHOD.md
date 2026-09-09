# Paper 1 — Method Design

Companion to `PAPER1_ROUNDTRIP_PROBLEM.md`. Target: ISPRS IJGI.
Status: drafted 2026-08-30, incorporating the four scope refinements.

---

## 1. Design overview

A controlled, fully paired experiment. Every legal volume in the corpus passes through
every pipeline condition, so all comparisons are within-subject.

- **Factor of interest:** encoding condition (baseline → ablation ladder → full profile).
- **Ground truth:** two arms — synthetic solids with analytically known volumes
  (precision), and real buildings with registered condominium plans (relevance).
- **Outcome:** a survival matrix, property class × pipeline stage, at three tolerances.

The round trip alone measures *self-consistency* — a pipeline can round-trip a wrong
volume perfectly. Accuracy claims come only from the ground-truth arms.

---

## 2. Units of analysis

| Level | Role |
|---|---|
| **Legal volume** (`IfcSpace` → CityJSON `BuildingRoom` → LSBU) | **Primary.** Sample size, statistics, and every headline number are per-volume. |
| **Face** | Derived diagnostic. Where semantic loss lives (which face was a party wall), where planarity is measured, and where validity failures are counted (degenerate faces, unpaired edges). |
| **Building** | Derived diagnostic. Sum-of-parts check: private units + common property = building envelope, no gaps, no double counting. |

**Parcel footprint link.** Kept in scope, but as an *attribute of the volume*, not a
separate unit. Georeferencing error determines whether the volume lands on the correct
parcel, which is a legal outcome rather than a geometric one. Operationalised as:
(a) binary — does the volume's footprint fall within its registered parcel; and
(b) continuous — horizontal displacement of the footprint centroid, in metres.

---

## 3. Corpus and ground truth

### 3.1 Synthetic arm (precision control)

Parametrically generated IFC with analytically exact volumes — no survey uncertainty, so
pipeline error is isolated from input error. Seeded by the existing generator at
`3D-Cadastre/IFC/create_three_storey_land_parcel_ifc.py`.

Required members, each with a closed-form volume:
- Rectangular box (control; the 120 m³ reference solid).
- Prism with sloped upper surface (the 160 m³ attic case) — tests non-axis-aligned faces.
- Multi-storey stack — tests vertical adjacency and shared horizontal faces.
- Unit with a re-entrant (L-shaped) plan — tests non-convexity.
- Two units sharing a party wall — the semantic case, and the sum-of-parts case.
- Deliberately degenerate members: near-coplanar faces, a sliver face, an unclosed shell.
  These are **not** discarded; they measure whether the pipeline *detects* invalidity or
  silently propagates it.

### 3.2 Real arm (legal relevance)

Real IFC models of buildings with registered condominium plans. The plan area is the legal
reference against which "legally material error" is claimed.

**Area-convention confound — must be handled explicitly.** Registered plans state *areas*
to a specific measurement convention (inner face / centre-line, balconies included or
excluded). If that convention differs from where `IfcSpace` places its boundary, the offset
will exceed the pipeline error being measured. Procedure:
1. Record the convention used by each plan.
2. Compute the convention offset independently, per unit.
3. Report pipeline error and convention offset as **separate terms**; never fold them.
An unresolvable convention disqualifies the model from the accuracy analysis, though it may
still be used in the round-trip (self-consistency) analysis.

### 3.3 Ground-truth claims each arm supports

| Arm | Supports |
|---|---|
| Synthetic | Accuracy against exact volume; validity detection; ablation attribution. |
| Real | Legal materiality; generalisation to production IFC; failure modes absent from clean synthetic input. |
| Round trip (both arms) | Self-consistency, survival matrix, n-cycle drift. |

---

## 4. Conditions

Conditions are **frozen before any measurement is collected.** If the profile changes
after collection begins, the run is discarded and re-collected in full.

| Id | Condition | CRS | Geometry type | Semantics carrier | Tolerance |
|---|---|---|---|---|---|
| C0 | Baseline (as-is) | EPSG:4326 | `MULTIPOLYGON Z` | dropped / partial columns | 1e-7° grid snap |
| C1 | +CRS | EPSG:5235 | `MULTIPOLYGON Z` | dropped | 1e-7° equiv. |
| C2 | +geometry type | EPSG:4326 | closed `POLYHEDRALSURFACE Z`, validated | dropped | 1e-7° |
| C3 | +semantics carrier | EPSG:4326 | `MULTIPOLYGON Z` | per-face semantic array + Pset JSONB | 1e-7° |
| C4 | +tolerance | EPSG:4326 | `MULTIPOLYGON Z` | dropped | explicit 1 mm, applied in projected frame |
| C5 | Full profile | EPSG:5235 | closed `POLYHEDRALSURFACE Z`, validated | per-face semantic array + Pset JSONB | 1 mm metric |

**One factor at a time (C1–C4), plus the full profile (C5).** Factors are expected to
interact — a 1e-7° grid means a different physical distance than a 1 mm metric tolerance,
so CRS and tolerance are not independent. Where the sum of individual effects ≠ the C5
effect, report the interaction rather than suppressing it.

The ablation is what upgrades the claim from "our profile is better" to an attributable
statement, e.g. *"CRS accounts for the majority of geometric error while geometry type
accounts for all validity failures."*

---

## 5. Round-trip protocol

Pipeline stages:

- **S0** — source IFC
- **S1** — CityJSON after conversion
- **S2** — PostGIS stored representation
- **S3** — CityJSON reconstructed from the database

Transitions measured: S0→S1, S1→S2, S2→S3, and end-to-end S0→S3.

### 5.1 Isolation rule (non-negotiable)

The back-conversion S2→S3 is a **genuine reconstruction read from the database only**. It
runs as a separate process whose sole input is a DB connection. It has no access to the
source IFC, the S1 CityJSON, or any in-memory or on-disk cache from the forward pass.
Enforced by: separate process, no filesystem path to the corpus, and a logged assertion of
open file handles. State this explicitly in the paper — a carried-over value inflates the
survival rate and a reviewer will look for it.

### 5.2 Object matching

Matching is performed **twice**, independently:
- **M1** — by declared object identifier.
- **M2** — by geometric nearest-neighbour (centroid, with volume as tie-break).

Metrics are computed on M2 pairs. **Disagreement between M1 and M2 is the identity-loss
metric** — this avoids the circularity of using the identifier to measure identifier
stability.

### 5.3 n-cycle drift test

The full chain is not invertible: there is no CityJSON→IFC direction, so cycle 2 has no
IFC to begin from. The n-cycle test therefore runs over the **CityJSON → PostGIS →
CityJSON sub-loop only**, n = 10, per condition.

Pre-registered prediction: under C0, the fixed 1e-7° grid snap should make the transform
idempotent, with drift reaching a fixed point after one or two cycles. Monotonic drift
would indicate a repeated non-idempotent transform — a per-cycle 4326↔metric reprojection
being the prime candidate. Either outcome is reportable; stating the prediction in advance
makes it a test rather than an exploration.

---

## 6. Metrics and the survival matrix

### 6.1 What a metric is — three measurement types

Not every loss is a delta. Three types are measured, and they must not be conflated.

**Type 1 — continuous deltas (a true Δ, with units).** Report **signed**, not absolute.
If tessellation systematically under-reports sloped or curved volumes, every registered
unit is short in the same direction: that is a bias, which is both a stronger finding
than scatter and a correctable one. Report the signed mean (bias) separately from the
spread.

| Quantity | Δ reported as | Why it is in the paper |
|---|---|---|
| Floor area | Δ m² and Δ % | The figure that appears on the condominium plan — the legal number |
| Volume | Δ m³ and Δ % | The 3D legal object itself |
| Vertex position | mm — mean, 95th pct, max | Where the shape moved |
| Whole-shape difference | symmetric Hausdorff distance, mm | Worst-case boundary displacement |
| Face flatness | planarity RMS residual, mm | A face that was planar in IFC may not be after re-encoding |
| Footprint position | horizontal displacement of centroid, m | Decides parcel assignment |

**Type 2 — count deltas.** Δ in vertex count, face count, object count. 480 vertices in
and 476 out means four were welded away; which four, and whether they were load-bearing
for the shape, is a face-level diagnostic.

**Type 3 — binary, where no delta exists.** Watertight or not. Manifold or not. Semantic
label present or absent. Parent–child link present or absent. Identifier preserved or
not. These do not shrink by a margin; they are there or they are gone, and they are
reported as pass rates.

**The asymmetry (important).** Type 3 failures *destroy* Type 1 measurements. If a room
arrives as a set of loose panels that no longer enclose anything, its volume is not off
by 0.3 m³ — it is **undefined**, and no area or volume can be computed at all. That is a
strictly worse outcome than any delta, and it is invisible in a study that reports only
deltas. This is why coordinate and topology are separate rows of the survival matrix, and
why a volume that fails closure is recorded as `undefined`, never as a large error and
never dropped from the sample.

### 6.2 Metrics by property class

| Class | Metrics | Type |
|---|---|---|
| **Coordinate** | Vertex displacement (mean, 95th pct, max); symmetric Hausdorff distance; signed volume delta ΔV and ΔV/V; signed floor-area delta ΔA and ΔA/A; planarity RMS residual per face; footprint centroid displacement | 1 |
| **Topology** | Watertight closure; manifoldness (every edge bounded by exactly 2 faces); orientation consistency; self-intersection present; vertex and face count delta | 3, plus 2 for the counts |
| **Semantics** | Per-face semantic surface type retention; party-wall face identifiable; LADM class / RRR mapping retention | 3 |
| **Identity** | M1–M2 matching disagreement; parent/child link retention; LSBU `component_units` membership retention | 3 |
| **Attribute** | IFC Pset key-value retention rate; LoD declaration; CRS and georeferencing metadata; unit declaration; storey assignment | 3, reported as a rate |

### 6.3 The survival matrix (paper's main figure)

Rows = property class. Columns = S0→S1, S1→S2, S2→S3, end-to-end. One matrix per
condition. Each cell reports **% of volumes surviving at tolerance ε**, with ε ∈
{1 mm, 10 mm, 100 mm} so the cliff is visible. Classes that are inherently binary
(closure, manifoldness — Type 3 in §6.1) report pass rate and are marked tolerance-independent.
Volumes whose closure failed are reported as `undefined` in the coordinate row, not as a
large delta and not excluded.

A single aggregate survival figure is **not** reported. Coordinates, topology, semantics
and identity fail in different ways and for different reasons; aggregating makes the loss
unattributable, which defeats the purpose of the taxonomy.

### 6.4 Legally material error thresholds (RQ2)

Each metric is additionally classified against the legal outcome it can change:

| Legal outcome | Driven by | Threshold |
|---|---|---|
| Registered floor area | coordinate, convention offset | to be set from Sri Lankan condominium registration practice |
| Registered volume | coordinate, topology (closure) | as above |
| Share fraction (condominium) | volume ratios across units in a building | derived — any error that changes a rounded share |
| Overlap / double-registration detection | topology, coordinate | any error that flips an intersection test |
| Parcel assignment | georeferencing | binary: footprint inside correct parcel |

---

## 7. Analysis plan

- Fully paired design: each volume passes through all conditions → paired comparisons.
- Error distributions are expected to be non-normal and heavy-tailed (a few pathological
  units dominating). Use Wilcoxon signed-rank rather than paired t; report medians with
  bootstrapped CIs.
- Report **effect sizes and confidence intervals**, not p-values alone.
- Report per-volume outliers individually; in a cadastre the tail is the point.
- Synthetic and real arms analysed separately and never pooled.

---

## 8. Reproducibility

Pin and report: ifcopenshell, GEOS, PostGIS, PostgreSQL, shapely, pyproj versions. GEOS
version already demonstrably changes validity outcomes in this pipeline — it is a
controlled variable, not an implementation detail. Publish the synthetic corpus generator,
the metric harness, and the condition definitions.

---

## 9. Threats to validity

| Threat | Mitigation |
|---|---|
| Source IFC is itself non-manifold — ground truth undefined | Synthetic arm gives exact volumes; degenerate members measure detection rather than accuracy |
| Area-convention offset swamps pipeline error (real arm) | Measured and reported as a separate term (§3.2) |
| Survival rate inflated by carry-over | Process isolation rule (§5.1) |
| Circular identity measurement | Dual matching M1/M2 (§5.2) |
| Small n in the real arm | Synthetic arm carries the statistical claims; real arm carries materiality |
| Single-implementation generalisation | Profile stated as format-level requirements, not InfoBhoomi API calls; ablation isolates which requirement does the work |

---

## 10. Open items

- Corpus size: how many synthetic members, how many real buildings.
- Source of real condominium models and their registered plans.
- Numeric legally-material thresholds (§6.4) — needs Sri Lankan registration practice.
- Whether the PostGIS→CityJSON exporter is a paper artefact or production code.
