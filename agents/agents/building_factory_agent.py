"""
InfoBhoomi Building Factory Agent
===================================
Creates ~1000 buildings with layer_id=3, seeds all their attribute data,
creates RRR records for every new building, and back-fills RRR records for
all existing land parcels that don't already have one.

Execution phases
----------------
  1. Initialise party pool (PartyPoolAgent)
  2. Fetch anchor coordinates from existing features
  3. Create N buildings in batches of 10 via survey_rep_data/save/
  4. Seed building attributes via DataSeederAgent (Admin Info, Overview, Utility)
     — includes no_floors seeded with 1-15 units randomly
  5. Seed RRR for every new building (5 tenure types)
  6. Seed RRR for existing land parcels that have no RRR yet

Rate limiting
-------------
  All HTTP via DataSeederAgent._request() which enforces 0.25s between calls
  and backs off on HTTP 429.

Usage
-----
    from agents.building_factory_agent import BuildingFactoryAgent
    agent = BuildingFactoryAgent(count=1000)
    agent.authenticate()
    agent.run()
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import random
import uuid
import requests
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

from .party_pool_agent import PartyPoolAgent
from .data_seeder_agent import (
    DataSeederAgent, LAND_LAYER_IDS, BUILDING_LAYER_IDS, UNIT_LAYER_IDS,
    _unit_admin as _gen_unit_admin,
)

# ── Env ────────────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE_URL = os.getenv("IB_BASE_URL", "http://127.0.0.1:8000/api/user").rstrip("/")
IB_TOKEN = os.getenv("IB_TOKEN", "")
IB_USER  = os.getenv("IB_USERNAME", "admin_bw")
IB_PASS  = os.getenv("IB_PASSWORD", "")

# ── Console helpers ─────────────────────────────────────────────────────────────
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

def _ok(m):   print(f"  {GREEN}✔{RESET}  {m}")
def _skip(m): print(f"  {YELLOW}–{RESET}  {m}")
def _err(m):  print(f"  {RED}✘{RESET}  {m}")
def _info(m): print(f"  {CYAN}·{RESET}  {m}")
def _head(m): print(f"\n{BOLD}{'─'*60}{RESET}\n  {m}\n{'─'*60}")

# ── Building geometry helper ───────────────────────────────────────────────────
_BUILDING_SIZE_DEG = 0.0003  # ~30 m square in WGS84

def _small_square(lon: float, lat: float, seed: int) -> dict:
    """Return a tiny polygon GeoJSON centred near (lon, lat) with a seeded jitter."""
    rng  = random.Random(seed)
    jitter_lon = rng.uniform(-0.0005, 0.0005)
    jitter_lat = rng.uniform(-0.0005, 0.0005)
    cx = lon + jitter_lon
    cy = lat + jitter_lat
    h  = _BUILDING_SIZE_DEG / 2
    # Small square: SW → SE → NE → NW → close
    coords = [
        [cx - h, cy - h],
        [cx + h, cy - h],
        [cx + h, cy + h],
        [cx - h, cy + h],
        [cx - h, cy - h],
    ]
    return {"type": "Polygon", "coordinates": [coords]}


# ── Fallback anchor grid for Sri Lanka (if no existing features available) ─────
# Centres of known GND-dense areas in Sabaragamuwa / Central / Western provinces
_FALLBACK_ANCHORS = [
    (80.404,  6.684),  # Ratnapura
    (80.364,  7.254),  # Kegalle
    (80.637,  7.291),  # Kandy
    (80.356,  7.483),  # Kurunegala
    (80.015,  6.822),  # Kalutara
    (80.217,  6.937),  # Horana
    (80.555,  7.005),  # Avissawella
    (80.703,  6.927),  # Nuwara Eliya approaches
    (80.498,  7.153),  # Gampola
    (80.485,  6.543),  # Balangoda
]


@dataclass
class FactoryStats:
    buildings_created:  int = 0
    buildings_failed:   int = 0
    attrs_seeded:       int = 0
    units_created:      int = 0
    units_failed:       int = 0
    units_attrs_seeded: int = 0
    rrr_buildings:      int = 0
    rrr_land:           int = 0
    rrr_land_skipped:   int = 0
    errors:             list = field(default_factory=list)


class BuildingFactoryAgent:

    _REQUEST_DELAY = 0.25
    _MAX_RETRIES   = 5
    _RETRY_BACKOFF = [5, 10, 20, 40, 60]
    _BATCH_SIZE    = 3    # buildings per POST — smaller batches avoid GND spatial query timeout

    def __init__(
        self,
        count:            int  = 1000,
        dry_run:          bool = False,
        skip_land_rrr:    bool = False,
        skip_attrs:       bool = False,
        skip_rrr:         bool = False,
        seed_bld_rrr:     bool = False,   # fill RRR for all existing buildings
        create_apt_units: bool = False,   # create apartment units for each new building
        limit:            Optional[int] = None,
    ):
        self.count            = count
        self.dry_run          = dry_run
        self.skip_land_rrr    = skip_land_rrr
        self.skip_attrs       = skip_attrs
        self.skip_rrr         = skip_rrr
        self.seed_bld_rrr     = seed_bld_rrr
        self.create_apt_units = create_apt_units
        self.limit            = limit          # cap total features processed
        self.session       = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._last_req     = 0.0
        self.stats         = FactoryStats()

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        if IB_TOKEN:
            self.session.headers["Authorization"] = f"Token {IB_TOKEN}"
            _ok("Using pre-set token")
            return True
        resp = self.session.post(
            f"{BASE_URL}/login/",
            json={"username": IB_USER, "password": IB_PASS},
            timeout=15,
        )
        if resp.status_code == 200:
            token = resp.json().get("token") or resp.json().get("auth_token")
            if token:
                self.session.headers["Authorization"] = f"Token {token}"
                _ok(f"Logged in as {IB_USER}")
                return True
        _err(f"Auth failed: HTTP {resp.status_code}")
        return False

    # ── Rate-limited HTTP ──────────────────────────────────────────────────────

    def _pace(self):
        elapsed = time.perf_counter() - self._last_req
        gap = self._REQUEST_DELAY - elapsed
        if gap > 0:
            time.sleep(gap)
        self._last_req = time.perf_counter()

    def _request(self, method: str, path: str,
                 payload=None) -> tuple[Optional[requests.Response], float]:
        url = f"{BASE_URL}{path}"
        t0  = time.perf_counter()
        for attempt in range(self._MAX_RETRIES + 1):
            self._pace()
            try:
                if method == "GET":
                    r = self.session.get(url, timeout=30)
                elif method == "POST":
                    r = self.session.post(url, json=payload, timeout=120)
                else:
                    r = self.session.patch(url, json=payload, timeout=30)
            except Exception as exc:
                _err(f"Request exception: {exc}")
                return None, (time.perf_counter() - t0) * 1000
            if r.status_code != 429:
                return r, (time.perf_counter() - t0) * 1000
            wait = self._RETRY_BACKOFF[min(attempt, len(self._RETRY_BACKOFF) - 1)]
            print(f"    {YELLOW}[429] rate-limited — waiting {wait}s (attempt {attempt+1})…{RESET}")
            time.sleep(wait)
        return r, (time.perf_counter() - t0) * 1000

    # ── Phase 1: Fetch existing features for anchor coordinates ───────────────

    def _fetch_anchors(self) -> list[tuple[float, float]]:
        """
        Fetch all existing features. Extract WGS84-looking centroid coordinates
        from land parcel polygons to use as anchor points for building placement.
        Falls back to hardcoded Sri Lanka locations if nothing usable is found.
        """
        _info("Fetching existing features to derive anchor coordinates …")
        r, _ = self._request("POST", "/survey_rep_data_user/", {})
        if r is None or r.status_code != 200:
            status = r.status_code if r is not None else "timeout/no response"
            body   = r.text[:300] if r is not None else ""
            _skip(f"Could not fetch features (HTTP {status}): {body}")
            _skip("Falling back to hardcoded anchor grid")
            return list(_FALLBACK_ANCHORS)

        body     = r.json()
        features = body if isinstance(body, list) else body.get("features", [])
        anchors: list[tuple[float, float]] = []

        for feat in features:
            props    = feat.get("properties", {}) if isinstance(feat, dict) and "properties" in feat else feat
            layer_id = props.get("layer_id")
            geom     = feat.get("geometry") or feat.get("geom") or {}

            if layer_id not in LAND_LAYER_IDS:
                continue
            if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
                continue

            coords_list = (geom["coordinates"][0]
                           if geom["type"] == "Polygon"
                           else geom["coordinates"][0][0])
            if not coords_list:
                continue

            # Compute simple centroid
            xs = [c[0] for c in coords_list if isinstance(c, (list, tuple)) and len(c) >= 2]
            ys = [c[1] for c in coords_list if isinstance(c, (list, tuple)) and len(c) >= 2]
            if not xs:
                continue

            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)

            # Accept only WGS84-looking coordinates (Sri Lanka region)
            if 79.0 <= cx <= 82.5 and 5.5 <= cy <= 10.0:
                anchors.append((cx, cy))

        if anchors:
            _ok(f"Extracted {len(anchors)} anchor coordinates from existing parcels")
            return anchors

        _skip("No WGS84 parcel anchors found — using fallback grid")
        return list(_FALLBACK_ANCHORS)

    # ── Phase 2: Create buildings in batches ──────────────────────────────────

    def _build_feature(self, anchor_lon: float, anchor_lat: float, seed: int) -> dict:
        """Build a GeoJSON feature dict for one building."""
        return {
            "type": "Feature",
            "geometry": _small_square(anchor_lon, anchor_lat, seed),
            "properties": {
                "uuid":      str(uuid.uuid4()),
                "layer_id":  3,
                "crs":       "EPSG:4326",
                "parent_uuid": [],
            },
        }

    def _create_buildings(self, anchors: list[tuple[float, float]]) -> list[int]:
        """
        POST batches of buildings to survey_rep_data/save/.
        Returns list of successfully created su_ids.
        """
        _head(f"Phase 2 — Creating {self.count} buildings (batch={self._BATCH_SIZE})")
        if self.dry_run:
            _info("DRY RUN — skipping building creation")
            return []

        created_su_ids: list[int] = []
        n_anchors     = len(anchors)
        n_batches     = math.ceil(self.count / self._BATCH_SIZE)

        for batch_idx in range(n_batches):
            start = batch_idx * self._BATCH_SIZE
            end   = min(start + self._BATCH_SIZE, self.count)
            batch = []
            for i in range(start, end):
                anchor_lon, anchor_lat = anchors[i % n_anchors]
                batch.append(self._build_feature(anchor_lon, anchor_lat, seed=i * 9973 + 13))

            resp, ms = self._request("POST", "/survey_rep_data/", batch)

            if resp is None:
                _err(f"Batch {batch_idx+1}/{n_batches}: timeout/error")
                self.stats.buildings_failed += len(batch)
                continue

            if resp.status_code not in (200, 201):
                _err(f"Batch {batch_idx+1}/{n_batches}: HTTP {resp.status_code} — {resp.text[:120]}")
                self.stats.buildings_failed += len(batch)
                continue

            body    = resp.json()
            records = (body if isinstance(body, list)
                       else body.get("saved_records", body.get("saved", body.get("data", []))))
            for rec in records:
                props  = rec.get("properties", rec)
                su_id  = props.get("su_id") or props.get("id")
                if su_id:
                    created_su_ids.append(int(su_id))

            n_ok = len(records)
            self.stats.buildings_created += n_ok
            _ok(f"Batch {batch_idx+1}/{n_batches}: {n_ok} buildings created "
                f"({self.stats.buildings_created}/{self.count}) [{ms:.0f}ms]")

        _ok(f"Buildings created: {self.stats.buildings_created}  "
            f"failed: {self.stats.buildings_failed}")
        return created_su_ids

    # ── Phase 3: Seed attributes ───────────────────────────────────────────────

    def _seed_attributes(self, su_ids: list[int]):
        """Run DataSeederAgent over the given su_ids (buildings only, layer_id=3)."""
        if not su_ids:
            return
        if self.skip_attrs:
            _info("--skip-attrs set — skipping attribute seeding")
            return

        _head(f"Phase 3 — Seeding attributes for {len(su_ids)} buildings")

        seeder = DataSeederAgent(dry_run=self.dry_run, force=False)
        # Share the authenticated session so we don't re-login
        seeder.session = self.session
        seeder.session.headers.update({"Content-Type": "application/json"})

        total = len(su_ids)
        for idx, su_id in enumerate(su_ids, 1):
            seeder._process_feature(su_id, 3, idx, total)

        self.stats.attrs_seeded = len(su_ids)
        _ok(f"Attribute seeding done: {self.stats.attrs_seeded} buildings")

    # ── Phase 4: Seed RRR for new buildings ───────────────────────────────────

    def _seed_rrr_buildings(self, su_ids: list[int], party_pool: dict):
        if not su_ids:
            return
        if self.skip_rrr:
            _info("--skip-rrr set — skipping building RRR seeding")
            return

        _head(f"Phase 4 — Seeding RRR for {len(su_ids)} new buildings")

        seeder = DataSeederAgent(dry_run=self.dry_run, force=False)
        seeder.session = self.session

        total = len(su_ids)
        for idx, su_id in enumerate(su_ids, 1):
            outcome = seeder.seed_rrr(su_id, party_pool)
            tag = {
                "created": f"{GREEN}created{RESET}",
                "exists":  f"{YELLOW}exists{RESET}",
                "error":   f"{RED}ERROR{RESET}",
            }.get(outcome, outcome)
            if idx % 50 == 0 or idx == total:
                print(f"    [{idx}/{total}] su_id={su_id}  RRR → {tag}")

        self.stats.rrr_buildings = seeder.result.rrr_created
        _ok(f"Building RRR: {seeder.result.rrr_created} created, "
            f"{seeder.result.rrr_skipped} skipped, "
            f"{seeder.result.rrr_errors} errors")

    # ── Phase 3b: Create apartment units for new buildings ────────────────────

    def _create_apt_units(self, building_su_ids: list[int]) -> list[int]:
        """
        For each new building, create a realistic set of apartment units (layer_id=12).

        Unit count per building is derived deterministically from the seeded
        ``no_floors`` value (same seed as ``_bld_admin``):
          • 1-2 floors  → 1 unit per floor
          • 3-5 floors  → 2 units per floor
          • 6+ floors   → 3 units per floor

        Returns list of all created unit su_ids.
        """
        if not self.create_apt_units or not building_su_ids:
            if not self.create_apt_units:
                _info("--create-apt-units not set — skipping apartment unit creation")
            return []

        _head(f"Phase 3b — Creating apartment units for {len(building_su_ids)} buildings")
        if self.dry_run:
            _info("DRY RUN — skipping apartment unit creation")
            return []

        created_unit_ids: list[int] = []

        for bld_idx, bld_su_id in enumerate(building_su_ids, 1):
            # Derive no_floors from the same deterministic seed used in _bld_admin
            rng_bld   = random.Random(bld_su_id * 11 + 10)
            no_floors = rng_bld.randint(1, 10)

            # Decide units per floor
            if no_floors <= 2:
                units_per_floor = 1
            elif no_floors <= 5:
                units_per_floor = 2
            else:
                units_per_floor = 3

            bld_unit_ids: list[int] = []
            for floor in range(1, no_floors + 1):
                for unit_num in range(1, units_per_floor + 1):
                    apt_label = f"F{floor:02d}-U{unit_num:02d}"
                    payload = {
                        "parent_su_id":  bld_su_id,
                        "apt_name":      apt_label,
                        "floor_no":      floor,
                        "floor_area":    round(random.Random(bld_su_id * floor * unit_num).uniform(40.0, 180.0), 1),
                        "bld_property_type": "Residential",
                        "ext_builduse_type": "Residential",
                    }
                    resp, ms = self._request("POST", "/bld-unit/create/", payload)
                    if resp is None:
                        _err(f"  bld={bld_su_id}  floor={floor}  unit={unit_num}: timeout")
                        self.stats.units_failed += 1
                        continue
                    if resp.status_code not in (200, 201):
                        _err(f"  bld={bld_su_id}  floor={floor}  unit={unit_num}: "
                             f"HTTP {resp.status_code} — {resp.text[:80]}")
                        self.stats.units_failed += 1
                        continue
                    unit_su_id = resp.json().get("su_id")
                    if unit_su_id:
                        bld_unit_ids.append(int(unit_su_id))
                        self.stats.units_created += 1

            created_unit_ids.extend(bld_unit_ids)
            if bld_idx % 50 == 0 or bld_idx == len(building_su_ids):
                _ok(f"  [{bld_idx}/{len(building_su_ids)}] bld={bld_su_id}: "
                    f"{len(bld_unit_ids)} units created "
                    f"(total {self.stats.units_created})")

        _ok(f"Apartment units created: {self.stats.units_created}  "
            f"failed: {self.stats.units_failed}")
        return created_unit_ids

    def _seed_apt_unit_attrs(self, unit_su_ids: list[int]):
        """Seed attribute data for newly created apartment units (layer_id=12)."""
        if not unit_su_ids or self.skip_attrs:
            return

        _head(f"Phase 3c — Seeding attributes for {len(unit_su_ids)} apartment units")

        seeder = DataSeederAgent(dry_run=self.dry_run, force=False)
        seeder.session = self.session
        seeder.session.headers.update({"Content-Type": "application/json"})

        total = len(unit_su_ids)
        for idx, su_id in enumerate(unit_su_ids, 1):
            seeder._process_feature(su_id, 12, idx, total)

        self.stats.units_attrs_seeded = len(unit_su_ids)
        _ok(f"Apartment unit attribute seeding done: {self.stats.units_attrs_seeded} units")

    # ── Phase 5: Seed RRR for existing land parcels ───────────────────────────

    def _seed_rrr_land(self, party_pool: dict):
        if self.skip_land_rrr:
            _info("--skip-land-rrr set — skipping land parcel RRR seeding")
            return

        _head("Phase 5 — Seeding RRR for existing land parcels")
        _info("Fetching all land parcel su_ids …")

        r, _ = self._request("POST", "/survey_rep_data_user/", {})
        if r is None or r.status_code != 200:
            status = r.status_code if r is not None else "timeout/no response"
            body   = r.text[:300] if r is not None else ""
            _err(f"Could not fetch land parcel list (HTTP {status}): {body}")
            return

        body     = r.json()
        features = body if isinstance(body, list) else body.get("features", [])

        land_ids: list[int] = []
        for feat in features:
            props    = feat.get("properties", {}) if isinstance(feat, dict) and "properties" in feat else feat
            su_id    = props.get("su_id")
            layer_id = props.get("layer_id")
            if su_id and layer_id in LAND_LAYER_IDS:
                land_ids.append(int(su_id))

        if self.limit:
            land_ids = land_ids[: self.limit]

        _info(f"Found {len(land_ids)} land parcels to process for RRR")

        seeder = DataSeederAgent(dry_run=self.dry_run, force=False)
        seeder.session = self.session

        _consecutive_errors = 0
        total = len(land_ids)
        for idx, su_id in enumerate(land_ids, 1):
            outcome = seeder.seed_rrr(su_id, party_pool)
            if outcome == "error":
                _consecutive_errors += 1
                # Print full detail for the first 5 errors so we can diagnose
                if _consecutive_errors <= 5 and seeder.result.errors:
                    err = seeder.result.errors[-1]
                    print(f"    [{idx}/{total}] su_id={su_id}  RRR → {RED}ERROR{RESET}  "
                          f"HTTP {err.get('http')}  {err.get('detail','')}")
                else:
                    print(f"    [{idx}/{total}] su_id={su_id}  RRR → {RED}ERROR{RESET}")
                if _consecutive_errors >= 10:
                    _err(f"10 consecutive errors — aborting land RRR phase after {idx} attempts. "
                         f"Fix the RRR endpoint then re-run.")
                    break
            else:
                _consecutive_errors = 0  # reset on success
            if outcome != "error" and (idx % 100 == 0 or idx == total):
                tag = f"{GREEN}created{RESET}" if outcome == "created" else f"{YELLOW}exists{RESET}"
                print(f"    [{idx}/{total}] su_id={su_id}  RRR → {tag}  "
                      f"(created={seeder.result.rrr_created}, "
                      f"skipped={seeder.result.rrr_skipped})")

        self.stats.rrr_land         = seeder.result.rrr_created
        self.stats.rrr_land_skipped = seeder.result.rrr_skipped
        _ok(f"Land parcel RRR: {seeder.result.rrr_created} created, "
            f"{seeder.result.rrr_skipped} already had RRR, "
            f"{seeder.result.rrr_errors} errors")

    # ── Phase 6: Seed RRR for all existing buildings ──────────────────────────

    def _seed_rrr_existing_buildings(self, party_pool: dict):
        if not self.seed_bld_rrr:
            return

        _head("Phase 6 — Seeding RRR for all existing buildings (layer_id=3)")
        _info("Fetching all building su_ids …")

        r, _ = self._request("POST", "/survey_rep_data_user/", {})
        if r is None or r.status_code != 200:
            status = r.status_code if r is not None else "timeout/no response"
            body   = r.text[:300] if r is not None else ""
            _err(f"Could not fetch building list (HTTP {status}): {body}")
            return

        body     = r.json()
        features = body if isinstance(body, list) else body.get("features", [])

        bld_ids: list[int] = []
        for feat in features:
            props    = feat.get("properties", {}) if isinstance(feat, dict) and "properties" in feat else feat
            su_id    = props.get("su_id")
            layer_id = props.get("layer_id")
            if su_id and layer_id in BUILDING_LAYER_IDS:
                bld_ids.append(int(su_id))

        if self.limit:
            bld_ids = bld_ids[: self.limit]

        _info(f"Found {len(bld_ids)} buildings to process for RRR")

        seeder = DataSeederAgent(dry_run=self.dry_run, force=False)
        seeder.session = self.session

        _consecutive_errors = 0
        total = len(bld_ids)
        for idx, su_id in enumerate(bld_ids, 1):
            outcome = seeder.seed_rrr(su_id, party_pool)
            if outcome == "error":
                _consecutive_errors += 1
                if _consecutive_errors <= 5 and seeder.result.errors:
                    err = seeder.result.errors[-1]
                    print(f"    [{idx}/{total}] su_id={su_id}  RRR → {RED}ERROR{RESET}  "
                          f"HTTP {err.get('http')}  {err.get('detail','')}")
                else:
                    print(f"    [{idx}/{total}] su_id={su_id}  RRR → {RED}ERROR{RESET}")
                if _consecutive_errors >= 10:
                    _err(f"10 consecutive errors — aborting building RRR phase after {idx} attempts.")
                    break
            else:
                _consecutive_errors = 0
            if outcome != "error" and (idx % 100 == 0 or idx == total):
                tag = f"{GREEN}created{RESET}" if outcome == "created" else f"{YELLOW}exists{RESET}"
                print(f"    [{idx}/{total}] su_id={su_id}  RRR → {tag}  "
                      f"(created={seeder.result.rrr_created}, "
                      f"skipped={seeder.result.rrr_skipped})")

        self.stats.rrr_buildings    += seeder.result.rrr_created
        _ok(f"Building RRR: {seeder.result.rrr_created} created, "
            f"{seeder.result.rrr_skipped} already had RRR, "
            f"{seeder.result.rrr_errors} errors")

    # ── Summary ────────────────────────────────────────────────────────────────

    def _print_summary(self):
        s = self.stats
        print(f"\n{BOLD}{'═'*60}{RESET}")
        print(f"  Building Factory Summary")
        print(f"{'═'*60}")
        print(f"  Buildings created  : {s.buildings_created:>5}")
        if s.buildings_failed:
            print(f"  {RED}Buildings failed   : {s.buildings_failed:>5}{RESET}")
        print(f"  Attributes seeded  : {s.attrs_seeded:>5}")
        if s.units_created or s.units_failed:
            print(f"  Apt units created  : {s.units_created:>5}")
            if s.units_failed:
                print(f"  {RED}Apt units failed   : {s.units_failed:>5}{RESET}")
            print(f"  Unit attrs seeded  : {s.units_attrs_seeded:>5}")
        print(f"  RRR (buildings)    : {s.rrr_buildings:>5}")
        print(f"  RRR (land) created : {s.rrr_land:>5}")
        print(f"  RRR (land) skipped : {s.rrr_land_skipped:>5}")
        if s.errors:
            print(f"  {RED}Errors             : {len(s.errors):>5}{RESET}")
            for e in s.errors[:10]:
                print(f"    {e}")
        print(f"{'═'*60}\n")

    # ── Main ──────────────────────────────────────────────────────────────────

    def run(self):
        print(f"\n{BOLD}{'═'*60}{RESET}")
        print(f"  InfoBhoomi Building Factory Agent")
        print(f"  target={self.count} buildings  layer_id=3")
        if self.dry_run:
            print(f"  {YELLOW}DRY RUN — no data will be written{RESET}")
        print(f"{'═'*60}")

        # ── Phase 0: Authenticate ──
        if not self.authenticate():
            sys.exit(1)

        # ── Phase 0b: Build party pool ──
        _head("Phase 0 — Building party pool")
        pool_agent = PartyPoolAgent()
        pool_agent.session = self.session
        pool_agent.session.headers.update({"Content-Type": "application/json"})
        # Share the already-authenticated session
        if IB_TOKEN:
            pool_agent.session.headers["Authorization"] = f"Token {IB_TOKEN}"
        party_pool = pool_agent.get_or_create_pool()

        if not party_pool.get("persons"):
            _err("Party pool has no persons — cannot seed RRR. Aborting.")
            sys.exit(1)

        # ── Phase 1: Anchor coordinates ──
        _head("Phase 1 — Extracting geometry anchors")
        anchors = self._fetch_anchors()

        # ── Phase 2: Create buildings ──
        new_su_ids = self._create_buildings(anchors)

        # ── Phase 3: Seed building attributes ──
        self._seed_attributes(new_su_ids)

        # ── Phase 3b: Create apartment units for each new building ──
        new_unit_su_ids = self._create_apt_units(new_su_ids)

        # ── Phase 3c: Seed attributes for new apartment units ──
        self._seed_apt_unit_attrs(new_unit_su_ids)

        # ── Phase 4: Seed RRR for new buildings ──
        self._seed_rrr_buildings(new_su_ids, party_pool)

        # ── Phase 5: Seed RRR for existing land parcels ──
        self._seed_rrr_land(party_pool)

        # ── Phase 6: Seed RRR for all existing buildings ──
        self._seed_rrr_existing_buildings(party_pool)

        self._print_summary()
