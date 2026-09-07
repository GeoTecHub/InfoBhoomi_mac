"""
Claude provider — wraps the anthropic Python SDK already used by the legacy
research_agent.py.
"""

from __future__ import annotations

from typing import Any

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from agent_center.ai_provider.base import (
    AIProvider,
    AIProviderError,
    LLMResponse,
    parse_loose_json,
)


class ClaudeProvider(AIProvider):
    name = "claude"

    def __init__(self, api_key: str = "", model: str = ""):
        super().__init__()
        self._api_key = api_key or ANTHROPIC_API_KEY
        self._model = model or CLAUDE_MODEL
        self._client: Any = None  # lazy import to avoid hard dependency at module load

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    def _client_ref(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except Exception as exc:  # pragma: no cover - runtime install error
                raise AIProviderError(
                    "anthropic package not installed; run `pip install anthropic`."
                ) from exc
            if not self._api_key:
                raise AIProviderError("ANTHROPIC_API_KEY is not configured.")
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    # ── Internal request ──────────────────────────────────────────────────────

    def _create(self, prompt: str, *, max_tokens: int, temperature: float) -> Any:
        try:
            return self._client_ref().messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(f"Claude API error: {type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _extract_text(response: Any) -> str:
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                return block.text
        raise AIProviderError("Claude response did not contain a text block.")

    @staticmethod
    def _extract_usage(response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        return int(getattr(usage, "input_tokens", 0)), int(getattr(usage, "output_tokens", 0))

    # ── Public API ────────────────────────────────────────────────────────────

    def _record_usage(self, in_tok: int, out_tok: int) -> None:
        self.last_usage = {
            "input_tokens": in_tok, "output_tokens": out_tok,
            "model": self._model, "provider": self.name,
        }

    def generate_text(self, prompt: str, *, max_tokens: int = 2000, temperature: float = 0.2) -> LLMResponse:
        resp = self._create(prompt, max_tokens=max_tokens, temperature=temperature)
        in_tok, out_tok = self._extract_usage(resp)
        self._record_usage(in_tok, out_tok)
        return LLMResponse(
            text=self._extract_text(resp),
            input_tokens=in_tok, output_tokens=out_tok,
            model=self._model, provider=self.name,
        )

    def generate_json(self, prompt: str, *, max_tokens: int = 2000, temperature: float = 0.2) -> dict[str, Any]:
        json_prompt = (
            prompt.strip()
            + "\n\nRespond with a single JSON object only — no markdown fences, no prose."
        )
        resp = self._create(json_prompt, max_tokens=max_tokens, temperature=temperature)
        text = self._extract_text(resp)
        in_tok, out_tok = self._extract_usage(resp)
        self._record_usage(in_tok, out_tok)
        return parse_loose_json(text)
