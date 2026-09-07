"""
Fine-grained symptom fingerprint.
=================================
Identifies "the same problem" across debugging rounds so the Change Memory
agent can answer ``was_attempted(...)`` and the Solution Architect can avoid
re-proposing fixes that already failed.

Decision #5 in the locked plan: fine-grained fingerprint =
    function_id | component_kind | endpoint | http_method | status_code | missing_field

Two issues are considered the same iff every field above matches exactly.
Any difference (e.g. different missing_field, different status_code) makes
the fingerprint distinct, allowing the agents to retry with new context.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal


ComponentKind = Literal["frontend", "backend", "db", "unknown"]


@dataclass(frozen=True)
class Symptom:
    function_id:    str  = ""
    component_kind: ComponentKind = "unknown"
    endpoint:       str  = ""
    http_method:    str  = ""
    status_code:    int | None = None
    missing_field:  str  = ""

    def fingerprint(self) -> str:
        return fingerprint(
            function_id=self.function_id,
            component_kind=self.component_kind,
            endpoint=self.endpoint,
            http_method=self.http_method,
            status_code=self.status_code,
            missing_field=self.missing_field,
        )


def fingerprint(
    function_id:    str | None = "",
    component_kind: str | None = "unknown",
    endpoint:       str | None = "",
    http_method:    str | None = "",
    status_code:    int | None = None,
    missing_field:  str | None = "",
) -> str:
    """
    Build a deterministic, human-readable fingerprint string.
    Format: ``function_id|component_kind|endpoint|HTTP_METHOD|status_code|missing_field``
    """
    parts = [
        (function_id or "").strip(),
        (component_kind or "unknown").strip().lower(),
        _normalise_endpoint(endpoint or ""),
        (http_method or "").strip().upper(),
        str(status_code) if status_code is not None else "",
        (missing_field or "").strip(),
    ]
    return "|".join(parts)


def fingerprint_hash(fp: str) -> str:
    """Short stable hash for indexing fingerprints in JSON."""
    return hashlib.sha1(fp.encode("utf-8")).hexdigest()[:12]


def _normalise_endpoint(endpoint: str) -> str:
    """
    Drop trailing slash variation and strip query strings, but keep the path
    template (``/api/user/lnd-admin-info/su_id={su_id}/`` stays as-is so that
    parameterised endpoints fingerprint identically across calls).
    """
    endpoint = endpoint.split("?", 1)[0]
    endpoint = endpoint.rstrip("/")
    return endpoint


def from_api_evidence(
    *,
    function_id: str,
    api_evidence: dict | None = None,
    component_kind: str = "backend",
    missing_field: str = "",
) -> Symptom:
    """
    Convenience: build a Symptom from a FunctionQAAgent ``api_check`` dict.
    Falls back to empty values when fields are missing.
    """
    api_evidence = api_evidence or {}
    return Symptom(
        function_id=function_id,
        component_kind=component_kind,  # type: ignore[arg-type]
        endpoint=str(api_evidence.get("path", "")),
        http_method=str(api_evidence.get("method", "")),
        status_code=api_evidence.get("status_code"),
        missing_field=missing_field,
    )
