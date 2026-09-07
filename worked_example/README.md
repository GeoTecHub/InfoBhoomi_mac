# One legal volume, followed through every stage

A complete worked example with real data at each step of the encoding chain. Every number
below was produced on 2026-08-30 from files in this repository; nothing is illustrative.

**Specimen:** the space named `1`, long name *Dining Room*, from
`3D-Cadastre/IFC/simple-model-spaces01.ifc`.
GlobalId `26JHatoHX8uPohez7UDUgn`.

It was chosen because it is a rectangular box: **8 vertices, 12 triangles**, so every
quantity can be checked with a calculator.

| File in this folder | Stage |
|---|---|
| `S0_source_mesh.json` | source geometry and the quantities authored by the BIM tool |
| `S1_cityjson_room1.json` | the room as CityJSON (single-room slice) |
| `S1_cityjson_full.json` | the whole converted model, for context |
| `S2_geom_3d.wkt` | exactly what is written to `la_ls_build_unit.geom_3d` |
| `S4_metric_row.json` | the measurement record for this volume |

---

## Stage 0 — the source IFC

Geometry after IfcOpenShell tessellation, in IFC world coordinates, metres:

```
  idx            X            Y        Z
   0     -20.0171      17.4407   0.0000
   1     -20.0171      17.4407   3.0480
   2     -20.0171       7.3439   3.0480
   3     -20.0171       7.3439   0.0000
   4      -7.9203       7.3439   3.0480
   5      -7.9203       7.3439   0.0000
   6      -7.9203      17.4407   3.0480
   7      -7.9203      17.4407   0.0000

faces (12 triangles, vertex indices)
  [1,0,3] [2,1,3] [2,3,5] [4,2,5] [4,5,6] [6,5,7]
  [6,7,0] [1,6,0] [3,0,7] [3,7,5] [6,1,2] [4,6,2]
```

Dimensions: 12.0968 × 10.0968 × 3.0480 m.

The file also carries quantities **authored by the BIM application**, independent of any
geometry we compute:

```json
"Qto_SpaceBaseQuantities": {
  "Height": 3048.0,
  "GrossVolume": 13146.929340525447,
  "NetVolume": 13146.929340525443
}
```

Note the unit inconsistency inside the file itself: height in millimetres, volume in cubic
feet. See the verification arithmetic below.

## Stage 1 — CityJSON

```json
{
  "type": "BuildingRoom",
  "attributes": {
    "name": "1",
    "longname": "Dining Room",
    "floor": "Ground floor",
    "area_m2": 122.14,
    "geometry_source": "ifc_shape",
    "property_sets": { "Pset_SpaceCommon": { "Reference": "Dining Room 1", "IsExternal": false } }
  },
  "parents": ["3$4TpeCH15qfifOhkT6X$S"],
  "geometry": [{ "type": "MultiSurface", "lod": 2.2, "boundaries": [[[0,1,2]], [[3,0,2]], ... ] }]
}
```

Vertices are shared across the whole model in a single list, in **local ENU metres**:

```json
"vertices": [[-20.017, 17.441, 3.048], [-20.017, 17.441, 0.0], [-20.017, 7.344, 0.0], ...]
```

with the geographic placement held separately in metadata:

```json
"metadata": {
  "referenceSystem": "local-ENU-metres",
  "georeferencing": { "method": "manual_placement", "anchor_lon": 80.0, "anchor_lat": 6.9,
                      "base_z": 0.0, "rotation_deg": 0.0, "scale": 1.0, "crs": "EPSG:4326" }
}
```

Three things are already visible at this stage.

1. **Coordinates are rounded to three decimals**, i.e. to the millimetre: −20.0171 becomes
   −20.017. Measured across all seven rooms, this shifts vertices by up to **0.495 mm** and
   changes volume by **+0.003%**.
2. **The geometry type is `MultiSurface`, not `Solid`.** Even in CityJSON, where a solid
   primitive exists, the room is emitted as a collection of surfaces. Nothing asserts that
   it encloses anything.
3. **The semantic surface labels are synthesised, not carried.** `FloorSurface`,
   `CeilingSurface` and `InteriorWallSurface` are assigned by inspecting each face normal —
   pointing down, up, or neither. They are not derived from `IfcRelSpaceBoundary`, which is
   absent from this file and from every other model tested. A party wall is therefore
   indistinguishable from any other interior wall.

## Stage 2 — what is written to PostGIS

`la_ls_build_unit.geom_3d`, 2 087 characters, twelve independent triangles:

```
MULTIPOLYGON Z (((79.99981887152065 6.900156672228473 3.048,
                  79.99981887152065 6.900156672228473 0.0,
                  79.99981887152065 6.900065971130866 0.0,
                  79.99981887152065 6.900156672228473 3.048)),
                ((79.9998188715... )), ... )
```

Each triangle is its own polygon. The first two ordinates are **degrees**; the third is
**metres**. The twelve triangles do in fact share vertices exactly, so the shell is closed —
but `MULTIPOLYGON Z` makes no such promise, so no consumer may assume it and the database
cannot compute a volume from it.

## Stage 3 — reconstruction from the database

Not yet available. This requires the PostGIS→CityJSON exporter, which does not exist, and
which must run as a separate process reading only the database.

## The measurement record

```json
{
  "id": "26JHatoHX8uPohez7UDUgn", "name": "1", "status": "ok",
  "v_src_m3": 372.279581,
  "v_out_m3": 372.279581,
  "dv_m3": 0.0,            "dv_pct": 0.0,
  "v_naive_stored_units": 3.026097673133049e-08,
  "v_proj_m3": 369.858029, "dv_proj_pct": -0.650466,
  "proj_disp_mm": 43.755,  "max_vertex_disp_mm": 0.0,
  "src_tris": 12, "out_tris": 12, "src_verts": 8, "out_verts": 8,
  "src_watertight": true,  "src_unpaired_edges": 0,
  "out_watertight": true,  "out_unpaired_edges": 0
}
```

`v_naive_stored_units` = 3.03 × 10⁻⁸ is what a volume computation returns if run directly on
the stored coordinates. Its unit is degree²·metre. It is not a volume, and the number is
printed precisely so that nobody mistakes it for one.

---

## Verify it yourself

**1. The box.** 12.0968 × 10.0968 × 3.0480 = **372.2796 m³**. The harness reports
372.279581. ✔

**2. Against the BIM application's own figure.** The authored `GrossVolume` is 13 146.93,
in cubic feet. 372.279581 × 35.3146667215 = **13 146.9293**. Authored: 13 146.9293. ✔
Agreement to ten significant figures, from a number computed by different software from a
different representation.

**3. The floor area.** 12.0968 × 10.0968 = **122.14 m²**, which is the `area_m2` attribute
CityJSON carries. ✔

**4. The scale error.** π × 6 378 137 / 180 = 111 319.49 m per degree of latitude, as used.
The true meridian arc at 6.9° is π M / 180 = 110 590.30 m, with
M = a(1−e²)/(1−e² sin²φ)^{3/2}. Ratio 1.006594, so north–south is overstated by 0.6594%,
and since only one dimension is affected the volume error is −0.655%.
Measured: **−0.650466%**. ✔

**5. The consequence.** 372.2796 − 369.8580 = **2.42 m³** lost from one dining room. On its
122.14 m² floor area the same proportion is **0.79 m²**.

---

## The loss ledger for this one volume

| Stage | What changed | Magnitude | Class |
|---|---|---|---|
| S0 → S1 | coordinates rounded to the millimetre | +0.003% volume, ≤0.5 mm | geometric, quantisation |
| S0 → S1 | `IfcSpace` becomes `MultiSurface`, not a solid | no coordinate change | structural |
| S0 → S1 | semantic labels synthesised from face normals | party wall not identifiable | semantic |
| S0 → S1 | property sets retained in `attributes` | none | — |
| S1 → S2 | geographic CRS via a spherical meridian constant | **−0.650%** volume, 43.8 mm | geometric, systematic |
| S1 → S2 | `MULTIPOLYGON Z` — closure no longer asserted | volume not computable in the database | structural |
| S1 → S2 | parent link and semantics have no column | lost | structural, semantic |
| S2 → S3 | — | not yet measurable | — |

The two geometric losses run in opposite directions and differ by two orders of magnitude,
which is the argument for reporting them per stage and signed rather than as one aggregate
figure.
