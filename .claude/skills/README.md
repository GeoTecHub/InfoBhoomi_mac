# Municipal Web-GIS — Claude Skills

This folder contains reusable Claude skill definitions for the Municipal Web-GIS project.
Each skill is a focused "procedure" Claude follows when you ask it to help with a specific type of task.

---

## Available Skills

### 1. `gis-ui-reviewer` — UI/UX Review
**Trigger:** "Review this Angular/OpenLayers screen" or "Improve UI/UX of [component]"

Analyses Angular + OpenLayers component files and gives structured UI/UX feedback across:
layout, typography, contrast, theme consistency, map interaction, and accessibility.
Produces a review report + targeted code snippets (UI-only changes, clearly commented).

📄 [SKILL.md](./gis-ui-reviewer/SKILL.md)

---

### 2. `gis-theme-refactor` — Theme Refactor
**Trigger:** "Add theme toggle", "Fix contrast", "Migrate to CSS variables", "Refactor styles"

Guides the migration from hard-coded colours to a semantic CSS variable system with light/dark
toggle support. Generates `ThemeService`, `ThemeToggleComponent`, extended CSS token set, and
OpenLayers-compatible theme integration.

📄 [SKILL.md](./gis-theme-refactor/SKILL.md)

---

### Supporting Docs

| File | Purpose |
|---|---|
| `project-context.md` | Project-wide reference: stack, file paths, LADM model, OL config, design constraints |

---

## How to Use

1. Open a new Claude conversation
2. Attach `project-context.md` as context
3. Paste the component files you want to work on (`.html`, `.ts`, `.css`)
4. Start your message with the skill trigger phrase

### Example
```
[Attach project-context.md]
[Paste land-info-panel.component.html + .css + .ts]

"Review this Angular/OpenLayers screen — focus on layout and contrast at 1366×768"
```

---

## Updating Skills

After applying Claude's suggestions and testing with real users, improve the skill by:
1. Noting what worked and what did not
2. Opening the relevant `SKILL.md`
3. Updating the "Rules" or "Code Output Rules" section
4. Asking Claude: *"Update the skill rules based on [what did not work]"*

This keeps the skills improving over time.
