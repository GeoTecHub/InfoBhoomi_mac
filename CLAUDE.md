# Memory

## Me
Milinda - Software / Engineering

## People
| Who | Role |
|-----|------|
| *(add people as you work)* | |

## Terms & Acronyms
| Term | Meaning |
|------|---------|
| IB | InfoBhoomi (the project) |
| LADM | Land Administration Domain Model (ISO 19152) |
| RRR | Rights, Restrictions, Responsibilities (LADM concept) |
| su_id | Spatial Unit ID — PK of LA_Spatial_Unit_Model, FK in survey_rep |
| GND | Grama Niladhari Division (Sri Lanka admin boundary) |
| QA agent | agents/agents/qa_agent.py — automated functional test suite |
| perf agent | agents/agents/gis_perf_agent.py — timing/performance tests |
| orchestrator | agents/orchestrator.py — runs perf + QA agents in sequence |

## Projects
| Name | What |
|------|------|
| **InfoBhoomi** | Municipal Land Administration Web-GIS for Sri Lanka. Django 5.1 + DRF + PostGIS backend, Angular 21 frontend. LADM ISO 19152 compliant. |

→ Details: memory/projects/infobhoomi.md

## Tools & Stack
| Tool | Purpose |
|------|---------|
| TypeScript | Preferred language |
| Python | Preferred language |
| Django 5.1 + DRF | Backend API |
| PostGIS | Spatial DB (PostgreSQL) |
| Angular 21 | Frontend |
| OpenLayers | Map engine |

## Preferences
- Code in TypeScript or Python
- Tasks tracked in TASKS.md

## Current 3D Cadastre Handoff

- Current stage: P4 is mostly complete; P4b is now started.
- Design reference: `3D_CADASTRE_INTEGRATION_DESIGN.md`.
- Latest completed slice: P4b LSBU composition foundation plus first Unit Composition workflow wiring.
- Backend fields added to `LA_LS_Build_Unit_Model`: `building_unit_type`, `cadastral_id`, `component_units`.
- Backend migration added: `InfoBhoomi_Backend_dev2/user/migrations/0015_lsbu_composition_fields.py`.
- Backend migration `user.0015_lsbu_composition_fields` was applied successfully.
- Backend endpoints exist for composition: `/api/user/bld-3d/units/` and `/api/user/bld-3d/lsbu/compose/`.
- Frontend side panel now loads/saves legal-space type, cadastral ID, and component room ids through the existing Building Units / Strata section.
- Frontend Unit Composition dialog exists and is reachable from Building Units / Strata. It renders rooms in 3D, supports two-way list/model selection, posts composition, and refreshes building data after save.
- Verification done: backend `venv\Scripts\python.exe manage.py check` passed; frontend `npm run build` passed after running outside sandbox. Existing Angular optional-chain and bundle-budget warnings remain.
- Next major work: browser-test the P4b Unit Composition workflow with a real imported IFC building, then add reassign/unassign, CityJSON membership sync, and BAUnit linkage.
