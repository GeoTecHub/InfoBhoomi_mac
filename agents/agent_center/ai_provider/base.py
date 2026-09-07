"""
LLM provider abstraction.
=========================
Both the Plain-Language Reporter (Step 4) and the Solution Architect Agent
(Step 6) call into providers conforming to this ABC. Token usage is reported
back so the dashboard can show a per-round cost ledger.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class AIProviderError(RuntimeError):
    """Raised on transport, auth, parsing, or response-shape failures."""


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AIProvider(ABC):
    """Common interface for any LLM provider used by the pipeline."""

    name: str = "base"

    def __init__(self):
        # Populated by every generate_*() call so callers can read usage after
        # generate_json() (which would otherwise lose it). Format:
        #   {"input_tokens", "output_tokens", "model", "provider"}
        self.last_usage: dict[str, object] = {}

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    def generate_text(self, prompt: str, *, max_tokens: int = 2000, temperature: float = 0.2) -> LLMResponse: ...

    @abstractmethod
    def generate_json(self, prompt: str, *, max_tokens: int = 2000, temperature: float = 0.2) -> dict[str, Any]: ...


# ── Prompt builders shared across providers ──────────────────────────────────

def build_fix_prompt(issue: dict[str, Any]) -> str:
    """
    Original prompt schema kept verbatim for backward-compat with the existing
    FixProposalAgent (which imports it from agent_center.ai_provider).
    """
    return f"""
You are helping debug InfoBhoomi, a municipal land administration Web-GIS.

Return only JSON with this exact object shape:
{{
  "title": "short fix proposal title",
  "summary": "concise issue summary",
  "root_cause": "most likely root cause based on evidence",
  "risk_notes": ["risk 1", "risk 2"],
  "implementation_plan": ["step 1", "step 2", "step 3"],
  "patch_preview": "unified diff preview if enough evidence exists, otherwise empty string",
  "suspected_files": ["path/to/file.py"],
  "tests_to_rerun": ["function-or-category"]
}}

Do not invent a confident patch when evidence is insufficient. In that case,
leave patch_preview empty and make implementation_plan investigative.
Never include secrets, API keys, passwords, or tokens.

Issue evidence:
{json.dumps(issue, indent=2, ensure_ascii=False)}
""".strip()


def parse_loose_json(text: str) -> dict[str, Any]:
    """
    Best-effort JSON extraction.
    Handles models that wrap JSON in markdown fences or add prose around it.
    Raises AIProviderError on irrecoverable failure.
    """
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` style fences
        fence = text.find("\n")
        if fence != -1:
            text = text[fence + 1 :]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise AIProviderError(f"Could not parse JSON from response: {exc}") from exc
        raise AIProviderError("Response did not contain a JSON object.")
