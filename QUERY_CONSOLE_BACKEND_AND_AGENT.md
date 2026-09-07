# GIS Query Console — Backend Support Analysis, Easy-Win Fixes & Query Agent Design

_InfoBhoomi · Query Builder (GIS Query Console)_

## 1. What "supported by the backend" actually means

The Query Builder you open from the **Home tab** (`home-tab.component.html:27` →
`GisQueryConsoleComponent`) is driven entirely by the query catalogue in
`infoBhoomi-frontedend-div2/src/app/components/dialogs/gis-query-console/query-categories.ts`.

Each query has an optional `backend` block. The rule is simple:

- **Has a `backend` block** → the console builds `{field, operator, value}` conditions
  and POSTs them to `query-parcels/` (`Query_Parcels_View` in
  `InfoBhoomi_Backend_dev2/user/views/search.py`). The query runs live.
- **No `backend` block** → the console shows _"This query is preview-only — it requires
  spatial datasets not yet in the live database."_ (`gis-query-console.component.ts:123-128`).

The backend engine is **attribute-only**. It filters `Survey_Rep_DATA_Model` (org-scoped)
by intersecting matches from su-keyed attribute tables. It supports operators
`= != > < >= <= %` (the `%` is `icontains`) and a fixed field whitelist. It has **no
spatial capability** — no `ST_DWithin`, `ST_Intersects`, `ST_Within`, and no reference
geometry layers (rivers, coastline, roads, slope rasters, environmental zones, dengue
points). That single fact decides which queries can and cannot be supported cheaply.

## 2. Status of all 20 queries

Before this change, 11 of 20 queries ran live and 9 were preview-only.

| Category | Query | Before | After this change |
|----------|-------|--------|-------------------|
| Land & Property | Parcel Search, Land Use, Vacant Land, Large Parcels | ✅ live | ✅ live |
| Buildings | Building Search, High-Rise, Poor Condition, Large Building | ✅ live | ✅ live |
| Revenue & Tax | Outstanding Tax, High Market Value, Low Assessment | ✅ live | ✅ live |
| Disaster & Risk | **Flood Risk by Elevation** | ⛔ preview | ✅ **now live** |
| Disaster & Risk | **Landslide Susceptibility** | ⛔ preview | ✅ **now live** |
| Urban Planning | **Zoning Compliance Check** | ⛔ preview | ✅ **now live** (partial) |
| Urban Planning | **FAR / Coverage Violations** | ⛔ preview | ✅ **now live** |
| Disaster & Risk | River Proximity Analysis | ⛔ preview | ⛔ spatial — see §5 |
| Disaster & Risk | Coastal Reservation Violations | ⛔ preview | ⛔ spatial — see §5 |
| Urban Planning | Road Widening Impact | ⛔ preview | ⛔ spatial — see §5 |
| Environment & Health | Sensitive Zone Buffer | ⛔ preview | ⛔ spatial — see §5 |
| Environment & Health | Dengue Hotspot Analysis | ⛔ preview | ⛔ spatial — see §5 |

The key discovery: **the data tables for the flood, landslide and zoning queries already
exist** (`la_ls_physical_env`, `la_ls_zoning`) — they simply were never wired into the
query engine's field whitelist. They were "preview-only" by omission, not by genuine
backend limitation. FAR/coverage needed two new columns. The remaining five are genuinely
spatial and need real GIS infrastructure.

## 3. The 9 originally-unsupported queries — why, and what each needs

| Query | Why it was preview-only | What it needs |
|-------|------------------------|---------------|
| Flood Risk by Elevation | `elevation` not in field whitelist | Already in `la_ls_physical_env.elevation` → just wire it (done) |
| Landslide Susceptibility | `slope`, `soil_type` not whitelisted | Already in `la_ls_physical_env` → wire it (done) |
| Zoning Compliance | `zoning` not whitelisted | Already in `la_ls_zoning.zoning_category` → wire it (done) |
| FAR / Coverage Violations | building has no FAR/coverage columns | Add `floor_area_ratio`, `plot_coverage` columns (done, migration 0019) |
| River Proximity | needs `ST_DWithin` + a rivers/canals layer | New PostGIS layer + spatial query support (§5) |
| Coastal Reservation | needs coastline layer + `ST_DWithin` + permit status | New layer + spatial support + `permit_status` field (§5) |
| Road Widening Impact | needs road-centerline layer + `ST_DWithin` | New layer + spatial support (§5) |
| Sensitive Zone Buffer | needs environmental-zones layer + `ST_DWithin` | New layer + spatial support (§5) |
| Dengue Hotspot | needs dengue point reports + temporal + spatial cluster | New time-stamped point table + spatial/temporal support (§5) |

## 4. What was implemented this session (the 4 easy wins)

These four queries now run against the live backend with **no spatial engine** — they only
needed attribute wiring.

**Backend**

- `user/models/spatial_units.py` — added `floor_area_ratio` and `plot_coverage`
  (nullable `DecimalField`s) to `LA_LS_Build_Unit_Model`.
- `user/migrations/0019_lsbu_far_coverage.py` — additive migration for those two columns
  (depends on `0018_archive_extra_legalspaces`).
- `user/views/search.py` (`Query_Parcels_View`):
  - Added `elevation`, `slope`, `soil_type`, `flood_zone` (from `la_ls_physical_env`) and
    `zoning`, `max_far`, `max_coverage` (from `la_ls_zoning`) to `LAND_FIELDS`.
  - Added `floor_area_ratio`, `plot_coverage` to `BUILDING_FIELDS`.
  - Introduced a `SU_KEYED_SOURCES` map and refactored `_matching_ids` to resolve any
    su-keyed attribute table generically (org isolation is still enforced because every
    match is intersected with the org-scoped `base_qs`).
  - Enriched the returned features with the new attributes so they show in the results
    table and exports.

**Frontend**

- `query-categories.ts` — added `backend` blocks to `flood_elev`, `landslide_slope`,
  `zoning_check`, `far_violation`.

**Important caveats**

- These queries will return **0 rows until the columns are populated**. `la_ls_physical_env`,
  `la_ls_zoning`, and the new build-unit FAR/coverage columns must contain data. The wiring
  is correct; data backfill is a separate task (e.g. a DEM-derived elevation/slope load, a
  zoning import, and a FAR/coverage computation from footprint vs. parcel area).
- **Flood query:** only the `elevation < x` condition runs server-side. The "zone" (ward)
  dropdown has no backend column, so it is ignored server-side (noted in code).
- **Zoning query:** only `zoning = <selected>` runs. The non-conformance test
  (`land_use != zoning`) is a column-vs-column comparison the engine cannot express yet;
  it needs either a computed flag column or a small engine extension.
- **Landslide query:** the soil dropdown vocabulary (`Laterite`, `Red-Yellow Podzolic`…)
  differs from the stored `soil_type` vocabulary (`CLAY/SAND/LOAM/SILT/ROCK/PEAT/FILL`).
  The filter uses `icontains` to be tolerant, but the dropdown options should eventually be
  aligned to the stored domain.

**To activate locally** (sandbox file mount is unreliable for this repo, so run on your
machine):

```bash
# backend
cd InfoBhoomi_Backend_dev2
venv\Scripts\python.exe manage.py migrate user
venv\Scripts\python.exe manage.py check

# frontend
cd ../infoBhoomi-frontedend-div2
npm run build
```

## 5. The 5 remaining queries — backend work required

All five are genuinely spatial. Making them live is a real project, not a wiring fix. Two
pieces are needed:

**(a) Reference geometry layers** — new PostGIS tables, each with a geometry column and a
GiST spatial index:

| Query | New layer(s) |
|-------|-------------|
| River Proximity | `water_bodies` (rivers, canals, lakes — line/polygon) |
| Coastal Reservation | `coastline` (line) + building `permit_status` attribute |
| Road Widening | `road_centerlines` (line, with `road_name`) |
| Sensitive Zone | `environmental_zones` (polygon, with `zone_type`) |
| Dengue Hotspot | `dengue_reports` (point, with `reported_date`) |

**(b) A spatial query capability.** The current engine resolves conditions as ORM
attribute filters. Spatial queries need distance/intersection predicates. The cleanest
path is a **separate endpoint** (e.g. `query-parcels/spatial/`) that accepts a small,
whitelisted spatial-condition vocabulary — `within_distance(layer, metres)`,
`intersects(layer)`, `within(layer)` — and translates them with GeoDjango
(`__distance_lte`, `__intersects`, `__within`) or raw PostGIS. Keep it whitelist-driven for
the same injection-safety reason the attribute engine uses a fixed field map. Buffer
distances should run in a projected CRS (e.g. SLD99 / EPSG:5234) for correct metre
distances rather than degrees.

Recommended order: water_bodies + road_centerlines first (highest municipal value and
simplest geometry), then environmental_zones and coastline, then dengue (also needs a
reporting pipeline to keep points current).

## 6. Query Agent — feasibility & design (design only; not built)

**Verdict: feasible, and a good fit.** Because every query is already a structured template
with typed parameters and a `backend` block, a natural-language agent does **not** need to
generate SQL. It only needs to (1) pick the right template and (2) fill its parameters.
That keeps the agent safe (it can only ever run vetted queries) and removes the main risk
of free-form NL→SQL.

### 6.1 Recommended architecture — intent routing over existing templates (Phase 1)

```
User question (NL)
   │
   ▼
Intent + parameter extraction        ← maps text → {queryId, params}
   │   (keyword/synonym routing, optionally LLM-assisted)
   ▼
Reuse existing path: queryParcels(layerId, conditions, logic)
   │
   ▼
Results → (a) results table   (b) highlight parcels on map   (c) printable report
```

Two implementation tiers for the routing step:

- **Deterministic (no LLM):** a keyword/synonym table mapping phrases to `queryId` and
  extracting numbers/units ("buildings over 5 floors" → `high_rise`, `min_floors=5`).
  Zero external dependency, fully predictable, cheap. Good first release.
- **LLM-assisted (optional upgrade):** send the catalogue (query ids, descriptions,
  param schemas) plus the user's question to an LLM and ask it to return **only**
  `{queryId, params}` as JSON — never raw SQL. Validate the returned `queryId` and params
  against the catalogue before executing. This handles paraphrase and multi-constraint
  questions far better, while the whitelist still guarantees safety. Needs an API key and a
  small backend proxy endpoint (don't call the model from the browser with a secret).

A practical hybrid: try deterministic routing first; fall back to the LLM only when
confidence is low.

### 6.2 The three user-facing deliverables in the request

1. **Answer in natural language + get the report.** The agent runs the chosen template,
   then renders: a one-line plain-language summary ("Found 23 parcels in a High flood zone
   below 5 m elevation"), the results table, and the generated condition/SQL preview. The
   console already returns `count`, `features`, and per-feature attributes — the agent just
   narrates them.
2. **Highlight associated land parcels.** Already supported. `highlightOnMap()` in
   `gis-query-console.component.ts` calls `mapService.highlightQueryResults(su_id, geojson)`.
   The agent reuses this directly — no new map code needed.
3. **Print the report.** Add a print/PDF action. Two options: (a) client-side — open a
   print-friendly view (query title, NL summary, parameters, results table, optional map
   snapshot) and use the browser print dialog; (b) server-side — a `query-report/` endpoint
   that renders a branded PDF. The existing `exportCSV` / `exportGeoJSON` / `exportSHP`
   actions are the precedent to mirror; a print/PDF button fits beside them.

### 6.3 Build phases

- **Phase 1** — chat box in the console; deterministic intent routing over existing
  templates; reuse `queryParcels` + `highlightOnMap`; NL summary; browser-print report.
- **Phase 2** — LLM-assisted routing (backend proxy + JSON-schema validation); branded
  server-side PDF with map snapshot.
- **Phase 3** — extend to the spatial queries once §5 lands; add follow-up/refine turns
  ("now only those over 200 m²").

### 6.4 Guardrails

Whitelist `queryId` and params against the catalogue; never execute model-authored SQL;
keep all queries org-scoped exactly as `query-parcels/` already does; cap result size (the
endpoint already slices to 500); log the resolved `{queryId, params}` for auditability.

---

_Files changed this session: `user/models/spatial_units.py`,
`user/migrations/0019_lsbu_far_coverage.py`, `user/views/search.py`,
`gis-query-console/query-categories.ts`._
