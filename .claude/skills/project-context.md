# Municipal Web-GIS — Project Context Reference

> Attach this file whenever invoking any GIS skill to provide Claude with stable project knowledge.
> Last updated: 2026-02-28

---

## 1. Application Purpose

A **Municipal Land Administration Web-GIS** built for Sri Lankan local government use. Officers use it to:
- View, create, and edit **land parcels** and **buildings** on an interactive map
- Manage **Rights, Restrictions, and Responsibilities (RRR)** per LADM ISO 19152
- Run **spatial queries** (GIS Query Console) and **attribute queries** (Query Builder)
- Print **A4 parcel reports** and export data to shapefile/GeoJSON
- Administer **users, roles, organizations, and layers** (admin module)

---

## 2. Technology Stack

| Concern | Technology |
|---|---|
| Framework | **Angular** — standalone components, signals (`signal()`, `computed()`, `input()`), control flow (`@if`, `@for`) |
| Map engine | **OpenLayers** — vector layers, WMS tile layers, draw/modify/select interactions |
| UI components | **Angular Material** (MDC) — `mat-fab`, `mat-icon`, `mat-dialog`, `mat-menu`, `mat-tooltip` |
| Select inputs | `@ng-select/ng-select` |
| HTTP | Angular `HttpClient` via `APIsService` |
| State | Angular services + Signals (no NgRx) |
| Styling | Component-scoped CSS + global `src/styles.css` with CSS variable system |
| Language | TypeScript (strict mode), HTML templates |
| Build | Angular CLI |

---

## 3. Source Tree Key Paths

```
src/
  styles.css                          ← global CSS variables & utility classes
  app/
    app.component.*                   ← root component
    components/
      map/                            ← OL map host component
      tools/                          ← map toolbar (draw, modify, select, split…)
      side-panel/
        side-panel.component.*        ← tabbed side panel shell
        land-info-panel/              ← land parcel attributes, collapsible sections
        building-info-panel/          ← building attributes
        land-tab/                     ← parcel search/list tab
        building-tab/                 ← building search/list tab
        home-tab/                     ← dashboard/home tab
        legal-spaces-tab/             ← legal space tab
        external-tab/                 ← external data tab
      shared/
        popups/
          print-panel/                ← A4 print dialog
          query-builder/              ← attribute/spatial query UI
          export-data/                ← shapefile/GeoJSON export
          import-data/                ← shapefile import
          confirm-dialog/             ← generic yes/no confirmation
    admin/
      admin.component.*               ← admin shell
      common/
        admin-header/                 ← top nav bar for admin module
        admin-side-bar/               ← sidebar nav for admin module
      home-page/                      ← admin dashboard
      layers-list/                    ← manage WMS/vector layers
      organizations/                  ← org CRUD
      roles-list/                     ← roles CRUD
      user/                           ← user CRUD
    services/
      map.service.ts                  ← OL map init, basemap switching, highlight
      layer.service.ts                ← layer registry, add/remove layers
      style-factory.service.ts        ← per-feature OL style functions
      feature.service.ts              ← feature CRUD via GeoServer WFS-T
      draw.service.ts                 ← OL draw/modify/select interactions
      split.service.ts                ← polygon split tool
      geom.service.ts                 ← geometry helpers
      auth.service.ts                 ← JWT auth
      permissions.service.ts          ← role-based permission checks
      sidebar-control.service.ts      ← controls side panel open/close state
      app-state.service.ts            ← selected feature, active layer state
      data.service.ts                 ← shared feature data bus
    models/
      land-parcel.model.ts            ← LADM LA_Parcel, LandUse, RRR enums
      building-info.model.ts          ← building & RRR types
      form-data.model.ts              ← form field definitions
    core/
      PermissionIds.ts                ← permission ID constants
      constant.ts                     ← app-wide constants
```

---

## 4. LADM Data Model Summary

The app is **LADM ISO 19152 compliant**. Key domain concepts:

| Concept | Angular Model | Notes |
|---|---|---|
| Land Parcel | `LandParcelModel` in `land-parcel.model.ts` | Has parcel ID, land use, tenure, area, assessment value, survey method |
| Land Use | `LandUse` enum | RES, COM, AGR, IND, MIX, REC, TRN, PUB, VAC |
| RRR | `RRREntry`, `RRRInfo` in `building-info.model.ts` | Rights (ownership, lease…), Restrictions (mortgage…), Responsibilities |
| Party | `PartyType` enum | Natural person, corporate body, group |
| Survey | `SurveyMethod`, `AccuracyLevel` enums | Cadastral, GPS, aerial, etc. |
| Building | `BuildingInfoModel` | Linked to parcel |

**Critical parcel attributes** (must always be visible without scrolling):
- Parcel ID / Reference number
- Status (active / inactive / disputed)
- Land Use classification
- Tenure type
- Area (m²)
- Assessment value

---

## 5. Map / OpenLayers Configuration

- **Default projection:** EPSG:5235 (Sri Lanka Transverse Mercator) — centre ~(500000, 500000)
- **Also supported:** EPSG:4326, EPSG:3857, EPSG:27700, EPSG:28355, EPSG:32644
- **Zoom controls:** repositioned to `bottom: 278px; right: 18px` (custom OL override in `styles.css`)
- **Basemaps:** OSM, Bing, Sentinel, NASA MODIS, NASA Landsat, NASA WMS (switchable at runtime)
- **Layer styles:** Driven by `makePerFeatureStyleFn()` in `style-factory.service.ts`; each feature carries a `baseHex` property for its colour
- **Selection highlight:** Accent orange (`#f39c12` stroke + rgba fill)
- **Dialog positioning:** Some dialogs use `.dialog-move-bottom-left` to anchor at bottom-left of viewport, floating above the map

---

## 6. Dialog / Overlay Architecture

Angular Material `MatDialog` is used for all overlays. Panel classes control styling:

| Panel class | Purpose | Current background |
|---|---|---|
| *(default)* | Standard dialogs (confirm, export, import) | White |
| `.dropdown-dialog-panel` | Quick picker dropdowns | White, 420 px wide, bottom-left anchor |
| `.lpr-dark-dialog` | **Land Parcel Report** | Dark green `#060e09` |
| `.gqc-dark-dialog` | **GIS Query Console** | Dark navy `#070e1a` |
| `.arh-dark-dialog` | **Add Right Holder** | Dark ash `#1e293b` |
| `.rrr-centered-dialog` | RRR sub-dialogs | White |

---

## 7. User Roles & Permissions

Permissions are checked via `PermissionsService` using constants in `PermissionIds.ts`.
Common permission groups: `canView()`, `canAdd()`, `canEdit()`, `canDelete()`.
Role examples: admin, assessment officer, planning officer, data entry clerk.

---

## 8. Design Constraints

| Constraint | Detail |
|---|---|
| Environment | Day-time office, bright ambient light, Sri Lankan government buildings |
| Primary theme | **Light (default)** — high contrast preferred over saturated colours |
| Accessibility | WCAG AA target — 4.5:1 for normal text, 3:1 for large text/UI components |
| Languages | English (primary); Sinhala labels possible — Unicode, min 12px |
| Print | A4 portrait, triggered from Print Panel dialog |
| Min font size | 12px body data, 11px secondary labels |
| Target resolutions | 1366×768 (minimum) to 1920×1080 |
| Browser | Modern Chromium-based (Chrome, Edge) |

---

## 9. How to Use This Context File

When invoking a GIS skill, paste the relevant component code alongside this context. Example prompt:

```
[Attach: project-context.md]
[Paste: land-info-panel.component.html + .css + .ts]

"Review this Angular/OpenLayers screen" — focus on layout and contrast.
```

Or for theme work:

```
[Attach: project-context.md]
[Paste: styles.css + side-panel.component.css]

"Add theme toggle and migrate the side panel to CSS variables"
```
