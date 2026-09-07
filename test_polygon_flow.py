"""
Polygon Create → Save → Retrieve Timing Test
============================================
Tests the full round-trip: draw polygon → POST to survey_rep_data/ → retrieve via survey_rep_data_user/
Measures time at each intermediate step and reports any issues.

Usage:
    python test_polygon_flow.py

Configure BASE_URL and TOKEN below (or use environment variables).
"""

import os
import sys
import json
import time
import uuid
import requests

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
BASE_URL = os.environ.get("IB_BASE_URL", "https://infobhoomiback.geoinfobox.com/api/user")
TOKEN    = os.environ.get("IB_TOKEN", "")          # set your DRF token here or via env var

# If you don't know the token, set USERNAME + PASSWORD and the script will login.
USERNAME = os.environ.get("IB_USERNAME", "")
PASSWORD = os.environ.get("IB_PASSWORD", "")

# Layer ID to use for the test polygon. Leave 0 to auto-discover from your layers.
LAYER_ID = int(os.environ.get("IB_LAYER_ID", "0"))

# Test polygon — small area within GND 12231 (org_id=1 allowed area), EPSG:4326
# Centroid ~81.0654, 6.9978 (Sri Lanka)
TEST_POLYGON_COORDS = [
    [
        [81.0649, 6.9973],
        [81.0659, 6.9973],
        [81.0659, 6.9983],
        [81.0649, 6.9983],
        [81.0649, 6.9973],
    ]
]
# ──────────────────────────────────────────────────────────────────────────────


ANSI_GREEN  = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_RED    = "\033[91m"
ANSI_CYAN   = "\033[96m"
ANSI_RESET  = "\033[0m"
ANSI_BOLD   = "\033[1m"

timings = {}   # step_name -> elapsed_ms
issues  = []   # list of issue strings


def ok(msg):    print(f"  {ANSI_GREEN}[OK]{ANSI_RESET} {msg}")
def warn(msg):  print(f"  {ANSI_YELLOW}[WARN]{ANSI_RESET} {msg}"); issues.append(f"WARN: {msg}")
def err(msg):   print(f"  {ANSI_RED}[ERR]{ANSI_RESET} {msg}"); issues.append(f"ERROR: {msg}")
def info(msg):  print(f"  {ANSI_CYAN}[--]{ANSI_RESET} {msg}")
def step(title):print(f"\n{ANSI_BOLD}{title}{ANSI_RESET}")


def timed_request(label, method, url, **kwargs):
    """Run an HTTP request, record timing, return (response, elapsed_ms)."""
    t0 = time.perf_counter()
    resp = getattr(requests, method)(url, **kwargs)
    elapsed = (time.perf_counter() - t0) * 1000
    timings[label] = elapsed
    return resp, elapsed


def headers(token):
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }


# ─── STEP 0: Resolve token ────────────────────────────────────────────────────
step("STEP 0 — Authenticate")
token = TOKEN

if not token:
    if not USERNAME or not PASSWORD:
        print(f"\n{ANSI_RED}No token or credentials configured.{ANSI_RESET}")
        print("Set IB_TOKEN, or IB_USERNAME + IB_PASSWORD environment variables,")
        print("or edit the TOKEN / USERNAME / PASSWORD constants at the top of this script.")
        sys.exit(1)

    info(f"Logging in as '{USERNAME}' ...")
    resp, ms = timed_request("login", "post", f"{BASE_URL}/login/",
                             json={"username": USERNAME, "password": PASSWORD})
    if resp.status_code == 200:
        token = resp.json().get("token") or resp.json().get("Token")
        if token:
            ok(f"Login OK — token acquired  ({ms:.1f}ms)")
        else:
            err(f"Login response 200 but no token in body: {resp.text[:200]}")
            sys.exit(1)
    else:
        err(f"Login failed — HTTP {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)
else:
    ok(f"Using pre-configured token  (no network call)")

H = headers(token)


# ─── STEP 1: Discover a valid layer_id ────────────────────────────────────────
step("STEP 1 — Discover available layers")
layer_id = LAYER_ID

if not layer_id:
    resp, ms = timed_request("get_layers", "get", f"{BASE_URL}/layerdata_get_user/", headers=H)
    if resp.status_code == 200:
        layers = resp.json()
        if not layers:
            err("No layers returned — cannot determine a valid layer_id. Set IB_LAYER_ID manually.")
            sys.exit(1)
        layer_id = layers[0].get("layer_id") or layers[0].get("id")
        ok(f"Got {len(layers)} layers in {ms:.1f}ms — using layer_id={layer_id} ({layers[0].get('layer_name','?')})")
        if len(layers) > 1:
            info("All available layers:")
            for l in layers[:10]:
                print(f"      layer_id={l.get('layer_id','?'):>4}  name={l.get('layer_name','?')}")
    else:
        err(f"Layer fetch failed — HTTP {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)
else:
    ok(f"Using pre-configured layer_id={layer_id}")


# ─── STEP 2: Build the polygon payload ────────────────────────────────────────
step("STEP 2 — Build polygon payload (client-side)")

t0 = time.perf_counter()
feature_uuid = str(uuid.uuid4())

payload = [
    {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": TEST_POLYGON_COORDS,
        },
        "properties": {
            "uuid":       feature_uuid,
            "layer_id":   layer_id,
            "crs":        "EPSG:4326",
            "parent_uuid": [],
            # gnd_id intentionally omitted → backend auto-detects
        },
    }
]

build_ms = (time.perf_counter() - t0) * 1000
timings["payload_build"] = build_ms
ok(f"Payload built  ({build_ms:.2f}ms)  uuid={feature_uuid}")
info(f"Polygon coords: {len(TEST_POLYGON_COORDS[0])} vertices")


# ─── STEP 3: POST to save endpoint ────────────────────────────────────────────
step("STEP 3 — POST polygon to survey_rep_data/")

resp_save, save_ms = timed_request(
    "save_polygon",
    "post",
    f"{BASE_URL}/survey_rep_data/",
    headers=H,
    json=payload,
)

info(f"HTTP {resp_save.status_code}  ({save_ms:.1f}ms)")

saved_id   = None
saved_uuid = None

if resp_save.status_code in (200, 201):
    body = resp_save.json()
    saved_records = body.get("saved_records", [])
    errors        = body.get("errors", [])
    warnings      = body.get("warnings", [])

    if saved_records:
        rec = saved_records[0]
        props = rec.get("properties", {})
        saved_id   = props.get("id")
        saved_uuid = props.get("uuid")
        gnd_id     = props.get("gnd_id")
        calc_area  = props.get("calculated_area")
        ok(f"Polygon saved — id={saved_id}  uuid={saved_uuid}")
        ok(f"  gnd_id={gnd_id}  calculated_area={calc_area} m²")
    else:
        err(f"No saved_records in response (errors={errors})")

    if errors:
        for e in errors:
            err(f"Backend error for feature [{e.get('index')}]: {e.get('errors') or e.get('detail')}")

    if warnings:
        for w in warnings:
            warn(f"Backend warning: {w}")

    # Timing breakdown from response headers (if any)
    x_timing = resp_save.headers.get("X-Timing")
    if x_timing:
        info(f"X-Timing header: {x_timing}")

elif resp_save.status_code == 403:
    err(f"403 Forbidden — check token, role, and permission_id=201 add=True for this user's role")
    try: print("       ", json.dumps(resp_save.json(), indent=2))
    except: print("       ", resp_save.text[:400])
    sys.exit(1)
elif resp_save.status_code == 400:
    err(f"400 Bad Request")
    try: print("       ", json.dumps(resp_save.json(), indent=2))
    except: print("       ", resp_save.text[:400])
else:
    err(f"Unexpected HTTP {resp_save.status_code}: {resp_save.text[:400]}")
    sys.exit(1)


# ─── STEP 4: Retrieve all features (map load) ─────────────────────────────────
step("STEP 4 — Retrieve features via survey_rep_data_user/")

resp_get, get_ms = timed_request(
    "retrieve_features",
    "post",
    f"{BASE_URL}/survey_rep_data_user/",
    headers=H,
    json={},
)

info(f"HTTP {resp_get.status_code}  ({get_ms:.1f}ms)")

if resp_get.status_code == 200:
    features = resp_get.json()
    # GeoJSON FeatureCollection or list?
    if isinstance(features, dict) and features.get("type") == "FeatureCollection":
        feature_list = features.get("features", [])
    elif isinstance(features, list):
        feature_list = features
    else:
        feature_list = []
        warn(f"Unexpected response shape: {type(features)} — first 200 chars: {str(features)[:200]}")

    ok(f"Retrieved {len(feature_list)} feature(s)")

    # Verify the saved polygon is in the response
    if saved_uuid:
        found = next(
            (f for f in feature_list
             if f.get("properties", {}).get("uuid") == saved_uuid
             or str(f.get("properties", {}).get("id")) == str(saved_id)),
            None,
        )
        if found:
            geom = found.get("geometry") or {}
            ok(f"Saved polygon confirmed in response  id={found['properties'].get('id')}  geom_type={geom.get('type')}")
            coord_count = sum(len(r) for r in (geom.get("coordinates") or [[]])) if geom else 0
            ok(f"  Geometry has {coord_count} coordinate(s) in response")
        else:
            warn(f"Saved uuid={saved_uuid} / id={saved_id} NOT found in retrieval response")
            warn(f"  (may be a different layer, org, or status filter — check Survey_Rep_DATA_Filter_User_View)")
else:
    err(f"Retrieve failed — HTTP {resp_get.status_code}: {resp_get.text[:200]}")


# ─── STEP 5: Timing Summary ───────────────────────────────────────────────────
step("TIMING SUMMARY")

order = [
    ("login",             "Login (network)"),
    ("get_layers",        "Layer discovery (network)"),
    ("payload_build",     "Payload build (client)"),
    ("save_polygon",      "POST survey_rep_data/ (network + backend)"),
    ("retrieve_features", "POST survey_rep_data_user/ (network + backend)"),
]

total = 0.0
for key, label in order:
    ms = timings.get(key)
    if ms is None:
        continue
    flag = ""
    if ms > 3000:
        flag = f"  {ANSI_RED}** SLOW (>3s){ANSI_RESET}"
    elif ms > 1000:
        flag = f"  {ANSI_YELLOW}* WARN (>1s){ANSI_RESET}"
    total += ms
    print(f"  {label:<45} {ms:>8.1f}ms{flag}")

print(f"  {'-'*55}")
print(f"  {'TOTAL (all timed steps)':<45} {total:>8.1f}ms")

# ─── STEP 6: Issue Report ─────────────────────────────────────────────────────
if issues:
    step("ISSUES DETECTED")
    for i, issue in enumerate(issues, 1):
        color = ANSI_RED if issue.startswith("ERROR") else ANSI_YELLOW
        print(f"  {color}[{i}]{ANSI_RESET} {issue}")
else:
    step("NO ISSUES DETECTED")
    ok("Full polygon create -> save -> retrieve cycle completed successfully.")

print()
