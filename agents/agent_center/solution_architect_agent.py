"""
Solution Architect Agent (Step 6 of the pipeline).
===================================================
Takes the ArchitectOutput (Investigators' findings) plus the optional
ReportResult (plain-language report from Step 4) and produces a structured
Solution Plan grouped by layer (Frontend / Backend / DB / Migration).

Each SolutionItem carries:
  - rationale       (why this change addresses the problem)
  - file_path       (where to apply the change)
  - sub_component   (component/service/view/serializer name)
  - proposed_diff   (unified diff text — what the Implementer should apply)
  - proposed_full_text (optional full-file replacement when the diff is too risky)
  - risk_notes
  - tests_to_rerun  (function_ids or category names)
  - confidence      (high/medium/low)
  - fingerprint     (ChangeMemory dedup key — used in P4 + P6)

Decision #1: user picks Gemini or Claude per call.
Decision #5 / #7: ChangeMemory anti-suggestions are pulled from the Architect's
``prior_failed_strategies`` and passed to the LLM so it cannot re-propose a
fix that already failed (fine fingerprint match).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal

from agent_center.ai_provider import AIProviderError, pick_provider
from agent_center.cost_ledger import CostLedger
from agent_center.architect_agent import ArchitectOutput
from agent_center.symptom_fingerprint import fingerprint as build_fingerprint


Layer = Literal["frontend", "backend", "db", "migration"]
Confidence = Literal["high", "medium", "low"]


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class SolutionItem:
    item_id:             str
    layer:               Layer
    sub_component:       str
    file_path:           str
    rationale:           str
    proposed_diff:       str
    proposed_full_text:  str = ""
    risk_notes:          list[str] = field(default_factory=list)
    tests_to_rerun:      list[str] = field(default_factory=list)
    confidence:          Confidence = "medium"
    fingerprint:         str = ""
    user_edited:         bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SolutionPlan:
    queue_id:        str
    issue_id:        str
    headline:        str
    summary:         str
    items:           list[SolutionItem] = field(default_factory=list)
    llm_used:        str = ""
    llm_model:       str = ""
    input_tokens:    int = 0
    output_tokens:   int = 0
    fallback:        bool = False
    fallback_reason: str = ""
    user_amended:    bool = False
    generated_at:    str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["items"] = [i.to_dict() for i in self.items]
        return d

    def items_by_layer(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {"frontend": [], "backend": [], "db": [], "migration": []}
        for item in self.items:
            out.setdefault(item.layer, []).append(item.to_dict())
        return out


class SolutionArchitectAgent:
    """Builds a SolutionPlan from Investigator evidence."""

    def __init__(self, *, default_provider: str | None = None):
        self.default_provider = default_provider

    # ── Public API ────────────────────────────────────────────────────────────

    def propose(
        self,
        *,
        architect_output: ArchitectOutput,
        report_markdown:  str = "",
        llm_choice:       str | None = None,
    ) -> SolutionPlan:
        choice = llm_choice or self.default_provider
        try:
            provider = pick_provider(choice)
            data = self._call_llm(provider, architect_output, report_markdown)
            return self._plan_from_llm(architect_output, data, provider_name=provider.name, model=provider.model)
        except AIProviderError as exc:
            return self._plan_from_fallback(architect_output, fallback_reason=str(exc))
        except Exception as exc:  # safety: never crash the dashboard
            return self._plan_from_fallback(architect_output, fallback_reason=f"{type(exc).__name__}: {exc}")

    # ── LLM path ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(
        output: ArchitectOutput,
        report_markdown: str,
    ) -> str:
        # Compress investigator findings to keep the prompt small. We only send
        # warning/error severity findings (the LLM doesn't need "ok" noise).
        def _slim(findings):
            slim = []
            for f in findings:
                if f.severity in ("warning", "error"):
                    slim.append({
                        "severity": f.severity,
                        "title":    f.title,
                        "detail":   f.detail[:300],
                        "subcomponent": f.affected_subcomponent,
                        "evidence_keys": list((f.evidence or {}).keys())[:10],
                    })
            return slim[:12]

        prior = output.plan.prior_failed_strategies or []
        prior_compact = [
            {
                "file_path":     p.get("file_path"),
                "agent":         p.get("agent"),
                "fingerprint":   p.get("symptom_fingerprint"),
                "outcome":       p.get("verification_outcome"),
                "summary":       (p.get("diff") or "")[:200],
            }
            for p in prior[:10]
        ]

        return f"""
You are the Solution Architect for InfoBhoomi (Django 5.1 + DRF + PostGIS
backend, Angular 21 frontend). The Investigators have already gathered
evidence; your job is to propose specific, implementable code changes
grouped by layer.

ORIGINAL USER PROMPT:
"{output.plan.prompt}"

PLAIN-LANGUAGE REPORT (from the Reporter Agent):
{report_markdown or "(no report supplied)"}

ROUTED FUNCTIONS (component map entries):
{json.dumps(output.plan.component_map_entries, indent=2)[:4000]}

INVESTIGATOR FINDINGS (only warning/error, top 12 per layer):
- frontend:
{json.dumps(_slim(output.fe.findings), indent=2)}
- backend:
{json.dumps(_slim(output.be.findings), indent=2)}
- db:
{json.dumps(_slim(output.db.findings), indent=2)}

ALREADY-TRIED STRATEGIES THAT FAILED — DO NOT REPROPOSE THESE
(unless your new proposal is materially different):
{json.dumps(prior_compact, indent=2)}

Return ONLY a JSON object with this shape:
{{
  "headline":     "one-sentence summary of the fix plan",
  "summary":      "2-4 sentence overview",
  "items": [
    {{
      "layer":              "frontend" | "backend" | "db" | "migration",
      "sub_component":      "short name of the part you're changing",
      "file_path":          "path/relative/to/repo/root",
      "rationale":          "why this change fixes the issue",
      "proposed_diff":      "unified diff text",
      "proposed_full_text": "optional full file content if a diff is too risky",
      "risk_notes":         ["risk 1", "risk 2"],
      "tests_to_rerun":     ["function_id_or_category"],
      "confidence":         "high" | "medium" | "low"
    }}
  ]
}}

Constraints:
- Each file_path must live under either ``infoBhoomi-frontedend-div2/`` or ``InfoBhoomi_Backend_dev2/``.
- Prefer SMALL diffs. Empty proposed_diff is allowed only when proposed_full_text is set.
- 1-6 items total. If the evidence is insufficient, return fewer items with confidence "low" and explain in rationale.
- Do not include secrets, tokens, or passwords.
""".strip()

    def _call_llm(
        self,
        provider,
        output: ArchitectOutput,
        report_markdown: str,
    ) -> dict[str, Any]:
        prompt = self._build_prompt(output, report_markdown)
        data = provider.generate_json(prompt, max_tokens=4500, temperature=0.2)
        if not isinstance(data, dict):
            raise AIProviderError(f"LLM returned non-object response: {type(data).__name__}")
        usage = getattr(provider, "last_usage", {}) or {}
        try:
            CostLedger().record(
                step="solution_architect",
                provider=usage.get("provider", provider.name),
                model=usage.get("model", provider.model),
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                queue_id=output.plan.queue_id,
                linked_issue_id=output.issue.get("issue_id", ""),
            )
        except Exception:
            pass
        return data

    def _plan_from_llm(
        self,
        output: ArchitectOutput,
        data: dict[str, Any],
        *,
        provider_name: str,
        model: str,
    ) -> SolutionPlan:
        items = []
        for raw in data.get("items", []) or []:
            item = self._build_item(raw, output)
            if item is not None:
                items.append(item)
        return SolutionPlan(
            queue_id= output.plan.queue_id,
            issue_id= output.issue.get("issue_id", ""),
            headline= str(data.get("headline", "")),
            summary=  str(data.get("summary", "")),
            items=    items,
            llm_used= provider_name,
            llm_model=model,
        )

    @staticmethod
    def _build_item(raw: dict[str, Any], output: ArchitectOutput) -> SolutionItem | None:
        layer = str(raw.get("layer", "")).lower()
        if layer not in {"frontend", "backend", "db", "migration"}:
            return None
        file_path = str(raw.get("file_path", "")).strip()
        if not file_path:
            return None
        # Compute the fingerprint we'll persist into the ChangeMemory ledger
        # when this item gets applied (P4). Architect already tagged a function_id;
        # we use the first one for the fingerprint key.
        fn_id = (output.plan.selected_function_ids or [""])[0]
        fp = build_fingerprint(
            function_id=fn_id,
            component_kind=layer if layer != "migration" else "db",
            endpoint="",
            http_method="",
            status_code=None,
            missing_field=str(raw.get("sub_component", "")).strip(),
        )
        return SolutionItem(
            item_id=          f"SI-{uuid.uuid4().hex[:8].upper()}",
            layer=            layer,  # type: ignore[arg-type]
            sub_component=    str(raw.get("sub_component", "")).strip(),
            file_path=        file_path,
            rationale=        str(raw.get("rationale", "")).strip(),
            proposed_diff=    str(raw.get("proposed_diff", "")),
            proposed_full_text=str(raw.get("proposed_full_text", "")),
            risk_notes=       [str(r) for r in raw.get("risk_notes", []) or []][:6],
            tests_to_rerun=   [str(t) for t in raw.get("tests_to_rerun", []) or []][:6],
            confidence=       str(raw.get("confidence", "medium")).lower() if str(raw.get("confidence", "")).lower() in {"high","medium","low"} else "medium",  # type: ignore[arg-type]
            fingerprint=      fp,
        )

    # ── Local fallback ────────────────────────────────────────────────────────

    def _plan_from_fallback(
        self,
        output: ArchitectOutput,
        *,
        fallback_reason: str,
    ) -> SolutionPlan:
        """
        When no LLM is available, produce an investigative-only plan.
        Each Investigator finding with severity error/warning becomes a
        low-confidence item asking the developer to look at that file.
        """
        items: list[SolutionItem] = []
        fn_id = (output.plan.selected_function_ids or [""])[0]

        for layer_key, layer_label, layer_result in (
            ("frontend", "frontend", output.fe),
            ("backend",  "backend",  output.be),
            ("db",       "db",       output.db),
        ):
            for f in layer_result.findings:
                if f.severity not in ("error", "warning"):
                    continue
                file_path = str(f.evidence.get("file") or f.affected_subcomponent or "")
                if not file_path:
                    continue
                fp = build_fingerprint(
                    function_id=fn_id,
                    component_kind=layer_key,
                    endpoint="",
                    http_method="",
                    status_code=None,
                    missing_field=f.title,
                )
                items.append(SolutionItem(
                    item_id=          f"SI-{uuid.uuid4().hex[:8].upper()}",
                    layer=            layer_label,  # type: ignore[arg-type]
                    sub_component=    f.affected_subcomponent or "",
                    file_path=        file_path,
                    rationale=        f"Investigator flagged: {f.title}. {f.detail or ''}".strip(),
                    proposed_diff=    "",
                    proposed_full_text="",
                    risk_notes=       ["No LLM was available; this is an investigative pointer, not a confident patch."],
                    tests_to_rerun=   [fn_id] if fn_id else [],
                    confidence=       "low",
                    fingerprint=      fp,
                ))
                if len(items) >= 6:
                    break
            if len(items) >= 6:
                break

        return SolutionPlan(
            queue_id=        output.plan.queue_id,
            issue_id=        output.issue.get("issue_id", ""),
            headline=        "Investigative-only plan (no LLM available).",
            summary=         "The Solution Architect could not reach a configured LLM. The items below are investigative pointers, not patches — open each file and follow the Investigator finding.",
            items=           items,
            llm_used=        "local-fallback",
            llm_model=       "",
            fallback=        True,
            fallback_reason= fallback_reason,
        )


# ── Helpers used by the dashboard when persisting user edits ─────────────────

def merge_user_edits(plan_dict: dict[str, Any], edits: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Merge user-amended fields onto an existing plan dict.
    Editable fields per item: rationale, proposed_diff, proposed_full_text,
    risk_notes, tests_to_rerun, confidence.
    """
    by_id = {item["item_id"]: item for item in plan_dict.get("items", [])}
    EDITABLE = {"rationale", "proposed_diff", "proposed_full_text",
                "risk_notes", "tests_to_rerun", "confidence"}
    for edit in edits or []:
        item_id = edit.get("item_id")
        if not item_id or item_id not in by_id:
            continue
        target = by_id[item_id]
        for key in EDITABLE:
            if key in edit:
                target[key] = edit[key]
        target["user_edited"] = True
    plan_dict["user_amended"] = True
    return plan_dict
