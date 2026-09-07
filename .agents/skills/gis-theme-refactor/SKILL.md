# Angular Theme Refactor for Municipal Web-GIS

## Skill Identity
**Name:** `gis-theme-refactor`
**Trigger phrases:**
- "Add theme toggle" / "Add dark/light toggle"
- "Fix contrast issues"
- "Convert to light default theme"
- "Migrate hard-coded colours to CSS variables"
- "Fix the dark dialog panels"
- "Make the theme consistent"
- "Refactor styles" / "Improve colour system"

---

## Project Context

### Current Theme State (as of last audit)

**What exists:**
- Global CSS variables in `src/styles.css` covering primary, secondary, accent, neutral, status, background, text, and border tokens
- Several **hard-coded hex colours** throughout button classes in `styles.css` (e.g. `background-color: #779ab8` repeated in every `.primary-*-btn` class)
- Three **one-off dark dialog themes** applied via Angular CDK panel classes:
  - `.lpr-dark-dialog` — dark green (Land Parcel Report)
  - `.gqc-dark-dialog` — dark navy (GIS Query Console)
  - `.arh-dark-dialog` — dark ash (Add Right Holder)
- OpenLayers styles are **fully programmatic** in `style-factory.service.ts` — uses `feature.get('baseHex')` per feature, no CSS dependency

**What is missing:**
- No `ThemeService` to toggle between themes
- No `data-theme` attribute or `.theme-light` / `.theme-dark` body class
- No dark-theme equivalents for the main app shell (side panel, toolbar, admin pages)
- No `localStorage` persistence of theme choice

---

## Refactor Process

### Phase 1 — Audit
When the user shares component files or asks to audit, do the following:

1. Scan all `.css` files for hard-coded colour literals (hex, rgb, rgba, named colours)
2. Map each hard-coded value to the nearest existing CSS variable (see token map below)
3. Report unmapped colours that need new tokens
4. Identify which components use the special dark dialog panel classes

#### Token Mapping Reference
| Hard-coded value | Correct CSS variable |
|---|---|
| `#779ab8` | `var(--color-primary)` |
| `#31485c` | `var(--color-primary-d1)` |
| `#9dc2e3` | `var(--color-primary-l1)` |
| `#c8dcee` | `var(--color-primary-l2)` |
| `#2c3e50` | `var(--color-text-primary)` or `var(--color-neutral-d3)` |
| `#7f8c8d` | `var(--color-text-secondary)` or `var(--color-neutral-d1)` |
| `#ffffff` | `var(--color-secondary-l1)` or `var(--color-background-l1)` |
| `#f4f4f4` | `var(--color-neutral-l1)` |
| `#e0e0e0` | `var(--color-neutral-l2)` |
| `#dcdcdc` | `var(--color-border-l1)` |
| `#28a745` | `var(--color-success)` |
| `#dc3545` | `var(--color-error)` |
| `#ffc107` | `var(--color-warning)` |
| `#17a2b8` | `var(--color-info)` |
| `#f39c12` | `var(--color-accent)` |
| `#e67e22` | `var(--color-accent-dark)` |
| `#fad7a0` | `var(--color-accent-light)` |

---

### Phase 2 — Design the Theme System

#### 2a. Extend CSS Variables for Semantic Theming
Add **semantic tokens** to `styles.css` under `:root` (light theme defaults). These wrap the existing palette tokens:

```css
:root {
  /* ── Semantic surface tokens ── */
  --surface-app-bg:        var(--color-background-l1);     /* main page background */
  --surface-panel:         var(--color-secondary-l1);      /* side panel, cards */
  --surface-panel-alt:     var(--color-neutral-l1);        /* alternating rows, inset areas */
  --surface-header:        var(--color-primary-d1);        /* toolbar, admin header */
  --surface-dialog:        var(--color-secondary-l1);      /* standard dialog background */
  --surface-overlay:       rgba(49, 72, 92, 0.85);         /* map overlay backdrops */

  /* ── Semantic text tokens ── */
  --text-primary:          var(--color-text-primary);
  --text-secondary:        var(--color-text-secondary);
  --text-inverse:          var(--color-text-inverse);
  --text-on-header:        var(--color-secondary-l1);
  --text-link:             var(--color-blue-2);

  /* ── Semantic interactive tokens ── */
  --btn-primary-bg:        var(--color-primary);
  --btn-primary-text:      var(--color-secondary-l1);
  --btn-primary-hover-bg:  var(--color-primary-d1);
  --btn-danger-bg:         var(--color-error);
  --btn-danger-text:       var(--color-secondary-l1);

  /* ── Semantic border tokens ── */
  --border-default:        var(--color-border-l1);
  --border-strong:         var(--color-border-d1);
  --border-focus:          var(--color-primary);

  /* ── OpenLayers map tokens ── */
  --map-parcel-default-fill:     rgba(119, 154, 184, 0.30);   /* #779ab8 @ 30% */
  --map-parcel-default-stroke:   #31485c;
  --map-parcel-selected-fill:    rgba(243, 156, 18, 0.35);    /* accent highlight */
  --map-parcel-selected-stroke:  #e67e22;
  --map-parcel-label-color:      #000000;
  --map-parcel-label-bg:         rgba(255, 255, 255, 0.85);
}

/* ── Dark theme overrides ── */
[data-theme="dark"] {
  --surface-app-bg:        #0f1923;
  --surface-panel:         #1e293b;
  --surface-panel-alt:     #162032;
  --surface-header:        #060e14;
  --surface-dialog:        #1e293b;
  --surface-overlay:       rgba(6, 14, 26, 0.92);

  --text-primary:          #e2e8f0;
  --text-secondary:        #94a3b8;
  --text-inverse:          #0f1923;
  --text-on-header:        #c8dae8;
  --text-link:             #60a5fa;

  --btn-primary-bg:        #3c71a6;
  --btn-primary-hover-bg:  #4a8ac4;
  --border-default:        #2d3f50;
  --border-strong:         #4a5568;
  --border-focus:          #60a5fa;

  --map-parcel-default-fill:     rgba(60, 113, 166, 0.40);
  --map-parcel-default-stroke:   #60a5fa;
  --map-parcel-selected-fill:    rgba(243, 156, 18, 0.50);
  --map-parcel-selected-stroke:  #f39c12;
  --map-parcel-label-color:      #f1f5f9;
  --map-parcel-label-bg:         rgba(15, 25, 35, 0.85);
}
```

#### 2b. ThemeService (TypeScript)
Create `src/app/services/theme.service.ts`:

```typescript
import { Injectable, signal, effect } from '@angular/core';

export type ThemeMode = 'light' | 'dark';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly STORAGE_KEY = 'gis-theme';

  /** Reactive signal — components can read this directly */
  readonly theme = signal<ThemeMode>(this.loadPersistedTheme());

  constructor() {
    // Apply theme to <html> element whenever signal changes
    effect(() => {
      this.applyTheme(this.theme());
    });
  }

  toggle(): void {
    this.theme.set(this.theme() === 'light' ? 'dark' : 'light');
    localStorage.setItem(this.STORAGE_KEY, this.theme());
  }

  setTheme(mode: ThemeMode): void {
    this.theme.set(mode);
    localStorage.setItem(this.STORAGE_KEY, mode);
  }

  private loadPersistedTheme(): ThemeMode {
    const stored = localStorage.getItem(this.STORAGE_KEY) as ThemeMode | null;
    // Default to 'light' for office use; fall back if stored value is invalid
    return stored === 'dark' ? 'dark' : 'light';
  }

  private applyTheme(mode: ThemeMode): void {
    const html = document.documentElement;
    if (mode === 'dark') {
      html.setAttribute('data-theme', 'dark');
    } else {
      html.removeAttribute('data-theme');
    }
  }
}
```

#### 2c. Theme Toggle Component
Create `src/app/components/shared/theme-toggle/theme-toggle.component.ts`:

```typescript
import { Component, inject } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ThemeService } from '../../../services/theme.service';

@Component({
  selector: 'app-theme-toggle',
  standalone: true,
  imports: [MatIconModule, MatButtonModule, MatTooltipModule],
  template: `
    <button
      mat-icon-button
      (click)="themeService.toggle()"
      [matTooltip]="themeService.theme() === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'"
      aria-label="Toggle theme"
    >
      <mat-icon>{{ themeService.theme() === 'light' ? 'dark_mode' : 'light_mode' }}</mat-icon>
    </button>
  `,
  styles: [`
    button { /* UI-only */
      color: var(--text-on-header);
    }
  `]
})
export class ThemeToggleComponent {
  protected readonly themeService = inject(ThemeService);
}
```

Add `<app-theme-toggle>` to the main header component (`admin-header` or the toolbar).

---

### Phase 3 — Migrate Hard-coded Colours

#### 3a. Global Button Classes in `styles.css`
Replace all hard-coded `#779ab8` instances with `var(--btn-primary-bg)`:

```css
/* BEFORE */
.primary-bg-btn {
  background-color: #779ab8;
  color: white;
}

/* AFTER — UI-only change */
.primary-bg-btn {
  background-color: var(--btn-primary-bg);
  color: var(--btn-primary-text);
  transition: background-color 0.2s ease;
}
.primary-bg-btn:hover {
  background-color: var(--btn-primary-hover-bg);
}
```

Apply the same pattern to: `.primary-sm-btn`, `.primary-sm-btn-2`, `.primary-bg-lg-btn`, `.primary-custom-sm-btn`, `.primary-custom-sm-btn-2`, `.admin-primary-bg-btn`.

#### 3b. Consolidate Dark Dialog Panels
The three one-off dark dialog classes (`.lpr-dark-dialog`, `.gqc-dark-dialog`, `.arh-dark-dialog`) should gradually migrate to use the semantic tokens. Example migration for `.lpr-dark-dialog`:

```css
/* BEFORE */
.lpr-dark-dialog .mat-mdc-dialog-surface {
  background: #060e09 !important;
  color: #d0ead8 !important;
}

/* AFTER — preserves visual appearance but uses variables in dark mode */
/* UI-only change */
.lpr-dialog .mat-mdc-dialog-surface {
  background: var(--surface-dialog) !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--border-default) !important;
}
```

> **Migration note:** Do this panel by panel. The dark dialog panels currently have their own custom look — decide with the user whether to preserve the visual identity or unify under the global theme.

#### 3c. Side Panel Component
In `side-panel.component.css`, replace any hard-coded colours:

```css
/* UI-only change — example */
.side-panel {
  background: var(--surface-panel);
  border-right: 1px solid var(--border-default);
  color: var(--text-primary);
}
```

---

### Phase 4 — OpenLayers Map Theme Integration

OL styles in `style-factory.service.ts` are TypeScript — they cannot read CSS variables directly. Instead, use the `ThemeService` signal to drive OL style changes.

**Pattern — inject ThemeService into MapService and react to theme changes:**

```typescript
// In map.service.ts — UI-only addition
import { ThemeService } from './theme.service';
import { effect } from '@angular/core';

// Inside constructor or init method:
private readonly themeService = inject(ThemeService);

// Re-render all vector layers when theme changes
effect(() => {
  const theme = this.themeService.theme();
  this.refreshVectorLayerStyles(theme);
});

private refreshVectorLayerStyles(theme: 'light' | 'dark'): void {
  // Get the parcel layer group and force a style refresh
  // Actual implementation depends on how layer references are stored in map.service.ts
  this.map?.getLayers().forEach(layer => {
    if (layer instanceof VectorLayer) {
      layer.changed(); // triggers OL re-render
    }
  });
}
```

**In `style-factory.service.ts` — read theme from a getter passed in:**

```typescript
// UI-only change — add theme-aware colour selection
export function makePerFeatureStyleFn(
  getShowLabels: () => boolean,
  getShowArea?: () => boolean,
  getTheme?: () => 'light' | 'dark'   // NEW optional parameter
) {
  return (feature: FeatureLike, resolution: number) => {
    const isDark = getTheme?.() === 'dark';

    // Selected parcel highlight — adapts to theme
    const isSelected = feature.get('selected') === true;
    if (isSelected) {
      return new Style({
        stroke: new Stroke({
          color: isDark ? '#f39c12' : '#e67e22',
          width: 3,
        }),
        fill: new Fill({
          color: isDark ? 'rgba(243,156,18,0.50)' : 'rgba(243,156,18,0.35)',
        }),
        zIndex: 999,
      });
    }

    // ... rest of existing logic unchanged
  };
}
```

---

### Phase 5 — Verification Checklist
Before declaring the refactor done, verify:

- [ ] Light theme: all text/background pairs meet WCAG AA (≥ 4.5:1 for normal text)
- [ ] Dark theme: all text/background pairs meet WCAG AA
- [ ] Theme toggle persists across page refresh (check `localStorage`)
- [ ] OL map parcel highlights are visible in both themes
- [ ] The three dark dialog panels still function correctly
- [ ] Admin pages (header, sidebar, tables) adapt to theme correctly
- [ ] No hard-coded hex colours remain in global `styles.css` (audit with grep: `grep -r "#[0-9a-fA-F]\{3,8\}" src/`)
- [ ] Print layout unaffected (print CSS should force light theme)

---

## Code Output Rules

1. Every CSS or TS change must include a `/* UI-only change */` or `// UI-only change` comment
2. Never remove or modify existing CSS variable definitions — only extend them
3. Never change component TypeScript business logic (data fetching, permissions, LADM logic)
4. Keep the `ThemeService` as the **single source of truth** — do not read `localStorage` directly in components
5. For OL style changes, always test visually — OL does not hot-reload styles automatically
6. Provide `grep` or search commands to help the user find remaining hard-coded colours

---

## Example Interaction Pattern

**User says:** "Add theme toggle and fix the contrast issues in the side panel"

**Codex does:**
1. Asks: "Should I preserve the special look of the dark dialog panels (LPR, GQC, ARH) or unify them under the global theme?"
2. Outputs: Phase 2 semantic token additions to `styles.css`
3. Outputs: `theme.service.ts` + `theme-toggle.component.ts`
4. Outputs: Migrated `side-panel.component.css` using semantic variables
5. Shows: Where to add `<app-theme-toggle>` in the header template
6. Provides: The verification grep command to find remaining hard-coded colours

---

## Boundaries
- Do **not** change routing, guards, or authentication
- Do **not** modify LADM data models or API contracts
- Do **not** remove the `.lpr-dark-dialog`, `.gqc-dark-dialog`, `.arh-dark-dialog` classes without explicit user approval — other code may depend on them
- When migrating a panel, migrate **one panel at a time** and ask the user to test before proceeding
