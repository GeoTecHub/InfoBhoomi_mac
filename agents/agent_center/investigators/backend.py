"""
BackendInvestigator — read-only inspection of Django sub-components.
====================================================================
Checks performed:
  - Path exists on disk.
  - File reads successfully.
  - Python syntax (``py_compile``) — does the file even import-parse?
  - Suspect markers (TODO/FIXME, pdb.set_trace, breakpoint(), naked excepts).

Heavy ``manage.py check`` is NOT run here (slow, requires DB/env). It belongs
in the Verification QA Agent (P5).
"""

from __future__ import annotations

import py_compile
import re
import time
from pathlib import Path
from typing import Iterable

from config import PROJECT_ROOT
from agent_center.component_map import BackendSubcomponent
from agent_center.investigators.base import (
    BaseInvestigator,
    InvestigationFinding,
    InvestigationResult,
)


_TODO_PATTERN     = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)
_BREAKPOINT       = re.compile(r"^\s*(breakpoint\s*\(|import\s+pdb|pdb\.set_trace\s*\()", re.MULTILINE)
_NAKED_EXCEPT     = re.compile(r"^\s*except\s*:\s*(#|$)", re.MULTILINE)


class BackendInvestigator(BaseInvestigator):
    layer = "backend"

    def __init__(self, project_root: Path | None = None):
        self.project_root = (project_root or PROJECT_ROOT).resolve()

    def investigate(self, subcomponents: Iterable[BackendSubcomponent]) -> InvestigationResult:
        started = time.perf_counter()
        findings: list[InvestigationFinding] = []
        inspected: list[str] = []

        for sc in subcomponents:
            inspected.append(sc.path)
            target = self.project_root / sc.path

            if not target.exists():
                findings.append(InvestigationFinding(
                    layer="backend",
                    severity="error",
                    title="Backend path missing",
                    detail=f"Declared {sc.kind} '{sc.path}' was not found on disk.",
                    affected_subcomponent=sc.path,
                    evidence={"resolved": str(target), "kind": sc.kind},
                ))
                continue

            if target.is_dir():
                # Treat as collection of .py files
                for py in sorted(target.glob("*.py")):
                    findings.extend(self._inspect_python_file(py, sc))
            elif target.suffix == ".py":
                findings.extend(self._inspect_python_file(target, sc))
            else:
                # Not a .py file — only read it (e.g. urls.py renamed, etc.)
                findings.extend(self._read_only_file(target, sc))

        return InvestigationResult(
            layer="backend",
            status=self._worst(findings) if findings else "ok",
            findings=findings,
            inspected_subcomponents=inspected,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # ── Python-aware checks ───────────────────────────────────────────────────

    def _inspect_python_file(
        self,
        path: Path,
        sc: BackendSubcomponent,
    ) -> list[InvestigationFinding]:
        findings: list[InvestigationFinding] = []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(InvestigationFinding(
                layer="backend",
                severity="error",
                title="Could not read source file",
                detail=str(exc),
                affected_subcomponent=sc.path,
                evidence={"file": str(path)},
            ))
            return findings

        # py_compile — fast syntax check.
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            findings.append(InvestigationFinding(
                layer="backend",
                severity="error",
                title="Python syntax error",
                detail=str(exc.msg).strip(),
                affected_subcomponent=sc.path,
                evidence={"file": str(path), "exc": str(exc)},
            ))
            return findings  # No point in further checks on a broken file.

        line_count = text.count("\n") + 1
        size_kb    = round(path.stat().st_size / 1024, 1)

        if _BREAKPOINT.search(text):
            findings.append(InvestigationFinding(
                layer="backend",
                severity="warning",
                title="Debug breakpoint left in source",
                detail=f"Found pdb / breakpoint() call in {path.name}.",
                affected_subcomponent=sc.path,
                evidence={"file": str(path)},
            ))
        if _NAKED_EXCEPT.search(text):
            findings.append(InvestigationFinding(
                layer="backend",
                severity="warning",
                title="Naked except clause",
                detail=f"`except:` swallowing all errors in {path.name}.",
                affected_subcomponent=sc.path,
                evidence={"file": str(path)},
            ))
        todos = _TODO_PATTERN.findall(text)
        if todos:
            findings.append(InvestigationFinding(
                layer="backend",
                severity="info",
                title=f"{len(todos)} TODO/FIXME marker(s) present",
                affected_subcomponent=sc.path,
                evidence={"file": str(path), "count": len(todos)},
            ))

        findings.append(InvestigationFinding(
            layer="backend",
            severity="ok",
            title="Inspected (syntax OK)",
            detail=f"{sc.kind} {path.name}",
            affected_subcomponent=sc.path,
            evidence={"file": str(path), "lines": line_count, "size_kb": size_kb, "kind": sc.kind},
        ))
        return findings

    def _read_only_file(
        self,
        path: Path,
        sc: BackendSubcomponent,
    ) -> list[InvestigationFinding]:
        try:
            size_kb = round(path.stat().st_size / 1024, 1)
        except OSError:
            size_kb = -1
        return [
            InvestigationFinding(
                layer="backend",
                severity="ok",
                title="Inspected (non-Python file)",
                detail=f"{sc.kind} {path.name}",
                affected_subcomponent=sc.path,
                evidence={"file": str(path), "size_kb": size_kb, "kind": sc.kind},
            )
        ]
