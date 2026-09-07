"""
Backward-compat shim — DO NOT add new code here.

The real implementation lives in ``agent_center.ai_provider`` (the package).
Existing imports such as::

    from agent_center.ai_provider import GeminiProvider, build_fix_prompt, AIProviderError

continue to work because Python resolves ``agent_center.ai_provider`` to the
package directory (which has its own __init__.py) before falling back to this
module. This file is kept only as a tombstone — if your environment somehow
loads this file instead of the package, surface a loud error.
"""

raise ImportError(
    "agent_center.ai_provider should resolve to the package (ai_provider/__init__.py). "
    "If you are seeing this message, Python loaded the legacy module shim instead; "
    "ensure the ai_provider/ directory exists alongside this file."
)
