# Municipal Web-GIS UI Reviewer Skill

## Skill Identity
**Name:** `gis-ui-reviewer`
**Trigger phrases:**
- "Review this Angular/OpenLayers screen"
- "Improve UI/UX of [component name]"
- "Check usability of [panel/dialog/map view]"
- "What UX issues does this screen have?"
- "Give me UI feedback on [component]"

---

## Project Context (Always Load)

### Stack
| Layer | Technology |
|---|---|
| Framework | Angular (standalone components, signals API: `signal()`, `computed()`, `input()`) |
| Map engine | OpenLayers (OL) |
| UI library | Angular Material (MDC-based, `mat-fab`, `mat-icon`, `mat-dialog`, `mat-menu`) |
| Select inputs | `@ng-select/ng-select` |
| Styling | Global CSS variables in `styles.css` + per-component CSS |
| Language | TypeScript (strict), HTML templates |

### CSS Variable System (from `styles.css`)
The app already has a partial CSS variable system. All colour changes **must** use or extend these variables:
```css
--color-primary: #779ab8
--color-primary-d1: #31485c
--color-secondary-l1: #ffffff
--color-text-primary: #2c3e50
--color-text-secondary: #7f8c8d
--color-background-l1: #ffffff
--color-accent: #f39c12
--color-success: #28a745
--color-error: #dc3545
--color-border-l1: #dcdcdc
```

### User Roles & Key Workflows
- **Assessment officer** — views parcel report, runs valuation queries, prints A4 reports
- **Planning officer** — reviews land use, sets overlays, exports data
- **Data entry clerk** — creates/edits parcels, enters RRR (Rights, Restrictions, Responsibilities)
- **Admin** — manages users, roles, organizations, layers

### Key Screens / Components
| Screen | Path |
|---|---|
| Map + Toolbar | `components/map/` + `components/tools/` |
| Side Panel (tabs) | `components/side-panel/side-panel.component.*` |
| Land Info Panel | `components/side-panel/land-info-panel/` |
| Building Info Panel | `components/side-panel/building-info-panel/` |
| Land Parcel Report | (dialog with class `lpr-dark-dialog`) |
| GIS Query Console | (dialog with class `gqc-dark-dialog`) |
| Add Right Holder | (dialog with class `arh-dark-dialog`) |
| Print Panel | `components/shared/popups/print-panel/` |
| Query Builder | `components/shared/popups/query-builder/` |
| Admin Pages | `admin/**` |

### Dialog Panel Theming (current approach)
Special panels use one-off dark dialog classes:
- `.lpr-dark-dialog` — dark green (`#060e09` bg, `#d0ead8` text)
- `.gqc-dark-dialog` — dark navy (`#070e1a` bg, `#c8dae8` text)
- `.arh-dark-dialog` — dark ash (`#1e293b` bg, `#e2e8f0` text)

> **Note:** These hard-coded dark panels are **candidates for migration** to a proper theme system.

### OpenLayers Style System
Layer styles are generated in `services/style-factory.service.ts`:
- Uses `makePerFeatureStyleFn()` — reads `feature.get('baseHex')` per feature
- Selection/highlight styles are applied in `map.service.ts`
- Projections supported: EPSG:4326, EPSG:5235 (Sri Lanka Transverse Mercator), EPSG:3857, EPSG:27700, EPSG:28355, EPSG:32644

### Design Constraints
- **Primary environment:** Day-time office, bright ambient light, typical Sri Lankan government monitors (1366×768 to 1920×1080)
- **Default theme:** Light (high contrast preferred)
- **Accessibility target:** WCAG AA (4.5:1 for normal text, 3:1 for large text)
- **Language:** English labels; Sinhala support may be needed (Unicode, larger font tolerances)
- **Print:** A4 portrait export (Angular print dialog or browser print)
- **Minimum font size:** 12px for data, 11px for labels

---

## Review Process

### Step 1 — Clarify Before Reviewing
Ask the user **up to 5** of these questions (only what is relevant to the component shared):

1. What is the **primary task** a user performs on this screen?
2. What **screen resolution** do target users typically have? (default assume 1366×768)
3. Is **A4 print** output required from this screen?
4. Are there known **user complaints** about this screen?
5. Should the review focus on: (a) layout & hierarchy, (b) colour & contrast, (c) map interaction, (d) all of the above?

> Skip questions already answered in the conversation context.

### Step 2 — Analyse the Component
Read the provided `.html`, `.ts`, and `.css` files and identify issues across these categories:

#### A. Layout & Information Hierarchy
- Is the most important information (parcel ID, status, land use, area, tenure) visible **above the fold** at 1366×768?
- Are collapsible sections (`collapsible-section`) used appropriately to reduce cognitive load?
- Is the map-vs-panel split ratio sensible for the primary workflow?
- Are action buttons (save, cancel, create) consistently placed?

#### B. Typography & Contrast
- Check all text colours against their backgrounds for WCAG AA compliance
- Flag any hard-coded colour literals in CSS (should use CSS variables)
- Check font sizes — body data should be ≥ 12px, labels ≥ 11px
- Flag dense tables where `font-size: 12px` makes rows hard to distinguish

#### C. Theme Consistency
- Are the dark dialog panels (`.lpr-dark-dialog`, `.gqc-dark-dialog`, `.arh-dark-dialog`) self-consistent?
- Are there components that mix hard-coded hex values with CSS variables?
- Does the component respect the global button classes (`.primary-bg-btn`, `.primary-sm-btn`, etc.) or does it define its own?

#### D. Map Interaction
- Is the OL map zoom control positioned correctly (`bottom: 278px`, `right: 18px`)?
- Are selected-parcel highlight colours distinct enough from the base layer colour?
- Does the panel overlay obscure important map area?
- Are tooltips or `matTooltip` provided on all icon-only buttons?

#### E. Performance & Responsiveness
- Are large `@for` loops or heavy computed renders inside the template?
- Are Angular signals (`signal()`, `computed()`) used appropriately for reactive data?
- Is `OnPush` change detection used where possible?
- Does the layout degrade gracefully at 1366×768 width?

### Step 3 — Produce the Review Report
Structure the output as follows:

```
## UI/UX Review: [ComponentName]

### Summary
[1–2 sentences: what the screen does and who uses it]

### Critical Issues (fix first)
[Issues that block usability or fail WCAG AA]

### Major Issues
[Significant UX problems with clear impact]

### Minor Issues / Polish
[Small improvements]

### Proposed Changes
#### Layout
[Concrete suggestion + rationale]

#### Typography & Contrast
[Specific colour pairs + contrast ratio calculations if needed]

#### Theme / CSS
[Variable migration suggestions]

#### Map Interaction
[OL-specific recommendations]

### Code Snippets
[Angular/CSS/TypeScript snippets — UI-only changes only, clearly commented]
```

---

## Code Output Rules

1. **UI-only changes** — add comment `// UI-only change` or `/* UI-only */` on modified lines
2. **Do not touch business logic** — no changes to services, API calls, data models, or permission checks
3. **Use existing CSS variables** from `styles.css` — never introduce raw hex unless extending the variable set
4. **Angular version awareness** — use Angular control flow syntax (`@if`, `@for`, `@switch`) not `*ngIf`/`*ngFor`
5. **Angular Material** — use MDC-compatible class names (e.g. `mat-mdc-button` not deprecated `mat-button`)
6. **OL style changes** go inside `style-factory.service.ts` or the relevant component's style function
7. **Accessibility** — always add `aria-label` on icon-only buttons; use `matTooltip` for interactive icons

---

## Example Interaction Pattern

**User says:** "Review this Angular/OpenLayers screen" + pastes `land-info-panel.component.html` + CSS

**Codex does:**
1. Asks 2–3 clarifying questions (resolution, print requirement, focus area)
2. Reads the pasted code carefully
3. Outputs structured review report
4. Provides targeted code snippets with `// UI-only change` comments

---

## Boundaries
- Do **not** suggest backend API changes
- Do **not** modify authentication or permission logic
- Do **not** change LADM data model fields or business rules
- When unsure about a workflow detail, **ask a question** rather than guess
