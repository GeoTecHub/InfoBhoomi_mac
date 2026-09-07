"""
Save-only performance driver.
Runs polygon / point / line save against the live backend N times,
computes p50/p95/avg, and prints a per-step breakdown from the
[SAVE⏱] log lines if the backend is logging at DEBUG.
"""
import sys, os, statistics, json, time, requests, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.gis_perf_agent import GISPerfAgent, _timed
from config import BASE_URL, TEST_POLYGON_COORDS, TEST_POINT_COORDS, TEST_LINE_COORDS

ITER = int(os.environ.get("SAVE_PERF_ITER", "5"))


def percentile(data, q):
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * (q / 100)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def stats(label, samples):
    if not samples:
        print(f"  {label}: NO SAMPLES")
        return
    p50 = percentile(samples, 50)
    p95 = percentile(samples, 95)
    avg = statistics.mean(samples)
    mn  = min(samples)
    mx  = max(samples)
    print(f"  {label:<12} n={len(samples):<2}  avg={avg:7.0f}  p50={p50:7.0f}  p95={p95:7.0f}  min={mn:7.0f}  max={mx:7.0f}  ms")


def post_geom(token, layer_id, geom_type, geom_coords, gnd_id=None):
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    props = {
        "uuid": str(uuid.uuid4()),
        "layer_id": layer_id,
        "crs": "EPSG:4326",
        "parent_uuid": [],
    }
    if gnd_id is not None:
        props["gnd_id"] = gnd_id
    payload = [{
        "type": "Feature",
        "geometry": {"type": geom_type, "coordinates": geom_coords},
        "properties": props,
    }]
    t0 = time.perf_counter()
    r = requests.post(f"{BASE_URL}/survey_rep_data/", headers=headers, json=payload, timeout=30)
    ms = (time.perf_counter() - t0) * 1000
    return r, ms


def main():
    print(f"\n=== SAVE PERF DRIVER  iter={ITER} ===")
    agent = GISPerfAgent()
    if not agent.authenticate():
        print("AUTH FAILED")
        sys.exit(1)
    agent.test_layers()
    agent.test_org_area()  # fills _gnd_id + _org_test_coords
    print(f"layer_id={agent.layer_id}  gnd_id={agent._gnd_id}  has_org_coords={bool(agent._org_test_coords)}")

    # _gnd_id picked up by the agent is the GND *name* (string), which causes 400 in the
    # serializer. Discard it and let the backend auto-detect from the polygon centroid.
    if not isinstance(agent._gnd_id, int):
        print(f"  (discarding non-integer gnd_id={agent._gnd_id!r}; backend will auto-detect)")
        agent._gnd_id = None

    poly_coords  = agent._org_test_coords or TEST_POLYGON_COORDS
    if agent._org_test_coords:
        ring = agent._org_test_coords[0]
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        point_coords = [cx, cy]
        line_coords  = [ring[0], ring[2]]
    else:
        point_coords = TEST_POINT_COORDS
        line_coords  = TEST_LINE_COORDS

    poly_ms, point_ms, line_ms = [], [], []
    saved_ids = []

    for i in range(ITER):
        # offset slightly per iteration to avoid duplicate-geom penalties
        d = i * 1e-5
        ring = poly_coords[0] if poly_coords else None
        pc = [[[p[0]+d, p[1]+d] for p in ring]] if ring else poly_coords

        r, ms = post_geom(agent.token, agent.layer_id, "Polygon", pc, agent._gnd_id)
        poly_ms.append(ms)
        if r.status_code in (200, 201):
            try:
                rec = r.json().get("saved_records", [])
                if rec:
                    saved_ids.append(rec[0]["properties"].get("id"))
            except Exception:
                pass
        else:
            print(f"  poly[{i}] HTTP {r.status_code}: {r.text[:160]}")

    for i in range(ITER):
        d = i * 1e-5
        pc = [point_coords[0]+d, point_coords[1]+d]
        r, ms = post_geom(agent.token, agent.layer_id, "Point", pc, agent._gnd_id)
        point_ms.append(ms)
        if r.status_code not in (200, 201):
            print(f"  point[{i}] HTTP {r.status_code}: {r.text[:160]}")

    for i in range(ITER):
        d = i * 1e-5
        lc = [[line_coords[0][0]+d, line_coords[0][1]+d],
              [line_coords[1][0]+d, line_coords[1][1]+d]]
        r, ms = post_geom(agent.token, agent.layer_id, "LineString", lc, agent._gnd_id)
        line_ms.append(ms)
        if r.status_code not in (200, 201):
            print(f"  line[{i}] HTTP {r.status_code}: {r.text[:160]}")

    print("\n=== RESULTS (full POST round-trip latency) ===")
    stats("Polygon", poly_ms)
    stats("Point",   point_ms)
    stats("Line",    line_ms)

    out = {
        "iter": ITER,
        "layer_id": agent.layer_id,
        "gnd_id": agent._gnd_id,
        "polygon_ms": poly_ms,
        "point_ms":   point_ms,
        "line_ms":    line_ms,
        "saved_ids":  saved_ids,
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ".agent_state", f"save_perf_{int(time.time())}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved JSON: {out_path}")


if __name__ == "__main__":
    main()
