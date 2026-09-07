"""BackendImplementer — scoped to AGENT_BE_ROOT (excluding migrations)."""

from __future__ import annotations

from pathlib import Path

from config import AGENT_BE_ROOT
from agent_center.implementers.base import BaseImplementer, ScopeViolation
from agent_center.solution_architect_agent import SolutionItem


class BackendImplementer(BaseImplementer):
    layer = "backend"
    allowed_root = AGENT_BE_ROOT

    # Migrations get their own implementer; refuse them here so the dashboard's
    # dispatcher sends them to DBMigrationImplementer instead.
    def can_handle(self, item: SolutionItem) -> bool:
        try:
            target = self._resolve_in_scope(item.file_path)
        except ScopeViolation:
            return False
        return "migrations" not in target.parts
