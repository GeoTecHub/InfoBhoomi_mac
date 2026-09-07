import tempfile
import unittest
from pathlib import Path

from agent_center.debug_router_agent import DebugRouterAgent
from agent_center.db_verification_agent import DBVerificationAgent
from agent_center.fix_proposal_agent import FixProposalAgent
from agent_center.function_qa_agent import FunctionQAAgent
from agent_center.function_registry import all_functions, categories, get_function
from agent_center.structured_memory import StructuredMemory


class FunctionRegistryTests(unittest.TestCase):
    def test_registry_has_unique_ids_and_required_metadata(self):
        functions = all_functions()
        ids = [fn.id for fn in functions]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("Auth", categories())
        self.assertIn("RRR", categories())
        for fn in functions:
            self.assertTrue(fn.display_name)
            self.assertTrue(fn.category)
            self.assertTrue(fn.endpoints)
            self.assertIn(fn.verification, {"api", "db", "api+db"})

    def test_get_function(self):
        fn = get_function("survey.geometry")
        self.assertEqual(fn.category, "Survey Geometry")


class DebugRouterTests(unittest.TestCase):
    def test_routes_parcel_save_issue_to_survey_geometry(self):
        routes = DebugRouterAgent().route("parcel polygon is not saving")
        self.assertTrue(routes)
        self.assertEqual(routes[0].function_id, "survey.geometry")

    def test_routes_rrr_owner_issue_to_rrr(self):
        routes = DebugRouterAgent().route("RRR owner is not showing")
        self.assertTrue(any(route.function_id == "rrr.lifecycle" for route in routes[:2]))


class StructuredMemoryTests(unittest.TestCase):
    def test_memory_redacts_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StructuredMemory(Path(tmp) / "memory.json")
            issue = memory.record_issue(
                function_category="Auth",
                sub_function="Login",
                symptom="token failed",
                detected_by="test",
                api_evidence={"Authorization": "Token abc", "safe": "ok"},
            )
            self.assertEqual(issue["api_evidence"]["Authorization"], "<redacted>")
            self.assertEqual(issue["api_evidence"]["safe"], "ok")

    def test_recurring_issue_refreshes_solution(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StructuredMemory(Path(tmp) / "memory.json")
            first = memory.record_issue(
                function_category="Auth",
                sub_function="Login",
                symptom="auth failed",
                detected_by="test",
                proposed_solution="old",
            )
            second = memory.record_issue(
                function_category="Auth",
                sub_function="Login",
                symptom="auth failed",
                detected_by="test",
                root_cause="new root cause",
                proposed_solution="new solution",
            )
            self.assertEqual(first["issue_id"], second["issue_id"])
            self.assertEqual(second["root_cause"], "new root cause")
            self.assertEqual(second["proposed_solution"], "new solution")

    def test_recurring_issue_deduplicates_debug_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StructuredMemory(Path(tmp) / "memory.json")
            for _ in range(3):
                memory.record_issue(
                    function_category="Auth",
                    sub_function="Login",
                    symptom="auth failed",
                    detected_by="test",
                    debug_notes="The request failed before credentials were validated.",
                )
            issue = memory.list_issues()[0]
            self.assertEqual(issue["debug_notes"].count("credentials were validated"), 1)


class FixProposalTests(unittest.TestCase):
    def test_rejects_paths_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = FixProposalAgent(workspace_root=Path(tmp), memory=StructuredMemory(Path(tmp) / "memory.json"))
            with self.assertRaises(ValueError):
                agent.validate_workspace_path("../outside.py")

    def test_accepts_paths_inside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = FixProposalAgent(workspace_root=Path(tmp), memory=StructuredMemory(Path(tmp) / "memory.json"))
            path = agent.validate_workspace_path("inside/file.py")
            self.assertTrue(str(path).startswith(str(Path(tmp).resolve())))

    def test_gemini_provider_falls_back_without_breaking(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StructuredMemory(Path(tmp) / "memory.json")
            agent = FixProposalAgent(workspace_root=Path(tmp), memory=memory)
            issue = memory.record_issue(
                function_category="RRR",
                sub_function="RRR lifecycle",
                symptom="owner is not showing",
                detected_by="test",
            )
            proposal = agent.propose_from_issue(issue, provider="gemini")
            self.assertEqual(proposal["ai_provider"], "gemini")
            self.assertTrue(proposal["implementation_plan"])


class FunctionQAAgentTests(unittest.TestCase):
    def test_auth_failure_solution_for_connection_error(self):
        agent = FunctionQAAgent()
        solution = agent._auth_failure_solution(
            {
                "ok": False,
                "method": "login",
                "base_url": "http://127.0.0.1:8000/api/user",
                "error": "ConnectionError: Failed to establish a new connection",
            }
        )
        self.assertIn("unreachable", solution["root_cause"])
        self.assertIn("Start the backend server", solution["proposed_solution"])

    def test_auth_failure_solution_for_dns_error(self):
        agent = FunctionQAAgent()
        solution = agent._auth_failure_solution(
            {
                "ok": False,
                "method": "login",
                "base_url": "https://infobhoomiback.geoinfobox.com/api/user",
                "error": "NameResolutionError: Failed to resolve host ([Errno 11001] getaddrinfo failed)",
            }
        )
        self.assertIn("DNS", solution["root_cause"])
        self.assertIn("internet/DNS/VPN", solution["proposed_solution"])


class DBVerificationAgentTests(unittest.TestCase):
    def test_status_is_safe_to_display(self):
        status = DBVerificationAgent().status()
        self.assertEqual(status["agent"], "DB Verification Agent")
        self.assertEqual(status["mode"], "read-only verification; never writes to the database")
        self.assertNotIn("password", str(status.get("target", {}).get("database_url_configured", "")))


if __name__ == "__main__":
    unittest.main()


# ── P0 hardening tests ────────────────────────────────────────────────────────

import json as _json
from agent_center.structured_memory import StructuredMemory as _SM


class StructuredMemoryHardeningTests(unittest.TestCase):
    def test_redacts_authorization_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _SM(Path(tmp) / "m.json")
            issue = mem.record_issue(
                function_category="Auth", sub_function="Login", symptom="x",
                detected_by="test",
                api_evidence={"Authorization": "Token abc.def", "Cookie": "sid=xyz", "safe": "ok"},
            )
            self.assertEqual(issue["api_evidence"]["Authorization"], "<redacted>")
            self.assertEqual(issue["api_evidence"]["Cookie"], "<redacted>")
            self.assertEqual(issue["api_evidence"]["safe"], "ok")

    def test_redacts_password_pwd_passwd_pass_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _SM(Path(tmp) / "m.json")
            issue = mem.record_issue(
                function_category="Auth", sub_function="Login", symptom="y",
                detected_by="test",
                api_evidence={
                    "user_password": "p", "pwd": "p", "passwd": "p",
                    "client_secret": "s", "secret_key": "s",
                    "x-api-key": "k", "X-CSRFToken": "c",
                    "harmless_field": "ok",
                },
            )
            ev = issue["api_evidence"]
            for k in ("user_password", "pwd", "passwd", "client_secret",
                      "secret_key", "x-api-key", "X-CSRFToken"):
                self.assertEqual(ev[k], "<redacted>", k)
            self.assertEqual(ev["harmless_field"], "ok")

    def test_redacts_token_substring_in_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = _SM(Path(tmp) / "m.json")
            issue = mem.record_issue(
                function_category="Auth", sub_function="Login", symptom="z",
                detected_by="test",
                api_evidence={"trace": "Authorization: Bearer abc.def.ghi sent"},
            )
            self.assertIn("<redacted>", issue["api_evidence"]["trace"])
            self.assertNotIn("abc.def.ghi", issue["api_evidence"]["trace"])

    def test_evidence_size_cap_applied(self):
        from config import AGENT_EVIDENCE_MAX_BYTES
        with tempfile.TemporaryDirectory() as tmp:
            mem = _SM(Path(tmp) / "m.json")
            huge = "X" * (AGENT_EVIDENCE_MAX_BYTES * 2)
            issue = mem.record_issue(
                function_category="Auth", sub_function="Login", symptom="size",
                detected_by="test",
                api_evidence={"body": huge},
            )
            # The dict gets replaced with the truncation marker because its
            # serialised size exceeds the cap.
            ev = issue["api_evidence"]
            self.assertTrue(
                ev.get("<truncated>") is True or
                (isinstance(ev.get("body"), str) and "<truncated>" in ev["body"]),
                f"Expected truncation marker, got {ev}",
            )

    def test_atomic_save_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            mem = _SM(path)
            mem.record_issue(function_category="X", sub_function="y",
                             symptom="z", detected_by="t")
            self.assertTrue(path.exists())
            reloaded = _SM(path)
            self.assertEqual(len(reloaded.list_issues()), 1)


# ── Dashboard auth tests ──────────────────────────────────────────────────────

class DashboardAuthTests(unittest.TestCase):
    """Targeted tests of the auth gate without spinning up an HTTP server."""

    def test_authorised_requires_token_match(self):
        from agent_center import dashboard_server as ds

        # Patch in a known token without touching disk.
        ds._DASHBOARD_TOKEN = "expected-secret"

        class FakeHandler:
            headers = {"X-Agent-Token": "expected-secret"}

        # Use the real method bound to a fake instance.
        result = ds.DashboardHandler._authorised(FakeHandler())  # type: ignore[arg-type]
        self.assertTrue(result)

    def test_authorised_rejects_wrong_token(self):
        from agent_center import dashboard_server as ds
        ds._DASHBOARD_TOKEN = "expected-secret"

        class FakeHandler:
            headers = {"X-Agent-Token": "wrong"}

        self.assertFalse(ds.DashboardHandler._authorised(FakeHandler()))  # type: ignore[arg-type]


class DashboardApplySafetyTests(unittest.TestCase):
    def test_empty_item_ids_selects_no_plan_items(self):
        from agent_center import dashboard_server as ds

        plan = {
            "items": [
                {"item_id": "A", "layer": "backend", "file_path": "x.py"},
                {"item_id": "B", "layer": "backend", "file_path": "y.py"},
            ]
        }
        self.assertEqual([item.item_id for item in ds._items_from_plan(plan, None)], ["A", "B"])
        self.assertEqual(ds._items_from_plan(plan, []), [])
        self.assertEqual([item.item_id for item in ds._items_from_plan(plan, ["B"])], ["B"])

    def test_validate_migration_edit_rejects_non_migration_edits(self):
        from agent_center import dashboard_server as ds

        class FakeMemory:
            def get_edit(self, edit_id):
                return {
                    "edit_id": edit_id,
                    "agent": "BackendImplementer",
                    "file_path": "InfoBhoomi_Backend_dev2/user/views.py",
                    "rolled_back": False,
                }

        old = ds.ChangeMemory
        ds.ChangeMemory = lambda: FakeMemory()
        try:
            ok, error, status = ds._validate_migration_edit("EDIT-1")
        finally:
            ds.ChangeMemory = old
        self.assertFalse(ok)
        self.assertEqual(status, 400)
        self.assertIn("not a committed DB migration", error)

    def test_validate_migration_edit_accepts_committed_migration(self):
        from agent_center import dashboard_server as ds

        class FakeMemory:
            def get_edit(self, edit_id):
                return {
                    "edit_id": edit_id,
                    "agent": "DBMigrationImplementer",
                    "file_path": "InfoBhoomi_Backend_dev2/user/migrations/0042_fix.py",
                    "rolled_back": False,
                }

        old = ds.ChangeMemory
        ds.ChangeMemory = lambda: FakeMemory()
        try:
            ok, error, status = ds._validate_migration_edit("EDIT-1")
        finally:
            ds.ChangeMemory = old
        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertEqual(status, 200)

    def test_authorised_rejects_when_no_token_generated(self):
        from agent_center import dashboard_server as ds
        ds._DASHBOARD_TOKEN = ""

        class FakeHandler:
            headers = {"X-Agent-Token": "anything"}

        self.assertFalse(ds.DashboardHandler._authorised(FakeHandler()))  # type: ignore[arg-type]
