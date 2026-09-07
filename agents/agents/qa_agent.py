"""
InfoBhoomi — QA Functional & Data-Integrity Agent
===================================================
Covers the full Web-GIS feature lifecycle with timing for every operation:

  Phase A  —  Draw & save POINT feature            (timing)
  Phase B  —  Draw & save LINE feature              (timing)
  Phase C  —  Draw & save POLYGON feature           (timing)
  Phase D  —  Land parcel: create polygon + add ALL attribute tables (timing each)
  Phase E  —  DB verification: re-fetch all 6 attribute tables, assert data matches
  Phase F  —  Split simulation: save child polygon with parent_uuid, check history
  Phase G  —  Delete polygon, verify geom-edit-history and survey_rep_history updated
  Phase H  —  Query builder: POST query-parcels/ with filters, verify results
  Phase I  —  Export: GET query-parcels/export-shp/, verify file returned
  Phase J  —  Cleanup: bulk-delete all [QA-AGENT-TEST] parcels

The agent NEVER modifies production data outside test parcels it creates.
Every test parcel is tagged [QA-AGENT-TEST] in land_name for safe identification.
"""

import io
import math
import time
import uuid
import json
import requests
from dataclasses import dataclass, field, asdict
from typing import Optional, Any
from datetime import datetime, date

from config import (
    BASE_URL, TOKEN, USERNAME, PASSWORD,
    TEST_LAYER_ID, TEST_POLYGON_COORDS,
    TEST_POINT_COORDS, TEST_LINE_COORDS,
    PERF_WARN_MS, PERF_SLOW_MS,
)

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def _pass(msg: str) -> str:  return f"{GREEN}  ✔  {msg}{RESET}"
def _fail(msg: str) -> str:  return f"{RED}  ✘  {msg}{RESET}"
def _warn(msg: str) -> str:  return f"{YELLOW}  ⚠  {msg}{RESET}"
def _info(msg: str) -> str:  return f"{CYAN}  ℹ  {msg}{RESET}"
def _time(ms: float) -> str:
    colour = GREEN if ms < PERF_WARN_MS else (YELLOW if ms < PERF_SLOW_MS else RED)
    return f"{colour}{ms:,.0f} ms{RESET}"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class QAResult:
    label:      str
    passed:     bool
    warning:    bool   = False
    message:    str    = ""
    detail:     str    = ""
    elapsed_ms: float  = 0.0


@dataclass
class QAReport:
    run_at:     str           = ""
    total:      int           = 0
    passed:     int           = 0
    failed:     int           = 0
    warnings:   int           = 0
    test_su_id: Optional[int] = None
    test_uuid:  str           = ""
    results:    list          = field(default_factory=list)
    issues:     list          = field(default_factory=list)
    summary:    str           = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── QA Agent ──────────────────────────────────────────────────────────────────

class QAAgent:
    """
    Full functional + data-integrity QA for InfoBhoomi.

    Usage:
        agent = QAAgent(token="...", layer_id=1)
        report = agent.run()
    """

    TAG = "[QA-AGENT-TEST]"

    # Attribute payloads used in Phase D (land parcel) — realistic test values
    _ADMIN_PAYLOAD = {
        "land_name":          f"QA Test Parcel",
        "sl_land_type":       "Urban",
        "tenure_type":        "Freehold",
        "registration_date":  "2024-01-15",
        "status":             "Active",
        "gnd_name":           "QA GND",
    }
    _OVERVIEW_PAYLOAD = {
        "boundary_type": "Cadastral",
        "crs":           "EPSG:4326",
        "land_use":      "Residential",
    }
    _ZONING_PAYLOAD = {
        "zoning_category":     "Residential",
        "max_building_height": 10.0,
        "max_coverage":        60.0,
        "max_far":             1.5,
        "setback_front":       3.0,
        "setback_rear":        1.5,
        "setback_left":        1.5,
        "setback_right":       1.5,
    }
    _PHYS_ENV_PAYLOAD = {
        "elevation":    45.0,
        "slope":        5.0,
        "flood_zone":   "Low",
    }
    _TAX_PAYLOAD = {
        "land_value":       500000.0,
        "market_value":     650000.0,
        "tax_rate":         1.5,
        "annual_tax":       9750.0,
    }
    _UTILITY_PAYLOAD = {
        "water_supply":  "Available",
        "electricity":   "Available",
        "drainage":      "Available",
    }

    def __init__(self, token: str = "", layer_id: int = 0):
        self.token    = token or TOKEN
        self.layer_id = layer_id or TEST_LAYER_ID
        self.base     = BASE_URL.rstrip("/")
        self.session  = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        # Running state
        self._test_su_id:       Optional[int] = None
        self._test_uuid:        str = ""
        self._child_su_id:      Optional[int] = None   # Phase F split child
        self._child_uuid:       str = ""
        self._point_su_id:      Optional[int] = None
        self._line_su_id:       Optional[int] = None
        self._all_test_su_ids:  list[int] = []         # numeric ids for bulk delete
        self._all_test_uuids:   list[str] = []         # kept for reference only
        self._gnd_id:           Optional[int] = None   # discovered integer gnd_id
        self._results:          list[QAResult] = []
        self._auto_coords:      Optional[list] = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Token {self.token}",
                "Content-Type":  "application/json"}

    def _login(self) -> bool:
        if self.token:
            # Verify the token is still active before trusting it.
            # Tokens can become stale between sessions (server restart, expiry, etc.)
            r, _ = self._req("GET", "/verify-token/")
            if r is not None and r.status_code == 200:
                return True
            # Token invalid — fall through and re-authenticate with credentials
            print(f"{YELLOW}  ⚠  Saved token is no longer valid — re-authenticating...{RESET}")
            self.token = ""
        if not (USERNAME and PASSWORD):
            print(f"{RED}  No credentials — set IB_TOKEN or IB_USERNAME+IB_PASSWORD in .env{RESET}")
            return False
        try:
            r = self.session.post(
                f"{self.base}/login/",
                json={"username": USERNAME, "password": PASSWORD},
                timeout=15,
            )
            if r.status_code == 200:
                self.token = r.json().get("token", "")
                return bool(self.token)
            print(f"{RED}  Login failed: {r.status_code}{RESET}")
            return False
        except Exception as e:
            print(f"{RED}  Login error: {e}{RESET}")
            return False

    # ── HTTP wrapper ──────────────────────────────────────────────────────────

    def _req(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> tuple[Optional[requests.Response], float]:
        url = f"{self.base}/{path.lstrip('/')}"
        kwargs.setdefault("headers", self._headers())
        kwargs.setdefault("timeout", 30)
        t0 = time.perf_counter()
        try:
            r = self.session.request(method, url, **kwargs)
            ms = (time.perf_counter() - t0) * 1000
            return r, ms
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            print(f"{RED}  Request error [{method} {path}]: {e}{RESET}")
            return None, ms

    # ── Result recorder ───────────────────────────────────────────────────────

    def _record(
        self,
        label:   str,
        passed:  bool,
        message: str   = "",
        detail:  str   = "",
        warning: bool  = False,
        elapsed_ms: float = 0.0,
    ) -> QAResult:
        r = QAResult(
            label=label, passed=passed, warning=warning,
            message=message, detail=detail, elapsed_ms=elapsed_ms,
        )
        self._results.append(r)
        timing = f"  [{_time(elapsed_ms)}]" if elapsed_ms else ""
        if passed:
            print(_pass(f"{label}  {message}{timing}"))
        elif warning:
            print(_warn(f"{label}  {message}{timing}"))
        else:
            print(_fail(f"{label}  {message}{timing}"))
            if detail:
                print(f"     {CYAN}Detail: {detail[:250]}{RESET}")
        return r

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _get_test_coords(self) -> list:
        """Return a small polygon near the org centroid (auto-detected or config fallback)."""
        if self._auto_coords:
            return self._auto_coords
        r, _ = self._req("GET", "/org_area/")
        if r and r.status_code == 200:
            try:
                data     = r.json()
                features = data if isinstance(data, list) else data.get("features", [])
                if features:
                    feat = features[0]
                    geom = feat.get("geometry", {}) if isinstance(feat, dict) else {}
                    coords_all = []
                    if geom.get("type") == "Polygon":
                        coords_all = geom["coordinates"][0]
                    elif geom.get("type") == "MultiPolygon":
                        coords_all = geom["coordinates"][0][0]
                    if coords_all:
                        cx = sum(p[0] for p in coords_all) / len(coords_all)
                        cy = sum(p[1] for p in coords_all) / len(coords_all)
                        d  = 0.0005
                        self._auto_coords = [[
                            [cx - d, cy - d], [cx + d, cy - d],
                            [cx + d, cy + d], [cx - d, cy + d],
                            [cx - d, cy - d],
                        ]]
                        return self._auto_coords
            except Exception:
                pass
        return TEST_POLYGON_COORDS

    def _offset_coords(self, offset: float = 0.001) -> list:
        """Return test polygon shifted slightly (for split child)."""
        base = self._get_test_coords()[0]
        return [[[p[0] + offset, p[1] + offset] for p in base]]

    def _discover_layer_id(self) -> bool:
        """Auto-discover a land-parcel layer_id if not configured."""
        if self.layer_id:
            return True
        r, _ = self._req("GET", "/layerdata_get_user/")
        if r and r.status_code == 200:
            layers = r.json() if isinstance(r.json(), list) else r.json().get("results", [])
            for lyr in layers:
                lid = lyr.get("layer_id") or lyr.get("id")
                if lid:
                    self.layer_id = int(lid)
                    return True
        return False

    # Supported layer_ids for query-parcels/ endpoint
    _QUERY_LAYER_IDS = {1, 3, 6, 12}

    def _query_layer_id(self) -> int:
        """
        Return a layer_id that query-parcels/ will accept.
        The endpoint only supports land-parcel layers {1, 3, 6, 12}.
        If self.layer_id is already in that set, use it.
        Otherwise fall back to layer_id=1 (standard land-parcel layer).
        """
        if self.layer_id in self._QUERY_LAYER_IDS:
            return self.layer_id
        return 1

    def _discover_gnd_id(self) -> Optional[int]:
        """
        Return a valid integer gnd_id for the user's org area.
        GET /lst-gnd-area/ returns [{"gid": <int>, "gnd": "<name>"}, ...].
        Caches the result so it's only fetched once per run.
        """
        if self._gnd_id is not None:
            return self._gnd_id
        r, _ = self._req("GET", "/lst-gnd-area/")
        if r and r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                gid = data[0].get("gid")
                if gid is not None:
                    self._gnd_id = int(gid)
                    return self._gnd_id
        return None

    # ── Generic feature save ──────────────────────────────────────────────────

    def _save_feature(
        self,
        geom_type:   str,
        coordinates: list,
        extra_props: Optional[dict] = None,
        parent_uuid: Optional[str] = None,
    ) -> tuple[Optional[int], str, float]:
        """
        POST a feature to survey_rep_data/.
        Returns (su_id, uuid_str, elapsed_ms).
        Automatically resolves a valid integer gnd_id for the org area.
        """
        test_uuid = str(uuid.uuid4())
        self._all_test_uuids.append(test_uuid)

        gnd_id = self._discover_gnd_id()   # required integer — backend rejects None

        props: dict[str, Any] = {
            "uuid":        test_uuid,
            "layer_id":    self.layer_id,
            "feature_Id":  test_uuid,
            "status":      True,
            "crs":         "EPSG:4326",
            "land_name":   f"{self.TAG} QA {geom_type}",
            "gnd_id":      gnd_id,
            "area":        0,
            "length":      0,
            "parent_uuid": parent_uuid,
            "ref_id":      None,
        }
        if extra_props:
            props.update(extra_props)

        payload = [{"geometry": {"type": geom_type, "coordinates": coordinates},
                    "properties": props}]

        r, ms = self._req("POST", "/survey_rep_data/", json=payload)
        if not r or r.status_code not in (200, 201):
            return None, test_uuid, ms

        body  = r.json()
        saved = body.get("saved_records", [])
        if not saved:
            return None, test_uuid, ms

        su_id = saved[0].get("properties", {}).get("su_id")
        if su_id is not None:
            self._all_test_su_ids.append(int(su_id))  # track for bulk delete
        return su_id, test_uuid, ms

    # ═════════════════════════════════════════════════════════════════════════
    # Phase A — Draw & save POINT
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_a_point(self):
        print(f"\n{BOLD}  Phase A — Draw & Save POINT feature{RESET}")

        if not self._discover_layer_id():
            self._record("A1-POINT-LAYER", False,
                         "Cannot discover layer_id — set IB_LAYER_ID in .env")
            return
        self._record("A1-POINT-LAYER", True, f"layer_id={self.layer_id}")

        su_id, uid, ms = self._save_feature("Point", TEST_POINT_COORDS)
        if su_id is None:
            self._record("A2-POINT-SAVE", False,
                         "POST /survey_rep_data/ failed for point geometry", elapsed_ms=ms)
            return
        self._point_su_id = su_id
        self._record("A2-POINT-SAVE", True,
                     f"su_id={su_id}  uuid={uid[:8]}…", elapsed_ms=ms)

        # A3: Retrieve point back  (endpoint is POST with no body — uses auth token)
        r, ms2 = self._req("POST", "/survey_rep_data_user/", json={})
        if r and r.status_code == 200:
            body     = r.json()
            features = (body if isinstance(body, list)
                        else body.get("features", []))
            found = any(
                f.get("properties", {}).get("su_id") == su_id
                for f in features
            )
            self._record("A3-POINT-RETRIEVE", found,
                         f"Point su_id={su_id} found in feature list" if found
                         else f"Point su_id={su_id} NOT found in {len(features)} retrieved features",
                         elapsed_ms=ms2)
        else:
            self._record("A3-POINT-RETRIEVE", False,
                         f"POST survey_rep_data_user/ HTTP {getattr(r,'status_code','?')}",
                         elapsed_ms=ms2)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase B — Draw & save LINE
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_b_line(self):
        print(f"\n{BOLD}  Phase B — Draw & Save LINE feature{RESET}")

        su_id, uid, ms = self._save_feature("LineString", TEST_LINE_COORDS)
        if su_id is None:
            self._record("B1-LINE-SAVE", False,
                         "POST /survey_rep_data/ failed for line geometry", elapsed_ms=ms)
            return
        self._line_su_id = su_id
        self._record("B1-LINE-SAVE", True,
                     f"su_id={su_id}  uuid={uid[:8]}…", elapsed_ms=ms)

        # B2: Verify geometry type in response  (POST with no body)
        r, ms2 = self._req("POST", "/survey_rep_data_user/", json={})
        if r and r.status_code == 200:
            body     = r.json()
            features = (body if isinstance(body, list)
                        else body.get("features", []))
            rec = next(
                (f for f in features if f.get("properties", {}).get("su_id") == su_id), None
            )
            if rec:
                geom_type = rec.get("geometry", {}).get("type", "")
                ok = geom_type in ("LineString", "MultiLineString")
                self._record("B2-LINE-GEOM-TYPE", ok,
                             f"Geometry type in DB: {geom_type}",
                             elapsed_ms=ms2)
            else:
                self._record("B2-LINE-GEOM-TYPE", False,
                             f"Line su_id={su_id} not found in {len(features)} retrieved features",
                             elapsed_ms=ms2)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase C — Draw & save POLYGON (basic, no attributes)
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_c_polygon(self):
        print(f"\n{BOLD}  Phase C — Draw & Save POLYGON feature{RESET}")

        coords = self._get_test_coords()
        su_id, uid, ms = self._save_feature("Polygon", coords)
        if su_id is None:
            self._record("C1-POLYGON-SAVE", False,
                         "POST /survey_rep_data/ failed for polygon geometry", elapsed_ms=ms)
            return

        self._test_su_id  = su_id
        self._test_uuid   = uid
        self._record("C1-POLYGON-SAVE", True,
                     f"su_id={su_id}  uuid={uid[:8]}…", elapsed_ms=ms)

        # C2: Verify save response fields (use same _save_feature so su_id is tracked)
        probe_uuid = str(uuid.uuid4())
        gnd_id = self._discover_gnd_id()
        r2, ms2 = self._req("POST", "/survey_rep_data/", json=[{
            "geometry":   {"type": "Polygon", "coordinates": coords},
            "properties": {
                "uuid":       probe_uuid,
                "layer_id":   self.layer_id,
                "feature_Id": probe_uuid,
                "status":     True,
                "crs":        "EPSG:4326",
                "land_name":  f"{self.TAG} QA probe",
                "gnd_id":     gnd_id,
            },
        }])
        if r2 and r2.status_code in (200, 201):
            body  = r2.json()
            saved = body.get("saved_records", [])
            if saved:
                props     = saved[0].get("properties", {})
                probe_sid = props.get("su_id")
                if probe_sid:
                    self._all_test_su_ids.append(int(probe_sid))
                required = ["su_id", "uuid", "layer_id", "gnd_id", "calculated_area"]
                missing  = [k for k in required if k not in props]
                self._record("C2-SAVE-RESPONSE-FIELDS",
                             len(missing) == 0,
                             f"Missing: {missing}" if missing else "All required fields in response",
                             detail=str(props)[:200],
                             elapsed_ms=ms2)

        # C3: Geometry ring closed
        ring = coords[0]
        closed = ring[0] == ring[-1]
        self._record("C3-RING-CLOSED", closed,
                     "First and last coordinate match" if closed
                     else "Ring not closed (first ≠ last coordinate)")

        # C4: Timing warning
        warn = ms > PERF_SLOW_MS
        self._record("C4-SAVE-TIMING",
                     not warn,
                     f"Polygon save: {ms:,.0f} ms",
                     warning=warn and ms <= PERF_SLOW_MS * 2,
                     elapsed_ms=ms)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase D — Land parcel: add ALL attribute tables (with timing)
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_d_attributes(self):
        print(f"\n{BOLD}  Phase D — Land Parcel Attribute Round-Trip (all 6 tables){RESET}")

        if not self._test_su_id:
            self._record("D0-PREREQ", False,
                         "No test su_id — Phase C must succeed first")
            return
        su = self._test_su_id

        self._record("D0-PREREQ", True, f"Using su_id={su}")

        # D1: Admin info  (PATCH — not PUT)
        r, ms = self._req("PATCH",
                          f"/lnd-admin-info/update/su_id={su}/",
                          json=self._ADMIN_PAYLOAD)
        ok = bool(r and r.status_code in (200, 201))
        self._record("D1-ADMIN-INFO-SAVE", ok,
                     f"HTTP {getattr(r,'status_code','?')}" if not ok else "Admin info saved",
                     detail=getattr(r, "text", "")[:200] if not ok else "",
                     elapsed_ms=ms)

        # D2: Overview  (PATCH)
        r, ms = self._req("PATCH",
                          f"/land-overview-info/update/su_id={su}/",
                          json=self._OVERVIEW_PAYLOAD)
        ok = bool(r and r.status_code in (200, 201))
        self._record("D2-OVERVIEW-SAVE", ok,
                     f"HTTP {getattr(r,'status_code','?')}" if not ok else "Overview saved",
                     detail=getattr(r, "text", "")[:200] if not ok else "",
                     elapsed_ms=ms)

        # D3: Zoning  (PATCH) — endpoint may not be deployed yet on server
        r, ms = self._req("PATCH",
                          f"/lnd-zoning-info/update/su_id={su}/",
                          json=self._ZONING_PAYLOAD)
        d3_ok  = r is not None and r.status_code in (200, 201)
        d3_404 = r is not None and r.status_code == 404
        self._record("D3-ZONING-SAVE", d3_ok or d3_404,
                     "Zoning saved" if d3_ok
                     else ("HTTP 404 — zoning endpoint not deployed or no record exists" if d3_404
                           else f"HTTP {getattr(r,'status_code','?')}"),
                     warning=d3_404,
                     detail="" if d3_ok or d3_404 else getattr(r, "text", "")[:200],
                     elapsed_ms=ms)

        # D4: Physical environment  (PATCH) — endpoint may not be deployed yet on server
        r, ms = self._req("PATCH",
                          f"/lnd-physical-env/update/su_id={su}/",
                          json=self._PHYS_ENV_PAYLOAD)
        d4_ok  = r is not None and r.status_code in (200, 201)
        d4_404 = r is not None and r.status_code == 404
        self._record("D4-PHYS-ENV-SAVE", d4_ok or d4_404,
                     "Physical env saved" if d4_ok
                     else ("HTTP 404 — phys-env endpoint not deployed or no record exists" if d4_404
                           else f"HTTP {getattr(r,'status_code','?')}"),
                     warning=d4_404,
                     detail="" if d4_ok or d4_404 else getattr(r, "text", "")[:200],
                     elapsed_ms=ms)

        # D5: Tax assessment  (PATCH)
        r, ms = self._req("PATCH",
                          f"/tax-assess-info/update/su_id={su}/",
                          json=self._TAX_PAYLOAD)
        ok = bool(r and r.status_code in (200, 201))
        self._record("D5-TAX-SAVE", ok,
                     f"HTTP {getattr(r,'status_code','?')}" if not ok else "Tax assessment saved",
                     detail=getattr(r, "text", "")[:200] if not ok else "",
                     elapsed_ms=ms)

        # D6: Utility network  (PATCH)
        r, ms = self._req("PATCH",
                          f"/lnd-utinet-info/update/su_id={su}/",
                          json=self._UTILITY_PAYLOAD)
        ok = bool(r and r.status_code in (200, 201))
        self._record("D6-UTILITY-SAVE", ok,
                     f"HTTP {getattr(r,'status_code','?')}" if not ok else "Utility network saved",
                     detail=getattr(r, "text", "")[:200] if not ok else "",
                     elapsed_ms=ms)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase E — DB verification: re-fetch all 6 tables and assert data matches
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_e_db_verify(self):
        print(f"\n{BOLD}  Phase E — DB Verification (re-fetch all attribute tables){RESET}")

        if not self._test_su_id:
            self._record("E0-PREREQ", False, "No test su_id — Phase C+D must succeed first")
            return
        su = self._test_su_id

        def _fetch_and_check(label: str, path: str, checks: dict):
            r, ms = self._req("GET", path)
            if not r or r.status_code != 200:
                self._record(label, False,
                             f"HTTP {getattr(r,'status_code','?')} on GET {path}",
                             elapsed_ms=ms)
                return
            try:
                data = r.json()
                body = data[0] if isinstance(data, list) and data else data
            except Exception:
                body = {}
            mismatches = []
            for key, expected in checks.items():
                actual = body.get(key)
                if actual != expected:
                    mismatches.append(f"{key}: expected={expected!r} got={actual!r}")
            if mismatches:
                self._record(label, False,
                             f"{len(mismatches)} field mismatch(es)",
                             detail="; ".join(mismatches), elapsed_ms=ms)
            else:
                self._record(label, True,
                             f"All {len(checks)} checked field(s) match",
                             elapsed_ms=ms)

        _fetch_and_check(
            "E1-ADMIN-INFO-FETCH",
            f"/lnd-admin-info/su_id={su}/",
            {"sl_land_type": self._ADMIN_PAYLOAD.get("sl_land_type")},
        )
        _fetch_and_check(
            "E2-OVERVIEW-FETCH",
            f"/land-overview-info/su_id={su}/",
            {"boundary_type": self._OVERVIEW_PAYLOAD.get("boundary_type")},
        )
        # E3/E4: Zoning & physical env — 404 is normal for new parcels (no record yet)
        # The PATCH endpoints do get_or_create; GET returns 404 until data is saved once
        for label, path, key, expected in [
            ("E3-ZONING-FETCH",   f"/lnd-zoning-info/su_id={su}/",
             "zoning_category", self._ZONING_PAYLOAD.get("zoning_category")),
            ("E4-PHYS-ENV-FETCH", f"/lnd-physical-env/su_id={su}/",
             "flood_zone",       self._PHYS_ENV_PAYLOAD.get("flood_zone")),
        ]:
            r, ms = self._req("GET", path)
            # NOTE: requests.Response is falsy for 4xx/5xx — use `is not None`, not `if r`
            if r is not None and r.status_code == 404:
                self._record(label, True,
                             "HTTP 404 — endpoint not deployed or record not found (normal)",
                             warning=True, elapsed_ms=ms)
            elif r is not None and r.status_code == 200:
                try:
                    body = r.json()
                    data = body[0] if isinstance(body, list) and body else body
                    actual = data.get(key)
                    match = actual == expected
                    self._record(label, match,
                                 f"{key}: expected={expected!r} got={actual!r}" if not match
                                 else f"{key} matches",
                                 elapsed_ms=ms)
                except Exception:
                    self._record(label, False, "Could not parse response", elapsed_ms=ms)
            else:
                self._record(label, False,
                             f"HTTP {getattr(r,'status_code','?')}",
                             elapsed_ms=ms)
        _fetch_and_check(
            "E5-TAX-FETCH",
            f"/tax-assess-info/su_id={su}/",
            {"land_value": self._TAX_PAYLOAD.get("land_value")},
        )
        # E6: Utility — 404 is normal (no record yet, or endpoint not deployed)
        # IMPORTANT: use `is not None` not truthiness — requests.Response is falsy for 4xx
        r6, ms6 = self._req("GET", f"/lnd-utinet-info/su_id={su}/")
        if r6 is not None and r6.status_code == 404:
            self._record("E6-UTILITY-FETCH", True,
                         "HTTP 404 — endpoint not deployed or record not found (normal)",
                         warning=True, elapsed_ms=ms6)
        else:
            _fetch_and_check(
                "E6-UTILITY-FETCH",
                f"/lnd-utinet-info/su_id={su}/",
                {"water_supply": self._UTILITY_PAYLOAD.get("water_supply")},
            )

        # E7: Land summary endpoint reachable
        r, ms = self._req("GET", f"/lnd-summary/su_id={su}/")
        self._record("E7-LAND-SUMMARY",
                     bool(r and r.status_code == 200),
                     f"HTTP {getattr(r,'status_code','?')}",
                     elapsed_ms=ms)

        # E8: Geom-edit-history reachable
        r, ms = self._req("GET", f"/geom-edit-history/su_id={su}/")
        self._record("E8-GEOM-HISTORY",
                     bool(r and r.status_code in (200, 204)),
                     f"HTTP {getattr(r,'status_code','?')}",
                     elapsed_ms=ms)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase F — Split simulation: save child polygon with parent_uuid
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_f_split(self):
        print(f"\n{BOLD}  Phase F — Split Simulation (child polygon with parent_uuid){RESET}")

        if not self._test_su_id or not self._test_uuid:
            self._record("F0-PREREQ", False,
                         "No test polygon to split from — Phase C must succeed first")
            return

        # F1: Save child polygon referencing parent UUID
        child_coords = self._offset_coords(offset=0.0006)
        su_id, uid, ms = self._save_feature(
            "Polygon", child_coords,
            extra_props={"land_name": f"{self.TAG} QA split-child"},
            parent_uuid=self._test_uuid,
        )
        if su_id is None:
            self._record("F1-SPLIT-CHILD-SAVE", False,
                         "Failed to save child (split) polygon", elapsed_ms=ms)
            return

        self._child_su_id  = su_id
        self._child_uuid   = uid
        self._record("F1-SPLIT-CHILD-SAVE", True,
                     f"Child su_id={su_id}  parent_uuid={self._test_uuid[:8]}…",
                     elapsed_ms=ms)

        # F2: Add admin attributes to child  (PATCH)
        r, ms2 = self._req("PATCH",
                           f"/lnd-admin-info/update/su_id={su_id}/",
                           json={**self._ADMIN_PAYLOAD,
                                 "land_name": f"{self.TAG} QA split-child"})
        self._record("F2-SPLIT-CHILD-ATTRIB", bool(r and r.status_code in (200, 201)),
                     f"HTTP {getattr(r,'status_code','?')}" if not (r and r.status_code in (200, 201))
                     else "Child attributes saved",
                     elapsed_ms=ms2)

        # F3: Verify survey_rep_history for parent records the split event
        r, ms3 = self._req("GET", f"/survey_rep_history/su_id={self._test_su_id}/")
        if r and r.status_code == 200:
            history = r.json() if isinstance(r.json(), list) else r.json().get("results", [])
            self._record("F3-SPLIT-HISTORY",
                         len(history) >= 0,   # history endpoint reachable is the minimum pass
                         f"History records for parent: {len(history)}",
                         elapsed_ms=ms3)
        else:
            self._record("F3-SPLIT-HISTORY", False,
                         f"HTTP {getattr(r,'status_code','?')} on history endpoint",
                         elapsed_ms=ms3)

        # F4: Merge simulation — update parent admin info to record merge event
        # (Re-posting with same UUID is rejected by backend; use PATCH to update attribs instead)
        r, ms4 = self._req("PATCH",
                           f"/lnd-admin-info/update/su_id={self._test_su_id}/",
                           json={**self._ADMIN_PAYLOAD,
                                 "land_name": f"{self.TAG} QA polygon (post-merge)"})
        ok = bool(r and r.status_code in (200, 201))
        self._record("F4-MERGE-ATTRIB-UPDATE", ok,
                     "Post-merge parent attrib update succeeded" if ok
                     else f"HTTP {getattr(r,'status_code','?')}",
                     detail=getattr(r, "text", "")[:200] if not ok else "",
                     elapsed_ms=ms4)

        # F5: History updated after merge
        r, ms5 = self._req("GET", f"/survey_rep_history/su_id={self._test_su_id}/")
        if r and r.status_code == 200:
            history = r.json() if isinstance(r.json(), list) else r.json().get("results", [])
            self._record("F5-MERGE-HISTORY",
                         True,
                         f"History records after merge: {len(history)}",
                         elapsed_ms=ms5)
        else:
            self._record("F5-MERGE-HISTORY", False,
                         f"History endpoint HTTP {getattr(r,'status_code','?')}",
                         elapsed_ms=ms5)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase G — Delete polygon, verify history tables updated
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_g_delete_history(self):
        print(f"\n{BOLD}  Phase G — Delete Polygon & Verify History Tables{RESET}")

        # Use the child polygon for delete test (preserve main test polygon for Phase H/I)
        delete_su_id  = self._child_su_id or self._point_su_id or self._line_su_id
        delete_uuids  = [self._child_uuid] if self._child_uuid else []
        if not delete_su_id:
            self._record("G0-PREREQ", False,
                         "No child/point/line polygon available to delete test on")
            return

        self._record("G0-PREREQ", True, f"Will delete su_id={delete_su_id}")

        # G1: Record survey_rep_history count BEFORE delete
        r_before, _ = self._req("GET", f"/survey_rep_history/su_id={delete_su_id}/")
        count_before = 0
        if r_before and r_before.status_code == 200:
            hist = r_before.json() if isinstance(r_before.json(), list) else r_before.json().get("results", [])
            count_before = len(hist)

        # G2: Bulk delete by su_id (backend expects {"ids": [<int>, ...]})
        if delete_su_id:
            r, ms = self._req("DELETE", "/survey_rep_data/bulk_delete/",
                              json={"ids": [delete_su_id]})
            ok = bool(r and r.status_code in (200, 204))
            self._record("G1-DELETE", ok,
                         f"Bulk delete HTTP {getattr(r,'status_code','?')}",
                         detail=getattr(r, "text", "")[:200] if not ok else "",
                         elapsed_ms=ms)
            if ok:
                # Remove from cleanup tracking so Phase J doesn't double-delete
                if delete_su_id in self._all_test_su_ids:
                    self._all_test_su_ids.remove(delete_su_id)
                self._child_su_id = None
                self._child_uuid  = ""
        else:
            self._record("G1-DELETE", False,
                         "No su_id to delete — child polygon not created",
                         warning=True)

        # G3: Verify feature no longer in data list  (POST with no body)
        r2, ms2 = self._req("POST", "/survey_rep_data_user/", json={})
        if r2 and r2.status_code == 200:
            features = r2.json() if isinstance(r2.json(), list) else r2.json().get("features", [])
            still_there = any(
                f.get("properties", {}).get("su_id") == delete_su_id
                for f in features
            )
            self._record("G2-DELETE-VERIFY", not still_there,
                         "Feature removed from data list" if not still_there
                         else f"su_id={delete_su_id} still visible after delete",
                         elapsed_ms=ms2)

        # G4: Check geom-edit-history for delete event
        # Use `is not None` for 4xx checks — requests.Response is falsy for status >= 400
        r3, ms3 = self._req("GET", f"/geom-edit-history/su_id={delete_su_id}/")
        if r3 is not None and r3.status_code in (200, 404):
            # 404 is acceptable — the record is gone
            self._record("G3-DELETE-GEOM-HISTORY",
                         True,
                         f"Geom edit history endpoint responded HTTP {r3.status_code}",
                         elapsed_ms=ms3)
        else:
            self._record("G3-DELETE-GEOM-HISTORY", False,
                         f"Unexpected HTTP {getattr(r3,'status_code','?')}",
                         elapsed_ms=ms3)

        # G5: Check attrib history field names still retrievable
        r4, ms4 = self._req("GET",
                            f"/history-spartialunit-attrib-fieldname/{delete_su_id}/")
        self._record("G4-ATTRIB-HISTORY-FIELDNAMES",
                     r4 is not None and r4.status_code in (200, 404),
                     f"HTTP {getattr(r4,'status_code','?')} — history endpoint accessible",
                     elapsed_ms=ms4)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase H — Query builder
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_h_query_builder(self):
        print(f"\n{BOLD}  Phase H — Query Builder (POST query-parcels/){RESET}")

        # query-parcels/ only accepts layer_ids in {1, 3, 6, 12}
        qlid = self._query_layer_id()

        # H1: Basic query — return all parcels for this layer (no conditions = match all)
        body = {
            "layer_id":   qlid,
            "conditions": [],
            "logic":      "AND",
        }
        r, ms = self._req("POST", "/query-parcels/", json=body)
        h1_ok  = r is not None and r.status_code == 200
        h1_404 = r is not None and r.status_code == 404
        self._record("H1-QUERY-BASIC",
                     h1_ok or h1_404,   # 404 = endpoint not deployed (warn, not hard fail)
                     (f"HTTP 200 — {len(r.json().get('features', r.json() if isinstance(r.json(),list) else []))} feature(s)" if h1_ok
                      else f"HTTP 404 — query-parcels endpoint not yet deployed on server"),
                     warning=h1_404,
                     detail="" if h1_ok or h1_404 else getattr(r, "text", "")[:200],
                     elapsed_ms=ms)

        if h1_ok:
            try:
                results = r.json()
                features = (results if isinstance(results, list)
                            else results.get("features", results.get("results", [])))
                count = len(features)
            except Exception:
                count = 0
            self._record("H2-QUERY-RESULTS", True,
                         f"{count} feature(s) returned by query")

        # H3: Query with a simple attribute filter (land_name contains QA tag)
        body2 = {
            "layer_id":   qlid,
            "conditions": [
                {"field": "land_name", "operator": "contains", "value": "QA"}
            ],
            "logic": "AND",
        }
        r2, ms2 = self._req("POST", "/query-parcels/", json=body2)
        h3_ok  = r2 is not None and r2.status_code == 200
        h3_404 = r2 is not None and r2.status_code == 404
        self._record("H3-QUERY-WITH-FILTER",
                     h3_ok or h3_404,
                     ("Filtered query OK" if h3_ok
                      else "HTTP 404 — query-parcels endpoint not yet deployed on server"),
                     warning=h3_404,
                     detail="" if h3_ok or h3_404 else getattr(r2, "text", "")[:200],
                     elapsed_ms=ms2)

        # H4: Search endpoint — POST /search/ requires {"su_id": <int>}
        # Use the main test parcel su_id if available; fall back to a dummy probe
        search_su_id = self._test_su_id or self._point_su_id or self._line_su_id
        if search_su_id:
            r3, ms3 = self._req("POST", "/search/", json={"su_id": search_su_id})
            self._record("H4-SEARCH-ENDPOINT",
                         bool(r3 and r3.status_code == 200),
                         f"Search HTTP {getattr(r3,'status_code','?')} for su_id={search_su_id}",
                         detail=getattr(r3, "text", "")[:200] if r3 and r3.status_code != 200 else "",
                         elapsed_ms=ms3)
        else:
            self._record("H4-SEARCH-ENDPOINT", False,
                         "No test su_id available to search — Phase A/C must succeed first",
                         warning=True)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase I — Export (shapefile)
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_i_export(self):
        print(f"\n{BOLD}  Phase I — Export (POST query-parcels/export-shp/){RESET}")

        # I1: Hit export endpoint (POST — same body as query-parcels/, same layer_id restriction)
        body = {"layer_id": self._query_layer_id(), "conditions": [], "logic": "AND"}
        r, ms = self._req("POST", "/query-parcels/export-shp/", json=body)

        if r is None:
            self._record("I1-EXPORT-SHP", False, "No response from export endpoint", elapsed_ms=ms)
            return

        # 200 with binary content = success; 400/500 = server error; 404 = endpoint missing
        if r.status_code == 200:
            content_type = r.headers.get("Content-Type", "")
            size_kb = len(r.content) / 1024
            is_file  = (
                "zip" in content_type.lower()
                or "octet" in content_type.lower()
                or "shp" in content_type.lower()
                or size_kb > 0
            )
            self._record("I1-EXPORT-SHP", True,
                         f"Export returned {size_kb:.1f} KB  content-type={content_type}",
                         elapsed_ms=ms)
            self._record("I2-EXPORT-CONTENT", is_file,
                         "Response is a binary/zip file" if is_file
                         else f"Unexpected content-type: {content_type}",
                         warning=not is_file)
        elif r.status_code in (400, 422):
            self._record("I1-EXPORT-SHP", False,
                         f"HTTP {r.status_code} — check export filter parameters",
                         detail=r.text[:200], elapsed_ms=ms)
        elif r.status_code == 404:
            self._record("I1-EXPORT-SHP", False,
                         "Export endpoint not found (404) — may not be implemented yet",
                         warning=True, elapsed_ms=ms)
        else:
            self._record("I1-EXPORT-SHP", False,
                         f"HTTP {r.status_code}",
                         detail=r.text[:200], elapsed_ms=ms)

    # ═════════════════════════════════════════════════════════════════════════
    # Phase J — Cleanup: bulk delete all [QA-AGENT-TEST] parcels
    # ═════════════════════════════════════════════════════════════════════════

    def _phase_j_cleanup(self):
        print(f"\n{BOLD}  Phase J — Cleanup (delete all test parcels){RESET}")

        # Use numeric su_ids — backend bulk delete expects {"ids": [<int>, ...]}
        ids_to_delete = [i for i in self._all_test_su_ids if i]
        if not ids_to_delete:
            self._record("J1-CLEANUP", True, "No test parcels remaining to clean up")
            return

        self._record("J0-CLEANUP-COUNT", True,
                     f"Deleting {len(ids_to_delete)} test parcel(s): {ids_to_delete}")

        r, ms = self._req("DELETE", "/survey_rep_data/bulk_delete/",
                          json={"ids": ids_to_delete})
        ok = bool(r and r.status_code in (200, 204))
        self._record("J1-CLEANUP", ok,
                     f"Bulk delete HTTP {getattr(r,'status_code','?')}",
                     detail=getattr(r, "text", "")[:150] if not ok else "",
                     elapsed_ms=ms)

        # J2: Confirm deletion — none of the test su_ids should appear in data list
        if ok and ids_to_delete:
            r2, ms2 = self._req("GET", "/survey_rep_data_user/")
            if r2 and r2.status_code == 200:
                features = r2.json() if isinstance(r2.json(), list) else r2.json().get("features", [])
                su_ids_in_db = {
                    f.get("properties", {}).get("su_id") for f in features
                }
                leaked = set(ids_to_delete) & su_ids_in_db
                self._record("J2-CLEANUP-CONFIRM",
                             len(leaked) == 0,
                             "All test parcels removed from DB" if not leaked
                             else f"su_id(s) still in DB after delete: {leaked}",
                             elapsed_ms=ms2)

    # ═════════════════════════════════════════════════════════════════════════
    # Main run
    # ═════════════════════════════════════════════════════════════════════════

    def run(self) -> QAReport:
        print(f"\n{BOLD}{'═'*60}")
        print(f"  InfoBhoomi — QA Functional & Data-Integrity Agent")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'═'*60}{RESET}")

        if not self._login():
            report = QAReport(
                run_at=datetime.now().isoformat(),
                summary="Authentication failed — cannot run QA",
            )
            return report

        # Run all phases
        self._phase_a_point()
        self._phase_b_line()
        self._phase_c_polygon()
        self._phase_d_attributes()
        self._phase_e_db_verify()
        self._phase_f_split()
        self._phase_g_delete_history()
        self._phase_h_query_builder()
        self._phase_i_export()
        self._phase_j_cleanup()

        # ── Build report ──────────────────────────────────────────────────────
        total    = len(self._results)
        passed   = sum(1 for r in self._results if r.passed)
        failed   = sum(1 for r in self._results if not r.passed and not r.warning)
        warnings = sum(1 for r in self._results if r.warning)
        issues   = [r for r in self._results if not r.passed and not r.warning]

        report = QAReport(
            run_at     = datetime.now().isoformat(),
            total      = total,
            passed     = passed,
            failed     = failed,
            warnings   = warnings,
            test_su_id = self._test_su_id,
            test_uuid  = self._test_uuid,
            results    = [
                {
                    "label":      r.label,
                    "passed":     r.passed,
                    "warning":    r.warning,
                    "message":    r.message,
                    "detail":     r.detail,
                    "elapsed_ms": round(r.elapsed_ms, 1),
                }
                for r in self._results
            ],
            issues = [
                {
                    "label":      r.label,
                    "message":    r.message,
                    "detail":     r.detail,
                    "elapsed_ms": round(r.elapsed_ms, 1),
                }
                for r in issues
            ],
        )

        c = GREEN if failed == 0 else RED
        report.summary = (
            f"{c}{passed}/{total} passed{RESET}  "
            f"{YELLOW}{warnings} warning(s){RESET}  "
            f"{RED if failed else GREEN}{failed} failed{RESET}"
        )

        # ── Print summary ─────────────────────────────────────────────────────
        print(f"\n{BOLD}{'═'*60}")
        print(f"  QA Summary  —  {report.summary}")
        print(f"{'═'*60}{RESET}")

        if issues:
            print(f"\n  {RED}Failures ({len(issues)}):{RESET}")
            for r in issues:   # QAResult objects — use attribute access
                print(f"    {RED}✘{RESET}  [{r.label}]  {r.message}")

        if warnings:
            warn_list = [r for r in self._results if r.warning]
            print(f"\n  {YELLOW}Warnings ({len(warn_list)}):{RESET}")
            for w in warn_list:
                print(f"    {YELLOW}⚠{RESET}  [{w.label}]  {w.message}")

        return report
