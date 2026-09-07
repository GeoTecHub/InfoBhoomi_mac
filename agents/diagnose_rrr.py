"""
Quick diagnostic: test RRR POST for one building su_id.
Prints raw HTTP status and response body — no colour codes.
Run from agents/ directory:
    python diagnose_rrr.py
"""
import os, sys, json, requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BASE_URL = os.getenv("IB_BASE_URL", "http://127.0.0.1:8000/api/user").rstrip("/")
IB_TOKEN = os.getenv("IB_TOKEN", "")
IB_USER  = os.getenv("IB_USERNAME", "admin_bw")
IB_PASS  = os.getenv("IB_PASSWORD", "")

# ── Auth ──────────────────────────────────────────────────────────────
s = requests.Session()
s.headers.update({"Content-Type": "application/json"})

if IB_TOKEN:
    s.headers["Authorization"] = f"Token {IB_TOKEN}"
    print(f"Using pre-set token")
else:
    r = s.post(f"{BASE_URL}/login/", json={"username": IB_USER, "password": IB_PASS}, timeout=15)
    token = r.json().get("token") or r.json().get("auth_token")
    s.headers["Authorization"] = f"Token {token}"
    print(f"Logged in: HTTP {r.status_code}")

# ── Test building su_id ───────────────────────────────────────────────
TEST_SU_ID  = 15295   # first failing building
PERSON_PID  = 28      # first person from party pool

# Step 1: check if spatial unit exists
print(f"\n--- Step 1: GET rrr_data_get/?su_id={TEST_SU_ID} ---")
try:
    r = s.get(f"{BASE_URL}/rrr_data_get/?su_id={TEST_SU_ID}", timeout=30)
    print(f"HTTP {r.status_code}")
    print(r.text[:500])
except Exception as e:
    print(f"EXCEPTION: {type(e).__name__}: {e}")

# Step 2: try to POST an RRR
print(f"\n--- Step 2: POST rrr_data_save/ for su_id={TEST_SU_ID} ---")
payload = {
    "su_id":            TEST_SU_ID,
    "code":             f"DIAG-{TEST_SU_ID:06d}",
    "la_ba_unit_type":  "basicPropertyUnit",
    "admin_source_type": "Title Deed",
    "rights": [{
        "party":      PERSON_PID,
        "right_type": "Ownership",
        "share":      100.0,
        "share_type": "Full",
        "date_start": "2010-01-01",
        "date_end":   None,
        "description": "diagnostic test"
    }]
}
print("Payload:", json.dumps(payload, indent=2))
try:
    r = s.post(f"{BASE_URL}/rrr_data_save/", json=payload, timeout=60)
    print(f"HTTP {r.status_code}")
    print(r.text[:1000])
except Exception as e:
    print(f"EXCEPTION: {type(e).__name__}: {e}")
