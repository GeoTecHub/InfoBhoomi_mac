"""
InfoBhoomi Party Pool Agent
============================
Creates and caches a reusable pool of fake parties in sl_party so that
RRR seeding always has valid party PIDs to reference.

Pool composition
----------------
  80  individual persons  (ext_pid_type='NIC', SL names)
  10  government entities (sl_party_type='Government')
  10  corporate entities  (sl_party_type='Corporate')

Strategy
--------
  - Tries POST /sl-party/ for each synthetic party.
  - On HTTP 400 (duplicate NIC or email), falls back to
    POST /sl-party-data/ {ext_pid_type, ext_pid} to fetch the existing PID.
  - Persists all discovered PIDs to agents/.party_pool_cache.json so the
    next run skips creation entirely.

Usage
-----
    from agents.party_pool_agent import PartyPoolAgent
    agent = PartyPoolAgent()
    agent.authenticate()
    pool = agent.get_or_create_pool()
    # pool = {'persons': [1,2,...], 'government': [81,...], 'corporate': [91,...]}
"""

from __future__ import annotations

import json
import os
import sys
import time
import random
import requests
from typing import Optional
from dotenv import load_dotenv

# ── Env ────────────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE_URL = os.getenv("IB_BASE_URL", "http://127.0.0.1:8000/api/user").rstrip("/")
IB_TOKEN = os.getenv("IB_TOKEN", "")
IB_USER  = os.getenv("IB_USERNAME", "admin_bw")
IB_PASS  = os.getenv("IB_PASSWORD", "")

# ── Cache file ─────────────────────────────────────────────────────────────────
_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", ".party_pool_cache.json")

# ── Pool sizes ─────────────────────────────────────────────────────────────────
POOL_PERSONS = 80
POOL_GOV     = 10
POOL_CORP    = 10

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

# ── Realistic SL name pools ────────────────────────────────────────────────────
_FIRST = [
    "Kamal", "Nimal", "Sunil", "Ranjith", "Priya", "Dilani", "Chamari",
    "Roshan", "Lasantha", "Malini", "Saman", "Kumari", "Ajith", "Sandya",
    "Chathura", "Gayan", "Anusha", "Tharaka", "Hiruni", "Mahesh",
    "Ruwan", "Ishara", "Nuwan", "Dinesh", "Thilini", "Kavindi", "Nadun",
    "Sachini", "Amila", "Udara", "Supun", "Hansani", "Ishan", "Dilrukshi",
    "Pasan", "Senura", "Asiri", "Oshadhi", "Lahiru", "Vinusha",
]
_LAST = [
    "Perera", "Silva", "Fernando", "Jayawardena", "Wickramasinghe",
    "De Silva", "Bandara", "Gunawardena", "Rajapaksha", "Dissanayake",
    "Wijesekara", "Herath", "Kumarasinghe", "Amarasinghe", "Karunaratne",
    "Weerasinghe", "Pathirana", "Rathnayake", "Senanayake", "Liyanage",
]
_GOV_ENTITIES = [
    "Department of Land Commissioner",
    "Survey Department of Sri Lanka",
    "Urban Development Authority",
    "National Housing Development Authority",
    "Sri Lanka Land Reclamation Corporation",
    "Ministry of Lands",
    "Provincial Land Authority",
    "Municipal Council of Kandy",
    "Pradeshiya Sabha Kegalle",
    "Central Environmental Authority",
]
_CORP_ENTITIES = [
    "Lanka Holdings (Pvt) Ltd",
    "Serendib Properties Ltd",
    "Emerald Estates (Pvt) Ltd",
    "Sunshine Developers Ltd",
    "Cinnamon Land Corporation",
    "Ceylon Realty (Pvt) Ltd",
    "Pearl City Investments",
    "Green Valley Properties (Pvt) Ltd",
    "Blue Mountain Developers Ltd",
    "Golden Gate Holdings (Pvt) Ltd",
]


class PartyPoolAgent:
    _REQUEST_DELAY  = 0.25
    _MAX_RETRIES    = 3
    _RETRY_BACKOFF  = [5, 10, 20]

    def __init__(self):
        self.session   = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._last_req = 0.0

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

    def _post(self, path: str, payload: dict) -> Optional[requests.Response]:
        url = f"{BASE_URL}{path}"
        for attempt in range(self._MAX_RETRIES + 1):
            self._pace()
            try:
                r = self.session.post(url, json=payload, timeout=20)
            except Exception as exc:
                _err(f"Request error: {exc}")
                return None
            if r.status_code == 429:
                wait = self._RETRY_BACKOFF[min(attempt, len(self._RETRY_BACKOFF) - 1)]
                print(f"    {YELLOW}[429] waiting {wait}s…{RESET}")
                time.sleep(wait)
                continue
            return r
        return None

    # ── Create one party ───────────────────────────────────────────────────────

    def _create_or_find_party(self, payload: dict) -> Optional[int]:
        """
        POST /sl-party/ → returns pid on success.
        On 400 (duplicate), fetches by ext_pid_type + ext_pid.
        On 400 with no ext_pid fallback, tries sl_party_type + specific_tp lookup.
        """
        r = self._post("/sl-party/", payload)
        if r is None:
            return None

        if r.status_code == 201:
            pid = r.json().get("pid")
            return pid

        if r.status_code == 400:
            # Duplicate — try to find existing record
            ext_type = payload.get("ext_pid_type")
            ext_id   = payload.get("ext_pid")
            if ext_type and ext_id:
                r2 = self._post("/sl-party-data/", {"ext_pid_type": ext_type, "ext_pid": ext_id})
                if r2 and r2.status_code == 200:
                    data = r2.json()
                    entries = data if isinstance(data, list) else data.get("results", [])
                    if entries:
                        return entries[0].get("pid")
            _err(f"Could not create or find party: {r.text[:100]}")
            return None

        _err(f"Party creation HTTP {r.status_code}: {r.text[:100]}")
        return None

    # ── Build party payloads ───────────────────────────────────────────────────

    def _person_payload(self, i: int, user_id: int = 1) -> dict:
        rng  = random.Random(i * 31 + 7)
        first = rng.choice(_FIRST)
        last  = rng.choice(_LAST)
        nic   = f"{rng.randint(19700101, 20000101)}{rng.randint(1000, 9999)}"  # fake NIC
        return {
            "party_name":      last.upper(),
            "party_full_name": f"{first} {last}",
            "la_party_type":   "naturalPerson",
            "sl_party_type":   None,
            "specific_tp":     None,
            "ext_pid_type":    "NIC",
            "ext_pid":         f"SEED-NIC-{i:04d}",
            "email":           f"seed.person.{i:04d}@infobhoomi.lk",
            "gender":          rng.choice(["Male", "Female"]),
            "done_by":         user_id,
        }

    def _gov_payload(self, i: int, user_id: int = 1) -> dict:
        name = _GOV_ENTITIES[i % len(_GOV_ENTITIES)]
        return {
            "party_name":      name.upper(),
            "party_full_name": name,
            "la_party_type":   "legalPerson",
            "sl_party_type":   "Government",
            "specific_tp":     f"GOV-{i:03d}",
            "ext_pid_type":    "GovReg",
            "ext_pid":         f"SEED-GOV-{i:03d}",
            "email":           f"seed.gov.{i:03d}@infobhoomi.lk",
            "done_by":         user_id,
        }

    def _corp_payload(self, i: int, user_id: int = 1) -> dict:
        name = _CORP_ENTITIES[i % len(_CORP_ENTITIES)]
        return {
            "party_name":      name.upper(),
            "party_full_name": name,
            "la_party_type":   "legalPerson",
            "sl_party_type":   "Corporate",
            "specific_tp":     f"CORP-{i:03d}",
            "ext_pid_type":    "CorpReg",
            "ext_pid":         f"SEED-CORP-{i:03d}",
            "email":           f"seed.corp.{i:03d}@infobhoomi.lk",
            "done_by":         user_id,
        }

    # ── Main entry point ───────────────────────────────────────────────────────

    def get_or_create_pool(self) -> dict:
        """
        Returns a pool dict: {'persons': [...], 'government': [...], 'corporate': [...]}.
        Loads from cache if available and complete; otherwise creates and caches.
        """
        cached = self._load_cache()
        if cached and self._pool_complete(cached):
            _ok(f"Party pool loaded from cache: "
                f"{len(cached['persons'])} persons, "
                f"{len(cached['government'])} gov, "
                f"{len(cached['corporate'])} corp")
            return cached

        _info("Building party pool …")
        pool: dict = cached or {"persons": [], "government": [], "corporate": []}

        # ── Persons ──
        existing_count = len(pool["persons"])
        if existing_count < POOL_PERSONS:
            print(f"\n  {BOLD}Creating individual parties ({existing_count}→{POOL_PERSONS})…{RESET}")
            for i in range(existing_count, POOL_PERSONS):
                pid = self._create_or_find_party(self._person_payload(i))
                if pid:
                    pool["persons"].append(pid)
                    _ok(f"Person [{i+1}/{POOL_PERSONS}] pid={pid}")
                else:
                    _skip(f"Person [{i+1}/{POOL_PERSONS}] skipped")

        # ── Government ──
        existing_count = len(pool["government"])
        if existing_count < POOL_GOV:
            print(f"\n  {BOLD}Creating government parties ({existing_count}→{POOL_GOV})…{RESET}")
            for i in range(existing_count, POOL_GOV):
                pid = self._create_or_find_party(self._gov_payload(i))
                if pid:
                    pool["government"].append(pid)
                    _ok(f"Gov [{i+1}/{POOL_GOV}] pid={pid}")
                else:
                    _skip(f"Gov [{i+1}/{POOL_GOV}] skipped")

        # ── Corporate ──
        existing_count = len(pool["corporate"])
        if existing_count < POOL_CORP:
            print(f"\n  {BOLD}Creating corporate parties ({existing_count}→{POOL_CORP})…{RESET}")
            for i in range(existing_count, POOL_CORP):
                pid = self._create_or_find_party(self._corp_payload(i))
                if pid:
                    pool["corporate"].append(pid)
                    _ok(f"Corp [{i+1}/{POOL_CORP}] pid={pid}")
                else:
                    _skip(f"Corp [{i+1}/{POOL_CORP}] skipped")

        self._save_cache(pool)
        _ok(f"Party pool ready: {len(pool['persons'])} persons, "
            f"{len(pool['government'])} gov, {len(pool['corporate'])} corp")
        return pool

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _load_cache(self) -> Optional[dict]:
        if os.path.exists(_CACHE_PATH):
            try:
                with open(_CACHE_PATH) as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _save_cache(self, pool: dict):
        try:
            with open(_CACHE_PATH, "w") as f:
                json.dump(pool, f, indent=2)
        except Exception as exc:
            _err(f"Could not save party pool cache: {exc}")

    def _pool_complete(self, pool: dict) -> bool:
        return (
            len(pool.get("persons", [])) >= POOL_PERSONS
            and len(pool.get("government", [])) >= POOL_GOV
            and len(pool.get("corporate", [])) >= POOL_CORP
        )
