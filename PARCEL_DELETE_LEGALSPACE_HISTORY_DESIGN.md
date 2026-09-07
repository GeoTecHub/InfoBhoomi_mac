# Parcel Delete → Legal-Space Cascade + History Report — Design

**Status:** Implemented 2026-06-06 (pending local `manage.py check` + `npm run build`)
**Date:** 2026-06-06
**Owner:** Milinda
**Related:** `3D_CADASTRE_INTEGRATION_DESIGN.md`, `user/signals.py`, `user/views/survey.py`, `user/views/history.py`, `parcel-history.component.*`

---

## 1. QA Requirement

> When a land parcel is deleted, all legal spaces associated with it must also be
> deleted and moved to history. The History dialog should offer a history *report*
> showing every historical change to the land, including the **previous shapes of
> its parent and child parcels**.

**Scope of "legal space" (confirmed):** buildings and their units, plus any other
legal-space feature created by right-clicking a parcel and adding it through the web
app (building footprints, strata/apartment units, OLS/ILS legal spaces, utility
networks). Each is its own `LA_Spatial_Unit` (`su_id`) with `LA_LS_*` sub-tables.

**Report delivery (confirmed):** a new in-dialog **Report** tab. No PDF/file export
in this iteration.

**Deleted-parcel lookup (confirmed):** because a deleted parcel is no longer drawn on
the map, the History dialog must include a **search** that finds a deleted parcel by
`su_id` / label and opens its full history report — the data still exists (soft-delete),
it's just not selectable on the map.

---

## 2. Data Model & Linkage (as built)

The cadastral hierarchy is expressed through `survey_rep` (geometry + lineage) and
`la_spatial_unit` (the LADM spatial unit), with `LA_LS_*` legal-space sub-tables
hanging off each `su_id`.

| Level | `layer_id` | Identity | Link to parent |
|-------|-----------|----------|----------------|
| Land parcel | 1 or 6 | own `su_id` | split/merge lineage via `survey_rep.parent_id[]` |
| Building (legal space) | 3 | own `su_id` | `survey_rep.ref_id` = parcel's `survey_rep.id` (inferred by spatial containment on save) |
| Strata / apartment unit | 12 | own `su_id` | `survey_rep.parent_id = [building_su_id]` |
| OLS / ILS / utility legal spaces | various | own `su_id` | `ref_id` / `parent_id` to their host |

Legal-space sub-tables keyed by `su_id` (OneToOne unless noted):
`LA_LS_Land_Unit`, `LA_LS_Zoning`, `LA_LS_Physical_Env`, `LA_LS_Utinet_LU`,
`LA_LS_Build_Unit`, `LA_LS_Utinet_BU`, `LA_LS_Ols_Polygon_Unit`,
`LA_LS_Ols_PointLine_Unit`, `LA_LS_Utinet_Ols`, `LA_LS_Ils_Unit`,
`LA_LS_Apt_Unit` (FK to `LA_LS_Ils_Unit`), `LA_LS_Utinet_AU` (FK to `LA_LS_Ils_Unit`).

Administrative side: `SL_BA_Unit` (`on_delete=PROTECT`) and `LA_RRR`
(`on_delete=PROTECT`) — these are why deletion is **soft** (`status=False`), never a
SQL `DELETE`.

History / archive tables already present:
`parcel_history` (`Parcel_History_Model`) — unified UI audit log,
`parcel_event` (`Parcel_Event_Model`) — legal event stack for rectification,
`parcel_delete_archive` (`Parcel_Delete_Archive_Model`) — JSON snapshot of attribute
sub-tables at delete time,
`survey_rep_geom_history` (`Survey_Rep_Geom_History_Model`) — geometry snapshots,
`survey_rep_func_history` (`Survey_Rep_History_Model`) — tool/function log.

---

## 3. What Works Today

`Survey_Rep_DelView.delete` (`user/views/survey.py`) already:

1. Permission-checks (`permission_id=201`, `delete=True`).
2. For the primary feature: archives the 6 main sub-tables to `parcel_delete_archive`,
   snapshots geometry to `survey_rep_geom_history`, soft-deletes `SL_BA_Unit` +
   `LA_Spatial_Unit`, writes a `parcel_history` GEOMETRY/DELETE row.
3. Walks **one level** of `ref_id` children and `parent_id` siblings, soft-deleting
   each and snapshotting their geometry.
4. Re-activates split/merge parents when their last active child is removed.

The History dialog (`Parcel_History_View` → `parcel-history.component`) already shows
Geometry, Attributes, RRR, and Relationships tabs and an `affected_parcels`
panel listing parents and children (current shapes only).

---

## 4. Gaps vs. Requirement

| # | Gap | Where |
|---|-----|-------|
| G1 | Cascade is **one level** and keyed on the primary feature's own `ref_id`/`parent_id`. Deleting a *parcel* does not recursively reach buildings on it, nor the units inside those buildings. | `survey.py: delete_record_and_related` |
| G2 | Archive only snapshots 6 sub-tables. `LA_LS_Apt_Unit`, OLS/ILS, `Utinet_AU`, `Utinet_Ols` legal spaces are not archived. | `survey.py: _archive_and_soft_delete_su`, `signals.py` |
| G3 | No per-legal-space **history row** is written on cascade delete, so the dialog can't list "Building X deleted / Unit Y deleted with the parcel". Only one GEOMETRY/DELETE row for the primary feature is recorded. | `survey.py` |
| G4 | Geometry tab pulls `survey_rep_geom_history` for the **selected su_id only** — no previous shapes of parents/children. | `history.py: Parcel_History_View` |
| G5 | No consolidated **Report** view aggregating all change types + parent/child shape lineage. | `parcel-history.component`, `history.py` |
| G6 | A deleted parcel is hidden from the map, so there is no way to reach its history once removed. No deleted-parcel search exists. | new `Deleted_Parcel_Search_View`, `parcel-history.component` |

---

## 5. Proposed Design

### 5.1 Backend — recursive legal-space cascade (G1, G2, G3)

Introduce a single traversal that, given the deleted parcel's `survey_rep` row,
collects the full descendant set before soft-deleting:

```
collect_descendants(parcel_survey_row):
    targets = []                       # list of (survey_rep_row, su_id, relation)
    # buildings sitting on the parcel
    buildings = Survey_Rep.filter(ref_id=parcel_survey_row.id, layer_id=3, status=True)
    for b in buildings:
        targets.append((b, b.su_id_id, 'building'))
        # strata / apartment units inside each building
        units = Survey_Rep.filter(parent_id__contains=[b.su_id_id], layer_id=12, status=True)
        for u in units:
            targets.append((u, u.su_id_id, 'unit'))
    # other legal spaces linked by ref_id (OLS/ILS/utility) not already captured
    others = Survey_Rep.filter(ref_id=parcel_survey_row.id, status=True).exclude(layer_id=3)
    ...
    return targets
```

Notes:
- Traverse **buildings before units** so deletion order is leaf-first (units, then
  buildings, then parcel) — keeps geometry snapshots coherent.
- De-duplicate against `processed_ids` (the existing loop already tracks this set).
- Keep everything **soft** (`status=False`) — `PROTECT` on `SL_BA_Unit`/`LA_RRR` still
  applies; a parcel/building that still holds an active title/RRR should be blocked
  with a clear error rather than silently orphaned. Decision point — see §7 Q1.

For each target, extend `_archive_and_soft_delete_su` to:
- Snapshot **all** legal-space sub-tables (add `apt_unit`, `ols_*`, `ils`, `utinet_au`,
  `utinet_ols` to the archive payload — requires new nullable JSON columns on
  `parcel_delete_archive`, migration `00XX_archive_extra_legalspaces`).
- Write a `parcel_history` row per legal space:
  `record_type=RELATIONSHIP` or a new `record_type='legal_space'`,
  `action=DELETE`, `change_summary="Building 12507 deleted with parcel 12506"`,
  `snapshot={relation, layer_id, label, parent_su_id}`, `can_restore=False`.
  This is what makes the deletions visible in the dialog (G3).
- Write the geometry snapshot to `survey_rep_geom_history` (already done per target by
  `_archive_geom_history`; ensure it's called for every descendant).

The top-level `delete()` loop changes from "primary + one level of ref/parent" to
"primary + `collect_descendants` set", reusing the existing per-record helpers. The
`signals.py` `pre_delete` archive path stays as a safety net for any hard delete but is
not the primary mechanism (soft-delete path is).

### 5.2 Backend — parent/child previous shapes (G4)

In `Parcel_History_View.get`, after computing parent ids (`survey.parent_id`) and child
ids (`parent_id__contains=[su_id]` + `ref_id=su_id`), also fetch their geometry
lineage:

```
related_su_ids = parent_ids + child_ids
shape_lineage = Survey_Rep_Geom_History.filter(su_id__in=related_su_ids).order_by('-date_created')
```

Return a new response key `shape_lineage`: a list of
`{su_id, relation: 'parent'|'child', date, geom: geojson, calculated_area, status}`,
so the dialog can render previous shapes grouped by related parcel. Keep payload light —
return GeoJSON only (already how geometry rows are serialized) and cap per-parcel history
depth (e.g. latest 20) to avoid large responses.

### 5.3 Frontend — Report tab (G5)

Add a **Report** `mat-tab` to `parcel-history.component.html`, after Relationships.
It composes the data already loaded plus the new `shape_lineage`:

- **Header:** subject parcel `su_id` + label, generated timestamp, acting user.
- **Summary counts:** N attribute changes, N geometry changes, N RRR events,
  N legal spaces deleted with this parcel.
- **Lifecycle timeline:** reuse the existing `timeline` array, rendered chronologically
  (create → edits → split/merge → delete), one line per event.
- **Legal spaces removed:** table of buildings/units/legal spaces deleted with the
  parcel (from the new `legal_space` history rows): type, su_id, label, date.
- **Shape lineage:** for the parcel and each parent/child, a small list (or inline SVG
  mini-map) of previous shapes with date + area, driven by `shape_lineage`. Phase 1
  can render area + date text; Phase 2 can draw the GeoJSON in a tiny OpenLayers/SVG
  thumbnail.

No new API call — the Report tab is a pure projection of the augmented
`getParcelHistory` response, so it stays in sync with the other tabs.

### 5.4 Deleted-parcel search (new requirement)

A deleted parcel keeps its `su_id` and all history/archive rows; it's only hidden from
the map (`survey_rep.status=False`). Add a lookup path so users can reach it:

- **Backend** — `GET /api/user/deleted-parcels/?q=<term>`
  (`Deleted_Parcel_Search_View`). Queries `survey_rep` (or `parcel_delete_archive`)
  where `status=False` and `layer_id IN (1,6)`, matching `su_id` exactly or `label`
  by `icontains`. Returns `[{su_id, label, deleted_at, deleted_by, calculated_area}]`,
  newest first, capped (e.g. 50). `deleted_at`/`deleted_by` come from
  `parcel_delete_archive`.
- **Frontend** — a search box pinned at the top of the History dialog (visible on every
  tab). Typing a `su_id` or label shows matching deleted parcels; selecting one calls
  the existing `getParcelHistory(su_id)` and re-renders the dialog (including the Report
  tab) for that parcel. The dialog already accepts `suId` as input, so this just swaps
  `selectedSuId` and reloads. A small "Deleted" badge distinguishes archived results.

This makes the History dialog a standalone way to audit any parcel — live or deleted —
without needing it visible on the map.

---

## 6. Implementation Plan (phased)

**Phase 1 — Backend cascade (G1, G2, G3)**
1. Migration: add nullable JSON columns to `parcel_delete_archive` for the extra legal
   spaces; (optional) add `'legal_space'` to `Parcel_History_Model` record-type choices.
2. `survey.py`: add `collect_descendants`; rewrite the delete loop to use it;
   extend `_archive_and_soft_delete_su` to snapshot all sub-tables and emit a
   per-legal-space history row.
3. Unit test: delete a parcel with 1 building + 2 units → assert all soft-deleted,
   archive rows present, history rows present, `SL_BA_Unit`/`LA_RRR` PROTECT respected.

**Phase 2 — Parent/child shape lineage (G4)**
4. `history.py`: add `shape_lineage` to the `Parcel_History_View` response.
5. Serializer/shape: confirm GeoJSON + SRID handling matches existing geometry rows.

**Phase 3 — Report tab + thumbnails (G5)**
6. `parcel-history.component.ts`: bind `shapeLineage`, add `report` getters/counts,
   add an SVG path-builder that normalizes GeoJSON to a thumbnail viewBox.
7. `parcel-history.component.html` + `.css`: Report tab markup with inline SVG
   thumbnails for parcel + parent/child previous shapes.
8. `npm run build` (outside sandbox, per existing project note).

**Phase 4 — Deleted-parcel search (G6)**
9. Backend `Deleted_Parcel_Search_View` + URL `deleted-parcels/`.
10. Frontend search box in the History dialog header; wire to `getParcelHistory`.

**Phase 5 — Verification**
11. Backend `venv\Scripts\python.exe manage.py check` + new tests (cascade delete of
    parcel + building + 2 units; rights terminated; history rows emitted; search
    returns the deleted parcel).
12. Browser QA: right-click a parcel with a building + units, delete it, then search
    its `su_id` in History and confirm the Report tab lists removed legal spaces,
    terminated rights, and previous shapes with thumbnails.

---

## 7. Decisions (resolved — 2026-06-06)

**Q1 — Rights on cascade: TERMINATE, never block.** When a parcel is deleted, all
legal rights to its buildings/units become null and void. The cascade therefore
**soft-terminates** every `SL_BA_Unit` and `LA_RRR` on the parcel and its descendants
(`status=False`) and records each termination in history (`record_type='legal_space'`,
`action='terminate'`). No "clear rights first" block, no force-flag. Because we never
issue a SQL `DELETE`, the `PROTECT` constraints are never tripped — flipping `status`
satisfies integrity while voiding the rights.

**Q2 — Restore is OUT OF SCOPE.** Cascade-delete history is **read-only**. All emitted
rows keep `can_restore=False`. No per-legal-space restore in this iteration.

**Q3 — Geometry thumbnails REQUIRED.** The Report tab renders inline geometry
thumbnails for the parcel and each parent/child previous shape (not just date+area
text). Implementation: server returns GeoJSON in `shape_lineage`; the frontend draws
each shape as a small inline **SVG** (normalized to the feature's bounding box) — no
map tiles needed, so thumbnails render offline and print cleanly. Area + date caption
sits under each thumbnail.

**Q4 — Dedicated `'legal_space'` record type.** Add
`RECORD_LEGAL_SPACE = 'legal_space'` to `Parcel_History_Model` (`ACTION_TERMINATE`
already exists). Cleaner filtering for the Report tab's "Legal spaces removed" section
and the rights-termination rows. Tiny, additive migration.

---

## 7a. Implementation summary (2026-06-06)

Files changed:

- `user/models/history.py` — `Parcel_History_Model.RECORD_LEGAL_SPACE`; 9 new
  `parcel_delete_archive` columns (apt/OLS/ILS/utility snapshots + `parent_su_id`,
  `space_kind`, `layer_id`).
- `user/migrations/0018_archive_extra_legalspaces.py` — additive migration for the above.
- `user/views/survey.py` — `_by_su`, `_terminate_rights`, rewritten
  `_archive_and_soft_delete_su` (all legal-space snapshots + rights termination +
  `legal_space` history rows), new `_collect_legal_space_descendants`, and the
  cascade now drives section 3 of `delete_record_and_related`.
- `user/views/history.py` — `_geojson` + `_shape_lineage` helpers; `legal_spaces`
  and `shape_lineage` added to `Parcel_History_View`; new `Deleted_Parcel_Search_View`.
- `user/urls.py` — `deleted-parcels/` route.
- `parcel-history.component.ts/.html/.css` — Report tab (counts, lifecycle,
  legal-spaces-removed, terminated rights, SVG shape thumbnails), deleted-parcel
  search box, `FormsModule`.
- `api.service.ts` — `searchDeletedParcels(query)`.

Verification done here: Python additions syntax-checked (skeleton compile for
`survey.py`; `history.py`/migration/model parse clean). NOT run here due to a sandbox
mount-sync limitation: `manage.py makemigrations --check` / `migrate` and
`npm run build`. Run those locally:

```
cd InfoBhoomi_Backend_dev2 && venv\Scripts\python.exe manage.py migrate user 0018
venv\Scripts\python.exe manage.py check
cd ..\infoBhoomi-frontedend-div2 && npm run build
```

## 8. Risk & Rollback

- The delete path is performance-sensitive (it logs timings). The recursive traversal
  adds queries proportional to descendant count; batch with `__in` filters and reuse
  the existing single-`UPDATE` patterns.
- All changes are additive (new columns, new response key, new tab). Existing behavior
  for parcels with no legal spaces is unchanged.
- Rollback: revert the `survey.py`/`history.py` edits and the frontend tab; the new
  archive columns are nullable and harmless if left in place.
