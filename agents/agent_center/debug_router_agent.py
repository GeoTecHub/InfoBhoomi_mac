from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from agent_center.function_registry import FunctionDefinition, all_functions


@dataclass
class RoutedFunction:
    function_id: str
    display_name: str
    category: str
    score: int
    matched_terms: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class DebugRouterAgent:
    """Maps a user issue prompt to the most relevant function checks."""

    def route(self, prompt: str, limit: int = 5) -> list[RoutedFunction]:
        tokens = set(re.findall(r"[a-z0-9_]+", prompt.lower()))
        scored: list[RoutedFunction] = []

        for fn in all_functions():
            haystack = self._terms(fn)
            matches = sorted(tokens & haystack)
            phrase_bonus = sum(2 for kw in fn.keywords if kw.lower() in prompt.lower())
            score = len(matches) + phrase_bonus
            if score:
                scored.append(
                    RoutedFunction(
                        function_id=fn.id,
                        display_name=fn.display_name,
                        category=fn.category,
                        score=score,
                        matched_terms=matches[:12],
                    )
                )

        scored.sort(key=lambda item: (-item.score, item.category, item.display_name))
        return scored[:limit]

    def _terms(self, fn: FunctionDefinition) -> set[str]:
        text = " ".join(
            [
                fn.id,
                fn.display_name,
                fn.category,
                fn.subcategory,
                fn.frontend,
                " ".join(fn.keywords),
                " ".join(endpoint.path for endpoint in fn.endpoints),
            ]
        )
        return set(re.findall(r"[a-z0-9_]+", text.lower()))

