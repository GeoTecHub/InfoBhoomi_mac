"""
InfoBhoomi — GIS Performance Agent
====================================
Tests all major InfoBhoomi API endpoints, measures latency,
checks geometry validity, and returns structured findings.

Extends the logic from test_polygon_flow.py to cover:
  - Auth (login / token verify)
  - Layer CRUD
  - Spatial feature save (polygon, point, line)
  - Spatial feature retrieve
  - Spatial feature update
  - Spatial search
  - Land / Building summary
  - RRR data
  - Party data
  - GND / Org area
"""

import time
import uuid
import json
import requests
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime

from config import (
    BASE_URL, TOKEN, USERNAME, PASSWORD,
    TEST_LAYER_ID, TEST_POLYGON_COORDS, TEST_POINT_COORDS, TEST_LINE_COORDS,
    PERF_WARN_MS, PERF_SLOW_MS, PERF_CRITICAL_MS,
)

# ── ANSI colours ─────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class EndpointResult:
    label: str
    url: str
    method: str
    status_code: Optional[int] = None
    elapsed_ms: float = 0.0
    passed: bool = False
    warning: bool = False
    error_msg: str = ""
    notes: str = ""


@dataclass
class PerfReport:
    run_at: str = ""
    base_url: str = ""
    total_ms: float = 0.0
    results: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    saved_feature_id: Optional[int] = None
    saved_feature_uuid: Optional[str] = None
    layer_id: Optional[int] = None

    def to_dict(self):
        d = asdict(self)
        d["results"] = [asdict(r) for r in self.results]
        return d


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(level: str, msg: str):
    colours = {"OK": GREEN, "WARN": YELLOW, "ERR": RED, "INFO": CYAN}
    c = colours.get(level, RESET)
    print(f"  {c}[{level}]{RESET} {msg}")


def _timed(method: str, url: str, **kwargs) -> tuple[requests.Response, float]:
    t0 = time.perf_counter()
    resp = getattr(requests, method)(url, timeout=30, **kwargs)
    return resp, (time.perf_counter() - t0) * 1000


def _rate(ms: float) -> str:
    if ms >= PERF_CRITICAL_MS:
        return f"{RED}CRITICAL ({ms:.0f}ms){RESET}"
    if ms >= PERF_SLOW_MS:
        return f"{RED}SLOW ({ms:.0f}ms){RESET}"
    if ms >= PERF_WARN_MS:
        return f"{YELLOW}WARN ({ms:.0f}ms){RESET}"
    return f"{GREEN}OK ({ms:.0f}ms){RESET}"


# ── Main Agent Class ──────────────────────────────────────────────────────────

class GISPerfAgent:
    """
    Runs a comprehensive performance audit of the InfoBhoomi GIS API.
    Returns a PerfReport with per-endpoint timings and issues.
    """

    def __init__(self, token: str = "", layer_id: int = 0):
        self.token = token or TOKEN
        self.layer_id = layer_id or TEST_LAYER_ID
        self.report = PerfReport(
            run_at=datetime.utcnow().isoformat() + "Z",
            base_url=BASE_URL,
        )
        self._gnd_id: Optional[int] = None          # auto-discovered from org area
        self._org_test_coords: Optional[list] = None # polygon coords within org boundary
        self._sample_su_id: Optional[int] = None     # real su_id for search test

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        print(f"\n{BOLD}[AUTH] Authenticating...{RESET}")
        if self.token:
            _log("INFO", "Using pre-configured token — verifying...")
            resp, ms = _timed("get", f"{BASE_URL}/verify-token/",
                              headers=self._headers())
            r = self._record("Token Verify", "/verify-token/", "GET", resp, ms)
            if resp.status_code == 200:
                _log("OK", f"Token valid  {_rate(ms)}")
                return True
            else:
                _log("WARN", f"Token verify returned {resp.status_code} — re-authenticating with credentials")
                self.token = ""  # clear stale token before attempting credential login

        # Login with credentials
        if not USERNAME or not PASSWORD:
            _log("ERR", "No token or credentials set. Edit config.py or set env vars.")
            return False

        resp, ms = _timed("post", f"{BASE_URL}/login/",
                          json={"username": USERNAME, "password": PASSWORD})
        r = self._record("Login", "/login/", "POST", resp, ms)

        if resp.status_code == 200:
            body = resp.json()
            self.token = body.get("token") or body.get("Token", "")
            if self.token:
                _log("OK", f"Login OK  {_rate(ms)}")
                return True
            else:
                _log("ERR", f"Login 200 but no token in body: {str(body)[:100]}")
                self.report.issues.append("Login returned 200 but no token field found.")
                return False
        else:
            _log("ERR", f"Login failed HTTP {resp.status_code}: {resp.text[:200]}")
            self.report.issues.append(f"Login failed: HTTP {resp.status_code}")
            return False

    # ── Layers ────────────────────────────────────────────────────────────────

    def test_layers(self):
        print(f"\n{BOLD}[LAYERS] Testing layer endpoints...{RESET}")

        # GET user layers
        resp, ms = _timed("get", f"{BASE_URL}/layerdata_get_user/",
                          headers=self._headers())
        r = self._record("GET User Layers", "/layerdata_get_user/", "GET", resp, ms)
        if resp.status_code == 200:
            layers = resp.json()
            count = len(layers) if isinstance(layers, list) else "?"
            _log("OK", f"{count} layers returned  {_rate(ms)}")
            if isinstance(layers, list) and layers and not self.layer_id:
                # Prefer a user-created layer (type "user") over default/org layers
                # User layers are writable; default/org layers are typically read-only
                user_layer = next(
                    (l for l in layers if str(l.get("layer_type", "")).lower() in ("user", "my_layer", "custom")),
                    None,
                )
                chosen = user_layer or layers[0]
                self.layer_id = chosen.get("layer_id") or chosen.get("id")
                self.report.layer_id = self.layer_id
                layer_type = chosen.get("layer_type", "unknown")
                _log("INFO", f"Using layer_id={self.layer_id} (type={layer_type}) for geometry tests")
            r.notes = f"{count} layers returned"
        else:
            _log("ERR", f"Layer fetch failed HTTP {resp.status_code}")
            self.report.issues.append(f"GET /layerdata_get_user/ failed: HTTP {resp.status_code}")

        self.report.layer_id = self.layer_id

    # ── Spatial Features ──────────────────────────────────────────────────────

    def test_save_polygon(self) -> Optional[int]:
        """POST a polygon and return saved feature id."""
        print(f"\n{BOLD}[SPATIAL] Testing polygon save (survey_rep_data/)...{RESET}")
        if not self.layer_id:
            _log("WARN", "No layer_id — skipping polygon save test")
            self.report.issues.append("Polygon save skipped: no layer_id discovered.")
            return None

        feature_uuid = str(uuid.uuid4())
        coords = self._org_test_coords or TEST_POLYGON_COORDS
        props: dict = {
            "uuid": feature_uuid,
            "layer_id": self.layer_id,
            "crs": "EPSG:4326",
            "parent_uuid": [],
        }
        if self._gnd_id:
            props["gnd_id"] = self._gnd_id

        payload = [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": coords},
                "properties": props,
            }
        ]

        resp, ms = _timed("post", f"{BASE_URL}/survey_rep_data/",
                          headers=self._headers(), json=payload)
        r = self._record("POST Polygon", "/survey_rep_data/", "POST", resp, ms)

        if resp.status_code in (200, 201):
            body = resp.json()
            saved = body.get("saved_records", [])
            errors = body.get("errors", [])
            if saved:
                props = saved[0].get("properties", {})
                fid = props.get("id")
                fuuid = props.get("uuid")
                area = props.get("calculated_area")
                self.report.saved_feature_id = fid
                self.report.saved_feature_uuid = fuuid
                _log("OK", f"Polygon saved — id={fid}  area={area}m²  {_rate(ms)}")
                r.notes = f"id={fid} area={area}m²"
                return fid
            if errors:
                for e in errors:
                    msg = f"Backend error: {e.get('errors') or e.get('detail')}"
                    _log("ERR", msg)
                    self.report.issues.append(f"POST /survey_rep_data/ error: {msg}")
        else:
            _log("ERR", f"Polygon save HTTP {resp.status_code}: {resp.text[:200]}")
            self.report.issues.append(
                f"POST /survey_rep_data/ failed: HTTP {resp.status_code} — {resp.text[:150]}"
            )
        return None

    def test_save_point(self) -> Optional[int]:
        """POST a point feature."""
        print(f"\n{BOLD}[SPATIAL] Testing point save...{RESET}")
        if not self.layer_id:
            _log("WARN", "No layer_id — skipping point save test")
            return None

        # Use centre of org test polygon as point coords
        pt_coords = TEST_POINT_COORDS
        if self._org_test_coords:
            ring = self._org_test_coords[0]
            pt_coords = [
                sum(p[0] for p in ring) / len(ring),
                sum(p[1] for p in ring) / len(ring),
            ]
        pt_props: dict = {
            "uuid": str(uuid.uuid4()),
            "layer_id": self.layer_id,
            "crs": "EPSG:4326",
            "parent_uuid": [],
        }
        if self._gnd_id:
            pt_props["gnd_id"] = self._gnd_id

        payload = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": pt_coords},
                "properties": pt_props,
            }
        ]
        resp, ms = _timed("post", f"{BASE_URL}/survey_rep_data/",
                          headers=self._headers(), json=payload)
        r = self._record("POST Point", "/survey_rep_data/ (point)", "POST", resp, ms)
        if resp.status_code in (200, 201):
            saved = resp.json().get("saved_records", [])
            fid = saved[0]["properties"].get("id") if saved else None
            _log("OK", f"Point saved — id={fid}  {_rate(ms)}")
            return fid
        else:
            _log("ERR", f"Point save HTTP {resp.status_code}: {resp.text[:150]}")
            self.report.issues.append(f"POST point failed: HTTP {resp.status_code}")
        return None

    def test_save_line(self) -> Optional[int]:
        """POST a linestring feature."""
        print(f"\n{BOLD}[SPATIAL] Testing line save...{RESET}")
        if not self.layer_id:
            _log("WARN", "No layer_id — skipping line save test")
            return None

        ln_coords = TEST_LINE_COORDS
        if self._org_test_coords:
            ring = self._org_test_coords[0]
            ln_coords = [ring[0], ring[2]]   # diagonal of test polygon
        ln_props: dict = {
            "uuid": str(uuid.uuid4()),
            "layer_id": self.layer_id,
            "crs": "EPSG:4326",
            "parent_uuid": [],
        }
        if self._gnd_id:
            ln_props["gnd_id"] = self._gnd_id

        payload = [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": ln_coords},
                "properties": ln_props,
            }
        ]
        resp, ms = _timed("post", f"{BASE_URL}/survey_rep_data/",
                          headers=self._headers(), json=payload)
        r = self._record("POST Line", "/survey_rep_data/ (line)", "POST", resp, ms)
        if resp.status_code in (200, 201):
            saved = resp.json().get("saved_records", [])
            fid = saved[0]["properties"].get("id") if saved else None
            _log("OK", f"Line saved — id={fid}  {_rate(ms)}")
            return fid
        else:
            _log("ERR", f"Line save HTTP {resp.status_code}: {resp.text[:150]}")
            self.report.issues.append(f"POST line failed: HTTP {resp.status_code}")
        return None

    def test_retrieve_features(self):
        """POST survey_rep_data_user/ to retrieve all user features."""
        print(f"\n{BOLD}[SPATIAL] Testing feature retrieval...{RESET}")
        resp, ms = _timed("post", f"{BASE_URL}/survey_rep_data_user/",
                          headers=self._headers(), json={})
        r = self._record("GET Features", "/survey_rep_data_user/", "POST", resp, ms)
        if resp.status_code == 200:
            body = resp.json()
            if isinstance(body, dict) and body.get("type") == "FeatureCollection":
                feature_list = body.get("features", [])
            elif isinstance(body, list):
                feature_list = body
            else:
                feature_list = []
            count = len(feature_list)
            _log("OK", f"{count} features retrieved  {_rate(ms)}")
            r.notes = f"{count} features in response"

            # Grab a real su_id for the search test — try all known field names
            if feature_list:
                props0 = feature_list[0].get("properties", {})
                for field in ("id", "su_id", "su_id_field", "pk", "feature_id"):
                    val = props0.get(field)
                    if val is not None:
                        self._sample_su_id = val
                        break

            # Check if previously saved polygon is present
            if self.report.saved_feature_uuid:
                features = body.get("features", body) if isinstance(body, dict) else body
                found = any(
                    f.get("properties", {}).get("uuid") == self.report.saved_feature_uuid
                    for f in (features if isinstance(features, list) else [])
                )
                if found:
                    _log("OK", "Saved polygon confirmed in retrieval response")
                else:
                    _log("WARN", "Saved polygon uuid NOT found in retrieval response")
                    self.report.issues.append(
                        "Saved polygon not found in survey_rep_data_user/ response. "
                        "Check layer/org/status filters."
                    )
        else:
            _log("ERR", f"Retrieve HTTP {resp.status_code}: {resp.text[:200]}")
            self.report.issues.append(f"GET /survey_rep_data_user/ failed: HTTP {resp.status_code}")

    def test_update_feature(self, feature_id: int):
        """PATCH an attribute update on a saved feature."""
        print(f"\n{BOLD}[SPATIAL] Testing feature update (id={feature_id})...{RESET}")
        payload = {"notes": f"perf_test_update_{datetime.utcnow().isoformat()}"}
        resp, ms = _timed("patch", f"{BASE_URL}/survey_rep_data/update/id={feature_id}/",
                          headers=self._headers(), json=payload)
        r = self._record(
            "PATCH Feature Update",
            f"/survey_rep_data/update/id={feature_id}/",
            "PATCH", resp, ms,
        )
        if resp.status_code in (200, 204):
            _log("OK", f"Feature updated  {_rate(ms)}")
        else:
            _log("WARN", f"Update HTTP {resp.status_code}: {resp.text[:150]}")
            self.report.issues.append(
                f"PATCH /survey_rep_data/update/ failed: HTTP {resp.status_code}"
            )

    # ── Search ────────────────────────────────────────────────────────────────

    def test_search(self):
        print(f"\n{BOLD}[SEARCH] Testing spatial search...{RESET}")
        if not self._sample_su_id:
            _log("WARN", "No su_id available — skipping search test")
            return
        payload = {"su_id": self._sample_su_id}
        resp, ms = _timed("post", f"{BASE_URL}/search/",
                          headers=self._headers(), json=payload)
        r = self._record("Spatial Search", "/search/", "POST", resp, ms)
        if resp.status_code == 200:
            results = resp.json()
            count = len(results) if isinstance(results, list) else "?"
            _log("OK", f"{count} search results  {_rate(ms)}")
            r.notes = f"{count} results"
        else:
            _log("WARN", f"Search HTTP {resp.status_code}: {resp.text[:150]}")

    # ── GND id discovery ─────────────────────────────────────────────────────

    def _discover_gnd_id(self):
        """
        Fetch a valid integer gnd_id from GET /lst-gnd-area/.
        This is more reliable than reading it from org_area properties,
        because /lst-gnd-area/ always returns [{gid: <int>, gnd: "<name>"}, ...].
        Called once before the spatial-save tests so all three saves succeed.
        """
        # Only skip if we already have a valid integer; a string set by test_org_area is unusable.
        if isinstance(self._gnd_id, int):
            return
        try:
            resp, ms = _timed("get", f"{BASE_URL}/lst-gnd-area/",
                              headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    gid = data[0].get("gid")
                    if gid is not None:
                        self._gnd_id = int(gid)
                        _log("INFO", f"Discovered gnd_id={self._gnd_id} from lst-gnd-area/  {_rate(ms)}")
                        return
            _log("WARN", f"lst-gnd-area/ HTTP {resp.status_code} — gnd_id not set; "
                         "spatial saves may fail with HTTP 400")
        except Exception as e:
            _log("WARN", f"Could not discover gnd_id: {e}")

    # ── GND / Org Area ────────────────────────────────────────────────────────

    def test_org_area(self):
        print(f"\n{BOLD}[ORG] Testing org area fetch...{RESET}")
        resp, ms = _timed("get", f"{BASE_URL}/org_area/", headers=self._headers())
        r = self._record("GET Org Area", "/org_area/", "GET", resp, ms)
        if resp.status_code == 200:
            _log("OK", f"Org area received  {_rate(ms)}")
            # Auto-detect a GND id and a safe test point inside the org boundary
            try:
                data = resp.json()
                # data may be a list of GND features or a FeatureCollection
                features = data if isinstance(data, list) else data.get("features", [])
                if features:
                    first = features[0]
                    props = first.get("properties", {})
                    # Show available fields so we can debug field name mismatches
                    _log("INFO", f"Org area property fields: {list(props.keys())[:10]}")
                    # Try all known field name variations for GND id
                    for field in ("gnd", "gnd_id", "gnd_10m_id", "gnd10m_id", "id", "pk", "gnd_code"):
                        val = props.get(field)
                        if val is not None:
                            self._gnd_id = val
                            break
                    geom = first.get("geometry", {})
                    coords = geom.get("coordinates", [])
                    # Extract a centroid-ish point from the first polygon ring
                    if coords and geom.get("type") == "Polygon":
                        ring = coords[0]
                        n = len(ring)
                        cx = sum(p[0] for p in ring) / n
                        cy = sum(p[1] for p in ring) / n
                        offset = 0.0005
                        self._org_test_coords = [[
                            [cx - offset, cy - offset],
                            [cx + offset, cy - offset],
                            [cx + offset, cy + offset],
                            [cx - offset, cy + offset],
                            [cx - offset, cy - offset],
                        ]]
                        _log("INFO", f"Auto-detected gnd_id={self._gnd_id}  "
                                     f"test point≈({cx:.4f}, {cy:.4f})")
                    elif coords and geom.get("type") == "MultiPolygon":
                        ring = coords[0][0]
                        n = len(ring)
                        cx = sum(p[0] for p in ring) / n
                        cy = sum(p[1] for p in ring) / n
                        offset = 0.0005
                        self._org_test_coords = [[
                            [cx - offset, cy - offset],
                            [cx + offset, cy - offset],
                            [cx + offset, cy + offset],
                            [cx - offset, cy + offset],
                            [cx - offset, cy - offset],
                        ]]
                        _log("INFO", f"Auto-detected gnd_id={self._gnd_id}  "
                                     f"test point≈({cx:.4f}, {cy:.4f})")
            except Exception as e:
                _log("WARN", f"Could not auto-detect org coords: {e}")
        else:
            _log("WARN", f"Org area HTTP {resp.status_code}")

        resp2, ms2 = _timed("get", f"{BASE_URL}/org_loc_get/", headers=self._headers())
        r2 = self._record("GET Org Location", "/org_loc_get/", "GET", resp2, ms2)
        if resp2.status_code == 200:
            _log("OK", f"Org location received  {_rate(ms2)}")
        else:
            _log("WARN", f"Org location HTTP {resp2.status_code}")

    # ── RRR ───────────────────────────────────────────────────────────────────

    def test_rrr(self):
        print(f"\n{BOLD}[RRR] Testing RRR endpoints...{RESET}")
        resp, ms = _timed("get", f"{BASE_URL}/rrr_data_get/",
                          headers=self._headers(), params={"su_id": 1})
        r = self._record("GET RRR Data", "/rrr_data_get/", "GET", resp, ms)
        if resp.status_code == 200:
            _log("OK", f"RRR data received  {_rate(ms)}")
        else:
            _log("WARN", f"RRR HTTP {resp.status_code}: {resp.text[:100]}")

    # ── Party ─────────────────────────────────────────────────────────────────

    def test_party(self):
        print(f"\n{BOLD}[PARTY] Testing party endpoints...{RESET}")
        # GET party types list (read-only, no required fields)
        resp, ms = _timed("get", f"{BASE_URL}/lst-sl-party-type-1/",
                          headers=self._headers())
        r = self._record("GET Party Types", "/lst-sl-party-type-1/", "GET", resp, ms)
        if resp.status_code == 200:
            body = resp.json()
            count = len(body) if isinstance(body, list) else "?"
            _log("OK", f"{count} party types  {_rate(ms)}")
            r.notes = f"{count} records"
        else:
            _log("WARN", f"Party types HTTP {resp.status_code}: {resp.text[:100]}")

    # ── Lookup Lists ──────────────────────────────────────────────────────────

    def test_lookups(self):
        print(f"\n{BOLD}[LOOKUPS] Testing lookup list endpoints...{RESET}")
        endpoints = [
            ("Lst Party Type",      "/lst-sl-party-type-1/"),
            ("Lst Right Type",      "/lst-sl-righttype-9/"),
            ("Lst Land Use Type",   "/lst-ec-extlandusetype-28/"),
            ("Lst Org Names",       "/lst-org-name-40/"),
        ]
        for label, path in endpoints:
            resp, ms = _timed("get", f"{BASE_URL}{path}", headers=self._headers())
            self._record(f"GET {label}", path, "GET", resp, ms)
            status = "OK" if resp.status_code == 200 else "WARN"
            _log(status, f"{label}  {_rate(ms)}")

    # ── User Info ─────────────────────────────────────────────────────────────

    def test_user_info(self):
        print(f"\n{BOLD}[USER] Testing user info endpoints...{RESET}")
        resp, ms = _timed("get", f"{BASE_URL}/me/", headers=self._headers())
        r = self._record("GET Me", "/me/", "GET", resp, ms)
        if resp.status_code == 200:
            user = resp.json()
            _log("OK", f"User: {user.get('username', '?')}  {_rate(ms)}")
        else:
            _log("WARN", f"/me/ HTTP {resp.status_code}")

    # ── Run Full Suite ────────────────────────────────────────────────────────

    def run(self) -> PerfReport:
        """
        Run the full performance suite.
        Returns a PerfReport with all timings and issues.
        """
        print(f"\n{BOLD}{'='*60}")
        print("  InfoBhoomi GIS Performance Agent")
        print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"{'='*60}{RESET}")

        if not self.authenticate():
            self.report.issues.append("Authentication failed — cannot run performance tests.")
            return self.report

        self.test_user_info()
        self.test_org_area()
        self.test_layers()
        self.test_lookups()

        # Discover a valid integer gnd_id before any spatial-save tests.
        # /lst-gnd-area/ is the reliable source; org_area field names vary by org.
        self._discover_gnd_id()

        # Core GIS flow: save → retrieve → update
        polygon_id = self.test_save_polygon()
        self.test_save_point()
        self.test_save_line()
        self.test_retrieve_features()
        if polygon_id:
            self.test_update_feature(polygon_id)

        self.test_search()
        self.test_rrr()
        self.test_party()

        # Totals
        self.report.total_ms = sum(r.elapsed_ms for r in self.report.results)

        # Flag slow endpoints as issues
        for r in self.report.results:
            if r.elapsed_ms >= PERF_CRITICAL_MS:
                self.report.issues.append(
                    f"CRITICAL LATENCY: {r.label} ({r.url}) took {r.elapsed_ms:.0f}ms"
                )
            elif r.elapsed_ms >= PERF_SLOW_MS:
                self.report.issues.append(
                    f"SLOW: {r.label} ({r.url}) took {r.elapsed_ms:.0f}ms (threshold: {PERF_SLOW_MS}ms)"
                )

        self._print_summary()
        return self.report

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
        }

    def _record(
        self,
        label: str,
        path: str,
        method: str,
        resp: requests.Response,
        ms: float,
    ) -> EndpointResult:
        passed = resp.status_code in (200, 201, 204)
        warning = ms >= PERF_WARN_MS
        r = EndpointResult(
            label=label,
            url=path,
            method=method,
            status_code=resp.status_code,
            elapsed_ms=ms,
            passed=passed,
            warning=warning,
        )
        self.report.results.append(r)
        return r

    def _print_summary(self):
        print(f"\n{BOLD}{'='*60}")
        print("  TIMING SUMMARY")
        print(f"{'='*60}{RESET}")
        for r in self.report.results:
            flag = ""
            if r.elapsed_ms >= PERF_CRITICAL_MS:
                flag = f"  {RED}★ CRITICAL{RESET}"
            elif r.elapsed_ms >= PERF_SLOW_MS:
                flag = f"  {RED}● SLOW{RESET}"
            elif r.elapsed_ms >= PERF_WARN_MS:
                flag = f"  {YELLOW}○ WARN{RESET}"
            status = f"{GREEN}✓{RESET}" if r.passed else f"{RED}✗{RESET}"
            print(f"  {status} {r.method:<5} {r.label:<35} {r.elapsed_ms:>8.0f}ms{flag}")

        print(f"  {'-'*58}")
        print(f"  {'TOTAL':<42} {self.report.total_ms:>8.0f}ms")

        if self.report.issues:
            print(f"\n{BOLD}{RED}  ISSUES FOUND ({len(self.report.issues)}){RESET}")
            for i, issue in enumerate(self.report.issues, 1):
                print(f"    {RED}[{i}]{RESET} {issue}")
        else:
            print(f"\n  {GREEN}{BOLD}All endpoints passed with no issues.{RESET}")
        print()
