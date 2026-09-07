"""
Base classes for Investigator agents.
=====================================
Every Investigator answers ONE question for ONE layer:
    "Given these sub-components, what evidence can I find of a problem?"

Read-only. No file edits. No API calls that mutate state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal


Severity = Literal["ok", "info", "warning", "error"]


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class InvestigationFinding:
    """One piece of evidence collected by an Investigator."""

    layer:                Literal["frontend", "backend", "db"]
    severity:             Severity
    title:                str
    detail:               str = ""
    affected_subcomponent: str = ""        # path or table
    evidence:             dict[str, Any] = field(default_factory=dict)
    found_at:             str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InvestigationResult:
    """Aggregate output of one Investigator run."""

    layer:    Literal["frontend", "backend", "db"]
    status:   Literal["ok", "warning", "error"]
    findings: list[InvestigationFinding] = field(default_factory=list)
    inspected_subcomponents: list[str]   = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer":    self.layer,
            "status":   self.status,
            "findings": [f.to_dict() for f in self.findings],
            "inspected_subcomponents": list(self.inspected_subcomponents),
            "elapsed_ms": self.elapsed_ms,
        }

    @classmethod
    def empty(cls, layer: Literal["frontend", "backend", "db"]) -> "InvestigationResult":
        return cls(layer=layer, status="ok")


class BaseInvestigator(ABC):
    """All Investigators share the same surface area."""

    layer: Literal["frontend", "backend", "db"] = "frontend"

    @abstractmethod
    def investigate(self, subcomponents: Iterable[Any]) -> InvestigationResult:
        """
        Inspect a list of layer-specific sub-components and return findings.
        Concrete subclasses accept their own ``Subcomponent`` dataclass type.
        """

    # ── Helpers shared by subclasses ──────────────────────────────────────────

    @staticmethod
    def _worst(findings: Iterable[InvestigationFinding]) -> Literal["ok", "warning", "error"]:
        worst: Literal["ok", "warning", "error"] = "ok"
        for f in findings:
            if f.severity == "error":
                return "error"
            if f.severity == "warning":
                worst = "warning"
        return worst
