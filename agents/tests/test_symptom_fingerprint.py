"""Tests for agent_center.symptom_fingerprint — fine-grained dedup keys."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_center.symptom_fingerprint import (
    Symptom,
    fingerprint,
    fingerprint_hash,
    from_api_evidence,
)


class FingerprintTests(unittest.TestCase):
    def test_full_fingerprint_format(self):
        fp = fingerprint(
            function_id="rrr.lifecycle",
            component_kind="backend",
            endpoint="/rrr_data_get/",
            http_method="GET",
            status_code=200,
            missing_field="owner",
        )
        self.assertEqual(fp, "rrr.lifecycle|backend|/rrr_data_get|GET|200|owner")

    def test_endpoint_normalisation_strips_query_and_trailing_slash(self):
        a = fingerprint(endpoint="/foo/", http_method="GET")
        b = fingerprint(endpoint="/foo?x=1", http_method="GET")
        self.assertEqual(a, b)

    def test_method_uppercased(self):
        a = fingerprint(endpoint="/x", http_method="get")
        b = fingerprint(endpoint="/x", http_method="GET")
        self.assertEqual(a, b)

    def test_different_status_code_distinct(self):
        a = fingerprint(function_id="f", endpoint="/x", http_method="GET", status_code=200)
        b = fingerprint(function_id="f", endpoint="/x", http_method="GET", status_code=500)
        self.assertNotEqual(a, b)

    def test_different_missing_field_distinct(self):
        a = fingerprint(function_id="f", missing_field="owner")
        b = fingerprint(function_id="f", missing_field="ba_unit_id")
        self.assertNotEqual(a, b)

    def test_hash_is_stable_and_short(self):
        h = fingerprint_hash("rrr.lifecycle|backend|/x|GET|200|y")
        self.assertEqual(len(h), 12)
        self.assertEqual(h, fingerprint_hash("rrr.lifecycle|backend|/x|GET|200|y"))


class SymptomDataclassTests(unittest.TestCase):
    def test_symptom_method_matches_function(self):
        s = Symptom(function_id="f", endpoint="/x", http_method="POST", status_code=400)
        self.assertEqual(
            s.fingerprint(),
            fingerprint(function_id="f", endpoint="/x", http_method="POST", status_code=400),
        )


class FromApiEvidenceTests(unittest.TestCase):
    def test_builds_symptom_from_api_check_dict(self):
        evidence = {"path": "/lnd-admin-info/su_id=412/", "method": "GET", "status_code": 500}
        s = from_api_evidence(function_id="land.attributes", api_evidence=evidence)
        self.assertEqual(s.endpoint, "/lnd-admin-info/su_id=412/")
        self.assertEqual(s.http_method, "GET")
        self.assertEqual(s.status_code, 500)
        self.assertEqual(s.component_kind, "backend")


if __name__ == "__main__":
    unittest.main()
