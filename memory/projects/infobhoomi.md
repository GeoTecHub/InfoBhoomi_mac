# InfoBhoomi — Project Memory

**Full name:** InfoBhoomi Land Administration Web-GIS
**Purpose:** Municipal land administration for Sri Lankan local government (LADM ISO 19152)

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.1, DRF, PostGIS, Python |
| Frontend | Angular 21, OpenLayers, Angular Material |
| DB | PostgreSQL + PostGIS |
| Auth | DRF Token Authentication |
| Projection | EPSG:5235 (Sri Lanka) primary, EPSG:4326 for storage |

---

## Key Paths

```
InfoBhoomi_Backend_dev2/
  user/
    models/
      core.py          ← Survey_Rep_DATA_Model (survey_rep table)
      spatial_units.py ← LA_Spatial_Unit_Model, LA_LS_* attribute models
      assessments.py   ← Assessment_Model, Tax_Info_Model
      history.py       ← Parcel_Delete_Archive_Model
      auth.py          ← Custom User model
    views/
      survey.py        ← Save/retrieve/delete geometry (survey_rep_data/)
      land.py          ← Land attribute views + Lnd_Summary_View
      search.py        ← Query_Parcels_View, Query_Parcels_SHP_Export_View
    signals.py         ← pre_delete archive + post_save placeholder creation
    apps.py            ← registers signals in ready()
    migrations/
      0001_initial.py
      0002_baseline_schema.py  ← faked (DB already had schema)
      0003_create_parcel_archive_table.py

agents/
  orchestrator.py      ← runs perf agent then QA agent in cycles
  agents/
    gis_perf_agent.py  ← timing tests (PATCH not PUT for feature update)
    qa_agent.py        ← 42-test functional suite
    research_agent.py  ← uses Anthropic tool_use API (not raw JSON)
  .env                 ← IB_BASE_URL=http://127.0.0.1:8000/api/user (local)
```

---

## 3D Cadastre Current Handoff (May 2026)

Design reference: `3D_CADASTRE_INTEGRATION_DESIGN.md`.

Current stage:
- P4 is mostly complete: IFC/CityJSON import, City 3D feed/search, viewer data-shape fix, and City 3D UI foundation exist.
- P4b has started: Legal Space Building Unit composition persistence is now added.

Latest completed P4b slice:
- Backend `LA_LS_Build_Unit_Model` has `building_unit_type`, `cadastral_id`, and `component_units`.
- Migration: `InfoBhoomi_Backend_dev2/user/migrations/0015_lsbu_composition_fields.py`.
- Existing building-unit list/detail/create/update views now carry those fields.
- IFC import creates imported room units as `UNASSIGNED` and stores their CityJSON room id in `component_units`.
- Frontend `BuildingUnit` has `legalSpaceType`.
- Frontend Building Units / Strata panel shows Legal Space Type and saves/loads the new fields.
- P4b Unit Composition dialog is wired from the Building Units / Strata panel. It loads unassigned room units, renders the building CityJSON rooms in 3D, supports two-way list/model selection, and posts composition to `/api/user/bld-3d/lsbu/compose/`.
- The backend migration `user.0015_lsbu_composition_fields` was applied successfully.
- Checks passed: backend `manage.py check`; frontend `npm run build` (existing Angular warnings remain).

Next work:
- Browser-test the Unit Composition workflow with a real imported IFC building.
- Confirm selected CityJSON rooms/spaces can be assigned to Private/Common Property LSBUs and persist after refresh.
- Add reassign/unassign support for already composed room units.
- Update CityJSON membership metadata.
- Add two-way highlight between room list and 3D room mesh.
- Add BAUnit linkage for private/common ownership.

---

## DB Key Facts

- **survey_rep** table = `Survey_Rep_DATA_Model` — stores all geometry (polygons, points, lines)
- **su_id** in survey_rep is a FK to `la_spatial_unit.su_id` (soft FK, db_constraint=False)
- After INSERT into survey_rep, view explicitly runs:
  `Survey_Rep_DATA_Model.objects.filter(id=X).update(su_id_id=X)`
  (fallback because trigger `trg_survey_rep_su_id` may not exist on restored DBs)
- **la_spatial_unit** is the LADM anchor record — created for every saved geometry
- Attribute tables (la_ls_land_unit, la_ls_zoning, etc.) created lazily on first edit

---

## Known Issues Fixed (April 2026)

### 1. ladm_anti_conflict() trigger — pg_sleep(4) stub
**Symptom:** Every survey_rep INSERT/UPDATE took 20 seconds. D1/D2/D6 attribute saves took 4s each.
**Root cause:** `ladm_anti_conflict()` function body was literally `PERFORM pg_sleep(4); RETURN NEW;` — a developer placeholder never implemented.
**Tables affected:** survey_rep, la_spatial_unit, la_ls_land_unit, la_ls_utinet_lu, la_ls_build_unit, la_ls_utinet_bu, la_rrr, la_spatial_source, la_admin_source
**Fix applied:**
```sql
DROP TRIGGER IF EXISTS ladm_trigger ON survey_rep;
DROP TRIGGER IF EXISTS ladm_trigger ON la_spatial_unit;
DROP TRIGGER IF EXISTS ladm_trigger ON la_ls_land_unit;
DROP TRIGGER IF EXISTS ladm_trigger ON la_ls_utinet_lu;
DROP TRIGGER IF EXISTS ladm_trigger ON la_ls_build_unit;
DROP TRIGGER IF EXISTS ladm_trigger ON la_ls_utinet_bu;
DROP TRIGGER IF EXISTS ladm_trigger ON la_rrr;
DROP TRIGGER IF EXISTS ladm_trigger ON la_spatial_source;
DROP TRIGGER IF EXISTS ladm_trigger ON la_admin_source;
DROP FUNCTION IF EXISTS public.ladm_anti_conflict();
```

### 2. gnd_id column deleted by migration
**History:** A migration deleted the `gnd_id` column from `survey_rep`. User replaced the DB to restore it. The new DB did not have `trg_survey_rep_su_id` trigger re-created.
**Fix:** Added fallback `Survey_Rep_DATA_Model.objects.filter(id=X).update(su_id_id=X)` in save view after LA_Spatial_Unit_Model creation.

### 3. status column type mismatch
**Symptom:** `operator does not exist: character varying = boolean` errors on survey_rep queries.
**Fix:** `ALTER TABLE survey_rep ALTER COLUMN status TYPE BOOLEAN USING CASE WHEN status IN ('true','True','TRUE','1','t') THEN TRUE ELSE FALSE END;`

### 4. record.area AttributeError in search.py and land.py
**Symptom:** H1, I1 (query-parcels), E7 (lnd-summary) returning HTTP 500.
**Fix:** Changed `record.area` → `record.calculated_area` in both views. The model field is `calculated_area`, not `area`.

### 5. Migration state (0002 faked)
**History:** User deleted all migrations except 0001. Ran `makemigrations --name baseline_schema` then `migrate --fake` to sync state without re-running SQL.
**0003** created with `SeparateDatabaseAndState` to create `parcel_delete_archive` table (state already captured in 0002).

### 6. post_save signal lock contention
**Fix:** Wrapped placeholder `get_or_create` calls in `transaction.on_commit()` in signals.py to avoid PostgreSQL lock contention inside the open survey_rep transaction.

### 7. Research agent JSON parse failures
**Fix:** Switched `_generate_fixes()` to use Anthropic tool_use API instead of raw JSON parsing. Code snippets with `{}` no longer break parsing.

### 8. RRR "Unknown holder" — party_name not displayed
**Symptom:** After saving an RRR, the holder name shows as "Unknown holder" in the panel.
**Root cause:** Backend `RRR_Data_get_View` returns parties nested under `rrr.parties[0].party_name`, but frontend `side-panel.component.ts` was reading `rrr.party_name` and `rrr.pid` directly at the RRR level (both `undefined`).
**Fix:** `side-panel.component.ts` — two blocks (land ~line 779, building ~line 977) — read from the parties array:
```typescript
const primaryParty = (rrr.parties || [])[0];
holder: primaryParty?.party_name || '',
holderId: String(primaryParty?.pid || ''),
share: primaryParty?.share ?? rrr.share,
```

### 9. Physical env 400 Bad Request
**Symptom:** `PATCH /api/user/lnd-physical-env/update/su_id=<id>/` returns 400.
**Root causes (3):**
1. `allowed_fields` empty for some roles → serializer got no data → validation failed.
2. Frontend sends `elevation`/`slope` as floats with too many decimal places (exceeds `max_digits`).
3. Frontend sends `flood_zone` as JavaScript boolean (`true`/`false`), but model is `CharField`.
**Fix:** `views/land.py` — `Lnd_Physical_Env_Update_View.patch()`:
- Early return HTTP 200 if `allowed_fields` is empty.
- Round `elevation` to 3 dp, `slope` to 2 dp before serializer.
- Coerce `flood_zone`: `True → 'High'`, `False → 'None'`.

---

## QA Agent Test Map (42 tests)

| Phase | Tests | What it covers |
|-------|-------|---------------|
| A | A1-A3 | Point save + retrieve |
| B | B1-B2 | Line save + geometry type |
| C | C1-C4 | Polygon save + response fields + timing |
| D | D0-D6 | All 6 attribute table saves |
| E | E1-E8 | DB verification of all attributes + land summary + geom history |
| F | F1-F5 | Split/merge simulation |
| G | G0-G4 | Delete + history tables |
| H | H1-H4 | Query builder (layer_ids 1,3,6,12 only) |
| I | I1-I2 | Shapefile export |
| J | J0-J1 | Cleanup |

**Current status (2026-04-09):** 41/42 passing. Only C4 (save timing) fails — fixed after dropping ladm_anti_conflict trigger.

---

## API Endpoints (local: http://127.0.0.1:8000/api/user)

| Method | URL | Purpose |
|--------|-----|---------|
| POST | /survey_rep_data/ | Save geometry (list of GeoJSON features) |
| POST | /survey_rep_data_user/ | Retrieve user's features (GeoJSON FeatureCollection) |
| PATCH | /survey_rep_data/update/id=\<pk\>/ | Update feature attributes |
| POST | /query-parcels/ | Query builder (layer_ids: 1,3,6,12) |
| POST | /query-parcels/export-shp/ | Export shapefile ZIP |
| PATCH | /lnd-admin-info/update/su_id=\<id\>/ | Save admin info |
| PATCH | /lnd-overview/update/su_id=\<id\>/ | Save overview |
| PATCH | /lnd-zoning/update/su_id=\<id\>/ | Save zoning |
| PATCH | /lnd-physical-env/update/su_id=\<id\>/ | Save physical env |
| PATCH | /lnd-tax-info/update/su_id=\<id\>/ | Save tax info |
| PATCH | /lnd-utility/update/su_id=\<id\>/ | Save utility network |
| GET | /lnd-summary/su_id=\<id\>/ | Land summary (permission-filtered) |
| GET | /geom-edit-history/su_id=\<id\>/ | Geometry edit history |
| DELETE | /delete-record/ | Bulk delete parcels |
