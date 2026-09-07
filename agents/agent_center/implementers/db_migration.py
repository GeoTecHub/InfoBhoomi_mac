"""
DBMigrationImplementer — scoped to InfoBhoomi_Backend_dev2/user/migrations/.

Decision #3 (locked plan): never run ``manage.py migrate`` automatically.
After committing the migration file the dashboard shows two buttons:

  1. "Apply migration now (dev only)" — calls ``apply_migration()``;
     the BE sub-process runs ``python manage.py migrate`` and streams the log.
     Refuses unless AGENT_ENVIRONMENT == 'development'.
  2. "Show me the command to run manually" — returns the exact shell command
     for the user to copy-paste in any environment.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from config import AGENT_BE_ROOT, AGENT_ENVIRONMENT
from agent_center.implementers.base import BaseImplementer, ScopeViolation
from agent_center.solution_architect_agent import SolutionItem


_MIGRATIONS_REL = Path("user") / "migrations"


@dataclass
class MigrationApplyResult:
    ok:          bool
    environment: str
    command:     str
    stdout:      str = ""
    stderr:      str = ""
    return_code: int | None = None
    error:       str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DBMigrationImplementer(BaseImplementer):
    """
    Scoped to <BE_ROOT>/user/migrations/.
    Migration items typically supply ``proposed_full_text`` for a brand-new file.
    """

    layer = "migration"
    allowed_root = AGENT_BE_ROOT / _MIGRATIONS_REL

    def can_handle(self, item: SolutionItem) -> bool:
        if item.layer != "migration":
            return False
        try:
            self._resolve_in_scope(item.file_path)
            return True
        except ScopeViolation:
            return False

    # ── Manual command (always available) ─────────────────────────────────────

    @staticmethod
    def manual_command() -> str:
        # Shell-quoted command suitable for copy-paste.
        be_root = str(AGENT_BE_ROOT)
        return shlex.join(["cd", be_root]) + " && " + shlex.join(["python", "manage.py", "migrate"])

    # ── Auto apply (dev only) ────────────────────────────────────────────────

    def apply_migration(
        self,
        *,
        timeout_seconds: int = 120,
        env_override: dict[str, str] | None = None,
    ) -> MigrationApplyResult:
        if AGENT_ENVIRONMENT != "development":
            return MigrationApplyResult(
                ok=False,
                environment=AGENT_ENVIRONMENT,
                command=self.manual_command(),
                error=(
                    f"Auto-apply is disabled outside development "
                    f"(current IB_AGENT_ENVIRONMENT={AGENT_ENVIRONMENT!r}). "
                    "Use the manual command shown."
                ),
            )

        cmd = ["python", "manage.py", "migrate"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(AGENT_BE_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=({**__import__("os").environ, **(env_override or {})}),
            )
            return MigrationApplyResult(
                ok=(proc.returncode == 0),
                environment=AGENT_ENVIRONMENT,
                command=" ".join(cmd),
                stdout=proc.stdout[-8000:],   # cap for sane payloads
                stderr=proc.stderr[-8000:],
                return_code=proc.returncode,
                error=("" if proc.returncode == 0 else f"manage.py migrate exited with {proc.returncode}"),
            )
        except subprocess.TimeoutExpired:
            return MigrationApplyResult(
                ok=False,
                environment=AGENT_ENVIRONMENT,
                command=" ".join(cmd),
                error=f"manage.py migrate exceeded {timeout_seconds}s timeout.",
            )
        except FileNotFoundError as exc:
            return MigrationApplyResult(
                ok=False,
                environment=AGENT_ENVIRONMENT,
                command=" ".join(cmd),
                error=f"Could not start subprocess: {exc}",
            )
