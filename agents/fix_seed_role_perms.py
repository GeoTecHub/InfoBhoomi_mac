"""
InfoBhoomi — Seed Role Permission Doctor
========================================
The data seeder writes attribute data through permission-gated update endpoints.
Each field is only saved when the seed user's role has `edit=True` for that
field's permission_id (see user/views/land.py and user/views/building.py). When
the role is missing those rows the API returns HTTP 200 but silently discards the
value — which is what the seeder reports as "not persisted".

This script logs in as the seed user, reads the *current* role permissions for
every permission_id the seeder needs, and reports which ones are missing edit (or
view) rights. With --apply it sets view+add+edit=True on the gaps.

  view  is needed so the seeder's read-back verification can confirm the write
  edit  is needed so the write is actually saved

Usage:
    python fix_seed_role_perms.py            # diagnose only (read-only)
    python fix_seed_role_perms.py --apply    # grant view+add+edit on the gaps

Applying requires the seed user to be an admin/super_admin AND hold edit on
permission_id 252 (the "manage role permissions" permission). If it doesn't, the
PATCH returns 403 and the script tells you so — you'll then need an admin account
or a direct DB update.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BASE_URL = os.getenv("IB_BASE_URL", "http://127.0.0.1:8000/api/user").rstrip("/")
IB_TOKEN = os.getenv("IB_TOKEN", "")
IB_USER  = os.getenv("IB_USERNAME", "admin_bw")
IB_PASS  = os.getenv("IB_PASSWORD", "")

BOLD, GREEN, YELLOW, RED, CYAN, RESET = (
    "\033[1m", "\033[92m", "\033[93m", "\033[91m", "\033[96m", "\033[0m")

# ── Permission IDs the seeder actually writes ───────────────────────────────────
# Derived 1:1 from the FIELD_PERMISSION_MAP dicts in the backend update views.
# {section: {permission_id: field_label}}
REQUIRED = {
    "Land · Admin":        {12: "land_name", 10: "sl_land_type", 9: "access_road", 11: "postal_ad_lnd"},
    "Land · Overview":     {13: "boundary_type/crs", 17: "ext_landuse_type"},
    "Land · Zoning":       {48: "zoning_category", 49: "max_building_height", 50: "max_coverage",
                            51: "max_far", 52: "setback_front", 53: "setback_rear", 54: "setback_side"},
    "Land · Physical Env": {43: "elevation", 44: "slope", 45: "soil_type", 46: "flood_zone", 47: "vegetation_cover"},
    "Land · Tax":          {56: "land_value", 57: "market_value", 26: "assessment_annual_value",
                            33: "tax_annual_value", 37: "tax_type", 58: "tax_status"},
    "Land · Utility":      {20: "water_supply", 19: "electricity", 21: "drainage_system"},
    "Building · Admin":    {110: "building_name", 113: "bld_property_type", 109: "access_road",
                            111: "postal_ad_build", 112: "house_hold_no", 114: "no_floors",
                            121: "wall_type", 157: "structure_type", 158: "condition", 156: "construction_year"},
    "Building · Overview": {118: "ext_builduse_type", 119: "ext_builduse_sub_type", 120: "roof_type"},
    "Building · Utility":  {122: "elec", 126: "water", 127: "drainage"},
}

# RRR section permissions (only needed if you run the seeder with --rrr)
RRR_PERMS = {"RRR · Land": {59: "land RRR"}, "RRR · Building": {162: "building RRR"}}


class PermDoctor:
    def __init__(self, apply: bool, include_rrr: bool):
        self.apply = apply
        self.include_rrr = include_rrr
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ── auth ───────────────────────────────────────────────────────────────────
    def authenticate(self) -> bool:
        if IB_TOKEN:
            self.session.headers["Authorization"] = f"Token {IB_TOKEN}"
            print(f"  {GREEN}✔{RESET}  Using pre-set token")
            return True
        try:
            r = self.session.post(f"{BASE_URL}/login/",
                                  json={"username": IB_USER, "password": IB_PASS}, timeout=15)
        except Exception as exc:
            print(f"  {RED}✘{RESET}  Auth error: {type(exc).__name__}: {exc}")
            return False
        if r.status_code == 200:
            token = r.json().get("token") or r.json().get("auth_token")
            if token:
                self.session.headers["Authorization"] = f"Token {token}"
                print(f"  {GREEN}✔{RESET}  Logged in as {IB_USER}")
                return True
        print(f"  {RED}✘{RESET}  Auth failed: HTTP {r.status_code} — {r.text[:120]}")
        return False

    # ── read current permission rows for the seed user's role ───────────────────
    def fetch_current(self, perm_ids: list[int]) -> dict:
        """POST /role-permission/ → {permission_id: row dict} for the caller's role."""
        try:
            r = self.session.post(f"{BASE_URL}/role-permission/",
                                  json={"permission_id": perm_ids}, timeout=30)
        except Exception as exc:
            print(f"  {RED}✘{RESET}  Could not read permissions: {type(exc).__name__}: {exc}")
            return {}
        if r.status_code != 200:
            print(f"  {RED}✘{RESET}  Could not read permissions: HTTP {r.status_code} — {r.text[:120]}")
            return {}
        rows = r.json()
        out = {}
        for row in rows:
            pid = row.get("permission_id")
            out[pid] = row
        return out

    # ── grant view+add+edit on one row ──────────────────────────────────────────
    def grant(self, row: dict) -> tuple[bool, str]:
        pk = row.get("id")
        payload = {"view": True, "add": True, "edit": True}
        try:
            r = self.session.patch(f"{BASE_URL}/role-permission/update/id={pk}/",
                                   json=payload, timeout=30)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        if r.status_code in (200, 201):
            return True, "granted"
        return False, f"HTTP {r.status_code} — {r.text[:100]}"

    # ── main ────────────────────────────────────────────────────────────────────
    def run(self):
        print(f"\n{BOLD}{'═'*64}{RESET}")
        print(f"  Seed Role Permission Doctor")
        print(f"  {'APPLY — will grant missing view/add/edit' if self.apply else 'DIAGNOSE ONLY — read-only'}")
        print(f"{'═'*64}")

        if not self.authenticate():
            sys.exit(1)

        sections = dict(REQUIRED)
        if self.include_rrr:
            sections.update(RRR_PERMS)

        all_ids = sorted({pid for sec in sections.values() for pid in sec})
        current = self.fetch_current(all_ids)
        if not current:
            print(f"\n  {RED}No permission rows returned. Either the role has none of these"
                  f"\n  permissions at all, or the read failed. Cannot proceed.{RESET}")
            sys.exit(1)

        total_gap = 0
        applied_ok = 0
        applied_fail = 0

        for section, perms in sections.items():
            missing = []
            for pid, label in perms.items():
                row = current.get(pid)
                if row is None:
                    missing.append((pid, label, "no row", None))
                elif not row.get("edit") or not row.get("view"):
                    state = f"view={row.get('view')} edit={row.get('edit')}"
                    missing.append((pid, label, state, row))
            if not missing:
                print(f"\n  {GREEN}✔ {section}{RESET}  — all editable")
                continue

            total_gap += len(missing)
            print(f"\n  {YELLOW}● {section}{RESET}  — {len(missing)} gap(s)")
            for pid, label, state, row in missing:
                line = f"      perm {pid:>3} ({label}): {state}"
                if not self.apply:
                    print(f"{YELLOW}{line}{RESET}")
                    continue
                if row is None:
                    # No row exists to PATCH — the update endpoint only edits rows.
                    print(f"{RED}{line}  → cannot fix via API (row missing — needs DB insert){RESET}")
                    applied_fail += 1
                    continue
                ok, msg = self.grant(row)
                if ok:
                    print(f"{GREEN}{line}  → granted{RESET}")
                    applied_ok += 1
                else:
                    print(f"{RED}{line}  → {msg}{RESET}")
                    applied_fail += 1
                time.sleep(0.2)

        # ── summary ──
        print(f"\n{BOLD}{'─'*64}{RESET}")
        if total_gap == 0:
            print(f"  {GREEN}No gaps — the seed role can already edit every seeded field.{RESET}")
        elif not self.apply:
            print(f"  {YELLOW}{total_gap} permission gap(s) found.{RESET}")
            print(f"  Re-run with {BOLD}--apply{RESET} to grant view+add+edit on them.")
        else:
            print(f"  Granted: {GREEN}{applied_ok}{RESET}   Failed: {RED}{applied_fail}{RESET}")
            if applied_fail:
                print(f"  {YELLOW}Failures usually mean the seed user is not an admin or lacks"
                      f"\n  edit on permission 252 (manage role permissions). Use an admin"
                      f"\n  account or fix those rows directly in the DB.{RESET}")
            if applied_ok:
                print(f"  {CYAN}Now re-run the seeder with --force to fill the previously-blocked"
                      f"\n  tables:  python seed_data.py --force{RESET}")
        print(f"{'═'*64}\n")


def main():
    p = argparse.ArgumentParser(description="Diagnose/fix the seed user's role permissions.")
    p.add_argument("--apply", action="store_true",
                   help="Grant view+add+edit on every gap (needs admin + perm 252).")
    p.add_argument("--rrr", action="store_true",
                   help="Also check the RRR section permissions (59/162).")
    args = p.parse_args()
    PermDoctor(apply=args.apply, include_rrr=args.rrr).run()


if __name__ == "__main__":
    main()
