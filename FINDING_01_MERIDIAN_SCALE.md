# Finding 1 — a systematic −0.65% volume bias in the georeferencing approximation

First empirical result of the Paper 1 measurement programme. Measured 2026-08-30 with
`scripts/roundtrip_metrics.py` on two IFC models already in this repository.

---

## Result

Every legal volume passing through the current InfoBhoomi encoding chain is **under-reported
by 0.65%**, in the same direction, regardless of its size or shape.

| Model | Spaces measured | Volume range (m³) | ΔV vs. EPSG:5235 | Direction |
|---|---|---|---|---|
| `simple-model-spaces01.ifc` | 7 | 372 – 1 843 | −0.6504 % to −0.6505 % | all negative |
| `IFC_01.ifc` (87 MB) | 129 | 5.3 – 116.9 | −0.6505 % to −0.6506 % | **129 of 129 negative** |

Maximum horizontal vertex displacement: **79.8 mm** (simple model), **38.1 mm** (IFC_01).

This is not scatter. It is a bias — a single multiplicative error applied to every volume in
the same direction — which makes it both more serious and more easily corrected than random
noise would be.

## Cause

`GeoProjector` in `ifc2cityjson_cadastral.py` converts local metric ENU coordinates to
geographic coordinates with an equirectangular approximation whose metres-per-degree of
latitude is derived from the WGS84 **semi-major axis** used as a sphere radius:

```python
self._m_per_deg_lat = math.pi * WGS84_A / 180.0        # 111 319.49 m
```

The true meridian arc per degree uses the **meridian radius of curvature**
*M* = a(1−e²)/(1−e² sin²φ)^{3/2}, which at 6.9° N gives 110 590.3 m.

| | metres per degree | error |
|---|---|---|
| Latitude — used | 111 319.49 | **+0.6594 %** |
| Latitude — true | 110 590.30 | — |
| Longitude — used | 110 513.24 | −0.0048 % |
| Longitude — true | 110 518.58 | — |

The longitude scale is very nearly correct because the parallel radius happens to be close
to *a* cos φ. The latitude scale is too large by 0.66%, so a north–south distance is
under-recovered by the same factor when the stored coordinates are read back through a real
geodetic projection.

Volume is scaled in one dimension only, so the predicted volume error is **−0.655 %**
against a measured **−0.6505 %** — agreement to within 0.005 percentage points. The
mechanism is therefore confirmed, not merely correlated.

## Latitude dependence across Sri Lanka

| Latitude | Meridian scale error | Volume / area error |
|---|---|---|
| 5.9° N | +0.6633 % | −0.659 % |
| 6.9° N | +0.6594 % | −0.655 % |
| 7.9° N | +0.6549 % | −0.651 % |
| 8.9° N | +0.6498 % | −0.646 % |
| 9.9° N | +0.6441 % | −0.640 % |

The bias varies by only 0.02 percentage points across the country, so a single correction
factor would remove almost all of it — but the error is present everywhere.

## Why it is legally material

Because volume is scaled in the north dimension only, **floor area carries the same 0.65%
error**. For a 100 m² apartment that is **0.65 m²**, and for a 120 m³ unit, 0.78 m³.

This exceeds the rounding at which condominium floor areas are ordinarily stated, so the
error is capable of changing a registered figure. And because it is systematic rather than
random, it does **not** cancel across the units of a building: every unit is short by the
same proportion. Share fractions, being ratios of unit extents, are therefore largely
preserved — but the absolute registered areas are all wrong in the same direction.

## Status of this measurement

Two caveats, stated so the result is not over-claimed.

1. **Self-inversion measures nothing.** Inverting the converter's own equirectangular
   formula returns the original coordinates to floating-point precision — 0.000% error, 0.0 mm
   displacement. That number is an artefact of using the same approximation in both
   directions and must not be reported as fidelity. The genuine error appears only when the
   stored geographic coordinates are read by an independent geodetic transformation, which
   is what any real consumer of an EPSG:4326 geometry will do.
2. **Coordinate-level closure is not type-level closure.** All 129 source meshes and all 129
   emitted geometries were watertight when tested by edge pairing on exact coordinates. The
   information is therefore present — but `MULTIPOLYGON Z` asserts nothing about closure, so
   no consumer can rely on it and no volume can be computed from the stored geometry by the
   database itself. This is a structural loss even though no coordinate was harmed.

## Consequences for the paper

- This is the first entry in the loss taxonomy, and it is a **geometric, systematic,
  correctable** loss of the kind §3.6 predicted would appear as a signed bias. It vindicates
  the decision to report signed deltas rather than absolute ones: an absolute-error report
  would have shown "0.65% error" and concealed that every unit errs the same way.
- It strengthens the CRS factor (C1) in the ablation: the metric CRS condition is not a
  matter of convenience but removes a measurable, legally material error.
- It is a *pipeline* error rather than a *format* error. CityJSON and PostGIS did not force
  it; the converter chose it. That distinction belongs in the taxonomy, and it is exactly the
  kind of loss an encoding profile can eliminate outright.

## Fix

Replace the spherical meridian constant with the meridian radius of curvature at the anchor
latitude, or — preferably, and consistent with the proposed profile — project through a real
geodetic transformation to EPSG:5235 and store metric coordinates, removing the
approximation rather than correcting it.
