"""
Plain-Language Reporter Agent (Step 4 of the pipeline).
========================================================
Takes the ArchitectAgent output (FE / BE / DB findings) plus the original
prompt and produces a plain-language report for the user.

Decision #1: the user picks Gemini or Claude per call. The picker passes
``llm_choice`` here. If no LLM is available (no API key) we fall back to a
deterministic local summary so the dashboard always shows *something*.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from agent_center.ai_provider import AIProviderError, pick_provider
from agent_center.cost_ledger import CostLedger
from agent_center.architect_agent import ArchitectOutput


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass
class LayerSummary:
    layer:    str
    status:   str
    headline: str
    bullets:  list[str] = field(default_factory=list)


@dataclass
class ReportResult:
    queue_id:      str
    issue_id:      str
    overall:       str                       # "ok" | "warning" | "error"
    headline:      str
    body_markdown: str
    layers:        list[LayerSummary] = field(default_factory=list)
    next_actions:  list[str] = field(default_factory=list)
    llm_used:      str = ""
    llm_model:     str = ""
    input_tokens:  int = 0
    output_tokens: int = 0
    fallback:      bool = False              # True when LLM unavailable
    fallback_reason: str = ""
    generated_at:  str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["layers"] = [asdict(l) for l in self.layers]
        return d


class ReporterAgent:
    """Generates the plain-language card shown after Step 4."""

    def __init__(self, *, default_provider: str | None = None):
        self.default_provider = default_provider

    # ── Public API ────────────────────────────────────────────────────────────

    def report(self, output: ArchitectOutput, *, llm_choice: str | None = None) -> ReportResult:
        choice = llm_choice or self.default_provider
        try:
            provider = pick_provider(choice)
            llm_response = self._call_llm(provider, output)
            return self._build_from_llm(output, llm_response, provider_name=provider.name, model=provider.model)
        except AIProviderError as exc:
            return self._build_from_fallback(output, fallback_reason=str(exc))
        except Exception as exc:  # safety net — never crash the dashboard
            return self._build_from_fallback(output, fallback_reason=f"{type(exc).__name__}: {exc}")

    # ── LLM path ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(output: ArchitectOutput) -> str:
        return f"""
You are a senior engineer writing a brief, plain-language report for a
non-technical product owner.

The original problem reported by the user:
"{output.plan.prompt}"

Three Investigators have just run against InfoBhoomi (Django + PostGIS
backend, Angular frontend). Their structured findings are below as JSON.

For each layer (Frontend, Backend, Database) summarise in one short sentence
what looks fine and what looks suspicious. Avoid jargon when possible.
Then propose 2-3 concrete next investigation steps.

Return ONLY a JSON object with this exact shape:
{{
  "headline": "one-sentence summary the user reads first",
  "overall":  "ok" | "warning" | "error",
  "frontend": {{ "status": "ok" | "warning" | "error", "headline": "...", "bullets": ["...", "..."] }},
  "backend":  {{ "status": "ok" | "warning" | "error", "headline": "...", "bullets": ["...", "..."] }},
  "database": {{ "status": "ok" | "warning" | "error", "headline": "...", "bullets": ["...", "..."] }},
  "next_actions": ["...", "...", "..."]
}}

Findings:
{json.dumps(output.summary(), indent=2)}

FE findings (truncated to top 8):
{json.dumps([f.to_dict() for f in output.fe.findings[:8]], indent=2)}

BE findings (top 8):
{json.dumps([f.to_dict() for f in output.be.findings[:8]], indent=2)}

DB findings (top 8):
{json.dumps([f.to_dict() for f in output.db.findings[:8]], indent=2)}
""".strip()

    def _call_llm(self, provider, output: ArchitectOutput) -> dict[str, Any]:
        prompt = self._build_prompt(output)
        data = provider.generate_json(prompt, max_tokens=1500, temperature=0.2)
        if not isinstance(data, dict):
            raise AIProviderError(f"LLM returned non-object response: {type(data).__name__}")
        usage = getattr(provider, "last_usage", {}) or {}
        try:
            CostLedger().record(
                step="reporter",
                provider=usage.get("provider", provider.name),
                model=usage.get("model", provider.model),
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                queue_id=output.plan.queue_id,
                linked_issue_id=output.issue.get("issue_id", ""),
            )
        except Exception:
            pass  # ledger must never break the report
        return data

    def _build_from_llm(
        self,
        output: ArchitectOutput,
        data: dict[str, Any],
        *,
        provider_name: str,
        model: str,
    ) -> ReportResult:
        layers = []
        for layer_key, layer_label in (("frontend", "Frontend"), ("backend", "Backend"), ("database", "Database")):
            entry = data.get(layer_key) or {}
            layers.append(LayerSummary(
                layer=layer_label,
                status=str(entry.get("status", "ok")),
                headline=str(entry.get("headline", "")),
                bullets=[str(b) for b in entry.get("bullets", [])][:6],
            ))
        body = self._render_markdown(
            headline=str(data.get("headline", "")),
            overall=str(data.get("overall", "ok")),
            layers=layers,
            next_actions=[str(a) for a in data.get("next_actions", [])],
            prompt=output.plan.prompt,
        )
        return ReportResult(
            queue_id=output.plan.queue_id,
            issue_id=output.issue.get("issue_id", ""),
            overall=str(data.get("overall", "ok")),
            headline=str(data.get("headline", "")),
            body_markdown=body,
            layers=layers,
            next_actions=[str(a) for a in data.get("next_actions", [])][:6],
            llm_used=provider_name,
            llm_model=model,
        )

    # ── Local fallback ────────────────────────────────────────────────────────

    def _build_from_fallback(
        self,
        output: ArchitectOutput,
        *,
        fallback_reason: str,
    ) -> ReportResult:
        worst = self._overall_status(output)
        layers = [
            self._fallback_layer("Frontend", output.fe),
            self._fallback_layer("Backend",  output.be),
            self._fallback_layer("Database", output.db),
        ]
        next_actions = self._fallback_next_actions(output)
        headline = self._fallback_headline(output, worst)
        body = self._render_markdown(
            headline=headline,
            overall=worst,
            layers=layers,
            next_actions=next_actions,
            prompt=output.plan.prompt,
        )
        return ReportResult(
            queue_id=output.plan.queue_id,
            issue_id=output.issue.get("issue_id", ""),
            overall=worst,
            headline=headline,
            body_markdown=body,
            layers=layers,
            next_actions=next_actions,
            llm_used="local-fallback",
            llm_model="",
            fallback=True,
            fallback_reason=fallback_reason,
        )

    @staticmethod
    def _overall_status(output: ArchitectOutput) -> str:
        statuses = [output.fe.status, output.be.status, output.db.status]
        if "error" in statuses:
            return "error"
        if "warning" in statuses:
            return "warning"
        return "ok"

    @staticmethod
    def _fallback_layer(label: str, result) -> LayerSummary:
        bullets: list[str] = []
        for f in result.findings:
            if f.severity in ("warning", "error"):
                line = f"{f.severity.upper()}: {f.title}"
                if f.affected_subcomponent:
                    line += f"  ({f.affected_subcomponent})"
                bullets.append(line)
            if len(bullets) >= 6:
                break
        if not bullets:
            bullets = [f"All {len(result.inspected_subcomponents)} sub-component(s) inspected without errors."]
        headline = {
            "ok":      f"{label} looks healthy.",
            "warning": f"{label} has soft issues to review.",
            "error":   f"{label} has hard failures that need attention.",
        }[result.status]
        return LayerSummary(layer=label, status=result.status, headline=headline, bullets=bullets)

    @staticmethod
    def _fallback_headline(output: ArchitectOutput, overall: str) -> str:
        n = len(output.plan.selected_function_ids)
        if overall == "error":
            return f"Investigators found hard failures across {n} routed function(s)."
        if overall == "warning":
            return f"Investigators flagged warnings across {n} routed function(s); no hard failures."
        return f"Investigators found no issues across {n} routed function(s)."

    @staticmethod
    def _fallback_next_actions(output: ArchitectOutput) -> list[str]:
        actions = []
        if output.fe.status == "error":
            actions.append("Open the Frontend findings card and review missing or unparseable files first.")
        if output.be.status == "error":
            actions.append("Open the Backend findings card; py_compile flagged a syntax problem.")
        if output.db.status == "error":
            actions.append("Open the Database findings card; a key_field probe failed or a table was unreachable.")
        if not actions:
            actions.append("If you still see the bug, click 'Resolve this issue' to ask the Solution Architect for a plan.")
        return actions[:6]

    # ── Markdown rendering ────────────────────────────────────────────────────

    @staticmethod
    def _render_markdown(
        *,
        headline: str,
        overall: str,
        layers: list[LayerSummary],
        next_actions: list[str],
        prompt: str,
    ) -> str:
        emoji = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
        out = []
        out.append(f"**{headline or 'Investigation complete.'}**  _(overall: {emoji.get(overall, overall.upper())})_")
        out.append("")
        out.append(f"> Original prompt: _{prompt}_")
        out.append("")
        for layer in layers:
            tag = emoji.get(layer.status, layer.status.upper())
            out.append(f"### {layer.layer}  ({tag})")
            if layer.headline:
                out.append(layer.headline)
            for b in layer.bullets:
                out.append(f"- {b}")
            out.append("")
        if next_actions:
            out.append("### Suggested next steps")
            for a in next_actions:
                out.append(f"- {a}")
        return "\n".join(out).rstrip() + "\n"
