"""
Gemini provider — google generativelanguage v1beta REST client.
Conforms to AIProvider so the rest of the pipeline doesn't care which LLM
is in use.
"""

from __future__ import annotations

from typing import Any

import requests

from config import GEMINI_API_KEY, GEMINI_MODEL
from agent_center.ai_provider.base import (
    AIProvider,
    AIProviderError,
    LLMResponse,
    parse_loose_json,
)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str = "", model: str = ""):
        super().__init__()
        self._api_key = api_key or GEMINI_API_KEY
        self._model = model or GEMINI_MODEL

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    # ── Internal request ──────────────────────────────────────────────────────

    def _post(self, prompt: str, *, max_tokens: int, temperature: float, json_mode: bool) -> dict[str, Any]:
        if not self._api_key:
            raise AIProviderError("GEMINI_API_KEY is not configured.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        gen_cfg: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_cfg,
        }
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise AIProviderError(f"Gemini request transport error: {exc}") from exc
        if resp.status_code >= 400:
            raise AIProviderError(f"Gemini API HTTP {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(f"Gemini response shape unexpected: {exc}") from exc

    @staticmethod
    def _extract_usage(data: dict[str, Any]) -> tuple[int, int]:
        usage = data.get("usageMetadata") or {}
        return int(usage.get("promptTokenCount", 0)), int(usage.get("candidatesTokenCount", 0))

    # ── Public API ────────────────────────────────────────────────────────────

    def _record_usage(self, in_tok: int, out_tok: int) -> None:
        self.last_usage = {
            "input_tokens": in_tok, "output_tokens": out_tok,
            "model": self._model, "provider": self.name,
        }

    def generate_text(self, prompt: str, *, max_tokens: int = 2000, temperature: float = 0.2) -> LLMResponse:
        data = self._post(prompt, max_tokens=max_tokens, temperature=temperature, json_mode=False)
        text = self._extract_text(data)
        in_tok, out_tok = self._extract_usage(data)
        self._record_usage(in_tok, out_tok)
        return LLMResponse(
            text=text, input_tokens=in_tok, output_tokens=out_tok,
            model=self._model, provider=self.name,
        )

    def generate_json(self, prompt: str, *, max_tokens: int = 2000, temperature: float = 0.2) -> dict[str, Any]:
        data = self._post(prompt, max_tokens=max_tokens, temperature=temperature, json_mode=True)
        text = self._extract_text(data)
        in_tok, out_tok = self._extract_usage(data)
        self._record_usage(in_tok, out_tok)
        return parse_loose_json(text)
