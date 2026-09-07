"""
FrontendInvestigator — read-only inspection of Angular sub-components.
======================================================================
Checks performed (cheap, no build):
  - Path exists on disk (file or directory).
  - For .ts files: file size, lines, suspect imports (broken relative refs,
    legacy services, marker comments like "TODO" / "FIXME").
  - For component directories: presence of .ts and .html siblings.

This is intentionally lightweight; the heavy lifting (real ng build) happens
in P5's Verification QA Agent.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable

from config import PROJECT_ROOT
from agent_center.component_map import FrontendSubcomponent
from agent_center.investigators.base import (
    BaseInvestigator,
    InvestigationFinding,
    InvestigationResult,
)


_BROKEN_IMPORT = re.compile(r"^\s*import\s+.*from\s+['\"](\.\.?/[^'\"]+)['\"]", re.MULTILINE)
_TODO_PATTERN  = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)


class FrontendInvestigator(BaseInvestigator):
    layer = "frontend"

    def __init__(self, project_root: Path | None = None):
        self.project_root = (project_root or PROJECT_ROOT).resolve()

    def investigate(self, subcomponents: Iterable[FrontendSubcomponent]) -> InvestigationResult:
        started = time.perf_counter()
        findings: list[InvestigationFinding] = []
        inspected: list[str] = []

        for sc in subcomponents:
            inspected.append(sc.path)
            target = self.project_root / sc.path

            if not target.exists():
                findings.append(InvestigationFinding(
                    layer="frontend",
                    severity="error",
                    title="Frontend path missing",
                    detail=f"Declared {sc.kind} '{sc.path}' was not found on disk.",
                    affected_subcomponent=sc.path,
                    evidence={"resolved": str(target), "kind": sc.kind},
                ))
                continue

            if target.is_dir():
                findings.extend(self._inspect_directory(target, sc))
            else:
                findings.extend(self._inspect_file(target, sc))

        return InvestigationResult(
            layer="frontend",
            status=self._worst(findings) if findings else "ok",
            findings=findings,
            inspected_subcomponents=inspected,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # ── File / directory checks ───────────────────────────────────────────────

    def _inspect_directory(
        self,
        path: Path,
        sc: FrontendSubcomponent,
    ) -> list[InvestigationFinding]:
        findings: list[InvestigationFinding] = []
        ts_files   = list(path.glob("*.ts"))
        html_files = list(path.glob("*.html"))

        if sc.kind == "component" and not ts_files:
            findings.append(InvestigationFinding(
                layer="frontend",
                severity="warning",
                title="Component directory has no .ts files",
                detail=f"Expected at least one .ts file under {sc.path}.",
                affected_subcomponent=sc.path,
                evidence={"directory": str(path)},
            ))
        if sc.kind == "component" and not html_files:
            findings.append(InvestigationFinding(
                layer="frontend",
                severity="info",
                title="Component directory has no template",
                detail=f"No .html template found under {sc.path} — may be inline-only.",
                affected_subcomponent=sc.path,
                evidence={"directory": str(path)},
            ))
        for ts in ts_files:
            findings.extend(self._inspect_file(ts, sc))
        return findings

    def _inspect_file(
        self,
        path: Path,
        sc: FrontendSubcomponent,
    ) -> list[InvestigationFinding]:
        findings: list[InvestigationFinding] = []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(InvestigationFinding(
                layer="frontend",
                severity="error",
                title="Could not read source file",
                detail=str(exc),
                affected_subcomponent=sc.path,
                evidence={"file": str(path)},
            ))
            return findings

        line_count = text.count("\n") + 1
        size_kb    = round(path.stat().st_size / 1024, 1)

        if path.stat().st_size == 0:
            findings.append(InvestigationFinding(
                layer="frontend",
                severity="warning",
                title="Source file is empty",
                affected_subcomponent=sc.path,
                evidence={"file": str(path), "lines": 0, "size_kb": 0},
            ))
            return findings

        # Check that relative imports resolve.
        broken_imports: list[str] = []
        for match in _BROKEN_IMPORT.finditer(text):
            rel = match.group(1)
            target = (path.parent / rel).resolve()
            # Try a few common extensions Angular uses.
            candidates = [target, target.with_suffix(".ts"), target.with_suffix(".tsx"), target / "index.ts"]
            if not any(c.exists() for c in candidates):
                broken_imports.append(rel)
        if broken_imports:
            findings.append(InvestigationFinding(
                layer="frontend",
                severity="warning",
                title="Suspicious relative imports",
                detail=f"{len(broken_imports)} relative import(s) did not resolve from {path.name}.",
                affected_subcomponent=sc.path,
                evidence={
                    "file": str(path),
                    "unresolved": broken_imports[:10],
                },
            ))

        todos = _TODO_PATTERN.findall(text)
        if todos:
            findings.append(InvestigationFinding(
                layer="frontend",
                severity="info",
                title=f"{len(todos)} TODO/FIXME marker(s) present",
                affected_subcomponent=sc.path,
                evidence={"file": str(path), "count": len(todos)},
            ))

        # Pure metadata finding — useful in the report.
        findings.append(InvestigationFinding(
            layer="frontend",
            severity="ok",
            title="Inspected",
            detail=f"{sc.kind} {path.name}",
            affected_subcomponent=sc.path,
            evidence={"file": str(path), "lines": line_count, "size_kb": size_kb, "kind": sc.kind},
        ))

        return findings
