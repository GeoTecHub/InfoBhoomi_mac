# Tasks

## Active
- Run locally then browser-verify the parcel-delete legal-space cascade + history report: apply migration `user.0018`, `manage.py check`, `npm run build`; delete a parcel with a building + units and confirm cascade (rights terminated, legal_space history rows), the new Report tab (counts, lifecycle, removed legal spaces, SVG shape thumbnails), and the deleted-parcel search. Design: `PARCEL_DELETE_LEGALSPACE_HISTORY_DESIGN.md`.
- Browser-verify P4b Unit Composition workflow with a real imported IFC building: open the dialog, select rooms, compose a private/common LSBU, refresh the side panel, and confirm persisted fields.
- Add remaining composition hardening: reassign/unassign support, CityJSON membership metadata update, and BAUnit ownership/common-property links.
- Browser-verify P4 City 3D viewer: imported building placement, search/fly-to, and admin-area filtering.

## Waiting On
- Local server launch still needs manual or alternate startup because background `Start-Process` hit a Windows `Path/PATH` environment conflict in Codex.

## Someday

## Done
- Created sample IFC `smaple data/land_parcel_002_four_storey_building.ifc`: 4 storeys, 12 unit spaces, linked to irregular sample parcel 2 / SU_ID 12506.
- Added parcel right-click import for 2D building footprints: opens the normal import dialog with Building as the target layer and links imported footprints to the selected parcel.
- Updated sample shapefile datasets in `smaple data`: irregular WGS84 polygons near Bandarawela - Liyangahawela - Poonagala Road, with building footprint inside parcel `LP-TEST-001`, packaged as Bandarawela ZIPs for import.
- Hardened DataSeederAgent for targeted land parcel seeding: added `--su-id` and `--land-only`, safer login/fetch error handling, request pacing for feature discovery, unsupported-layer protection, and HOW_TO_RUN commands.
- Created IFC Building Agent: configurable building-only IFC4 generator with interactive floor/unit prompts, WGS84 origin, local footprint coordinates, database land parcel ID reference, unit spaces, walls, slabs, metadata JSON, CLI runner, and sample spec.
- Created import-test IFC `3D-Cadastre/IFC/parcel_12505_two_storey_6_units.ifc`: 2 storeys, 6 apartment `IfcSpace` units, and 3 `IfcZone` groupings for parcel 12505; verified conversion to CityJSON.
- Applied backend migration `user.0015_lsbu_composition_fields` successfully.
- Wired the P4b Unit Composition dialog into the Building Units / Strata panel and refreshes building data after composition save.
- Added P4b Unit Composition backend endpoints and first composition dialog: unassigned room pool, two-way 3D/list selection, and LSBU compose action.
- Added P4b LSBU composition persistence fields to building units: legal-space type, cadastral ID, and component-unit membership metadata.
- Added cadastre-first IFC apartment workflow: spaces are marked as unit candidates, Unit Mode fades raw surfaces, unit room grouping is persisted into CityJSON metadata, and selected units highlight their rooms.
- Improved the IFC2CityJSON Python converter with professional QA reporting, CRS warnings, safer geometry handling, and repeatable sample conversion checks.
- Implemented browser-based IFC to CityJSON import and geometry QA report in the 3D Cadastre app.
- Added parcel/building history plan implementation: audit records for attributes, geometry, RRR, and parent-child links, plus a right-click History dialog with restore support for attribute rows.
