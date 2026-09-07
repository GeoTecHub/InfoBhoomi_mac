# InfoBhoomi 3D Cadastre Integration — Detailed Design

**Status:** Design (grounded in the real `user/` backend app + Angular frontend, verified by reading the code)
**Date:** 2026-05-30
**Decisions baked in:** consolidate converter on `ifc2cityjson_cadastral.py`; **manual georeferencing** in the import dialog; reuse the existing viewer.

> **Note on an earlier draft:** a first version of this doc named `infobhoomi/gis/models.py`, `CadastralObject3D`, `cadastre3d.ts`, `UserProfile.gnd`, and SRID 5235. **Those were wrong** (the reads had failed). This version is rebuilt from the actual code. Sections 1 & 4 (converter) were always correct — all three Python converters were read end-to-end.

---

## 1. App-selection verdict (your core question)

| Converter | Strengths | Gaps | Verdict |
|-----------|-----------|------|---------|
| `ifc_to_cityjson_FINAL.py` | Modular; rich **semantic surfaces** (Wall/Floor/Roof/Ceiling from normals); property-set + zone extraction; space bbox fallback | **Room-only** (requires `IfcSpace`); no georeferencing; float verts; no footprint | Best semantics, incomplete |
| `ifc2cityjson_vox.py` | Building shell + rooms; **georeferencing** (`IfcMapConversion`→placement); quantized int verts (scale 0.001); `cjio` validate; **voxel room detection** | No semantics; blocky voxels; no footprint | Best georef/spec, lossy |
| **`ifc2cityjson_cadastral.py`** | **Already merges** FINAL semantics + attributes with vox georef + quantized verts + Building→Room hierarchy; clean dataclass design | Missing footprint extraction; requires `IfcSpace`; CLI-only; no tests | **CHOSEN BASE** |

**Recommendation:** build on **`ifc2cityjson_cadastral.py`**. Add (1) **footprint extraction** and (2) **manual georeferencing transform** — neither original converter has these. Keep vox voxel detection as a **fallback** for IFCs with no `IfcSpace`.

**Viewer:** reuse what already exists (see §2) — InfoBhoomi already renders CityJSON in 3D. The standalone `3D-Cadastre/` app (three.js + web-ifc + iTowns) is a secondary source of reusable code, not a separate thing to bolt on.

---

## 2. Current state — InfoBhoomi already has most of the 3D plumbing

This is the biggest finding: **the 3D cadastre is largely wired already.** The work is mostly "feed it from IFC import," not "build it."

### 2.1 Backend (`user/` app — Django 5.1 + PostGIS; all endpoints under `/api/user/`)

- **Parcel identity:** `LA_Spatial_Unit_Model` (`la_spatial_unit`) — `su_id` (unique int), `label`, `parcel_status`. **No geometry here.**
- **Geometry + hierarchy:** `Survey_Rep_DATA_Model` (`survey_rep`, in `models/core.py`) — `id` (this is the `su_id` used everywhere, e.g. `filter(id=su_id)`), FK `su_id`, **`layer_id`** (3 = building, 12 = apartment/strata unit, 1/6 = land), `geom`, **`parent_id` = `ArrayField(Integer)`** ← *this is the parent/child mechanism*, `gnd_id`, `org_id`.
- **Per-unit 3D geometry already exists:** `LA_LS_Build_Unit_Model` (`la_ls_build_unit`) has `floor_no`, `floor_area`, `apt_name`, and **`geom_3d = GeometryField(dim=3, srid=4326)`** — the 3D solid column, explicitly commented *"populated by the 3D Cadastre project for cross-platform viz."*
- **Building-unit create/read/update already implemented** in `views/building.py`:
  - `Bld_Unit_Create_View` (`POST`) — creates a `survey_rep` row (`layer_id=12`, `parent_id=[parent]`, inherits `gnd_id`/`org_id`/`geom`), ensures the `la_spatial_unit` row, creates `la_ls_build_unit` **including `geom_3d` from a `geom_3d_wkt` payload (srid 4326)**, writes `Parcel_History_Model` relationship records, creates utilities. **This *is* the "parent/child as usual" path.**
  - `Bld_Units_List_View` (`GET ?parent_su_id=`) — lists child units via `filter(layer_id=12, parent_id__contains=[parent_su_id])`.
  - `Bld_Unit_Detail_View`, `Bld_Unit_Update_View` (accepts `geom_3d_wkt`).
- **3D fetch endpoint exists:** frontend calls `apiService.load3DData(feature_id)` returning CityJSON-ish (`{features:[…]}`). *(Confirm its backend view + where the full CityJSON is stored — see §8.)*
- **Admin area:** GND lives on `survey_rep.gnd_id` → `sl_gnd_10m_Model`. A user's area is org-scoped: `User_Roles_Model.org_id` + `Org_Area_Model.org_area` (ArrayField of GND ids). **There is no `UserProfile.gnd`** — filter by `gnd_id ∈ user's org_area`.

### 2.2 Frontend (Angular 21; OpenLayers 10.8 = 2D, **iTowns 2.46 = 3D**)

- **Map + right-click already wired:** `components/main/main.component.ts` has `contextMenuVisible`, `contextMenuPosition`, `handleRightClick`, `contextmenu` listener.
- **3D viewer dialog already exists:** `components/dialogs/three-d-building-viewer/` (`ThreeDBuildingViewerComponent` + `viewer/` 3D + `floor-plan-viewer/` 2D). It calls `apiService.load3DData(feature_id)`, validates CityJSON, renders 3D, switches to a 2D floor plan on surface-select (floor-plan data currently **mocked**).
- **Side panel already does CityJSON buildings:** `BuildingInfoPanelComponent` with unit/strata management + "3D model integration"; `building-info.model.ts` has `extractBuildingInfo(cityjson, objectId?)`. `LandInfoPanelComponent` for parcels.
- **Central API client:** `APIsService` (`api.service.ts`, ~1882 lines) already has `load3DData`. Search UI: `components/header/search/`.
- **3D data format:** CityJSON, LoD0–LoD4.

### 2.3 What's actually missing (the real scope)

| Gap | Where |
|-----|-------|
| **Converter: footprint + manual transform + library API** | `ifc2cityjson_cadastral.py` (§4) |
| **IFC/CityJSON import endpoint** that runs the converter and creates building + units | new view in `user/views/building.py` (§5) — *reuses existing `Bld_Unit_Create_View` logic* |
| **Storage of the assembled building CityJSON** the viewer reads | confirm where `load3DData` reads from; standardize (§5, §8) |
| **Context-menu actions** "Import 3D" / "View as 3D" | `main.component.ts` (§6) — *View-as-3D dialog already exists* |
| **City-3D whole-area view + admin filter + search-by-query** | new endpoint + frontend (§5, §6) |

---

## 3. Coordinate / georeferencing strategy (CORRECTED)

- The existing 3D column is **`geom_3d` SRID 4326 (WGS84)**, and `survey_rep.reference_coordinate` examples are `"EPSG:4326"`. So target **EPSG:4326** for stored geometry (confirm `survey_rep.geom` SRID — it may be 4326 or a local SL CRS). *(My earlier 5235 claim was wrong.)*
- IFC files are in **local metric coordinates**; almost never carry a valid `IfcMapConversion`. → **Manual placement** (your decision): the dialog lets the user set an **anchor** (lon/lat from clicking the parcel), **rotation**, and **scale**. The converter applies that affine transform to both the footprint and the 3D vertices, then output is reprojected to 4326. Store the transform in CityJSON metadata for reproducibility.
- Use `proj4` (already a frontend dep) / GeoDjango transforms for metric↔4326. A local metric working CRS (e.g. an SL grid or UTM 44N) is recommended for the rotate/scale math, then project to 4326 for storage.

---

## 4. Converter enhancements (`ifc2cityjson_cadastral.py`)

Standardize **one** copy under the backend (e.g. `user/services/ifc/ifc2cityjson_cadastral.py`); delete the duplicate copies in `GitProjects/IFC` and `3D-Cadastre/IFC`.

1. **`FootprintExtractor` (NEW):** project footprint-defining elements (ground `IfcSlab` at min-Z, else exterior `IfcWall`, else union of all shells) to 2D; `shapely` `buffer(0)` + `unary_union` → outer polygon; `simplify`. Returns polygon in IFC-local metres.
2. **`TransformParams` (NEW):** `anchor_lon/lat, base_z, rotation_deg, scale, src_anchor_xy`. `world = anchor + scale·R(θ)·(local − src_anchor)`. Applied in `CityJSONBuilder` (replace translate-only) **and** to the footprint; result reprojected to 4326. Prefill from `IfcMapConversion` if present.
3. **Library API (NEW):** `convert_ifc_to_cityjson(path, transform) -> dict` and `extract_footprint(path, transform) -> shapely Polygon` (return objects, not just files) so the import view calls it in-process.
4. **CityJSON-direct path:** if user uploads CityJSON, validate, derive footprint from lowest `GroundSurface`/floor semantics, apply transform.
5. **Per-unit solids for `geom_3d`:** for each Room/space, emit a closed solid → convertible to `geom_3d_wkt` (3D PolyhedralSurface, srid 4326) for the existing `Bld_Unit_Create_View`.
6. **Robustness:** counted/logged skips instead of bare `except`; keep `ifc_guid` on every object (join key); golden tests on `simple-model-spaces01.ifc` + `LargeBuilding.ifc`. Voxel fallback only when no `IfcSpace`.

---

## 5. Backend — new import + city/search endpoints (add to `user/`)

Follow the app's conventions (TokenAuth, `views/building.py`, `serializers/`, register in `user/urls.py`).

> **Built as `POST /api/user/cityjson/import/`** (`IFC_Cadastre_Import_View`) — see §9.3 for the as-built spec. The `bld-3d/*` names below were the original proposal; admin-area + search (§5 lines below) are still **P4**.

- **`POST /api/user/cityjson/import/`** — multipart: `parent_su_id` (or a land `su_id`), file (IFC/CityJSON), transform params.
  1. Resolve parcel/building `survey_rep`; authorize via `org_id`/`org_area`.
  2. Build `TransformParams`; run `convert_ifc_to_cityjson` + `extract_footprint`.
  3. Ensure a building `survey_rep` (`layer_id=3`) with the **footprint** as `geom`; persist the assembled **CityJSON** (see §8 storage decision).
  4. For each Room → call the **existing** `Bld_Unit_Create_View` logic: create `layer_id=12` child (`parent_id=[building_su_id]`) + `la_ls_build_unit` with `geom_3d_wkt`. This gives the side-panel parent/child + 3D solids **for free**.
  5. Return `{ building_su_id, footprint_created, units_created }`.
- **`GET /api/user/bld-3d/admin-area/`** — buildings whose `survey_rep.gnd_id ∈ user's org_area` (`Org_Area_Model.org_area` for `User_Roles_Model.org_id`), with their CityJSON refs → the **city-3D feed**. Renders only the login user's area by construction.
- **`GET /api/user/bld-3d/search/?q=`** — search `la_spatial_unit.label`, `apt_name`, building name; scope to org_area; return su_id + centroid/bbox for camera fly-to.
- Reuse / confirm the existing `load3DData` view as `GET .../bld-3d/{su_id}/`.

---

## 6. Frontend wiring

- **Context menu (`main.component.ts`):** add **"Import 3D object"** → new `Import3dDialog`; **"View as 3D"** → open the **existing** `ThreeDBuildingViewerComponent` with the parcel/building `su_id` (already works via `load3DData`). Add a toolbar **"City 3D view"** button → 3D scene fed by `bld-3d/admin-area/`.
- **Import dialog (manual placement):** file picker + a placement step over the parcel polygon (anchor click, rotation handle, scale field; default = centroid/0/1) → posts file + transform to `bld-3d/import/`. On success: refresh the parcel footprint layer and the side panel (units appear as children — same path `Bld_Units_List_View` already serves).
- **Search:** wire `header/search` (or a 3D search box) to `bld-3d/search/` → fly-to + highlight.
- **Right-click import in 3D (parity):** the `three-d-building-viewer` (or city-3D scene) right-click → same `Import3dDialog`. Keep the dialog host-level so 2D and 3D share it.
- **Floor-plan viewer:** replace the mocked floor-plan data with real per-room footprints from the imported CityJSON.

---

## 7. Requirement traceability

| Requirement | Mechanism | Already exists? |
|-------------|-----------|-----------------|
| Right-click parcel → import IFC/CityJSON | context menu → `Import3dDialog` → `bld-3d/import/` | menu ✅, dialog ❌ |
| Dialog to import IFC or CityJSON | `Import3dDialog`; converter handles both | ❌ |
| Footprint on parcel + side panel + parent/child | `FootprintExtractor` → `survey_rep.geom`; child units via existing `Bld_Unit_Create_View` (`parent_id` array, `geom_3d`) | unit/footprint plumbing ✅, IFC feed ❌ |
| Right-click building/parcel → view 3D | `ThreeDBuildingViewerComponent` via `load3DData` | ✅ (just add menu item) |
| City 3D view button (whole city) | toolbar → `bld-3d/admin-area/` scene | ❌ |
| Search object by query | `header/search` → `bld-3d/search/` | search UI ✅, endpoint ❌ |
| City-3D = only login user's admin area | `gnd_id ∈ org_area` filter, server-enforced | ❌ |
| Right-click import in 2D **and** 3D | shared host-level `Import3dDialog` | ❌ |

---

## 8. Open questions / risks

> **P0 RESOLVED (2026-05-30) — see §8.1.** The CityJSON JSONB store and the import-endpoint stub already exist; `survey_rep.geom` SRID is **4326**. The main blocker is cleared.

### 8.1 P0 findings (verified in code — exact)
- **CityJSON store exists but needs a parcel link.** `CityJSON_Model` (`user/models/misc.py`, table **`city_json`**) = **`cityjson_data` JSONField** + `created_at`. **It has NO `su_id` / parcel FK** → it can't yet be fetched per-building. **Action (small migration): add `su_id` IntegerField (db_index) + `name`** so a building's CityJSON is retrievable by parcel. This is still the §10 JSONB store (no new model, just one column).
- **Companion object table exists:** `City_Object_Model` (table `city_object`; PK `city_object_id`, `type`, `attributes`, `parents`, `children`, `geometry` — all JSON). On upload, `CityJSON_Upload.extract_city_objects()` **bulk-inserts each `CityObjects` entry** here. Handy for per-object queries and the unit-highlight feature — but note PK = `city_object_id` (no building scope), so add a building/`su_id` column if we rely on it for multi-building.
- **Endpoints exist** (`user/views/geo_utils.py`, in `user/urls.py`):
  - `GET/POST /api/user/cityjson/` — `CityJSON_Model_ListCreate`, queryset `.all()` (**no su_id filter yet** — add one once `su_id` exists). Serializer `CityJSON_Serializer` (`fields='__all__'`).
  - `GET /api/user/cityjson/<pk>/` — `CityJSON_Model_Retrieve`.
  - `POST /api/user/cityjson/upload/` — `CityJSON_Upload`: saves the doc + extracts `City_Object_Model` rows; returns `cityjson_id` + `city_objects_count`.
  - `City_Object_List` / `City_Object_Retrieve` also exist.
- **Import endpoint already stubbed with a real reference impl:** `IFCtoCityJSONView` (commented, imports `ifcopenshell` — "DISABLED pending ifcopenshell on server"). Its body already does walls/slabs/roofs/doors/windows → MultiSurface CityJSON (but **no IfcSpace, no semantics, no georef, no footprint**). → P2 = uncomment and **replace its body with the consolidated `ifc2cityjson_cadastral.py`** (footprint + manual transform + IfcSpace/semantics). *(Server needs `ifcopenshell` + `shapely`.)*
- **SRID = 4326 everywhere:** every `srid=` in migrations is `4326` — `survey_rep.geom` (incl. migration `0335–0338 alter ... geom`) and `la_ls_build_unit.geom_3d` (migration `0005`, `dim=3, srid=4326`). **2D and 3D share one CRS — no reprojection between parcel and 3D store.** (Still do rotate/scale/union math in a local metric CRS, then store 4326 — §9.1.)
- **BUG to fix:** `APIsService.load3DData(featureId)` ignores `featureId` — it calls `` `${baseUrl}cityjson` `` (no id, no filter) → returns the whole list. Fix to `cityjson/?su_id=${featureId}` (after adding `su_id`) or `cityjson/${id}/`. Also the viewer (`three-d-building-viewer`) validates `{features:[…]}`, but the store holds raw CityJSON (`type/version/CityObjects/vertices`) — **reconcile the loader to read CityJSON `CityObjects`**, not GeoJSON `features`.

### 8.2 Remaining open questions / risks
1. **Single source of truth:** `la_ls_build_unit.geom_3d` (per-LSBU solids) vs the assembled `cityjson` JSONB — keep both generated from one import so they can't drift.
2. **Footprint = building outline projection** vs surveyed boundary — confirm which is the legal 2D.
3. **Multi-building IFC** — current converter sends all spaces to the first building; needs `IfcRelContainedInSpatialStructure` traversal.
4. **Voxel-fallback units** are approximate — flag them in the UI.
5. **Vertext backend** (`vertext.service.ts`, secondary API) — clarify whether 3D should route there.
6. **Viewer data shape** — `three-d-building-viewer` validates `{features:[…]}` but `cityjson` table holds raw CityJSON (`CityObjects`); reconcile loader vs store format (§8.1 bug).
7. **`ifcopenshell` + `shapely` on the server** — required to enable `IFCtoCityJSONView`; if server install is hard, run the converter as an offline/worker step and POST the resulting CityJSON to `cityjson/`.

---

## 9. Phased plan

1. **P0 – Confirm storage — ✅ DONE (§8.1)** — `city_json` JSONB store (`cityjson_data`) + `cityjson/` endpoints + `City_Object_Model` extractor + commented `IFCtoCityJSONView` (real reference impl) all exist; SRID = 4326 throughout. Gaps found: `CityJSON_Model` has **no `su_id`** (add it), and `load3DData` is buggy + reads the wrong shape.
2. **P1 – Converter — ✅ DONE (§9.2)** — `FootprintExtractor` + `TransformParams` + `StoreyResolver` + library API + golden test; 12/12 checks pass on `LargeBuilding.ifc`.
3. **P2 – Import endpoint** — `bld-3d/import/` reusing `Bld_Unit_Create_View`; footprint→`survey_rep`, units→`layer_id=12`, solids→`geom_3d`.
4. **P3 – 2D frontend — ✅ DONE (§9.4)** — `load3DData` bug fixed, API import methods, Import-3D dialog (manual placement), context-menu "Import 3D Object" + "View as 3D"; Angular build clean.
5. **P4 – City 3D + search + admin filter** — backend feed + search endpoints ✅ live-proven (§9.5); viewer seam fixed ✅; **City-3D viewer UI built (§9.6, ng build clean, not browser-verified)** ✅. Remaining: right-click "Import 3D" parity inside the 3D scene (deferred to P4b).
6. **P4b – LSBU composition + cross-view sync — ✅ DONE (§9.7)** — model fields + migration `0015`, compose endpoints (live-proven), Unit Composition window with two-way highlight, side-panel Legal Space Type + opener button; `ng build` clean. Remaining: reassign/unassign + CityJSON-membership sync + browser QA.
7. **P5 – Hardening** — real floor plans, `cjio`/`val3dity` validation, perf at city scale, multi-building.

**Vertical slice first:** `simple-model-spaces01.ifc` → import on a test parcel → footprint + child units in the side panel → "View as 3D" (existing dialog) → appears in city-3D for that GND.

### 9.1 Test plan / vertical slice (concrete)

**Test data:** `C:\Users\nmmil\OneDrive\Programs\InfoBhoomi\3D-Cadastre\IFC\LargeBuilding.ifc`
- Verified contents: **8 `IfcSpace` rooms** (named 1–8) across **2 storeys** (Level 1, Level 2), 1 `IfcBuilding`, 20 walls. Schema IFC2X3.
- Hits the converter's real `IfcSpace` path (not the voxel fallback) — enough rooms to exercise apartment pooling + a common-property LSBU.
- **No `IfcMapConversion`** (the file's `IfcSite` carries Autodesk's Boston lat/long — ignore it). Confirms manual placement is required.

**CRS handling:**
- **Storage / serving CRS = WGS84 (EPSG:4326)** — matches `la_ls_build_unit.geom_3d` (srid 4326).
- **Working CRS = local metric** (UTM 44N / an SL grid) for the rotate / scale / solid-union / area math; **project to 4326 only for storage.** (Doing rotation/scale/union in raw degrees distorts geometry — degrees are not metric.)

**Placement:** anchor on **any chosen InfoBhoomi parcel** — default anchor = parcel **centroid** (lon/lat), surveyor adjusts rotation/scale. *(Depends on P0: confirm `survey_rep.geom` SRID so the parcel centroid → anchor transform is correct.)*

**Steps (end-to-end):**
1. Right-click a parcel → **Import 3D object** → pick `LargeBuilding.ifc`.
2. Manual placement: anchor = parcel centroid, rotation/scale as needed → submit.
3. Backend: converter produces CityJSON (8 rooms + shell) + footprint; footprint lands on the parcel; building `survey_rep` (layer_id=3) + CityJSON JSONB stored.
4. **2D check:** footprint drawn on the parcel; side panel shows the **building / LSBU level** (no unit list).
5. Open **Unit Composition** window → 8 rooms shown as the unassigned pool.
6. Pool **Level-1 rooms → "Apartment A"**, **Level-2 rooms → "Apartment B"** (Private; enter cadastral IDs); tag any circulation room as **Common Property** (Circulation) → linked to a shared **BAUnit**.
7. **Two-way highlight check:** select a unit in the list → its solid highlights in 3D, and vice versa.
8. Save → each LSBU created as `layer_id=12` child (`parent_id=[building_su_id]`), `geom_3d` = union of member rooms.
9. **Sync check:** the LSBUs + cadastral IDs + Legal Space Type appear **identically** in the 2D InfoBhoomi side panel and the city-3D panel.
10. **City-3D check:** the building renders in city-3D for that parcel's GND (admin-area feed), filtered to the login user's org area.

**Pass criteria:** footprint on parcel ✓; 8 rooms importable ✓; ≥2 private apartments + 1 common LSBU created with user cadastral IDs ✓; two-way highlight works ✓; 2D and 3D show identical LSBU info ✓; building appears only within the user's admin area ✓.

### 9.2 P1 — converter built & verified (2026-05-30)

**Code:** `InfoBhoomi_Backend_dev2/user/services/ifc/`
- `ifc2cityjson_cadastral.py` — consolidated converter (semantics + attributes + footprint + manual transform + storey inference).
- `__init__.py` — exports `process_ifc`, `convert_ifc_to_cityjson`, `extract_footprint`, `TransformParams`, `ConversionResult`, `UnitResult`.
- `test_convert.py` — golden/smoke test (run with a Python that has ifcopenshell + shapely).

**Library API (what the import endpoint will call):**
```python
process_ifc(ifc_path, transform: TransformParams|None) -> ConversionResult
# ConversionResult: .cityjson (dict), .footprint (shapely Polygon, EPSG:4326),
#   .footprint_wkt_4326, .units[UnitResult], .building_guid/name, .stats
# UnitResult: .guid .name .cityjson_id .floor .area_m2 .solid_wkt_4326 (MULTIPOLYGON Z) .attributes
convert_ifc_to_cityjson(ifc_path, transform) -> dict
extract_footprint(ifc_path, transform) -> shapely Polygon | None
```
`TransformParams(anchor_lon, anchor_lat, base_z, rotation_deg, scale, src_anchor_xy)` — manual placement; `world_enu = scale·R(θ)·(local−src_anchor)`, `z = base_z + scale·z`.

**Outputs (one transform pass, can't drift):**
- **CityJSON 2.0** — vertices in **local metric ENU** (m); `metadata.georeferencing` holds anchor/rotation/scale so the viewer places the model; rooms = `BuildingRoom` with per-surface semantics (Floor/Wall/Ceiling), parented to `Building`.
- **footprint** — valid **2D** Polygon, **EPSG:4326** → `survey_rep.geom`.
- **per-unit solids** — **`MULTIPOLYGON Z`** WKT (lon/lat/z m), **EPSG:4326** → `la_ls_build_unit.geom_3d` via the existing `geom_3d_wkt` path.

**Storey inference (`StoreyResolver`):** explicit IFC links first (`Decomposes` / `ContainedInStructure` / `IfcRelAggregates`), else fall back to matching each space's floor-Z against `IfcBuildingStorey.Elevation` (file-units→metres via `ifcopenshell.util.unit`). In `LargeBuilding.ifc`, `IfcRelAggregates` puts **all 8 spaces on Level 1** (Level 2 exists but holds no spaces; each space mesh is 0→4 m), so the explicit link resolves them correctly; the elevation fallback covers files that omit the relation.

**Verified on `LargeBuilding.ifc` (12/12 checks):** 1 Building + 8 BuildingRoom units, full hierarchy, semantic surfaces on every room, every unit resolves to its storey (all Level 1, matching the IFC aggregation), floor areas extracted, footprint valid 2D ~8×20 m, all 8 unit solids parse as 3D MultiPolygon.

**Notes / deps:** needs `ifcopenshell` + `shapely` (present in system Python 3.14; **NOT in the backend venv** — install there for P2). `pyproj` optional — geo projection uses an equirectangular tangent-plane around the anchor (sub-cm over a building); swap in pyproj later for large areas. ifcopenshell 0.7/0.8 settings handled. CityJSON is **not** quantized (raw ENU metres) — fine for the iTowns viewer; add cjio quantize/validate in P5.

### 9.3 P2 — import endpoint built & validated (2026-05-30)

**Changes:**
- **Model** (`user/models/misc.py`): `CityJSON_Model` gained `su_id` (IntegerField, db_index), `name`, `source_file`. Migration **`0014_cityjson_su_id.py`** (depends on `0013_create_geotag`).
- **List filter** (`geo_utils.py`): `CityJSON_Model_ListCreate` now supports `GET /api/user/cityjson/?su_id=<building>` and orders newest-first.
- **Import view** (`geo_utils.py`): `IFC_Cadastre_Import_View` → **`POST /api/user/cityjson/import/`** (multipart). Registered in `user/urls.py` (before the `<int:pk>` route).

**Request:** `file` (.ifc/.json), `parent_su_id` (target parcel `survey_rep.id`), optional `anchor_lon/anchor_lat` (default = **parcel centroid**), `rotation_deg`, `scale`, `base_z`.

**Pipeline (one transaction):**
1. Resolve parcel `survey_rep`; default anchor = `parcel.geom.centroid` (SRID 4326).
2. Lazily import `user.services.ifc.process_ifc` (returns 503 with a clear message if ifcopenshell/shapely absent) → CityJSON + footprint WKT + per-unit solids.
3. Create **building** `survey_rep` (`layer_id=3`, `parent_id=[parcel]`, `geom=footprint`, inherits `gnd_id`/`org_id`), ensure `la_spatial_unit` + `la_ls_build_unit` (building_name).
4. Store CityJSON in `city_json` keyed by `su_id=building_su_id`.
5. Each room → **unit** `survey_rep` (`layer_id=12`, `parent_id=[building]`) + `la_ls_build_unit` with `apt_name`, `floor_no`, `floor_area`, **`geom_3d`** (from the room's MULTIPOLYGON Z, SRID 4326).
6. Return `{building_su_id, cityjson_id, footprint_created, units_created}`.

This deliberately mirrors the existing `Bld_Unit_Create_View` parent/child pattern, so imported units behave exactly like manually-created ones (P4b LSBU pooling builds on these).

**Validation (offline):** `py_compile` clean; `manage.py check` RC=0 (URLConf + views + models import cleanly with deps absent, thanks to lazy import); `makemigrations user --check` → "No changes detected" (migration 0014 matches the model). **Not yet run end-to-end** — needs `ifcopenshell`+`shapely` in the backend venv and a live DB + a test parcel.

**Deploy checklist for P2 to run live:** (1) install `ifcopenshell` (0.8.x — **not on PyPI**; use conda or the IfcOpenShell standalone wheel) + `pip install shapely` in the backend venv; (2) `python manage.py migrate user`; (3) POST `LargeBuilding.ifc` + a real `parent_su_id`.

### 9.3.1 End-to-end attempt + GEOS-seam verification (2026-05-30)

A true HTTP→view→DB run was **not possible in this environment** — two hard blockers:
- **`ifcopenshell` can't be installed in the backend venv** (Python 3.11/Win): PyPI only lists `0.7.0.231018` and it has no cp311-win64 wheel; the 0.8.x line system-Python uses isn't on PyPI. (shapely installed fine → network is OK.)
- **No PostGIS running** (`localhost:5432` refused) — DB writes can't execute.

Instead I verified the **critical integration seam** the import view depends on, across the real env boundary: ran the converter under **system Python (real ifcopenshell 0.8.5 + shapely 2.1.2)** to produce the actual footprint + per-unit `MULTIPOLYGON Z` WKT, then parsed those exact strings in the **backend venv** via Django `GEOSGeometry(wkt, srid=4326)` — i.e. the same GEOS/GDAL the PostGIS writes go through. Result after the fix below: **8/8** (footprint parses + OGC-valid + srid 4326 + in WGS84 bounds; all 8 unit solids parse as 3D).

**Bug found & fixed (real):** the footprint passed system shapely's `is_valid` but the venv's older GEOS flagged a **self-intersection** — a cross-GEOS-version validity discrepancy that would have made `survey_rep.geom` writes fail/clean-up in PostGIS. `buffer(0)` was a no-op (its own GEOS thought it valid). Fixed in `FootprintExtractor._largest_valid_polygon`: **`set_precision` (grid-snap ~1e-7°≈1 cm) → `make_valid` → `buffer(0)` fallback**, applied as the final step. GEOS precision reduction removes the near-degenerate vertex deterministically, so the emitted WKT validates in any GEOS build. P1 still 12/12.

### 9.3.2 LIVE end-to-end test — ✅ PASSED (2026-05-30)

Both blockers from §9.3.1 turned out to be wrong: the backend **venv is actually Python 3.14** (not 3.11 as CLAUDE.md states), so `ifcopenshell 0.8.5` + `shapely 2.1.2` **installed cleanly via pip**; and **PostGIS is running** (`infobhoomi_dev`, 3627 parcels). So a true end-to-end run was done.

**Method:** drove the real `IFC_Cadastre_Import_View` via DRF `APIRequestFactory` + `force_authenticate` (real ORM, real GEOS/GDAL, real PostGIS), POSTing `LargeBuilding.ifc` onto a real parcel (`survey_rep id=11739`, layer 1, gnd 12458), anchor defaulted to the parcel centroid. Wrapped in an outer transaction that was **rolled back** — dev DB left untouched (verified: row counts restored).

**Result — PASS:**
- HTTP **201**; response `{building_su_id, cityjson_id, footprint_created:true, units_created:8}`.
- In-tx deltas: **+9 survey_rep** (1 building + 8 units), +9 la_spatial_unit, +9 la_ls_build_unit, +1 city_json.
- Building: `layer_id=3`, `parent_id=[11739]`, geom = **Polygon** (footprint).
- CityJSON row: **9 CityObjects** (1 Building + 8 rooms), keyed by building su_id.
- **8 child units** (`layer_id=12`, `parent_id=[building]`), all 8 `la_ls_build_unit` rows have **`geom_3d` = 3D MultiPolygon** (`hasz=True`).
- Sample unit: `apt_name='1'`, `floor_no=1`, `floor_area=49.92`, geom_3d MultiPolygon Z.
- **Rollback confirmed** — all counts restored to pre-test values.

**Migration `0014_cityjson_su_id` applied** to the dev DB (adds `su_id`/`name`/`source_file` to `city_json`). Deps now installed in venv. The full backend chain (IFC → CityJSON + footprint + LADM building + child units with 3D solids) is **verified working end-to-end**.

### 9.4 P3 — 2D frontend import flow (2026-05-30)

**Files:**
- `services/api.service.ts` — **fixed `load3DData`** (was ignoring the id and calling `cityjson/` → whole list; now `cityjson/?su_id=${featureId}`); added `getCityJsonById()` and `import3DObject({file, parentSuId, anchorLon/Lat, rotationDeg, scale, baseZ})` (multipart, `h(false)` auth-only header, progress events).
- `components/dialogs/import-3d/` (new) — `Import3dComponent` (standalone, OnPush): file picker + drag-drop (.ifc/.json), manual-placement fields (anchor lon/lat, rotation, scale, base-z; blank = parcel centre, backend default), upload-progress, success/error via `NotificationService`. Hides placement fields for direct CityJSON. Returns `{building_su_id, cityjson_id, footprint_created, units_created}`.
- `components/main/main.component.ts` + `.html` — context-menu items **"Import 3D Object"** (`onImport3D()` → opens dialog → on success `loadInitialMapLayers()` + `refreshCurrentSelection()`) and **"View as 3D"** (`onView3D()` → opens existing `ThreeDBuildingViewerComponent` with `feature_id`).

**Verified:** `tsc --noEmit` → 0 errors; **`ng build` (dev) → clean, no template/type errors** (42.7 s). Not yet exercised in a running browser against the live API (manual QA pending) — but the existing `three-d-building-viewer` already consumes `load3DData`, which now returns the correct per-building document.

**Note:** the `three-d-building-viewer` still validates `{features:[…]}` (GeoJSON-style) while the store returns raw CityJSON (`CityObjects`); reconciling that loader shape is a small follow-up (tracked in §8.2 risk 6) before "View as 3D" renders imported buildings. **→ Fixed in P4 (§9.5).**

### 9.5 P4 — City-3D feed, search & viewer seam (2026-05-30)

**Viewer seam fix (the §8.2-risk-6 / P3 follow-up):**
- `three-d-building-viewer.component.ts` — `load3DData` now returns a **list** of `CityJSON_Model` rows; added `extractCityJson(res)` to unwrap array / `{results:[]}` / single-row / bare-doc → the building's `cityjson_data`. Rewrote `validate3DData` to check **`CityObjects`** (CityJSON) instead of `features` (GeoJSON). The child `ViewerComponent` already consumed raw `CityObjects`/`vertices` correctly. So **"View as 3D" now renders imported buildings.**

**Backend endpoints (both scoped to the user's org area — `Org_Area_Model.org_area` GNDs vs `survey_rep.gnd_id`):**
- `GET /api/user/cityjson/admin-area/` → `City3D_AdminArea_View`: lightweight rows for every layer_id=3 building that has a stored CityJSON, within the user's area: `{su_id, gnd_id, name, cityjson_id, centroid}`. No geometry payload (the viewer fetches per-building via `/cityjson/?su_id=`).
- `GET /api/user/cityjson/search/?q=` → `City3D_Search_View`: matches `la_spatial_unit.label` + `la_ls_build_unit.apt_name/building_name` (and `cadastral_id` once P4b adds it — guarded dynamically), area-scoped; returns `{su_id, building_su_id, layer_id, kind, label, centroid}` for fly-to. Helper `_user_gnd_ids(user)`.
- Routes registered **before** `cityjson/<int:pk>/` so the literal paths win. `manage.py check` = 0 issues.

**Frontend service:** `api.service.ts` added `listAdminArea3DBuildings()` and `search3DObjects(q)`.

**Bug found & fixed during verification:** first run returned **HTTP 500** — `survey_rep.status` is a **varchar** column in the actual DB (the model declares `BooleanField`), so `filter(status=True)` produced invalid SQL (`argument of AND must be type boolean`). Removed the `status=True` predicate from both queries (the existing `Bld_Units_List_View` also doesn't filter on it). Re-verified after the fix.

**Verified:**
- Backend **live PASS** (rolled-back txn on dev DB, user id=1 / org_id=2, area = 34 GNDs, parcel id=11739): import → 201; `admin-area` status 200, count 1, **includes the new building = True**; `search('1')` status 200, **2 matches** (the unit labelled "1" + fuzzy), each with `building_su_id` + centroid for fly-to, area-scoped. DB untouched (rolled back).
- Frontend: `tsc` 0 errors; **`ng build` clean** (33.6 s) — viewer seam + service methods compile.

### 9.6 P4 UI — City-3D viewer (2026-05-30)

**New component `components/dialogs/city-3d-viewer/` (`City3dViewerComponent`, standalone, OnPush):**
- Loads `listAdminArea3DBuildings()`, then `forkJoin`s `load3DData(su_id)` for each → renders **all buildings in one three.js scene**. Each building is offset to its real-world position via the **equirectangular delta of its `metadata.georeferencing` anchor** vs a scene origin (first building's centroid) — same projection the backend converter uses, so relative placement is consistent.
- Reuses the proven geometry pipeline from `ViewerComponent` (`traverseBoundaries` → `earcut` ring triangulation, Z-up, OrbitControls).
- Left panel: **search box** wired to `search3DObjects(q)` (fly-to a hit's `building_su_id`) + a **building list** (click → fly-to). Loading/empty overlays.
- Entry point: a **"City 3D" button** (top-left of the map) in `main.component.html` → `onCity3D()` opens the dialog (96vw×90vh).

**Verified:** `tsc --noEmit` 0 errors; **`ng build` (dev) clean** (40.7 s). **NOT browser-verified** — three.js rendering, multi-building placement accuracy, and fly-to behaviour need manual QA with `npm start` against the live API (I can't run a browser in this environment). The data path it depends on (admin-area feed + per-building `load3DData` + search) is live-proven in §9.5.

**Still open in P4:** right-click "Import 3D" **parity inside** the 3D scene (currently import is 2D-map-only). Deferred — needs picking a parcel within the 3D scene first; revisit alongside P4b's Unit Composition picker which shares 3D-interaction plumbing.

### 9.7 P4b — LSBU composition (apartment pooling) (2026-06-01)

**Backend (`user/`):**
- `LA_LS_Build_Unit_Model` gained `building_unit_type`, `cadastral_id`, `component_units` (migration `0015_lsbu_composition_fields`, applied). `building.py` reads/writes them; IFC import seeds each room as `building_unit_type='UNASSIGNED'`, `component_units=[room_id]`.
- **Two endpoints** in `geo_utils.py` (registered in `urls.py`):
  - `GET /api/user/bld-3d/units/?building_su_id=` → `LSBU_Units_List_View`: returns the building's `pool` (UNASSIGNED rooms) + existing `lsbus`.
  - `POST /api/user/bld-3d/lsbu/compose/` → `LSBU_Compose_View`: groups selected units into one LSBU — first unit becomes the LSBU (type + cadastral_id + merged `component_units` + unioned `geom_3d` MULTIPOLYGON Z), others marked `ABSORBED` with a `parent_lsbu` back-pointer (reversible, no row deletion). Enforces: valid type, cadastral_id required for PRIVATE (RESIDENTIAL/COMMERCIAL), **exclusive membership** (409 if a unit is already in an LSBU).
- **Live-proven** (rolled-back txn, dev DB): import 8-room building → pool=8 → compose 4 → RESIDENTIAL "APT-A1", pool→4, 1 LSBU, `geom_3d` = MultiPolygon (48 polys), private-without-cadastral→400, reuse-absorbed→409. DB untouched.

**Frontend:**
- `api.service.ts`: `listBuildingUnits(buildingSuId)` + `composeLsbu({...})`.
- `components/dialogs/unit-composition/` (`UnitCompositionComponent`, standalone OnPush): loads the pool + the building CityJSON, renders rooms in three.js, **two-way highlight** (click a room in the model ↔ its list row, via a shared `roomId`→mesh map), Legal Space Type selector (private requires cadastral ID), composes via `composeLsbu`.
- `building-info-panel`: a Unit Composition opener (`openUnitComposition()` → opens the dialog with the building su_id) + `compositionChanged` emit; `side-panel.component.ts` reloads building data on success. Side panel also shows the per-unit Legal Space Type (parallel-session slice).

**Verified:** `ng build` (dev) **clean** (only pre-existing NG8107/NG8102 optional-chain warnings in unrelated `AdminHeaderComponent`/`BuildingReportComponent`; none in any 3D-cadastre file).

**Remaining (P4b polish):** reassign/unassign a unit between LSBUs (backend currently composes from the UNASSIGNED pool only; the `ABSORBED` back-pointer makes undo possible but no endpoint yet); update stored CityJSON membership metadata (`parent_lsbu` on Room objects, `children` on the LSBU object) after compose; in-dialog editing of existing LSBUs; **browser QA** of the whole workflow with a real imported IFC.

**Deferred to P4:** `bld-3d/admin-area/` (city feed, org_area filter) and `bld-3d/search/`. CityJSON-direct (.json) upload currently stores the doc without auto footprint/units (P5).

---

## 10. Storing CityJSON in PostgreSQL — cjdb evaluation & decision

**Can CityJSON be stored in PostgreSQL? Yes.** Three approaches:

| Approach | What it is | Fit for InfoBhoomi |
|----------|-----------|--------------------|
| **cjdb** (TU Delft) | Purpose-built CityJSON↔PostgreSQL importer/exporter. Creates a `cjdb` schema: `cj_object` (`object_id`, `type`, `attributes` JSONB, `geometry` JSONB in real-world coords, `parents`/`children` arrays, `ground_geometry` PostGIS + GiST) and `cj_metadata` (SRID, transform, bbox). Imports CityJSONFeature/CityJSONL, exports back, validates via cjio. | **Tooling, not primary store** (see below) |
| **Native PostGIS 3D** | Store solids as `POLYHEDRALSURFACE Z` / `SOLID` in a GeometryField; query with `ST_3D*`. **Already used** by `la_ls_build_unit.geom_3d` (SRID 4326). | **Yes — per-apartment legal solid** |
| **JSONB** | Raw CityJSON in a `JSONField`. Simplest; ideal for "load the whole building model for the viewer." | **Yes — full building model** |

**Why not cjdb as the primary store:** it manages its **own schema, SRID and object-id system**, separate from the Django-managed `survey_rep` / `la_ls_build_unit` tables where cadastral identity, the `parent_id` hierarchy and RBAC live. Using it live = **two sources of truth + two id systems** to reconcile. It's also designed for bulk dataset import/export, not per-building interactive insert/update.

**Decision — hybrid, single source of truth in Django (and it already exists):**
1. **Per-LSBU legal solid** → `la_ls_build_unit.geom_3d` (native PostGIS, indexed, already there). The cadastral truth.
2. **Full building CityJSON** (for the viewer) → the **existing `CityJSON_Model`** (table `city_json`): `cityjson_data` JSONField — **add an indexed `su_id` column** (P0 §8.1) so it's retrievable per building. No new model needed. Optionally add a 2D `ground_geometry` PostGIS column + GiST index later (cjdb-style) for spatial queries over the CityJSON.
3. **cjio/cjdb as tooling** — cjio for validation in the import pipeline; cjdb optionally for bulk import/export or interop. Not the app DB.

Import writes the assembled CityJSON to `cityjson` (keyed by building `su_id`) and the per-LSBU solids to `geom_3d`, from the *same* import run so they can't drift.

---

## 11. Legal Space Building Units, common property & manual unit composition

### 11.0 Terminology (LADM ISO 19152 — use these technical terms)
- **Unit** — the atomic legal/physical space = one `IfcSpace` / CityJSON `Room` (bedroom, kitchen, …). Identified by a **system UUID (auto-generated)**.
- **Legal Space Building Unit (LSBU)** — LADM `LA_LegalSpaceBuildingUnit`; a group of units forming one legally meaningful space (what users loosely call an "apartment"). Stored as the `layer_id=12` record.
- **Legal Space Type** — LADM **`LA_BuildingUnitType`** code list (this is the "apartment type" you asked for). Shown in **both** the 2D and 3D side panels, and is the category under which units are classified:
  - **Private / Exclusive** (privately owned) → `RESIDENTIAL` (apartment/flat), `COMMERCIAL` (shop/office). **Requires a cadastral, user-entered unique ID.**
  - **Common Property** (shared, undivided ownership; managed by the body corporate) → `CIRCULATION` (corridor, staircase, lift/elevator, lobby), `SERVICE` (plant/utility), `PARKING`, `AMENITY`. **System UUID; cadastral ID optional.**

> Summary of the hierarchy: a **Unit** (UUID) is classified under an **LSBU**, which has a **Legal Space Type**. **Private LSBUs (apartments) carry a cadastral, user-entered ID**; **common-property LSBUs (corridor/stairs/lift) do not require one** — only the auto UUID.

### 11.1 Model (decisions locked in)
**Modeling = 2-level (confirmed):** Building → LSBU. **Units live only inside the CityJSON** (no per-unit DB rows for now); the `3-level` option using `LA_LS_Ils_Unit_Model` is deferred.

LSBU = `Survey_Rep_DATA_Model` (`layer_id=12`, `parent_id=[building_su_id]`) + `LA_LS_Build_Unit_Model`, with NEW fields:
- **`building_unit_type`** (`LA_BuildingUnitType`) — required; drives Private-vs-Common behaviour and labelling.
- **`cadastral_id`** — **user-entered, accepted as given.** Required for Private types, optional for Common. *Never auto-generated, and the system does NOT enforce a uniqueness scope* — the cadastral user owns its correctness (per the decision). Store verbatim.
- **`uuid`** — `survey_rep.uuid`, the technical key (auto), present for every LSBU **and** every Unit (units' UUIDs live in the CityJSON).
- `geom_3d` = union of member-unit solids (multi-solid, SRID 4326); plus floor/area/use/RRR/utility fields (existing `la_ls_build_unit` + `la_ls_utinet_bu`).
- **Membership (exclusive):** each Unit belongs to **exactly one LSBU** (your "No" to multi-membership). Stored as (a) CityJSON `children` on the LSBU object **and** a `parent_lsbu` pointer on each Room object, plus (b) a JSONB `component_units` attribute on the LSBU row. Re-assigning a unit removes it from its previous LSBU first.

**Common-property ownership → BAUnit (confirmed):** every LSBU is also a spatial unit (`la_spatial_unit` via its `su_id`), so link it to a **BAUnit** (`SL_BA_Unit_Model`) through the existing **`LA_BAUnit_SpatialUnit_Model`** M:M table:
- **Private** LSBU → BAUnit of the apartment owner (`relation_type='PRIMARY'`).
- **Common Property** LSBU (corridor/stairs/lift/…) → the building's **shared/body-corporate BAUnit** (`relation_type='COMMON'` — add this value), i.e. undivided common ownership by all unit owners.
The import/composition step creates or reuses the appropriate BAUnit and writes the `LA_BAUnit_SpatialUnit_Model` link.

### 11.2 Side panels show LSBU-level info only — NOT a unit list
In both the 2D `BuildingInfoPanelComponent` and the city-3D panel, show **LSBU fields** — including **Legal Space Type** and **cadastral ID** — and **do not list the individual units**. Instead add a **"Unit Composition" button** that opens the separate window below.

### 11.3 Unit Composition window (separate window — manual unit picking)
A dedicated window/route, opened from either side panel (2D or 3D):
- Renders the building's **units (rooms)** in 3D (reuse the iTowns / ninja viewer), with the **unassigned-units pool** highlighted.
- The user **multi-selects units** (ctrl-click / box-select) and **attaches** them to:
  - an existing **Private LSBU** (apartment), or
  - a **Common Property LSBU** (corridor / staircase / lift / lobby …), or
  - a **new LSBU** created here (pick the Legal Space Type; if Private, enter the cadastral ID).
- **Save** → `POST/PATCH /api/user/bld-3d/lsbu/` (or extend `Bld_Unit_Create_View` / `Bld_Unit_Update_View`): merge selected unit solids → LSBU `geom_3d` (4326); create/update the `layer_id=12` LSBU (`parent_id=[building_su_id]`, `building_unit_type`, `cadastral_id`); record member unit ids; update stored CityJSON.
- Re-assigning a unit moves it between LSBUs (removed from the old, re-merged into the new); unassigning returns it to the pool.

**Two-way highlight (required confirmation aid):** selection is synced both directions —
- select a unit in the picker list → that unit's solid **highlights in the 3D model**;
- click a unit's solid in the 3D model → its row **highlights in the picker list**.
This lets the surveyor visually confirm the correct unit is attached to the intended apartment / legal space before saving. Implement via a shared selection signal keyed by the unit's CityJSON object id (UUID), driving both the iTowns feature style and the list state.

This keeps the side panels clean (LSBU-level) while unit-level editing lives in a focused 3D picker, available identically from 2D and 3D.

### 11.4 Sync — identical LSBU info in 2D InfoBhoomi **and** city-3D
Guaranteed by construction:
- **Single source of truth** = the LSBU DB row (`la_ls_build_unit` + `survey_rep`).
- **Same endpoints** both sides: `Bld_Unit_Detail_View` (GET), `Bld_Unit_Update_View` (PATCH), `Bld_Units_List_View` (GET `?parent_su_id=`).
- **Same field schema** — a shared LSBU model (extend `building-info.model.ts`, incl. `building_unit_type` + `cadastral_id`) used by both panels → field-for-field identical, all fields.
- **Same RBAC** — server-side `UNIT_ADMIN_FIELD_PERM` / `UNIT_UTIL_FIELD_PERM` honoured by both.
- After save both re-fetch → identical; optional live sync via a shared `LsbuStateService` (RxJS `BehaviorSubject` keyed by `su_id`).

### 11.5 Naming
- **Backend:** keep the managed table `la_ls_build_unit`; add `building_unit_type` + `cadastral_id`; treat `layer_id=12` as an LSBU. No destructive table rename.
- **Frontend:** label LSBUs as "Apartment / Common Space" per their `building_unit_type`; extend `building-info.model.ts` with a `LegalSpaceType` enum + `*_DISPLAY` map. Keep calling the `Bld_Unit_*` endpoints.

### 11.6 Resolved decisions (2026-05-30)
- **Modeling:** 2-level — units live in CityJSON only (3-level deferred). ✅
- **`cadastral_id`:** user-entered, stored verbatim; no system-enforced uniqueness scope. ✅
- **Common-property ownership:** link common LSBUs to a (shared/body-corporate) **BAUnit** via `LA_BAUnit_SpatialUnit_Model`. ✅
- **Unit membership:** exclusive — one unit → one LSBU. ✅
- **Confirmation:** two-way unit↔model highlight in the composition window (§11.3). ✅

Remaining to confirm later: `relation_type='COMMON'` value addition; whether the shared BAUnit is auto-created per building or selected; leftover/unassigned units are simply shown as the highlighted "unassigned pool" (no separate report).

---

## 12. Post-P4b refinements (2026-06-01, user-requested)

Executing one part at a time.

### Part A — Multi-anchor georeferencing ✅ DONE (build-verified)
Replaces the error-prone single rotation-angle input with **2–3 control-point pairs**; the system solves rotation + uniform scale + translation (2D similarity / Helmert).
- **Converter** (`ifc2cityjson_cadastral.py`): `TransformParams.from_anchor_pairs(pairs, base_z)` — each pair `{local:[x,y,z], lon, lat}`. Umeyama 2D similarity solve in a local-ENU metric frame around the first anchor's latitude; stores `rotation_deg/scale/anchor_lon/lat` in the existing fields + `fit_rms_m` (residual) + `n_anchors`. 2 pts = exact, 3+ = least-squares with residual reporting.
- **Math verified** offline: recovered known rotation 37° + scale exactly (RMS 0), round-trip 0 m, corrupted 3rd point → RMS 11.5 m (bad pick visible).
- **Import view** (`cityjson/import/`): accepts optional `anchor_pairs` (JSON); when ≥2 present, solves via `from_anchor_pairs` and overrides single-anchor inputs; returns `georeferencing` (incl. `method`, `fit_rms_m`) in the response.
- **Frontend** (`import-3d` dialog + `api.service`): placement-mode toggle (**Control points** [default] vs Single anchor); a 2–5 row anchor table (IFC X/Y/Z ↔ Lon/Lat), validates ≥2 complete pairs, sends `anchor_pairs`. Manual WGS84↔X/Y/Z entry (per user decision). `manage.py check` clean; `ng build` clean.
- *Remaining for A:* browser QA; optionally surface `fit_rms_m` as a post-import quality toast.

### Part B — Unified, editable, parcel-focused 3D view
**Decision (user):** this is a cadastral tool — legal spaces (rooms) are the objects; the building shell, parcel fabric and basemap are **context reused from existing assets**, not re-derived from IFC. So the vox shell-emission port was **dropped**, and the voxel room-detector is **deferred** until a space-less IFC appears (also avoids a `scipy` dependency — confirmed not installed).

**B1 + B2 ✅ DONE (build-verified):**
- **Backend:** `cityjson/admin-area/` now accepts optional `?parcel_su_id=` → returns only that parcel's buildings (`parent_id__contains`) **plus** the parcel's own 2D geometry as GeoJSON + centroid (`parcel` payload) — the reused cadastral fabric. Rows also carry `parent_su_id`. **Live-proven** (rolled-back): import → parcel feed returns count 1, `has_new=True`, parent matches, parcel Polygon + centroid present.
- **Frontend:** "View as 3D" (right-click a parcel) now opens the **closable** `City3dViewerComponent` in **parcel-focused mode** (`{parcelSuId, parcelLabel}`) instead of the old un-closable `ThreeDBuildingViewerComponent` (removed from `main`). The viewer: scene origin = parcel centroid; draws the **reused parcel polygon** as a flat ground slab at z=0 with outline, textured with an **OSM raster tile** (z18, parcel-bbox center; graceful fallback if the tile is blocked); buildings load on top via their georef anchor. `api.service.listAdminArea3DBuildings(parcelSuId?)`. `tsc` + `ng build` clean.
**B3a ✅ DONE (build-verified) — 3D picking drives the real side panel:**
- Every pickable mesh is tagged `userData = {kind, su_id, layerId}`: the parcel ground slab → `{parcel, parcelSuId, 1}`; building meshes → `{building, building su_id, 3}`. (Unit-level picking is B3b.)
- A raycaster **click** handler resolves the tagged `su_id` and **pushes the same `SelectedFeatureInfo` the 2D map emits** into `DrawService._selectedFeatureInfo` → the existing docked side panel runs its identical fetch/merge/tab logic (`fetchAndMergeLandParcelData` / `fetchAndMergeBuildingData`). **No panel duplication** — guaranteed 2D-identical fields by construction.
- The "View as 3D" dialog is now **non-modal, right-docked** (`hasBackdrop:false`, `position.right:0`, 64vw) so the real left side panel stays visible + interactive; pick also `setSidebarState(false)` to ensure it's open.
- `tsc` + `ng build` clean.
**B3b ✅ DONE (build-verified) — Units button + save-from-3D:**
- **Save from 3D works for free (B5):** the docked side panel saves via its existing `updateBuilding*`/`updateLand*` endpoints keyed on `this.selected_feature_ID` (set by the same `selectedFeatureInfo$` subscription B3a feeds). It is fully decoupled from the OpenLayers map — verified by reading the save path. So editing in the 3D-driven panel persists to the same DB, no new code.
- **Units / Compose button:** appears in the viewer header when a building is selected (3D mesh pick or building-list click → `selectBySuId(.,3)` sets `selectedBuildingSuId`). Opens the existing `UnitCompositionComponent` (3D room picker + **two-way highlight** + private/common LSBU compose) for that building; on success, re-fetches and redraws the building so the merged LSBU shows.
- Building-list rows now also select (drive side panel + enable Units button), not just fly-to.
- `tsc` + `ng build` clean.

**Scope note (honest):** the Unit Composition window already has the room-level two-way highlight (built in P4b). Picking an *individual room/unit* directly in the **main parcel viewer** (vs. inside the composition window) is **not** wired — main-viewer picks resolve to parcel or building level only. That's sufficient for the workflow (select building → Units button → compose with highlight), and avoids duplicating the room↔unit map in two viewers. If direct unit-pick in the main viewer is wanted later, it needs the `roomId→unit_su_id` map tagged onto room meshes there too.

### Part C — Role-based CRUD permissions ✅ DONE (live-verified)
- **Seeded** a new **"3D Cadastre"** permission category into `permission_list` via **migration `0016_3d_cadastre_permissions`** (applied) — 10 rows, ids **254–263**, `type=3`, sub-categories Import / Viewer / Composition (Import, Delete, View, City View, Search, Open Composition, Compose LSBU, Edit Legal Space Type, Edit Cadastral ID, Reassign Units). Idempotent `update_or_create` seed + reverse `unseed`. The Admin Panel role editor renders from this table, so the new category appears automatically.
- **Backend gating** (`geo_utils.py`): `_has_3d_perm(user, perm_id, action)` checks `Role_Permission_Model` across **all** the user's roles (fixed a single-role bug the test caught); fail-open only when the user has no roles at all. All five endpoints gated — import (`add`/254), admin-area (view/256 single or 257 city), search (258), composition list (259), compose (`add`/260) — returning 403 otherwise.
- **Live-verified** (rolled back): role **without** grant → compose **blocked**; role **with** grant → **allowed**. `manage.py check` clean, migrations in sync.
- **Frontend gating:** `Cadastre3DPermissions` id map in `core/constant.ts`; `main.component` loads them via `PermissionService.loadPermissions(roleId, …)` and `can3D(permId, action)` hides the context-menu **Import 3D Object** / **View as 3D** items and the **City 3D** toolbar button when the role lacks the grant (allow-all if unconfigured — backend still enforces). `tsc` + `ng build` clean.

---

## 13. Status summary (2026-06-01)
**All planned phases + the post-P4b refinement round are implemented and build/endpoint-verified.** P1 converter, P2 import (live E2E), P3 2D import flow, P4 city feed/search + viewer UI, P4b LSBU composition (live-proven), then refinements **A** (multi-anchor georef), **B** (closable parcel-focused 3D view: reused parcel fabric + OSM ground, clickable → real side panels identical to 2D, save-to-same-DB, Units/Compose button), and **C** (role permissions).

**Not yet done / explicitly deferred:** browser QA of the whole frontend (nothing run in a real browser — all verification is `ng build`/`tsc` + backend live-rollback); direct individual-room pick in the *main* viewer (composition window has it); reassign/unassign endpoint; CityJSON membership-metadata sync after compose; BAUnit common-property linkage; voxel fallback for space-less IFCs (deferred, needs `scipy`); cjio/val3dity validation; real floor-plan viewer (still mocked).

