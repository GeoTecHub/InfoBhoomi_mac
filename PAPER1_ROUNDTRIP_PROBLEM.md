# Paper 1 — Research Problem (agreed)

**Working title:** How much of a legal volume survives IFC → CityJSON → PostGIS?
**Target:** ISPRS International Journal of Geo-Information (IJGI)
**Role:** Anchor paper. Papers 2–n cite this one for the method and the taxonomy.
**Status:** problem framing agreed 2026-08-30. Plan and experiment design to follow.

---

## 1. Locked scope decisions

| Decision | Choice |
|---|---|
| Unit of analysis | **Legal volume only** — `IfcSpace`-derived room volumes and their aggregation into LSBUs. Walls/slabs/openings are context, not measured. |
| Round-trip depth | **Full round-trip** — IFC → CityJSON → PostGIS → CityJSON, compared to source at every hop. Yields per-hop loss *and* an end-to-end survival figure. |
| Treatment | **As-is + profiled variant.** Baseline = current InfoBhoomi pipeline. Treatment = same models through the proposed encoding profile. The profile is demonstrated, not merely proposed. |

---

## 2. Problem statement

In a cadastre the legal volume *is* the object of the right. It must therefore be the
same volume after encoding as it was before. At present there is no way to state, let
alone measure, whether it is.

IFC → CityJSON → PostGIS is the de-facto route from a designed building to a registered
3D unit. Each hop is an unspecified, lossy re-encoding:

- **IFC → CityJSON.** Parametric and BRep solids are tessellated (world coordinates,
  welded vertices). Most production IFC files carry no valid *IfcMapConversion* — the
  entity that relates the model's local engineering coordinate system to a projected map
  CRS — so georeferencing becomes a *manual assumption* (anchor, rotation, scale) rather
  than a measurement — the legal volume's absolute position is asserted, not surveyed.
- **CityJSON → PostGIS.** A room's closed shell is stored as `MULTIPOLYGON Z` in
  EPSG:4326: a surface *collection*, not a solid. No closure guarantee, no topology,
  horizontal units in degrees against a vertical component in metres. Coordinates are
  snapped to a 1e-7° grid so that results are stable across GEOS versions.
- **Semantics and structure.** CityJSON semantic surfaces, IFC property sets, and the
  Building → Storey → Room containment hierarchy collapse into a small number of
  columns plus a JSONB list of component ids.

None of this is a rendering artefact. In a registry, encoding loss is a change to the
object of a right: centimetre-scale drift and non-closed shells change computed volume,
change condominium share fractions, and break the very overlap test that is supposed to
detect double registration.

## 3. Gap addressed

Three literatures touch this and none closes it:

1. **IFC → CityGML/CityJSON conversion quality** — measures geometry, and stops at the
   file. No database hop, no legal criteria.
2. **LADM 3D data models** — prescribes *what* to model, but ISO 19152 has no normative
   3D encoding (deferred to Part 6). No statement of what an implementation must preserve.
3. **3D DBMS storage benchmarks** — measure storage size and query latency, i.e.
   performance, never fidelity.

No published work measures the **whole chain end-to-end against cadastral fitness
criteria**, and there exists no shared vocabulary for what was lost or requirement for
what must survive.

## 4. Research questions

- **RQ1** — What is lost, and at which hop? *(→ contribution: geometric / semantic /
  structural loss taxonomy)*
- **RQ2** — Which of those losses change a **legal** outcome — registered area, volume,
  share fraction, or overlap detection? *(→ separates cosmetic loss from disqualifying loss)*
- **RQ3** — What is the minimum set of constraints on each hop that makes a legal volume
  round-trip-faithful and registrable? *(→ contribution: the encoding profile)*

## 5. Contributions claimed

1. A **measurement method** for legal-volume fidelity across a multi-format encoding chain.
2. A **loss taxonomy** on three axes — geometric, semantic, structural — with each class
   tied to the legal outcome it can alter.
3. A **cadastral encoding profile** for IFC → CityJSON → PostGIS, validated by re-running
   the same corpus through it.

## 6. Implications for the build (not yet in the codebase)

- **PostGIS → CityJSON exporter.** Required by the full round-trip decision; does not
  exist yet. This is the main new engineering.
- **Profiled storage path.** Candidate: closed `POLYHEDRALSURFACE Z` in a projected metric
  CRS (EPSG:5235) with closure/orientation validation on write, alongside the existing
  `MULTIPOLYGON Z` / 4326 column so baseline and treatment coexist.
- **Loss metric harness.** Per-hop comparators for volume, Hausdorff distance, vertex and
  face counts, closure/manifoldness, attribute retention, hierarchy retention.

## 7. Ground truth (fourth decision, settled)

A round trip measures self-consistency, not correctness — a wrong volume can round-trip
perfectly. Accuracy therefore requires an external reference, and two are used:

- **Synthetic solids with analytically exact volumes** — perfect controls, no survey
  uncertainty, isolating pipeline error from input error. Gives *precision*.
- **Real buildings with registered condominium plan areas** — the legal reference that
  makes the "legally material error" claim possible. Gives *relevance*.

Settled before collection begins, because it determines whether the paper claims a loss
rate or an accuracy. See `PAPER1_METHOD.md` §3.

## 8. Still open

- Corpus size: how many synthetic members, how many real buildings.
- Source of real condominium models and their registered plans.
- Numeric legally-material error thresholds — needs Sri Lankan registration practice.
- Whether the PostGIS → CityJSON exporter ships as a paper artefact or as production code.

---

**Method design:** `PAPER1_METHOD.md` — units, conditions, round-trip protocol, metrics
and survival matrix, analysis plan, threats to validity.
