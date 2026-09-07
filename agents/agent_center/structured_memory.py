from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from config import AGENT_EVIDENCE_MAX_BYTES, AGENT_MEMORY_FILE, STATE_DIR
from agent_center._atomic import atomic_write_json, file_lock, read_json


ISSUE_STATUSES = {"open", "planned", "fixed", "rejected", "recurring"}

_SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "password", "passwd", "pwd", "pass",
    "token", "api_key", "apikey",
    "authorization", "auth_header",
    "cookie", "set_cookie", "set-cookie",
    "x-csrftoken", "csrftoken", "csrf_token",
    "secret", "secret_key", "client_secret",
    "private_key", "session_key",
)

_DROP_HEADER_NAMES: frozenset[str] = frozenset({
    "authorization", "cookie", "set-cookie", "x-csrftoken",
    "x-api-key", "proxy-authorization",
})

_TOKEN_PATTERN = re.compile(
    r"(Token|Bearer)\s+[A-Za-z0-9_\-\.=+/]{8,}",
    re.IGNORECASE,
)
_BASIC_AUTH_PATTERN = re.compile(
    r"Basic\s+[A-Za-z0-9+/=]{8,}",
    re.IGNORECASE,
)
_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+")


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class StructuredMemory:
    """Persistent issue memory for function QA and debugging."""

    def __init__(self, path: Path = AGENT_MEMORY_FILE):
        self.path = Path(path)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        loaded = read_json(self.path, default=None)
        if isinstance(loaded, dict) and loaded:
            loaded.setdefault("version", 1)
            loaded.setdefault("issues", [])
            loaded.setdefault("runs", [])
            loaded.setdefault("fixes", [])
            return loaded
        return {"version": 1, "issues": [], "runs": [], "fixes": []}

    def save(self) -> None:
        with file_lock(self.path):
            atomic_write_json(self.path, self.data)

    def record_run(self, report: dict[str, Any]) -> None:
        compact = {
            "run_id": report.get("run_id"),
            "ran_at": report.get("ran_at"),
            "scope": report.get("scope"),
            "status": report.get("status"),
            "summary": report.get("summary", {}),
            "report_file": report.get("report_file", ""),
        }
        self.data.setdefault("runs", []).insert(0, compact)
        self.data["runs"] = self.data["runs"][:100]
        self.save()

    def record_issue(
        self,
        *,
        function_category: str,
        sub_function: str,
        symptom: str,
        detected_by: str,
        api_evidence=None,
        db_evidence=None,
        root_cause: str = "",
        proposed_solution: str = "",
        debug_notes: str = "",
        status: str = "open",
        files_changed=None,
        test_results_before=None,
        test_results_after=None,
        approved_fix=None,
    ) -> dict[str, Any]:
        if status not in ISSUE_STATUSES:
            status = "open"

        recurring = self._find_open_issue(function_category, sub_function, symptom)
        now = utc_now()
        if recurring:
            recurring["status"] = "recurring"
            recurring["last_seen_at"] = now
            recurring["api_evidence"] = self._redact(api_evidence)
            recurring["db_evidence"] = self._redact(db_evidence)
            if root_cause:
                recurring["root_cause"] = root_cause
            if proposed_solution:
                recurring["proposed_solution"] = proposed_solution
            if approved_fix:
                recurring["approved_fix"] = self._redact(approved_fix)
            if files_changed:
                recurring["files_changed"] = files_changed
            if test_results_before:
                recurring["test_results_before"] = self._redact(test_results_before)
            if test_results_after:
                recurring["test_results_after"] = self._redact(test_results_after)
            if debug_notes:
                recurring["debug_notes"] = self._merge_debug_notes(
                    recurring.get("debug_notes", ""), debug_notes
                )
            self.save()
            return recurring

        issue = {
            "issue_id": f"ISS-{uuid.uuid4().hex[:10].upper()}",
            "function_category": function_category,
            "sub_function": sub_function,
            "symptom": symptom,
            "detected_by": detected_by,
            "api_evidence": self._redact(api_evidence),
            "db_evidence": self._redact(db_evidence),
            "root_cause": root_cause,
            "proposed_solution": proposed_solution,
            "approved_fix": self._redact(approved_fix or {}),
            "files_changed": files_changed or [],
            "test_results_before": self._redact(test_results_before),
            "test_results_after": self._redact(test_results_after),
            "status": status,
            "last_seen_at": now,
            "debug_notes": debug_notes,
        }
        self.data.setdefault("issues", []).insert(0, issue)
        self.data["issues"] = self.data["issues"][:500]
        self.save()
        return issue

    def update_issue(self, issue_id: str, **updates: Any) -> dict[str, Any]:
        for issue in self.data.setdefault("issues", []):
            if issue.get("issue_id") == issue_id:
                for key, value in updates.items():
                    if key == "status" and value not in ISSUE_STATUSES:
                        continue
                    issue[key] = self._redact(value)
                issue["last_seen_at"] = utc_now()
                self.save()
                return issue
        raise KeyError(issue_id)

    def list_issues(self, status: str | None = None, query: str = "") -> list[dict[str, Any]]:
        issues = self.data.get("issues", [])
        if status:
            issues = [i for i in issues if i.get("status") == status]
        if query:
            q = query.lower()
            issues = [i for i in issues if q in json.dumps(i, ensure_ascii=False).lower()]
        return issues

    def record_fix(self, fix: dict[str, Any]) -> dict[str, Any]:
        item = dict(fix)
        item.setdefault("fix_id", f"FIX-{uuid.uuid4().hex[:10].upper()}")
        item.setdefault("created_at", utc_now())
        item.setdefault("status", "planned")
        item = self._redact(item)
        self.data.setdefault("fixes", []).insert(0, item)
        self.save()
        return item

    def update_fix(self, fix_id: str, **updates: Any) -> dict[str, Any]:
        for fix in self.data.setdefault("fixes", []):
            if fix.get("fix_id") == fix_id:
                fix.update(self._redact(updates))
                fix["updated_at"] = utc_now()
                self.save()
                return fix
        raise KeyError(fix_id)

    def _find_open_issue(self, category: str, sub_function: str, symptom: str):
        needle = symptom.strip().lower()
        for issue in self.data.get("issues", []):
            if (
                issue.get("function_category") == category
                and issue.get("sub_function") == sub_function
                and issue.get("symptom", "").strip().lower() == needle
                and issue.get("status") in {"open", "planned", "recurring"}
            ):
                return issue
        return None

    def _redact(self, value: Any) -> Any:
        return self._redact_inner(value, depth=0)

    def _redact_inner(self, value: Any, depth: int) -> Any:
        if depth > 12:
            return "<redacted: depth-limit>"
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if not isinstance(k, str):
                    out[k] = self._redact_inner(v, depth + 1)
                    continue
                if k.lower() in _DROP_HEADER_NAMES:
                    out[k] = "<redacted>"
                elif self._sensitive(k):
                    out[k] = "<redacted>"
                else:
                    out[k] = self._redact_inner(v, depth + 1)
            return self._truncate_if_huge(out)
        if isinstance(value, list):
            redacted_list = [self._redact_inner(v, depth + 1) for v in value]
            return self._truncate_if_huge(redacted_list)
        if isinstance(value, str):
            return self._truncate_if_huge(self._redact_string(value))
        return value

    @staticmethod
    def _redact_string(text: str) -> str:
        text = _TOKEN_PATTERN.sub(lambda m: f"{m.group(1)} <redacted>", text)
        text = _BASIC_AUTH_PATTERN.sub("Basic <redacted>", text)
        text = _JWT_PATTERN.sub("<redacted-jwt>", text)
        return text

    @staticmethod
    def _truncate_if_huge(obj: Any) -> Any:
        try:
            blob = json.dumps(obj, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return obj
        if len(blob.encode("utf-8")) <= AGENT_EVIDENCE_MAX_BYTES:
            return obj
        if isinstance(obj, str):
            return obj[: AGENT_EVIDENCE_MAX_BYTES] + "...<truncated>"
        return {"<truncated>": True, "original_size_bytes": len(blob.encode("utf-8"))}

    def _merge_debug_notes(self, existing: str, new_note: str) -> str:
        notes = [line.strip() for line in (existing or "").splitlines() if line.strip()]
        for line in (new_note or "").splitlines():
            line = line.strip()
            if line and line not in notes:
                notes.append(line)
        return "\n".join(notes)

    @staticmethod
    def _sensitive(key: str) -> bool:
        lowered = key.lower()
        return any(needle in lowered for needle in _SENSITIVE_KEY_SUBSTRINGS)
