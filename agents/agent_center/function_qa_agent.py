from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from config import (
    AGENT_ALLOW_DESTRUCTIVE,
    AGENT_ENVIRONMENT,
    AGENT_RUN_REPORTS_DIR,
    BASE_URL,
    PASSWORD,
    TOKEN,
    USERNAME,
)
from agent_center.db_verification_agent import DBVerificationAgent
from agent_center.function_registry import (
    EndpointCheck,
    FunctionDefinition,
    all_functions,
    functions_by_category,
    get_function,
)
from agent_center.structured_memory import StructuredMemory, utc_now


@dataclass
class ApiCheckResult:
    method: str
    path: str
    purpose: str
    status: str
    status_code: int | None = None
    elapsed_ms: float = 0.0
    message: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FunctionRunResult:
    function_id: str
    display_name: str
    category: str
    subcategory: str
    status: str
    severity: str
    api_checks: list[dict[str, Any]]
    db_checks: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    elapsed_ms: float


class FunctionQAAgent:
    """Runs registry-defined function checks through API plus optional DB verification."""

    def __init__(
        self,
        *,
        allow_destructive: bool | None = None,
        memory: StructuredMemory | None = None,
        db_agent: DBVerificationAgent | None = None,
    ):
        self.allow_destructive = AGENT_ALLOW_DESTRUCTIVE if allow_destructive is None else allow_destructive
        self.memory = memory or StructuredMemory()
        self.db_agent = db_agent or DBVerificationAgent()
        self.session = requests.Session()
        self.base = BASE_URL.rstrip("/")
        self.token = TOKEN

    def run_function(self, function_id: str) -> dict[str, Any]:
        return self._run_many([get_function(function_id)], scope={"type": "function", "value": function_id})

    def run_category(self, category: str) -> dict[str, Any]:
        return self._run_many(functions_by_category(category), scope={"type": "category", "value": category})

    def run_all(self) -> dict[str, Any]:
        return self._run_many(all_functions(), scope={"type": "all", "value": "all"})

    def _run_many(self, functions: list[FunctionDefinition], scope: dict[str, str]) -> dict[str, Any]:
        started = time.perf_counter()
        run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
        auth_result = self._authenticate()
        results: list[dict[str, Any]] = []

        if not auth_result["ok"]:
            solution = self._auth_failure_solution(auth_result)
            issue = self.memory.record_issue(
                function_category="Auth",
                sub_function="Session access",
                symptom="Agent QA could not authenticate with the configured API credentials.",
                detected_by="Function QA Agent",
                api_evidence=auth_result,
                root_cause=solution["root_cause"],
                proposed_solution=solution["proposed_solution"],
                debug_notes=solution["debug_notes"],
                status="open",
            )
            report = self._build_report(
                run_id=run_id,
                scope=scope,
                functions=[],
                results=[],
                issues=[issue],
                started=started,
                status="failed",
            )
            return self._persist_report(report)

        all_issues: list[dict[str, Any]] = []
        for fn in functions:
            result = self._run_one(fn)
            results.append(result.__dict__)
            all_issues.extend(result.issues)

        status = "passed" if not all_issues else "failed"
        report = self._build_report(
            run_id=run_id,
            scope=scope,
            functions=[fn.id for fn in functions],
            results=results,
            issues=all_issues,
            started=started,
            status=status,
        )
        return self._persist_report(report)

    def _run_one(self, fn: FunctionDefinition) -> FunctionRunResult:
        started = time.perf_counter()
        api_results: list[ApiCheckResult] = []
        db_results: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []

        for endpoint in fn.endpoints:
            api_result = self._run_endpoint(endpoint)
            api_results.append(api_result)
            if api_result.status == "failed":
                issues.append(
                    self.memory.record_issue(
                        function_category=fn.category,
                        sub_function=fn.display_name,
                        symptom=f"{endpoint.purpose} failed for {endpoint.method} {endpoint.path}",
                        detected_by="Function QA Agent",
                        api_evidence=api_result.to_dict(),
                        root_cause="API endpoint did not return an expected success response.",
                        proposed_solution="Inspect the related backend view and frontend service for this function, then rerun the targeted check.",
                        test_results_before=api_result.to_dict(),
                        debug_notes=fn.notes,
                    )
                )

        for db_check in fn.db_checks:
            db_result = self.db_agent.verify_registered_table(db_check).to_dict()
            db_results.append(db_result)
            if db_result["enabled"] and not db_result["passed"]:
                issues.append(
                    self.memory.record_issue(
                        function_category=fn.category,
                        sub_function=fn.display_name,
                        symptom=f"DB verification failed for {db_check.table}",
                        detected_by="DB Verification Agent",
                        db_evidence=db_result,
                        root_cause="Read-only database check failed or expected table was unavailable.",
                        proposed_solution="Confirm database connection settings and table/model naming, then inspect persistence code for this function.",
                        test_results_before=db_result,
                    )
                )

        status = "passed"
        if issues:
            status = "failed"
        elif any(item.status == "skipped" for item in api_results):
            status = "partial"

        return FunctionRunResult(
            function_id=fn.id,
            display_name=fn.display_name,
            category=fn.category,
            subcategory=fn.subcategory,
            status=status,
            severity=fn.severity,
            api_checks=[item.to_dict() for item in api_results],
            db_checks=db_results,
            issues=issues,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    def _run_endpoint(self, endpoint: EndpointCheck) -> ApiCheckResult:
        if endpoint.destructive and not self._destructive_allowed():
            return ApiCheckResult(
                method=endpoint.method,
                path=endpoint.path,
                purpose=endpoint.purpose,
                status="skipped",
                message="Skipped destructive check. Enable only in safe environments with IB_AGENT_ALLOW_DESTRUCTIVE=true.",
                evidence={"environment": AGENT_ENVIRONMENT, "allow_destructive": self.allow_destructive},
            )

        if "{" in endpoint.path:
            return ApiCheckResult(
                method=endpoint.method,
                path=endpoint.path,
                purpose=endpoint.purpose,
                status="skipped",
                message="Skipped parameterized check. Provide controlled test data in a future run profile.",
                evidence={"required_parameters": self._extract_params(endpoint.path)},
            )

        url = f"{self.base}/{endpoint.path.lstrip('/')}"
        started = time.perf_counter()
        try:
            response = self.session.request(
                endpoint.method,
                url,
                json=endpoint.body,
                headers=self._headers(),
                timeout=30,
            )
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            ok = 200 <= response.status_code < 300
            return ApiCheckResult(
                method=endpoint.method,
                path=endpoint.path,
                purpose=endpoint.purpose,
                status="passed" if ok else "failed",
                status_code=response.status_code,
                elapsed_ms=elapsed,
                message="API check passed." if ok else f"API returned HTTP {response.status_code}.",
                evidence=self._response_evidence(response),
            )
        except Exception as exc:
            return ApiCheckResult(
                method=endpoint.method,
                path=endpoint.path,
                purpose=endpoint.purpose,
                status="failed",
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                message=f"Request failed: {type(exc).__name__}: {exc}",
                evidence={},
            )

    def _authenticate(self) -> dict[str, Any]:
        if self.token:
            self.session.headers.update({"Authorization": f"Token {self.token}"})
            try:
                response = self.session.get(f"{self.base}/verify-token/", headers=self._headers(), timeout=20)
                if response.status_code == 200:
                    return {"ok": True, "method": "token", "status_code": response.status_code}
            except Exception as exc:
                return {
                    "ok": False,
                    "method": "token",
                    "base_url": self.base,
                    "error_type": type(exc).__name__,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        if not (USERNAME and PASSWORD):
            return {
                "ok": False,
                "method": "none",
                "base_url": self.base,
                "message": "No IB_TOKEN or username/password configured.",
            }

        try:
            response = self.session.post(
                f"{self.base}/login/",
                json={"username": USERNAME, "password": PASSWORD},
                timeout=20,
            )
            if response.status_code == 200:
                token = response.json().get("token") or response.json().get("auth_token")
                if token:
                    self.token = token
                    self.session.headers.update({"Authorization": f"Token {token}"})
                    return {"ok": True, "method": "login", "status_code": response.status_code}
            return {
                "ok": False,
                "method": "login",
                "base_url": self.base,
                "status_code": response.status_code,
                "body": response.text[:300],
            }
        except Exception as exc:
            return {
                "ok": False,
                "method": "login",
                "base_url": self.base,
                "error_type": type(exc).__name__,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _auth_failure_solution(self, auth_result: dict[str, Any]) -> dict[str, str]:
        base_url = auth_result.get("base_url", self.base)
        error = str(auth_result.get("error", ""))
        status_code = auth_result.get("status_code")
        if auth_result.get("method") == "none":
            return {
                "root_cause": "No API token or login credentials are configured for the agent.",
                "proposed_solution": "Set IB_TOKEN or IB_USERNAME and IB_PASSWORD in agents/.env, then rerun the check.",
                "debug_notes": f"Configured API target: {base_url}",
            }
        if "NameResolutionError" in error or "getaddrinfo failed" in error or "Failed to resolve" in error:
            return {
                "root_cause": "DNS could not resolve the configured InfoBhoomi API domain.",
                "proposed_solution": (
                    f"Check internet/DNS/VPN access to {base_url}, verify the domain name, or change "
                    "IB_BASE_URL in agents/.env to a running local/staging backend API URL."
                ),
                "debug_notes": "The request failed before credentials were validated.",
            }
        if "ConnectionError" in error or "Failed to establish a new connection" in error:
            return {
                "root_cause": "The configured InfoBhoomi API server is unreachable.",
                "proposed_solution": (
                    f"Start the backend server for {base_url}, or change IB_BASE_URL in agents/.env "
                    "to the running backend API URL, then rerun the check."
                ),
                "debug_notes": "The request failed before credentials were validated.",
            }
        if status_code in (401, 403):
            return {
                "root_cause": "The configured token or credentials were rejected by the API.",
                "proposed_solution": "Refresh IB_TOKEN or update IB_USERNAME/IB_PASSWORD in agents/.env, then rerun the check.",
                "debug_notes": f"Configured API target: {base_url}",
            }
        if status_code == 404:
            return {
                "root_cause": "The API target is reachable, but the expected auth endpoint was not found.",
                "proposed_solution": "Check that IB_BASE_URL points to the backend user API root, for example /api/user.",
                "debug_notes": f"Configured API target: {base_url}",
            }
        return {
            "root_cause": "Authentication failed for the configured API target.",
            "proposed_solution": "Check IB_BASE_URL and credentials in agents/.env, then rerun the check.",
            "debug_notes": f"Configured API target: {base_url}",
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _destructive_allowed(self) -> bool:
        return self.allow_destructive and AGENT_ENVIRONMENT in {"development", "staging"}

    def _response_evidence(self, response: requests.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        evidence: dict[str, Any] = {"content_type": content_type}
        if "json" in content_type:
            try:
                data = response.json()
                if isinstance(data, list):
                    evidence["shape"] = "list"
                    evidence["count"] = len(data)
                elif isinstance(data, dict):
                    evidence["shape"] = "object"
                    evidence["keys"] = sorted(list(data.keys()))[:20]
                    if "features" in data and isinstance(data["features"], list):
                        evidence["feature_count"] = len(data["features"])
                else:
                    evidence["shape"] = type(data).__name__
            except Exception:
                evidence["body_preview"] = response.text[:300]
        else:
            evidence["body_preview"] = response.text[:300]
        return evidence

    def _extract_params(self, path: str) -> list[str]:
        params = []
        current = ""
        active = False
        for char in path:
            if char == "{":
                active = True
                current = ""
            elif char == "}" and active:
                active = False
                params.append(current)
            elif active:
                current += char
        return params

    def _build_report(
        self,
        *,
        run_id: str,
        scope: dict[str, str],
        functions: list[str],
        results: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        started: float,
        status: str,
    ) -> dict[str, Any]:
        summary = {
            "total_functions": len(results),
            "passed": sum(1 for item in results if item.get("status") == "passed"),
            "partial": sum(1 for item in results if item.get("status") == "partial"),
            "failed": sum(1 for item in results if item.get("status") == "failed"),
            "issues": len(issues),
        }
        return {
            "run_id": run_id,
            "ran_at": utc_now(),
            "scope": scope,
            "environment": AGENT_ENVIRONMENT,
            "destructive_enabled": self._destructive_allowed(),
            "functions": functions,
            "status": status,
            "summary": summary,
            "results": results,
            "issues": issues,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def _persist_report(self, report: dict[str, Any]) -> dict[str, Any]:
        AGENT_RUN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = AGENT_RUN_REPORTS_DIR / f"{report['run_id']}.json"
        report["report_file"] = str(report_path)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        latest = AGENT_RUN_REPORTS_DIR / "latest.json"
        latest.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        self.memory.record_run(report)
        return report

    @staticmethod
    def latest_report() -> dict[str, Any]:
        latest = AGENT_RUN_REPORTS_DIR / "latest.json"
        if not latest.exists():
            return {}
        return json.loads(latest.read_text(encoding="utf-8"))
