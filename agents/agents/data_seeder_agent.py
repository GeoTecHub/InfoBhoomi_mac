"""
InfoBhoomi Data Seeder Agent
============================
Scans all land parcels, buildings and apartment units in the system, identifies
which ones are missing attribute data, fills them with realistic generated
values, and reports a full summary of what was filled and what failed.

Usage:
    python seed_data.py                  # fill all missing data
    python seed_data.py --dry-run        # report what's missing without writing
    python seed_data.py --layer 1        # only process a specific layer_id
    python seed_data.py --limit 50       # cap at 50 features (spread across types)
    python seed_data.py --force          # re-fill even parcels that already have data
    python seed_data.py --rrr            # also create RRR records (needs party pool)
    python seed_data.py --no-verify      # skip read-back verification

Land layers   : 1, 6   (6 attribute tables each)
Building layers: 3     (3 attribute tables)
Unit layers   : 12     (3 attribute tables — same bld-* endpoints, unit payload)

Every generated payload uses ONLY the field names each backend update view
whitelists (see user/views/land.py and user/views/building.py). After each
PATCH the key field is read back (unless --no-verify) so writes that the API
silently rejected — e.g. when the seed user's role lacks edit permission — are
reported as 'not persisted' instead of being miscounted as 'filled'.
"""

from __future__ import annotations

import os
import sys
import time
import random
import requests
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

# ── Load .env ─────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE_URL   = os.getenv("IB_BASE_URL", "http://127.0.0.1:8000/api/user").rstrip("/")
IB_TOKEN   = os.getenv("IB_TOKEN", "")
IB_USER    = os.getenv("IB_USERNAME", "admin_bw")
IB_PASS    = os.getenv("IB_PASSWORD", "")

LAND_LAYER_IDS     = {1, 6}
BUILDING_LAYER_IDS = {3}
UNIT_LAYER_IDS     = {12}   # apartment / strata units — sub-units of buildings

# ── RRR tenure type cycle (su_id % 5) ─────────────────────────────────────────
_TENURE_FULL_OWN  = 0   # single owner, 100%
_TENURE_CO_OWN    = 1   # two co-owners, 50/50
_TENURE_GOVT      = 2   # government entity, 100%
_TENURE_LEASE     = 3   # lease with start/end dates
_TENURE_MORTGAGE  = 4   # ownership + mortgage block

# ── Colour helpers ─────────────────────────────────────────────────────────────
BOLD  = "\033[1m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
RED   = "\033[91m"
CYAN  = "\033[96m"
RESET = "\033[0m"

def _ok(msg):    print(f"  {GREEN}✔{RESET}  {msg}")
def _skip(msg):  print(f"  {YELLOW}–{RESET}  {msg}")
def _err(msg):   print(f"  {RED}✘{RESET}  {msg}")
def _info(msg):  print(f"  {CYAN}·{RESET}  {msg}")

# ── Realistic data pools ───────────────────────────────────────────────────────

LAND_NAMES = [
    "Karunaratne Estate", "Perera Homestead", "Silva Garden",
    "Fernando Land", "Jayawardena Property", "Wickramasinghe Lot",
    "De Silva Holdings", "Bandara Field", "Gunawardena Plot",
    "Rajapaksha Parcel", "Dissanayake Land", "Wijesekara Estate",
    "Herath Grounds", "Kumarasinghe Plot", "Amarasinghe Property",
]

SL_LAND_TYPES   = ["Urban", "Semi-Urban", "Rural", "Suburban", "Agricultural"]
LAND_USES       = ["Residential", "Commercial", "Agricultural", "Industrial", "Mixed Use", "Recreational"]
BOUNDARY_TYPES  = ["Cadastral", "General Boundary", "Fixed Boundary"]
CRS_OPTIONS     = ["EPSG:4326", "EPSG:5235"]
ROAD_ACCESS     = ["Motorway", "A-Road", "B-Road", "Gravel Road", "No Road Access"]
ZONING_CATS     = ["Residential", "Commercial", "Industrial", "Agricultural", "Mixed Use", "Conservation"]
FLOOD_ZONES     = ["Low", "Medium", "High", "None"]
SOIL_TYPES      = ["Lateritic", "Alluvial", "Sandy", "Clay", "Loam", "Rocky"]
VEG_COVERS      = ["None", "Sparse", "Moderate", "Dense"]
ROOF_TYPES      = ["Tile", "Sheet", "Concrete", "Asbestos", "Thatch"]
WALL_TYPES      = ["Brick", "Concrete", "Cadjan", "Timber", "Stone"]
STRUCTURE_TYPES = ["CONC_REINF", "STEEL_FRM", "MASONRY", "TIMBER", "COMPOSITE"]
CONDITIONS      = ["EXCELLENT", "GOOD", "FAIR", "POOR"]
UTILITY_AVAIL   = ["Available", "Not Available", "Partial"]
TAX_STATUSES    = ["Paid", "Unpaid", "Exempt"]
TAX_TYPES       = ["Residential", "Commercial", "Industrial", "Vacant"]
BLD_PROP_TYPES  = ["Residential", "Commercial", "Industrial", "Mixed Use"]
BLD_USE_SUBTYPES = ["Single House", "Apartment Block", "Shop", "Office Block",
                    "Warehouse", "Factory", "Mixed Block"]


def _land_admin(su_id: int) -> dict:
    # Fields accepted by Lnd_Admin_Info_Update_View whitelist only.
    rng = random.Random(su_id * 7 + 1)
    return {
        "land_name":    rng.choice(LAND_NAMES),
        "sl_land_type": rng.choice(SL_LAND_TYPES),
        "access_road":  rng.choice(ROAD_ACCESS),
        "postal_ad_lnd": f"No. {rng.randint(1, 200)}, {rng.choice(['Kandy', 'Kurunegala', 'Matale', 'Gampola', 'Dambulla'])} Road",
    }

def _land_overview(su_id: int) -> dict:
    # Lnd_Overview_Update_View whitelist: boundary_type, crs, ext_landuse_type, …
    rng = random.Random(su_id * 13 + 2)
    return {
        "boundary_type":    rng.choice(BOUNDARY_TYPES),
        "crs":              rng.choice(CRS_OPTIONS),
        "ext_landuse_type": rng.choice(LAND_USES),
    }

def _land_zoning(su_id: int) -> dict:
    # Lnd_Zoning_Update_View whitelist uses a single setback_side (no left/right).
    rng = random.Random(su_id * 17 + 3)
    return {
        "zoning_category":     rng.choice(ZONING_CATS),
        "max_building_height": round(rng.uniform(6.0, 20.0), 1),
        "max_coverage":        round(rng.uniform(40.0, 75.0), 1),
        "max_far":             round(rng.uniform(0.5, 3.0), 1),
        "setback_front":       round(rng.uniform(1.0, 5.0), 1),
        "setback_rear":        round(rng.uniform(1.0, 4.0), 1),
        "setback_side":        round(rng.uniform(0.5, 3.0), 1),
    }

def _land_phys_env(su_id: int) -> dict:
    # Lnd_Physical_Env_Update_View whitelist: elevation, slope, soil_type, flood_zone, vegetation_cover
    rng = random.Random(su_id * 19 + 4)
    return {
        "elevation":        round(rng.uniform(30.0, 500.0), 1),
        "slope":            round(rng.uniform(0.5, 30.0), 1),
        "soil_type":        rng.choice(SOIL_TYPES),
        "flood_zone":       rng.choice(FLOOD_ZONES),
        "vegetation_cover": rng.choice(VEG_COVERS),
    }

def _land_tax(su_id: int) -> dict:
    # Tax_Assessment_Update_View whitelist: land_value, market_value,
    # assessment_annual_value, tax_annual_value, tax_type, tax_status, …
    rng = random.Random(su_id * 23 + 5)
    land_val   = round(rng.uniform(200_000, 5_000_000), 0)
    market_val = round(land_val * rng.uniform(1.1, 1.5), 0)
    assess_val = round(land_val * rng.uniform(0.8, 1.0), 0)
    return {
        "land_value":               land_val,
        "market_value":             market_val,
        "assessment_annual_value":  assess_val,
        "tax_annual_value":         round(assess_val * 0.015, 2),
        "tax_type":                 rng.choice(TAX_TYPES),
        "tax_status":               rng.choice(TAX_STATUSES),
    }

def _land_utility(su_id: int) -> dict:
    # Lnd_Utility_Network_Info_Update_View input keys: water_supply, electricity, drainage_system
    rng = random.Random(su_id * 29 + 6)
    return {
        "water_supply":   rng.choice(UTILITY_AVAIL),
        "electricity":    rng.choice(UTILITY_AVAIL),
        "drainage_system": rng.choice(UTILITY_AVAIL),
    }

def _bld_admin(su_id: int) -> dict:
    # Bld_Admin_Info_Update_View whitelist (no `hight`/`roof_type` here —
    # roof_type belongs to the overview endpoint, height is not editable).
    rng = random.Random(su_id * 11 + 10)
    return {
        "building_name":    f"Building {su_id}",
        "bld_property_type": rng.choice(BLD_PROP_TYPES),
        "access_road":      rng.choice(ROAD_ACCESS),
        "postal_ad_build":  f"No. {rng.randint(1, 200)}, {rng.choice(['Main', 'Church', 'Temple', 'Lake', 'Station'])} Road",
        "house_hold_no":    str(rng.randint(100, 9999)),
        "no_floors":        rng.randint(1, 10),
        "wall_type":        rng.choice(WALL_TYPES),
        "structure_type":   rng.choice(STRUCTURE_TYPES),
        "condition":        rng.choice(CONDITIONS),
        "construction_year": rng.randint(1960, 2024),
    }

def _bld_overview(su_id: int) -> dict:
    # Bld_Overview_Update_View whitelist: ext_builduse_type, ext_builduse_sub_type, roof_type, wall_type, area
    rng = random.Random(su_id * 31 + 11)
    return {
        "ext_builduse_type":     rng.choice(BLD_PROP_TYPES),
        "ext_builduse_sub_type": rng.choice(BLD_USE_SUBTYPES),
        "roof_type":             rng.choice(ROOF_TYPES),
        "wall_type":             rng.choice(WALL_TYPES),
    }

def _bld_utility(su_id: int) -> dict:
    # Bld_Utility update uses model-field keys: elec, water, drainage (NOT water_supply/electricity)
    rng = random.Random(su_id * 37 + 12)
    return {
        "elec":     rng.choice(UTILITY_AVAIL),
        "water":    rng.choice(UTILITY_AVAIL),
        "drainage": rng.choice(UTILITY_AVAIL),
    }

# Unit-level (apartment, layer_id=12) data generators
APT_USE_TYPES  = ["Residential", "Office", "Commercial", "Mixed"]
APT_DIV_TYPES  = ["Studio", "1BR", "2BR", "3BR", "Penthouse", "Duplex"]
FLOOR_TYPES    = ["Tile", "Parquet", "Concrete", "Marble", "Vinyl"]

def _unit_admin(su_id: int) -> dict:
    """Apartment/strata units (layer 12) hit the building admin endpoint, so the
    payload must match the Bld_Admin_Info_Update_View whitelist. Unit-only fields
    such as apt_name/floor_no/floor_area are not editable through this endpoint and
    are intentionally omitted (the backend would silently drop them)."""
    rng = random.Random(su_id * 53 + 20)
    floor_no = rng.randint(1, 15)
    return {
        "building_name":     f"Unit {floor_no}{chr(65 + rng.randint(0, 5))}-{su_id % 100:02d}",
        "bld_property_type": rng.choice(APT_USE_TYPES),
        "postal_ad_build":   f"Unit {floor_no}{chr(65 + rng.randint(0, 5))}",
        "house_hold_no":     str(rng.randint(100, 9999)),
        "no_floors":         1,
        "wall_type":         rng.choice(WALL_TYPES),
        "structure_type":    rng.choice(STRUCTURE_TYPES),
        "condition":         rng.choice(CONDITIONS),
        "construction_year": rng.randint(1990, 2024),
    }

def _unit_overview(su_id: int) -> dict:
    # Bld_Overview_Update_View whitelist (units share this endpoint).
    rng = random.Random(su_id * 59 + 21)
    return {
        "ext_builduse_type":     rng.choice(APT_USE_TYPES),
        "ext_builduse_sub_type": rng.choice(APT_DIV_TYPES),
        "roof_type":             rng.choice(ROOF_TYPES),
        "wall_type":             rng.choice(WALL_TYPES),
    }

def _unit_utility(su_id: int) -> dict:
    # Bld_Utility update keys: elec, water, drainage.
    rng = random.Random(su_id * 61 + 22)
    return {
        "elec":     rng.choice(UTILITY_AVAIL),
        "water":    rng.choice(UTILITY_AVAIL),
        "drainage": rng.choice(UTILITY_AVAIL),
    }


# ── Attribute table configs ────────────────────────────────────────────────────
# (name, get_url_template, patch_url_template, key_field, payload_fn)
LAND_TABLES = [
    ("Admin Info",    "/lnd-admin-info/su_id={su}/",          "/lnd-admin-info/update/su_id={su}/",        "sl_land_type",    _land_admin),
    ("Overview",      "/land-overview-info/su_id={su}/",      "/land-overview-info/update/su_id={su}/",    "boundary_type",   _land_overview),
    ("Zoning",        "/lnd-zoning-info/su_id={su}/",         "/lnd-zoning-info/update/su_id={su}/",       "zoning_category", _land_zoning),
    ("Physical Env",  "/lnd-physical-env/su_id={su}/",        "/lnd-physical-env/update/su_id={su}/",      "flood_zone",      _land_phys_env),
    ("Tax",           "/tax-assess-info/su_id={su}/",         "/tax-assess-info/update/su_id={su}/",       "land_value",      _land_tax),
    ("Utility",       "/lnd-utinet-info/su_id={su}/",         "/lnd-utinet-info/update/su_id={su}/",       "water_supply",    _land_utility),
]

BUILDING_TABLES = [
    ("Admin Info",  "/bld-admin-info/su_id={su}/",      "/bld-admin-info/update/su_id={su}/",    "building_name",     _bld_admin),
    ("Overview",    "/bld-overview-info/su_id={su}/",   "/bld-overview-info/update/su_id={su}/", "ext_builduse_type", _bld_overview),
    ("Utility",     "/bld-utinet-info/su_id={su}/",     "/bld-utinet-info/update/su_id={su}/",   "water",             _bld_utility),
]

# Apartment units reuse the same bld-admin / bld-overview / bld-utinet endpoints
# (same la_ls_build_unit / la_ls_utinet_bu tables) with unit-specific payloads
UNIT_TABLES = [
    ("Unit Admin",    "/bld-admin-info/su_id={su}/",      "/bld-admin-info/update/su_id={su}/",    "building_name",     _unit_admin),
    ("Unit Overview", "/bld-overview-info/su_id={su}/",   "/bld-overview-info/update/su_id={su}/", "ext_builduse_type", _unit_overview),
    ("Unit Utility",  "/bld-utinet-info/su_id={su}/",     "/bld-utinet-info/update/su_id={su}/",   "water",             _unit_utility),
]


# ── Result tracking ────────────────────────────────────────────────────────────
@dataclass
class SeederResult:
    total_land:      int = 0
    total_buildings: int = 0
    total_units:     int = 0   # apartment/strata units (layer_id=12)
    land_filled:     int = 0
    bld_filled:      int = 0
    unit_filled:     int = 0
    land_skipped:    int = 0   # already had data
    bld_skipped:     int = 0
    unit_skipped:    int = 0
    unverified:      int = 0    # PATCH returned 200 but value did not persist (likely no edit permission)
    rrr_created:     int = 0
    rrr_skipped:     int = 0   # already had RRR
    rrr_errors:      int = 0
    errors:          list = field(default_factory=list)
    table_stats:     dict = field(default_factory=dict)  # table_name → {filled, skipped, unverified, errors}


# ── Main agent class ───────────────────────────────────────────────────────────
class DataSeederAgent:

    # Backend throttle: 300 requests/minute for authenticated users.
    # 12 requests per land parcel (6 GET + 6 PATCH) → need ≥0.24s between requests.
    # We use 0.25s baseline + exponential back-off on 429.
    _REQUEST_DELAY = 0.25          # seconds between every request
    _MAX_RETRIES   = 5             # max retries on 429
    _RETRY_BACKOFF = [5, 10, 20, 40, 60]  # wait seconds per retry attempt

    def __init__(self, dry_run: bool = False, force: bool = False,
                 only_layer: Optional[int] = None, limit: Optional[int] = None,
                 only_su_ids: Optional[list[int]] = None,
                 verify: bool = True, with_rrr: bool = False):
        self.dry_run    = dry_run
        self.force      = force
        self.only_layer = only_layer
        self.limit      = limit
        self.only_su_ids = set(only_su_ids or [])
        self.verify     = verify     # re-read after PATCH to confirm the write persisted
        self.with_rrr   = with_rrr   # also create RRR records (needs a party pool)
        self.session    = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.result     = SeederResult()
        self._last_req  = 0.0      # timestamp of last request (for pacing)
        self._last_err  = None     # detail of the most recent request exception

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        if IB_TOKEN:
            self.session.headers["Authorization"] = f"Token {IB_TOKEN}"
            _ok(f"Using pre-set token")
            return True
        try:
            resp = self.session.post(f"{BASE_URL}/login/",
                                     json={"username": IB_USER, "password": IB_PASS},
                                     timeout=15)
        except Exception as exc:
            _err(f"Auth failed: {type(exc).__name__} - {exc}")
            return False
        if resp.status_code == 200:
            token = resp.json().get("token") or resp.json().get("auth_token")
            if token:
                self.session.headers["Authorization"] = f"Token {token}"
                _ok(f"Logged in as {IB_USER}")
                return True
        _err(f"Auth failed: HTTP {resp.status_code} — {resp.text[:120]}")
        return False

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    def _pace(self):
        """Enforce minimum gap between requests to stay under throttle limit."""
        elapsed = time.perf_counter() - self._last_req
        gap = self._REQUEST_DELAY - elapsed
        if gap > 0:
            time.sleep(gap)
        self._last_req = time.perf_counter()

    def _request(self, method: str, path: str,
                 payload: Optional[dict] = None) -> tuple[Optional[requests.Response], float]:
        """Send a request with pacing + automatic retry on HTTP 429."""
        url = f"{BASE_URL}{path}"
        t0  = time.perf_counter()
        for attempt in range(self._MAX_RETRIES + 1):
            self._pace()
            try:
                if method == "GET":
                    r = self.session.get(url, timeout=60)
                else:
                    r = self.session.patch(url, json=payload, timeout=60)
            except Exception as exc:
                self._last_err = f"{type(exc).__name__}: {str(exc)[:120]}"
                print(f"      {RED}[{method} {path}] {self._last_err}{RESET}")
                return None, (time.perf_counter() - t0) * 1000

            if r.status_code != 429:
                return r, (time.perf_counter() - t0) * 1000

            # 429 — back off and retry
            wait = self._RETRY_BACKOFF[min(attempt, len(self._RETRY_BACKOFF) - 1)]
            print(f"      {YELLOW}[429] rate-limited — waiting {wait}s (attempt {attempt+1}/{self._MAX_RETRIES})…{RESET}")
            time.sleep(wait)

        return r, (time.perf_counter() - t0) * 1000

    def _get(self, path: str) -> tuple[Optional[requests.Response], float]:
        return self._request("GET", path)

    def _patch(self, path: str, payload: dict) -> tuple[Optional[requests.Response], float]:
        return self._request("PATCH", path, payload)

    # ── Feature discovery ─────────────────────────────────────────────────────

    def fetch_all_features(self) -> list[dict]:
        """POST survey_rep_data_user/ → list of feature property dicts."""
        _info("Fetching all features from survey_rep_data_user/ ...")
        self._pace()
        try:
            resp = self.session.post(f"{BASE_URL}/survey_rep_data_user/",
                                     json={}, timeout=30)
        except Exception as exc:
            _err(f"Failed to fetch features: {type(exc).__name__} - {exc}")
            return []
        if resp.status_code != 200:
            _err(f"Failed to fetch features: HTTP {resp.status_code} - {resp.text[:160]}")
            return []
        body = resp.json()
        features = body if isinstance(body, list) else body.get("features", [])
        _ok(f"Fetched {len(features)} total features")
        return features

    # ── Data check ────────────────────────────────────────────────────────────

    @staticmethod
    def _is_empty(val) -> bool:
        """A field counts as 'no data' only when it is None or an empty string.
        Numeric 0 is a legitimate value and must NOT be treated as empty."""
        return val is None or val == ""

    def _read_field(self, get_path: str, key_field: str):
        """Return (ok, value) where ok is False if the GET itself failed."""
        r, _ = self._get(get_path)
        if r is None or r.status_code != 200:
            return False, None
        try:
            return True, r.json().get(key_field)
        except Exception:
            return False, None

    def _has_data(self, get_path: str, key_field: str) -> bool:
        """Return True if the table already has meaningful data for this parcel."""
        ok, val = self._read_field(get_path, key_field)
        return ok and not self._is_empty(val)

    # ── Fill one table ────────────────────────────────────────────────────────

    def _fill_table(self, su_id: int, table_name: str,
                    get_url: str, patch_url: str,
                    key_field: str, payload_fn) -> str:
        """
        Returns: 'filled' | 'skipped' | 'unverified' | 'error'

          filled     → PATCH succeeded (and, when --verify, the key field reads back non-empty)
          skipped    → table already had data (and not --force)
          unverified → PATCH returned 200/201 but the key field did not persist;
                       almost always means the seed user's role lacks edit permission
          error      → PATCH failed (non-2xx / timeout)
        """
        stats = self.result.table_stats.setdefault(
            table_name, {"filled": 0, "skipped": 0, "unverified": 0, "errors": 0})

        if not self.force and self._has_data(get_url, key_field):
            stats["skipped"] += 1
            return "skipped"

        if self.dry_run:
            stats["filled"] += 1
            return "filled"

        payload = payload_fn(su_id)
        self._last_err = None
        r, ms = self._patch(patch_url, payload)
        if r is None or r.status_code not in (200, 201):
            code = r.status_code if r else "request-failed"
            detail = r.text[:80] if r else (self._last_err or "no response")
            self.result.errors.append({
                "su_id": su_id, "table": table_name,
                "http": code, "detail": detail,
            })
            stats["errors"] += 1
            return "error"

        # PATCH reported success — optionally confirm the value actually persisted.
        if self.verify and key_field in payload:
            ok, val = self._read_field(get_url, key_field)
            # Only flag as unverified when we could read the record back but the
            # key field is still empty. If the GET itself failed (e.g. no view
            # permission) we cannot disprove the write, so we trust the 200.
            if ok and self._is_empty(val):
                self.result.unverified += 1
                self.result.errors.append({
                    "su_id": su_id, "table": table_name,
                    "http": "unverified",
                    "detail": f"PATCH 200 but '{key_field}' still empty — check edit permission",
                })
                stats["unverified"] += 1
                return "unverified"

        stats["filled"] += 1
        return "filled"

    # ── RRR helpers ───────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict) -> tuple[Optional[requests.Response], float]:
        """POST with pacing + 429 retry."""
        url = f"{BASE_URL}{path}"
        t0  = time.perf_counter()
        for attempt in range(self._MAX_RETRIES + 1):
            self._pace()
            try:
                r = self.session.post(url, json=payload, timeout=60)
            except Exception as exc:
                print(f"      {RED}[POST {path}] exception: {type(exc).__name__}: {exc}{RESET}")
                return None, (time.perf_counter() - t0) * 1000
            if r.status_code != 429:
                return r, (time.perf_counter() - t0) * 1000
            wait = self._RETRY_BACKOFF[min(attempt, len(self._RETRY_BACKOFF) - 1)]
            print(f"      {YELLOW}[429] rate-limited — waiting {wait}s…{RESET}")
            time.sleep(wait)
        return r, (time.perf_counter() - t0) * 1000

    def has_rrr(self, su_id: int) -> bool:
        """Return True if the spatial unit already has at least one active BA unit / RRR."""
        r, _ = self._get(f"/rrr_data_get/?su_id={su_id}")
        if r is None or r.status_code != 200:
            return False
        try:
            body = r.json()
            records = body.get("records", [])
            # A record exists if there is at least one BA unit with at least one RRR
            for rec in records:
                if rec.get("rrrs"):
                    return True
        except Exception:
            pass
        return False

    def seed_rrr(self, su_id: int, party_pool: dict) -> str:
        """
        Create one RRR entry for su_id.
        Returns: 'created' | 'exists' | 'error'

        Tenure type is chosen deterministically by su_id % 5:
          0 → Full Ownership  (1 person, 100%)
          1 → Co-ownership    (2 persons, 50/50)
          2 → Government      (1 govt entity, 100%)
          3 → Lease           (1 person, fixed term)
          4 → Mortgage        (1 owner, with mortgage block)
        """
        if not self.dry_run and self.has_rrr(su_id):
            self.result.rrr_skipped += 1
            return "exists"

        if self.dry_run:
            self.result.rrr_created += 1
            return "created"

        persons   = party_pool.get("persons", [])
        govt      = party_pool.get("government", [])

        if not persons:
            self.result.rrr_errors += 1
            self.result.errors.append({"su_id": su_id, "table": "RRR", "http": "no_pool",
                                       "detail": "Party pool is empty"})
            return "error"

        rng      = random.Random(su_id * 43 + 99)
        tenure   = su_id % 5
        deed_ref = f"DEED-{su_id:06d}"

        # ── Build the rights array ──
        if tenure == _TENURE_FULL_OWN:
            pid   = rng.choice(persons)
            rights = [{"party": pid, "right_type": "Ownership",
                       "share": 100.0, "share_type": "Full",
                       "date_start": "2010-01-01", "date_end": None, "description": ""}]
            admin_source_type = "Title Deed"
            mortgage_data     = None

        elif tenure == _TENURE_CO_OWN:
            pid1, pid2 = rng.sample(persons, min(2, len(persons)))
            rights = [
                {"party": pid1, "right_type": "Ownership",
                 "share": 50.0, "share_type": "Equal",
                 "date_start": "2015-03-15", "date_end": None, "description": ""},
                {"party": pid2, "right_type": "Ownership",
                 "share": 50.0, "share_type": "Equal",
                 "date_start": "2015-03-15", "date_end": None, "description": ""},
            ]
            admin_source_type = "Title Deed"
            mortgage_data     = None

        elif tenure == _TENURE_GOVT:
            gov_pid = rng.choice(govt) if govt else rng.choice(persons)
            rights  = [{"party": gov_pid, "right_type": "Ownership",
                        "share": 100.0, "share_type": "Full",
                        "date_start": "1948-02-04", "date_end": None,
                        "description": "Government ownership"}]
            admin_source_type = "Government Gazette"
            mortgage_data     = None

        elif tenure == _TENURE_LEASE:
            pid    = rng.choice(persons)
            y_from = rng.randint(2005, 2018)
            y_to   = y_from + rng.randint(10, 30)
            rights = [{"party": pid, "right_type": "Lease",
                       "share": 100.0, "share_type": "Full",
                       "date_start": f"{y_from}-01-01",
                       "date_end":   f"{y_to}-12-31",
                       "description": f"{y_to - y_from}-year lease"}]
            admin_source_type = "Lease Agreement"
            mortgage_data     = None

        else:  # _TENURE_MORTGAGE
            pid    = rng.choice(persons)
            rights = [{"party": pid, "right_type": "Mortgage",
                       "share": 100.0, "share_type": "Full",
                       "date_start": f"{rng.randint(2010, 2022)}-06-01",
                       "date_end": None, "description": "Mortgage registered"}]
            admin_source_type = "Mortgage Deed"
            mortgage_data = {
                "amount":          round(rng.uniform(500_000, 5_000_000), 2),
                "interest":        round(rng.uniform(7.0, 15.0), 4),
                "ranking":         1,
                "mortgage_type":   rng.choice(["Conventional", "Equitable", "Legal"]),
                "mortgage_ref_id": f"MTG-{su_id:06d}",
                "mortgagee":       rng.choice(["Bank of Ceylon", "People's Bank",
                                               "Hatton National Bank", "Commercial Bank"]),
            }

        payload: dict = {
            "su_id":            su_id,
            "code":             deed_ref,
            "la_ba_unit_type":  "basicPropertyUnit",
            "admin_source_type": admin_source_type,
            "rights":           rights,
        }
        if mortgage_data:
            payload["mortgage"] = mortgage_data

        r, _ = self._post("/rrr_data_save/", payload)
        if r is not None and r.status_code in (200, 201):
            self.result.rrr_created += 1
            return "created"
        else:
            code   = r.status_code if r else "timeout"
            detail = r.text[:80] if r else "no response"
            self.result.rrr_errors += 1
            self.result.errors.append({"su_id": su_id, "table": "RRR",
                                       "http": code, "detail": detail})
            return "error"

    # ── Process one parcel / building / unit ──────────────────────────────────

    def _process_feature(self, su_id: int, layer_id: int, idx: int, total: int):
        is_land = layer_id in LAND_LAYER_IDS
        is_unit = layer_id in UNIT_LAYER_IDS
        if is_land:
            kind   = "Land"
            tables = LAND_TABLES
        elif is_unit:
            kind   = "Unit"
            tables = UNIT_TABLES
        elif layer_id in BUILDING_LAYER_IDS:
            kind   = "Building"
            tables = BUILDING_TABLES
        else:
            self.result.errors.append({
                "su_id": su_id,
                "table": "layer",
                "http": "unsupported",
                "detail": f"Unsupported layer_id={layer_id}",
            })
            _err(f"Skipping su_id={su_id}: unsupported layer_id={layer_id}")
            return 0, 0, 1

        print(f"\n  [{idx}/{total}] {BOLD}su_id={su_id}{RESET}  layer={layer_id}  ({kind})")

        filled  = 0
        skipped = 0
        errors  = 0

        for (tname, get_tmpl, patch_tmpl, key, fn) in tables:
            get_path   = get_tmpl.replace("{su}", str(su_id))
            patch_path = patch_tmpl.replace("{su}", str(su_id))
            outcome = self._fill_table(su_id, tname, get_path, patch_path, key, fn)
            if outcome == "filled":
                tag = f"{GREEN}filled{RESET}" if not self.dry_run else f"{YELLOW}would fill{RESET}"
                print(f"      {tname:20s} → {tag}")
                filled += 1
            elif outcome == "skipped":
                print(f"      {tname:20s} → {YELLOW}has data{RESET}")
                skipped += 1
            elif outcome == "unverified":
                print(f"      {tname:20s} → {YELLOW}not persisted (no edit perm?){RESET}")
                errors += 1
            else:
                print(f"      {tname:20s} → {RED}ERROR{RESET}")
                errors += 1

        if is_land:
            if filled:  self.result.land_filled  += 1
            else:       self.result.land_skipped  += 1
        elif is_unit:
            if filled:  self.result.unit_filled  += 1
            else:       self.result.unit_skipped  += 1
        else:
            if filled:  self.result.bld_filled   += 1
            else:       self.result.bld_skipped   += 1

        return filled, skipped, errors

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        print(f"\n{BOLD}{'═'*60}{RESET}")
        print(f"  InfoBhoomi Data Seeder Agent")
        if self.dry_run:
            print(f"  {YELLOW}DRY RUN — no data will be written{RESET}")
        if self.force:
            print(f"  {YELLOW}FORCE — will overwrite existing data{RESET}")
        if self.verify and not self.dry_run:
            print(f"  {CYAN}VERIFY — each write is read back to confirm it persisted{RESET}")
        if self.with_rrr:
            print(f"  {CYAN}RRR — will also create Rights/Restrictions/Responsibilities{RESET}")
        print(f"{'═'*60}")

        if not self.authenticate():
            sys.exit(1)

        features = self.fetch_all_features()
        if not features:
            _err("No features found — nothing to seed.")
            sys.exit(1)

        # ── Filter and categorise ─────────────────────────────────────────────
        land_features = []
        bld_features  = []
        unit_features = []   # apartment / strata units (layer_id=12)

        for f in features:
            props    = f.get("properties", {}) if isinstance(f, dict) and "properties" in f else f
            su_id    = props.get("su_id")
            layer_id = props.get("layer_id")
            if su_id is None or layer_id is None:
                continue
            if self.only_su_ids and int(su_id) not in self.only_su_ids:
                continue
            if self.only_layer and layer_id != self.only_layer:
                continue
            if layer_id in LAND_LAYER_IDS:
                land_features.append((int(su_id), int(layer_id)))
            elif layer_id in UNIT_LAYER_IDS:
                unit_features.append((int(su_id), int(layer_id)))
            elif layer_id in BUILDING_LAYER_IDS:
                bld_features.append((int(su_id), int(layer_id)))

        self.result.total_land      = len(land_features)
        self.result.total_buildings = len(bld_features)
        self.result.total_units     = len(unit_features)

        if self.limit:
            # Distribute the budget round-robin across categories so a small
            # --limit still touches buildings and units (not land-only).
            land_features, bld_features, unit_features = self._distribute_limit(
                [land_features, bld_features, unit_features], self.limit)

        print(f"\n  Found: {BOLD}{self.result.total_land}{RESET} land parcels, "
              f"{BOLD}{self.result.total_buildings}{RESET} buildings, "
              f"{BOLD}{self.result.total_units}{RESET} apartment units")
        if self.limit:
            print(f"  {YELLOW}Limiting to {self.limit} total features{RESET}")

        # ── Land parcels ──────────────────────────────────────────────────────
        if land_features:
            print(f"\n{BOLD}{'─'*60}{RESET}")
            print(f"  Processing {len(land_features)} Land Parcel(s)")
            print(f"{'─'*60}")
            for i, (su_id, layer_id) in enumerate(land_features, 1):
                self._process_feature(su_id, layer_id, i, len(land_features))

        # ── Buildings ─────────────────────────────────────────────────────────
        if bld_features:
            print(f"\n{BOLD}{'─'*60}{RESET}")
            print(f"  Processing {len(bld_features)} Building(s)")
            print(f"{'─'*60}")
            for i, (su_id, layer_id) in enumerate(bld_features, 1):
                self._process_feature(su_id, layer_id, i, len(bld_features))

        # ── Apartment units ───────────────────────────────────────────────────
        if unit_features:
            print(f"\n{BOLD}{'─'*60}{RESET}")
            print(f"  Processing {len(unit_features)} Apartment Unit(s)")
            print(f"{'─'*60}")
            for i, (su_id, layer_id) in enumerate(unit_features, 1):
                self._process_feature(su_id, layer_id, i, len(unit_features))

        # ── Rights / Restrictions / Responsibilities (opt-in) ─────────────────
        if self.with_rrr:
            processed = land_features + bld_features + unit_features
            self._seed_rrr_for(processed)

        # ── Summary ───────────────────────────────────────────────────────────
        self._print_summary()

    @staticmethod
    def _distribute_limit(buckets: list, limit: int) -> list:
        """Take up to `limit` items total, round-robin across the buckets so each
        non-empty category is represented. Order within each bucket is preserved."""
        out = [[] for _ in buckets]
        taken = 0
        idx = 0
        # cursor per bucket
        cursors = [0] * len(buckets)
        while taken < limit and any(cursors[i] < len(buckets[i]) for i in range(len(buckets))):
            b = idx % len(buckets)
            if cursors[b] < len(buckets[b]):
                out[b].append(buckets[b][cursors[b]])
                cursors[b] += 1
                taken += 1
            idx += 1
        return out

    def _seed_rrr_for(self, features: list):
        """Build (or load) a party pool and create one RRR per spatial unit."""
        print(f"\n{BOLD}{'─'*60}{RESET}")
        print(f"  Seeding RRR for {len(features)} spatial unit(s)")
        print(f"{'─'*60}")

        party_pool = {"persons": [], "government": [], "corporate": []}
        if not self.dry_run:
            try:
                from .party_pool_agent import PartyPoolAgent
            except ImportError as exc:
                _err(f"Cannot seed RRR — party pool agent unavailable: {exc}")
                return
            pool_agent = PartyPoolAgent()
            # Reuse our already-authenticated session so we don't log in twice.
            pool_agent.session = self.session
            party_pool = pool_agent.get_or_create_pool()
            if not party_pool.get("persons"):
                _err("Party pool is empty — skipping RRR seeding.")
                return

        for i, (su_id, _layer_id) in enumerate(features, 1):
            outcome = self.seed_rrr(su_id, party_pool)
            tag = {"created": f"{GREEN}created{RESET}",
                   "exists":  f"{YELLOW}has RRR{RESET}",
                   "error":   f"{RED}ERROR{RESET}"}.get(outcome, outcome)
            print(f"  [{i}/{len(features)}] su_id={su_id} → {tag}")

    def _print_summary(self):
        r = self.result
        print(f"\n{BOLD}{'═'*60}{RESET}")
        print(f"  Seeder Summary")
        print(f"{'═'*60}")
        print(f"  Land parcels  : {r.total_land:>5}  total")
        print(f"  {GREEN}  Filled       : {r.land_filled:>5}{RESET}")
        print(f"  {YELLOW}  Already done : {r.land_skipped:>5}{RESET}")
        print(f"  Buildings     : {r.total_buildings:>5}  total")
        print(f"  {GREEN}  Filled       : {r.bld_filled:>5}{RESET}")
        print(f"  {YELLOW}  Already done : {r.bld_skipped:>5}{RESET}")
        print(f"  Apt. Units    : {r.total_units:>5}  total")
        print(f"  {GREEN}  Filled       : {r.unit_filled:>5}{RESET}")
        print(f"  {YELLOW}  Already done : {r.unit_skipped:>5}{RESET}")
        if r.unverified:
            print(f"  {RED}  Not persisted: {r.unverified:>5}  (PATCH 200 but value did not save){RESET}")
        print(f"{'─'*60}")
        print(f"  Table breakdown:")
        for tname, stats in r.table_stats.items():
            bar  = f"{GREEN}{stats['filled']} filled{RESET}"
            bar += f"  {YELLOW}{stats['skipped']} skipped{RESET}"
            if stats.get("unverified"):
                bar += f"  {RED}{stats['unverified']} not-persisted{RESET}"
            if stats["errors"]:
                bar += f"  {RED}{stats['errors']} errors{RESET}"
            print(f"    {tname:20s}  {bar}")

        if r.unverified:
            print(f"\n  {YELLOW}Note: 'not persisted' rows mean the API accepted the PATCH but the"
                  f"\n  value did not change — almost always the seed user's role lacks"
                  f"\n  edit permission for that field. Grant edit perms or use a role"
                  f"\n  that has them, then re-run with --force.{RESET}")

        if r.rrr_created or r.rrr_skipped or r.rrr_errors:
            print(f"{'─'*60}")
            print(f"  RRR records   :")
            print(f"  {GREEN}  Created      : {r.rrr_created:>5}{RESET}")
            print(f"  {YELLOW}  Already done : {r.rrr_skipped:>5}{RESET}")
            if r.rrr_errors:
                print(f"  {RED}  Errors       : {r.rrr_errors:>5}{RESET}")

        if r.errors:
            print(f"\n{RED}{'─'*60}{RESET}")
            print(f"  {RED}{BOLD}{len(r.errors)} Error(s):{RESET}")
            for e in r.errors:
                print(f"    su_id={e['su_id']}  table={e['table']}  "
                      f"HTTP {e['http']}  — {e['detail']}")
        else:
            print(f"\n  {GREEN}No errors.{RESET}")

        if self.dry_run:
            print(f"\n  {YELLOW}DRY RUN — run without --dry-run to apply changes.{RESET}")
        print(f"{'═'*60}\n")
