#!/usr/bin/env python3
"""
roundtrip_metrics.py — first slice of the Paper 1 metric harness.

Measures what happens to a legal volume between the source IFC (S0) and the
representation InfoBhoomi writes into PostGIS (S2: MULTIPOLYGON Z, EPSG:4326).

Per IfcSpace it reports volume in and out (like-for-like, in the same local
metric frame), the signed delta, worst vertex displacement, triangle and vertex
counts, watertightness of source and stored geometry, and the number a naive
volume computation would return on the stored coordinates, whose horizontal
units are degrees and whose vertical unit is metres.

Usage:
    python3 scripts/roundtrip_metrics.py <file.ifc> --lon 80.0 --lat 6.9 --out scripts/metrics_x
"""
from __future__ import annotations

import argparse, csv, importlib.util, json, math, os, re, sys, time
from collections import defaultdict

try:
    from pyproj import Transformer as _PJ
except Exception:
    _PJ = None

HERE = os.path.dirname(os.path.abspath(__file__))
CONV = os.path.abspath(os.path.join(
    HERE, "..", "InfoBhoomi_Backend_dev2", "user", "services", "ifc", "ifc2cityjson_cadastral.py"))


def load_converter():
    spec = importlib.util.spec_from_file_location("ifc2cj", CONV)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclasses resolve types via sys.modules
    spec.loader.exec_module(mod)
    return mod


def mesh_volume(vertices, faces):
    """Signed volume by the divergence theorem over a triangle set."""
    v = 0.0
    for (a, b, c) in faces:
        x1, y1, z1 = vertices[a]
        x2, y2, z2 = vertices[b]
        x3, y3, z3 = vertices[c]
        v += (x1 * (y2 * z3 - y3 * z2)
              - x2 * (y1 * z3 - y3 * z1)
              + x3 * (y1 * z2 - y2 * z1)) / 6.0
    return v


def watertight(vertices, faces, ndigits=6):
    """Every undirected edge must be used exactly twice."""
    def key(i):
        return (round(vertices[i][0], ndigits),
                round(vertices[i][1], ndigits),
                round(vertices[i][2], ndigits))
    edges = defaultdict(int)
    for (a, b, c) in faces:
        for i, j in ((a, b), (b, c), (c, a)):
            ka, kb = key(i), key(j)
            edges[(ka, kb) if ka <= kb else (kb, ka)] += 1
    counts = list(edges.values())
    return {"watertight": bool(counts) and all(n == 2 for n in counts),
            "edges": len(counts),
            "unpaired_edges": sum(1 for n in counts if n != 2)}


POLY_RE = re.compile(r"\(\(([^()]*)\)\)")


def parse_multipolygon_z(wkt):
    """MULTIPOLYGON Z of triangles -> (vertices, faces) in stored coordinates."""
    verts, index, faces = [], {}, []
    for ring in POLY_RE.findall(wkt):
        pts = []
        for token in ring.split(","):
            parts = token.strip().split()
            if len(parts) >= 3:
                pts.append((float(parts[0]), float(parts[1]), float(parts[2])))
        if len(pts) >= 4:
            pts = pts[:3]
        if len(pts) != 3:
            continue
        tri = []
        for p in pts:
            k = (round(p[0], 12), round(p[1], 12), round(p[2], 12))
            if k not in index:
                index[k] = len(verts)
                verts.append(p)
            tri.append(index[k])
        faces.append(tuple(tri))
    return verts, faces


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc")
    ap.add_argument("--lon", type=float, default=80.0)
    ap.add_argument("--lat", type=float, default=6.9)
    ap.add_argument("--out", default="metrics")
    ap.add_argument("--limit", type=int, default=0, help="measure only the first N spaces")
    ap.add_argument("--proj-epsg", type=int, default=5235,
                    help="projected CRS used to test the equirectangular approximation")
    args = ap.parse_args()

    m = load_converter()
    t0 = time.time()
    tp = m.TransformParams(anchor_lon=args.lon, anchor_lat=args.lat)
    reader = m.IFCReader(args.ifc)
    if not reader.load():
        print("could not open IFC", file=sys.stderr)
        return 1
    t_load = time.time() - t0

    tf = m.Transformer(tp)
    geo = m.GeoProjector(args.lon, args.lat)
    mpdlat, mpdlon = geo._m_per_deg_lat, geo._m_per_deg_lon

    pj = None
    if _PJ is not None:
        try:
            pj = _PJ.from_crs("EPSG:4326", f"EPSG:{args.proj_epsg}", always_xy=True)
        except Exception:
            pj = None

    spaces = reader.get_spaces()
    if args.limit:
        spaces = spaces[:args.limit]

    rows = []
    t1 = time.time()
    for sp in spaces:
        sid = getattr(sp, "GlobalId", None)
        name = getattr(sp, "Name", None) or getattr(sp, "LongName", None) or ""
        mesh = m._extract_mesh(reader, sp)
        if not mesh:
            rows.append({"id": sid, "name": str(name), "status": "no_geometry"})
            continue

        wt_src = watertight(mesh.vertices, mesh.faces)
        wkt = m._room_solid_wkt_4326(mesh, tf)
        if not wkt:
            rows.append({"id": sid, "name": str(name), "status": "no_solid_emitted"})
            continue

        ov, of = parse_multipolygon_z(wkt)
        wt_out = watertight(ov, of, ndigits=12)

        enu = [tf.to_enu(*p) for p in mesh.vertices]
        v_src = mesh_volume(enu, mesh.faces)

        back = [((lon - args.lon) * mpdlon, (lat - args.lat) * mpdlat, z) for (lon, lat, z) in ov]
        v_out = mesh_volume(back, of)
        v_naive = mesh_volume(ov, of)

        dmax = 0.0
        for fi, (a, b, c) in enumerate(mesh.faces):
            if fi >= len(of):
                break
            for si, oi in zip((a, b, c), of[fi]):
                sx, sy, sz = enu[si]
                ox, oy, oz = back[oi]
                d = math.sqrt((sx - ox) ** 2 + (sy - oy) ** 2 + (sz - oz) ** 2)
                if d > dmax:
                    dmax = d

        # Independent check: reproject the STORED geographic coordinates with a real
        # geodetic transformation rather than inverting the converter's own
        # equirectangular approximation. Any difference here is a genuine loss that
        # self-inversion cannot reveal.
        v_proj = dv_proj_pct = proj_disp_mm = None
        if pj is not None:
            try:
                pe = [pj.transform(lon, lat) + (z,) for (lon, lat, z) in ov]
                # remove the constant offset so only shape/scale is compared
                cx = sum(p[0] for p in pe) / len(pe)
                cy = sum(p[1] for p in pe) / len(pe)
                ce = sum(p[0] for p in back) / len(back)
                cn = sum(p[1] for p in back) / len(back)
                pe = [(x - cx + ce, y - cy + cn, z) for (x, y, z) in pe]
                v_proj = mesh_volume(pe, of)
                if v_src:
                    dv_proj_pct = 100.0 * (v_proj - v_src) / v_src
                d = 0.0
                for i, p in enumerate(pe):
                    q = back[i]
                    d = max(d, math.hypot(p[0] - q[0], p[1] - q[1]))
                proj_disp_mm = d * 1000.0
            except Exception:
                pass

        dv = v_out - v_src
        rows.append({
            "id": sid, "name": str(name), "status": "ok",
            "v_src_m3": round(v_src, 6),
            "v_out_m3": round(v_out, 6),
            "dv_m3": round(dv, 6),
            "dv_pct": round(100.0 * dv / v_src, 6) if v_src else None,
            "v_naive_stored_units": v_naive,
            "v_proj_m3": round(v_proj, 6) if v_proj is not None else None,
            "dv_proj_pct": round(dv_proj_pct, 6) if dv_proj_pct is not None else None,
            "proj_disp_mm": round(proj_disp_mm, 3) if proj_disp_mm is not None else None,
            "max_vertex_disp_mm": round(dmax * 1000.0, 4),
            "src_tris": len(mesh.faces), "out_tris": len(of),
            "src_verts": len(mesh.vertices), "out_verts": len(ov),
            "src_watertight": wt_src["watertight"],
            "src_unpaired_edges": wt_src["unpaired_edges"],
            "out_watertight": wt_out["watertight"],
            "out_unpaired_edges": wt_out["unpaired_edges"],
        })

    t_geom = time.time() - t1
    ok = [r for r in rows if r.get("status") == "ok"]
    summary = {
        "file": os.path.basename(args.ifc),
        "size_mb": round(os.path.getsize(args.ifc) / 1048576, 2),
        "load_seconds": round(t_load, 1),
        "geometry_seconds": round(t_geom, 1),
        "spaces_total": len(spaces),
        "spaces_measured": len(ok),
        "spaces_no_geometry": sum(1 for r in rows if r.get("status") == "no_geometry"),
        "src_watertight_count": sum(1 for r in ok if r["src_watertight"]),
        "out_watertight_count": sum(1 for r in ok if r["out_watertight"]),
        "vertices_lost_total": sum(r["src_verts"] - r["out_verts"] for r in ok),
        "max_vertex_disp_mm": max([r["max_vertex_disp_mm"] for r in ok], default=None),
    }
    dps = sorted(abs(r["dv_proj_pct"]) for r in ok if r.get("dv_proj_pct") is not None)
    if dps:
        summary["median_abs_dv_proj_pct"] = dps[len(dps) // 2]
        summary["max_abs_dv_proj_pct"] = dps[-1]
    pdisp = [r["proj_disp_mm"] for r in ok if r.get("proj_disp_mm") is not None]
    if pdisp:
        summary["max_proj_disp_mm"] = max(pdisp)
    ds = sorted(abs(r["dv_pct"]) for r in ok if r.get("dv_pct") is not None)
    if ds:
        summary["median_abs_dv_pct"] = ds[len(ds) // 2]
        summary["max_abs_dv_pct"] = ds[-1]

    with open(args.out + ".json", "w") as fh:
        json.dump({"summary": summary, "units": rows}, fh, indent=1)
    # Every space gets a row, measured or not. A space the encoder could not turn
    # into a solid is a loss, and a loss that is absent from the CSV is invisible
    # to every downstream count. Failed rows carry their status with the
    # measurement columns left blank — never dropped, never zero.
    if rows:
        fields = list(ok[0].keys()) if ok else ["id", "name", "status"]
        for r in rows:
            for k in fields:
                r.setdefault(k, "")
        with open(args.out + ".csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
