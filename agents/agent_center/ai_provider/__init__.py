"""
Pluggable LLM providers for the InfoBhoomi self-healing pipeline.

Public re-exports:
    AIProvider         — abstract base class
    AIProviderError    — raised by any provider on transport/parse failure
    GeminiProvider     — google generativelanguage v1beta
    ClaudeProvider     — anthropic SDK
    pick_provider(...) — router used by Reporter / Solution Architect
    build_fix_prompt   — kept here for backward-compat with fix_proposal_agent
"""

from agent_center.ai_provider.base import AIProvider, AIProviderError, build_fix_prompt
from agent_center.ai_provider.gemini import GeminiProvider
from agent_center.ai_provider.claude import ClaudeProvider
from agent_center.ai_provider.router import pick_provider

__all__ = [
    "AIProvider",
    "AIProviderError",
    "GeminiProvider",
    "ClaudeProvider",
    "pick_provider",
    "build_fix_prompt",
]
