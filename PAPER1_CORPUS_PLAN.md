# Paper 1 — Corpus acquisition plan

Resolves the open item "test corpus" from `PAPER1_ROUNDTRIP_PROBLEM.md` §8.
Drafted 2026-08-30. External availability checked the same day.

---

## The key point first

**The paper is not blocked on data.** The synthetic arm carries the statistical claims,
and you already own the means to generate it. The real arm carries legal relevance, is
slower to obtain, and can be added later without invalidating anything already measured.
Start the synthetic arm now; start the real-arm paperwork now because it is slow; do not
wait for one before doing the other.

---

## 1. Synthetic arm — build it, starting today

**Source:** extend `3D-Cadastre/IFC/create_three_storey_land_parcel_ifc.py`, which already
generates parametric IFC in this repository.

**Why it is the backbone.** The true volume is known in closed form, so pipeline error is
isolated from input error. There is no acquisition risk, no licence, no ethics approval,
and the corpus can be regenerated exactly — which is what makes the study reproducible.

**Members required** (each with an analytic volume):

| Member | Tests |
|---|---|
| Rectangular box | Control; the simplest possible legal volume |
| Prism with sloped upper surface | Non-axis-aligned faces; the case where tessellation bias should appear |
| Multi-storey stack | Vertical adjacency, shared horizontal faces |
| Re-entrant (L-shaped) plan | Non-convexity |
| Two units sharing a party wall | Semantic case (which face was the party wall) and sum-of-parts case |
| Unit with a void or internal shaft | Interior shell — the case Simple Features geometry handles worst |
| Degenerate set: near-coplanar faces, sliver face, unclosed shell, duplicated vertex | Whether the pipeline **detects** invalidity or silently propagates it |

**Target size:** 8–12 model families, parameterised over dimensions and orientation, giving
roughly 50–80 legal volumes. That is comfortable for paired non-parametric tests across
six conditions.

**Deliberate design choice:** vary orientation and latitude/longitude placement across the
set. A 1 × 10⁻⁷ ° grid corresponds to a different physical distance depending on where and
in which direction it is applied, so placement must vary or the tolerance factor cannot be
separated from the CRS factor.

---

## 2. Real arm — three routes, in order of increasing effort

### Route A — Open IFC models with room spaces (fast, partial)

Publicly available production IFC models can be obtained from the Open IFC Model
Repository hosted by the University of Auckland, the sample IFC files published by STEP
Tools, the curated list maintained in BIMData's public repository, and individual
well-known research models such as the Duplex Apartment and Schependomlaan models that
circulate through public GitHub repositories.

- **Gives you:** real production IFC with real defects — the pathologies documented in the
  literature (open volumes, inconsistent face orientation, intersecting volumes, missing
  or incorrect space boundaries). This is exactly what the synthetic arm cannot supply.
- **Does not give you:** registered plans. Without a registered area, this material
  supports the round-trip (self-consistency), validity and detection analyses, but **not**
  the legal-materiality claim.
- **Effort:** days. **Recommended: do this regardless of what else happens.**
- **Check before use:** licence terms for redistribution, and whether the model actually
  contains `IfcSpace` entities — many published models do not.

### Route B — GeoBIM benchmark models (medium effort, high comparability)

The GeoBIM Benchmark 2019 used three building models — Myran, Up:Town and Savigliano —
which are **not** freely downloadable; access requires a signed data agreement. Only the
"specific geometries" test files are open.

- **Gives you:** models already characterised in a published benchmark, so your results
  become directly comparable with prior work, and reviewers recognise the corpus.
- **Effort:** an email to the benchmark team (TU Delft 3D geoinformation group) plus a data
  agreement. Weeks, not months.
- **Worth doing** if you want the paper to sit inside an existing evidence base rather than
  beside it.

### Route C — Sri Lankan condominium data (slow, but the only route to materiality)

This is the only source of buildings that have both a BIM model and a **registered
condominium plan**, and therefore the only route that supports RQ2's materiality claim.

Possible holders:

- **Condominium Management Authority** — approved condominium plans, unit schedules,
  common-property share values.
- **Survey Department / licensed surveyors** — the surveyed plans behind registration.
- **Developers and their architects** — the BIM models. In Sri Lanka, larger Colombo
  high-rise projects are the realistic candidates, since smaller developments are unlikely
  to have a coordinated IFC export.

- **Effort:** months. Requires a research data request, probably an MoU through the
  university, and almost certainly a confidentiality undertaking, since unit ownership is
  personal data.
- **Start this now**, in parallel with everything else, because the approval time dominates.

**What to ask for, precisely** — not "some condominium data", but:
1. The approved condominium plan for the building (unit schedule with floor areas and
   share values).
2. The measurement convention used for the floor areas — inner face, centre-line, and
   whether balconies and terraces are included. Without this the real arm's confound
   cannot be separated, and the data is much less useful.
3. The architect's or contractor's IFC export for the same building, ideally IFC4 with
   `IfcSpace` entities present.

### Route D — Student-modelled buildings (fallback, declare honestly)

Surveying students model an IFC from an approved condominium plan. This produces paired
IFC and registered area at low cost and is a plausible teaching activity.

**Caveat that must be stated in the paper if this route is used:** because the model is
built *from* the plan, the area-convention offset is zero by construction. The resulting
data is semi-synthetic. It validates the encoding chain against a registered figure, but it
cannot measure the physical-to-legal offset, and it must not be presented as if it could.

---

## 3. A statistical issue the corpus design must respect

Legal volumes within one building are **not independent observations**. They share a
model author, an export setting, a georeferencing decision and a construction geometry.
Treating forty apartments in one building as forty independent samples overstates the
effective sample size, and a reviewer will say so.

Consequences for the design:

- The **building** is the unit of independence in the real arm; the **volume** is the unit
  of measurement. Report both, and either use a mixed-effects model with building as a
  random effect, or report per-building results and treat the building count as n.
- The real arm therefore needs **several buildings**, not one large one. Three to eight
  buildings is a realistic target; a single 40-unit tower is one sample, not forty.
- The synthetic arm does not have this problem, since each model family is generated
  independently — which is a further reason it carries the statistical claims.

---

## 4. Recommended sequence

1. **Now:** extend the synthetic generator; build the full member set including the
   degenerate cases. This unblocks the exporter, the metric harness and every condition.
2. **Now, in parallel:** open the Sri Lankan data request (Route C). It is the long pole.
3. **This week:** collect Route A open models, filter for those containing `IfcSpace`, and
   run them through the baseline to find out what real production defects look like in your
   pipeline. This will also tell you whether the georeferencing prevalence claim in §1.1 of
   the manuscript holds up on a real sample.
4. **If Route C stalls:** fall back to Route D, and declare the semi-synthetic status.
5. **Optional but valuable:** request the GeoBIM benchmark models (Route B) for
   comparability with published results.

---

## 5. What each arm licenses you to claim

| Corpus | Round-trip survival | Validity / detection | Accuracy vs. exact volume | Legal materiality |
|---|---|---|---|---|
| Synthetic | Yes | Yes | Yes | No |
| Open IFC (Route A) | Yes | Yes | No | No |
| GeoBIM benchmark (Route B) | Yes | Yes | No | No |
| Sri Lankan condominium (Route C) | Yes | Yes | No | **Yes** |
| Student-modelled (Route D) | Yes | Yes | No | Partial — convention offset is zero by construction |

Route C is the only cell that unlocks the materiality column, which is what makes the paper
a cadastre paper rather than a conversion-quality paper. That is the reason to start it
today even though it will finish last.


---

## 6. Screening models before you import them — and what a first scan already showed

`scripts/ifc_fitness_scan.py` screens IFC files against what the InfoBhoomi converter
actually requires. It parses the STEP text directly, so it needs no ifcopenshell and can
triage a directory of downloaded models in seconds:

```
python3 scripts/ifc_fitness_scan.py path/to/models/ --csv results.csv
```

### What the converter requires

| Requirement | Behaviour if missing |
|---|---|
| At least one `IfcBuilding` | **Hard failure** — `process_ifc()` raises "No IfcBuilding found." |
| At least one `IfcSpace` | **Silent failure** — the import succeeds and produces zero legal volumes |
| A manual georeferencing anchor | Always required; supplied through the import UI, never read from the file |

Schema version is not a constraint: IFC2X3 and IFC4 both load, and non-metre length units
are handled through the project unit scale.

### First scan — the nine IFC files already in this repository

All nine passed the usability test: every one has an `IfcBuilding` and between 6 and 129
`IfcSpace` entities. Two results are worth carrying into the paper.

**Georeferencing.** Three of the nine carry an `IfcMapConversion` — and all three are files
generated by our own tooling. Of the files not authored here, **none** carries one. This is
a small sample and cannot support a population claim, but it is a real first data point for
the prevalence question raised in §1.1 of the manuscript, and it is the kind of number the
scan produces automatically as the corpus grows.

**Space boundaries.** *None* of the nine contains `IfcRelSpaceBoundary` at any level. The
information identifying which face of a room is shared with which neighbour is therefore
absent at source in every model available so far. This matters for the study design: the
party-wall semantic metric may have nothing to measure in real models, and the semantic axis
of the taxonomy may have to be evaluated primarily on the synthetic arm, where boundaries
can be authored deliberately. Deriving second-level boundaries algorithmically is possible
[31] but would introduce a reconstruction step of its own, which is itself lossy.

### An unforced loss found while checking this

The converter never reads `IfcMapConversion`. The identifier appears exactly once in
`ifc2cityjson_cadastral.py`, inside a docstring explaining why manual georeferencing is
used. Where the entity *is* present and valid, its content is therefore discarded and
replaced by a hand-entered anchor.

That is a structural loss the pipeline introduces unnecessarily, and it is separable from
the losses forced by format differences. It becomes a candidate requirement for the
encoding profile: *read `IfcMapConversion` when present and valid; fall back to a manual
anchor only when it is absent* — with the fallback recorded as metadata so the provenance
of the placement is never silently lost.
