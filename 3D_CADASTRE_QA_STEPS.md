# 3D Cadastre — Browser QA Script

**Goal:** validate the parts that have only been build/endpoint-verified, in a real browser.
**Test data:** `3D-Cadastre/IFC/LargeBuilding.ifc` (8 IfcSpace rooms, 2 storeys).
**Reference:** full design in `3D_CADASTRE_INTEGRATION_DESIGN.md`.

---

## 0. Pre-flight (one-time)

| # | Action | Expected |
|---|--------|----------|
| 0.1 | Backend: `cd InfoBhoomi_Backend_dev2 && venv\Scripts\python.exe manage.py migrate` | up to `0016_3d_cadastre_permissions` applied |
| 0.2 | Backend deps present: `venv\Scripts\python.exe -c "import ifcopenshell, shapely"` | no error (already installed) |
| 0.3 | Backend: `venv\Scripts\python.exe manage.py runserver` | serving on :8000 |
| 0.4 | Frontend: `cd infoBhoomi-frontedend-div2 && npm start` | serves; open the app, log in |
| 0.5 | Confirm `environment.ts` `API_URL` points at your running backend | requests hit local backend |
| 0.6 | Pick a **test parcel** in your GND/org area; note its `su_id` (click it → side panel shows it). Use a parcel you can pollute (this writes real rows). | have a target parcel |

> ⚠️ Steps 2–6 **write to the DB**. Use a dev DB / test parcel. To undo, delete the created building `survey_rep` (layer_id=3) + its child units (layer_id=12) + the `city_json` row for that building su_id.

---

## 1. Permissions appear in Admin Panel (Part C)
| # | Action | Expected |
|---|--------|----------|
| 1.1 | Admin Panel → Roles → edit a role | role permission editor opens |
| 1.2 | Look for category **“3D Cadastre”** | category present with 10 rows (Import / Viewer / Composition groups) |
| 1.3 | For your QA user's role, **grant**: Import 3D (add), View Building (view), City 3D (view), Search (view), Open Composition (view), Compose LSBU (add) | saved |
| 1.4 | (Negative) In a second role with **no** 3D grants, log in as that user | Import-3D / View-3D context items and City-3D button are **hidden** |

---

## 2. Import with multi-anchor georeferencing (Part A + P3)
| # | Action | Expected |
|---|--------|----------|
| 2.1 | On the 2D map, **right-click the test parcel** | context menu shows **Import 3D Object** + **View as 3D** |
| 2.2 | Click **Import 3D Object** | dialog opens; placement mode defaults to **Control points** |
| 2.3 | Pick `LargeBuilding.ifc` (browse or drag-drop) | filename shows; no error |
| 2.4 | Enter **2 anchor rows** — IFC X/Y/Z and the matching Lon/Lat. (For a first smoke test you may use the **Single anchor** mode instead → centroid default.) | “2 complete pair(s)” shown |
| 2.5 | Click **Import** | progress bar → success toast “footprint created, 8 unit(s)” |
| 2.6 | Map refreshes | a building footprint polygon appears on/near the parcel |
| 2.7 | Open the parcel’s side panel → building units list | 8 child units listed (all type **UNASSIGNED**) |

**Anchor-math sanity (optional):** import once with control points, once with single-anchor; the control-point placement should land the footprint where your Lon/Lat pairs say (rotation auto-solved).

---

## 3. Parcel-focused 3D view — closable, parcel + OSM (Part B1/B2)
| # | Action | Expected |
|---|--------|----------|
| 3.1 | Right-click the parcel → **View as 3D** | 3D viewer opens **right-docked**, left side panel still visible |
| 3.2 | Header has a **✕ Close** | clicking it closes the viewer (the old “can’t close” bug is gone) |
| 3.3 | Scene content | **parcel polygon as a flat ground slab** + **OSM map texture** on it + the imported building sitting on top |
| 3.4 | If OSM tile blocked by network/CORS | slab still shows (plain), no crash (graceful fallback) |
| 3.5 | Orbit/zoom/pan | smooth; building + parcel framed |

---

## 4. Clickable 3D → real side panel, identical to 2D (Part B3a + B4)
| # | Action | Expected |
|---|--------|----------|
| 4.1 | Click the **building** in 3D | left side panel switches to **Building** tab, populated (same fields as a 2D building click) |
| 4.2 | Click the **parcel ground** in 3D | side panel switches to **Land** tab, populated with the parcel’s LADM data |
| 4.3 | Compare a couple of fields against a 2D click on the same parcel/building | **identical values** |

---

## 5. Edit in 3D → saves to same DB (Part B5)
| # | Action | Expected |
|---|--------|----------|
| 5.1 | With the building selected from a 3D click, edit a field in the side panel (e.g. building name / a unit’s floor area) | field editable |
| 5.2 | Save | success toast |
| 5.3 | Reload (F5), select the same building (2D or 3D) | edited value **persisted** |
| 5.4 | (Cross-check) Backend shell: the `la_ls_build_unit` / `survey_rep` row reflects the change | matches |

---

## 6. Unit Composition + two-way highlight (P4b + B3b)
| # | Action | Expected |
|---|--------|----------|
| 6.1 | In the 3D viewer, select the **building** | a **Units / Compose** button appears in the header |
| 6.2 | Click **Units / Compose** | composition window opens; rooms render in 3D; left list shows the unassigned rooms |
| 6.3 | **Click a room in the 3D model** | its **list row highlights** |
| 6.4 | **Click a row in the list** | the **3D room highlights** (two-way) |
| 6.5 | Select 3–4 rooms; set Legal Space Type = **RESIDENTIAL**; enter a **Cadastral ID** (e.g. APT-A1); Save | success; window closes |
| 6.6 | Negative: try **RESIDENTIAL** with **no** cadastral ID | blocked with a “cadastral ID required” message |
| 6.7 | Back in the building, open Units list / side panel | one LSBU (APT-A1) now present; the pooled rooms no longer in the unassigned pool |
| 6.8 | Try composing a **Common Property** type (e.g. CIRCULATION) from remaining rooms — no cadastral ID needed | succeeds |
| 6.9 | Negative: re-compose using an already-grouped room | rejected (409 — exclusive membership) |

---

## 7. City 3D view + search (Part P4 + C)
| # | Action | Expected |
|---|--------|----------|
| 7.1 | Click the **City 3D** button (top-left of map) | full-area viewer opens; all imported buildings in your org area render |
| 7.2 | Buildings outside your GND/org area | **not** shown (admin-area filter) |
| 7.3 | Type a unit/apartment name or cadastral ID in **Search** → Enter | results list; clicking a result flies the camera to that building |
| 7.4 | Click a building in the list | camera fly-to + selection |

---

## 8. Permission enforcement (Part C, backend)
| # | Action | Expected |
|---|--------|----------|
| 8.1 | As the **no-3D-grant** user, even if you reach an endpoint (e.g. via direct call) | backend returns **403** for import / compose / view |
| 8.2 | As the granted user | endpoints succeed |

---

## What to capture per failure
- Browser console errors (F12) + the failing **network request/response** (status + JSON body).
- For 3D render issues: a screenshot + whether `load3DData`/`admin-area` returned CityJSON with non-empty `CityObjects`.
- For placement issues: the `georeferencing` block in the import response (`method`, `fit_rms_m`).

## Known not-yet-implemented (don’t file as bugs)
- Direct **individual-room pick in the main parcel viewer** (use Units/Compose window for room-level).
- **Reassign/unassign** a unit between LSBUs (compose only consumes the unassigned pool).
- CityJSON membership-metadata sync after compose; BAUnit common-property linkage.
- Voxel fallback for IFCs with **no** IfcSpace (needs scipy); cjio/val3dity validation; real floor-plan viewer (mocked).

---

## 9. Console diagnostics — copy-paste for support

Every new 3D code path logs to the browser console with a **`[3DQA]`** prefix, so a
failing run produces a clean trace you can copy and send.

**How to capture:**
1. Open the app, press **F12** → **Console** tab.
2. In the console filter box, type **`3DQA`** (hides all unrelated noise).
3. Reproduce the issue (import / view 3D / pick / compose / city view).
4. Right-click in the console → **Save as…** (or select all → copy) and paste it back to me.
5. Also expand and copy any red **`❌`** lines and any failing **Network** request (status + response body).

**Toggle:** logging is ON by default. To silence it: `localStorage.setItem('qa3d','0')` then reload. Re-enable: `localStorage.removeItem('qa3d')`.

**What each tag means (so you know which step failed):**

| Log line (prefix `[3DQA]`) | Tells us |
|----------------------------|----------|
| `[Main] onImport3D / onView3D / onCity3D` | which action you triggered + the su_id/layer |
| `[Main] 3D permissions loaded {…}` | which 3D permissions your role has (or allow-all) |
| `[Import3D] submit {mode, pairCount, …}` | the import request (anchor-pairs vs single) |
| `[Import3D] import OK {georeferencing:{method, fit_rms_m}}` | success + the solved transform + **fit error in metres** (high = bad anchor pick) |
| `[Import3D] ❌ import FAILED (HTTP …)` | server rejected import — body shows why |
| `[CityViewer] scene-init ok {webgl:true}` | three.js/WebGL initialised (false/❌ = GPU/WebGL problem) |
| `[CityViewer] admin-area response {buildings, hasParcel, parcelGeojsonType}` | did the backend return the parcel + buildings? |
| `[CityViewer] parcel-ground {rings}` / `❌ NO RINGS` | parcel slab drew, or parcel geometry was empty/unsupported |
| `[CityViewer] osm-tile ok` / `❌ osm-tile FAILED` | OSM basemap texture loaded or was blocked (not fatal) |
| `[CityViewer] building drawn {objects, vertices}` / `❌ building NOT drawn` | each building rendered, or had no geometry |
| `[CityViewer] pick {kind, su_id, layerId}` | what you clicked resolved to in 3D |
| `[CityViewer] select -> side panel {suId, layerId}` | selection was pushed to the side panel |
| `[UnitComp] loaded {poolUnits, cityObjects, roomMeshKeys}` | composition window data |
| `[UnitComp] ❌ HIGHLIGHT RISK: pool units exist but NO room meshes …` | **two-way highlight broken** — room ids don't match CityJSON object ids (sends both lists) |
| `[UnitComp] 3D→list / list→3D highlight {roomId, meshesForRoom}` | each highlight direction firing |
| `[UnitComp] compose request/OK` / `❌ compose FAILED (HTTP …)` | the apartment/LSBU save + server response |

The single most useful line for the highlight feature is the **`HIGHLIGHT RISK`** error — if you
see it, copy the `poolRoomIds` and `cityObjectIds` it prints; that tells me exactly how to fix the
room↔unit id mapping.
