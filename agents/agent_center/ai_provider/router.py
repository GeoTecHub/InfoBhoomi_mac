"""
LLM router: maps a (step, user_choice) → AIProvider instance, with fallback.

Step 4 (Plain-Language Reporter)  → user picks per-call (decision #1)
Step 6 (Solution Architect Agent) → user picks per-call (decision #1)
Default if user dismisses picker  → AGENT_DEFAULT_LLM env, then "gemini"
"""

from __future__ import annotations

from typing import Literal

from config import AGENT_DEFAULT_LLM
from agent_center.ai_provider.base import AIProvider, AIProviderError
from agent_center.ai_provider.gemini import GeminiProvider
from agent_center.ai_provider.claude import ClaudeProvider


ProviderName = Literal["gemini", "claude", "auto"]


def pick_provider(user_choice: str | None = None) -> AIProvider:
    """
    Resolve the user's selection (or the configured default) to an instance.

    Order of preference:
      1. explicit ``user_choice`` if it identifies an available provider
      2. AGENT_DEFAULT_LLM if it identifies an available provider
      3. any available provider (gemini first, then claude)
      4. raise AIProviderError if none is configured

    "Available" means the relevant API key is present in env.
    """
    requested = (user_choice or AGENT_DEFAULT_LLM or "").lower().strip()

    candidates: list[AIProvider]
    if requested == "claude":
        candidates = [ClaudeProvider(), GeminiProvider()]
    elif requested == "gemini":
        candidates = [GeminiProvider(), ClaudeProvider()]
    else:
        candidates = [GeminiProvider(), ClaudeProvider()]

    for provider in candidates:
        if provider.available:
            return provider

    raise AIProviderError(
        "No LLM provider is configured. Set GEMINI_API_KEY or ANTHROPIC_API_KEY in agents/.env."
    )


def list_provider_status() -> list[dict]:
    """Used by the dashboard /api/llm/status endpoint."""
    return [
        {"name": "gemini", "available": GeminiProvider().available, "model": GeminiProvider().model},
        {"name": "claude", "available": ClaudeProvider().available, "model": ClaudeProvider().model},
    ]
