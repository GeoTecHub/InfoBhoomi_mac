"""
Verification QA Agent (Step 8 of the pipeline).
================================================
Reruns the relevant function checks AND lightweight per-layer smoke tests
after the Implementers commit. Updates each linked edit's
``verification_outcome`` in ChangeMemory so the no-repeat-fix loop has data.

Decision #4: FE smoke = real ``ng build --configuration development``
(streamed via the BackgroundRunner). BE smoke = ``manage.py check`` + a
``py_compile`` of every file touched by Implementers in this round.

Public entry point::

    VerificationQAAgent().verify(
        queue_id=queue_id,
        committed_edit_ids=[...],          # ChangeMemory edit ids from P4 commit
        function_ids_to_rerun=[...],       # registry FunctionDefinition ids
        log=lambda line: ...,              # callback for streamed log lines
        is_cancelled=lambda: False,        # callback to short-circuit
    )
"""

from __future__ import annotations

import os
import py_compile
import shlex
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from config import AGENT_BE_ROOT, AGENT_FE_ROOT, PROJECT_ROOT
from agent_center.change_memory import ChangeMemory
from agent_center.component_map import DBSubcomponent, get_entry
from agent_center.function_qa_agent import FunctionQAAgent
from agent_center.investigators import DBInvestigator


LayerStatus = Literal["ok", "warning", "error", "skipped"]


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class LayerVerification:
    layer:        str
    status:       LayerStatus
    headline:     str
    details:      list[str] = field(default_factory=list)
    return_code:  int | None = None
    elapsed_ms:   float = 0.0
    inspected:    list[str] = field(default_factory=list)
    skipped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    queue_id:        str
    started_at:      str
    finished_at:     str = ""
    status:          Literal["running", "complete", "cancelled", "failed"] = "running"
    overall:         LayerStatus = "skipped"
    frontend:        LayerVerification | None = None
    backend:         LayerVerification | None = None
    db:              LayerVerification | None = None
    function_qa:     dict[str, Any] = field(default_factory=dict)
    edits_verified:  list[str] = field(default_factory=list)
    elapsed_ms:      float = 0.0
    error:           str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id":       self.queue_id,
            "started_at":     self.started_at,
            "finished_at":    self.finished_at,
            "status":         self.status,
            "overall":        self.overall,
            "frontend":       self.frontend.to_dict() if self.frontend else None,
            "backend":        self.backend.to_dict()  if self.backend  else None,
            "db":             self.db.to_dict()       if self.db       else None,
            "function_qa":    self.function_qa,
            "edits_verified": list(self.edits_verified),
            "elapsed_ms":     self.elapsed_ms,
            "error":          self.error,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _worst(*statuses: LayerStatus) -> LayerStatus:
    """
    Aggregate per-layer statuses. ``skipped`` only wins when *every* input
    is skipped — otherwise it's silently ignored so a single ``ok`` layer
    does not get hidden behind two skips.
    """
    rank = {"skipped": 0, "ok": 1, "warning": 2, "error": 3}
    worst: LayerStatus = "skipped"
    for s in statuses:
        if rank.get(s, 0) > rank.get(worst, 0):
            worst = s
    return worst


# ── Agent ─────────────────────────────────────────────────────────────────────

class VerificationQAAgent:
    """Per-layer smoke + registry rerun, with optional log streaming."""

    def __init__(
        self,
        *,
        change_memory: ChangeMemory | None = None,
        fe_root: Path | None = None,
        be_root: Path | None = None,
        ng_build_timeout: int = 300,    # 5 minutes (Decision #4)
        manage_check_timeout: int = 60,
    ):
        self.change_memory       = change_memory or ChangeMemory()
        self.fe_root             = (fe_root or AGENT_FE_ROOT).resolve()
        self.be_root             = (be_root or AGENT_BE_ROOT).resolve()
        self.ng_build_timeout    = ng_build_timeout
        self.manage_check_timeout = manage_check_timeout

    # ── Public entry ──────────────────────────────────────────────────────────

    def verify(
        self,
        *,
        queue_id: str,
        committed_edit_ids: Iterable[str] | None = None,
        function_ids_to_rerun: Iterable[str] | None = None,
        log: Callable[[str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> VerificationResult:
        log = log or (lambda _l: None)
        is_cancelled = is_cancelled or (lambda: False)
        committed_edit_ids = list(committed_edit_ids or [])
        function_ids_to_rerun = list(function_ids_to_rerun or [])

        result = VerificationResult(queue_id=queue_id, started_at=_utc_now(), status="running")
        started = time.perf_counter()

        try:
            edits = [self.change_memory.get_edit(eid) for eid in committed_edit_ids]
            edits = [e for e in edits if e is not None and not e.get("rolled_back")]
            layers_touched = {self._layer_for_edit(e) for e in edits}
            log(f"Verifying {len(edits)} edit(s) across layers: {sorted(layers_touched) or 'none'}")

            # ── Frontend smoke ───────────────────────────────────────────────
            if "frontend" in layers_touched:
                if is_cancelled(): return self._abort(result, started, "Cancelled before FE smoke.")
                result.frontend = self._fe_smoke(log, is_cancelled)
            else:
                result.frontend = self._skipped("frontend", "No frontend edits committed.")

            # ── Backend smoke ────────────────────────────────────────────────
            if "backend" in layers_touched or "migration" in layers_touched:
                if is_cancelled(): return self._abort(result, started, "Cancelled before BE smoke.")
                result.backend = self._be_smoke(edits, log, is_cancelled)
            else:
                result.backend = self._skipped("backend", "No backend or migration edits committed.")

            # ── DB smoke ─────────────────────────────────────────────────────
            if function_ids_to_rerun:
                if is_cancelled(): return self._abort(result, started, "Cancelled before DB smoke.")
                result.db = self._db_smoke(function_ids_to_rerun, log)
            else:
                result.db = self._skipped("db", "No function_ids supplied for DB rerun.")

            # ── Function QA rerun ────────────────────────────────────────────
            if function_ids_to_rerun:
                if is_cancelled(): return self._abort(result, started, "Cancelled before function QA rerun.")
                log(f"Rerunning {len(function_ids_to_rerun)} registry function(s)...")
                result.function_qa = self._rerun_functions(function_ids_to_rerun, log)

            # ── Aggregate + propagate to ChangeMemory ────────────────────────
            statuses = [
                result.frontend.status if result.frontend else "skipped",
                result.backend.status  if result.backend  else "skipped",
                result.db.status       if result.db       else "skipped",
            ]
            result.overall = _worst(*statuses)

            outcome = "passed" if result.overall == "ok" else (
                "partial" if result.overall == "warning" else "failed"
            )
            for e in edits:
                self.change_memory.update_verification(
                    e["edit_id"], outcome,
                    {
                        "layer_statuses": {
                            "frontend": result.frontend.status if result.frontend else "skipped",
                            "backend":  result.backend.status  if result.backend  else "skipped",
                            "db":       result.db.status       if result.db       else "skipped",
                        },
                        "function_qa_summary": result.function_qa.get("summary"),
                    },
                )
                result.edits_verified.append(e["edit_id"])

            result.status = "complete"
        except Exception as exc:
            result.status = "failed"
            result.error  = f"{type(exc).__name__}: {exc}"
            log(f"FATAL: {result.error}")
        finally:
            result.elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            result.finished_at = _utc_now()
        return result

    # ── Frontend ──────────────────────────────────────────────────────────────

    def _fe_smoke(
        self,
        log: Callable[[str], None],
        is_cancelled: Callable[[], bool],
    ) -> LayerVerification:
        started = time.perf_counter()
        details: list[str] = []
        log("[frontend] resolving build command...")
        cmd = self._fe_build_cmd()
        if cmd is None:
            return LayerVerification(
                layer="frontend", status="skipped",
                headline="No build tool found (npx / ng / npm).",
                skipped_reason="Could not find ng / npx in PATH and no package.json build script.",
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        log(f"[frontend] running: {' '.join(cmd)}  (cwd={self.fe_root})")
        rc, out_lines = self._stream_subprocess(
            cmd, cwd=self.fe_root, timeout=self.ng_build_timeout,
            log=log, label="frontend", is_cancelled=is_cancelled,
        )
        details = out_lines[-30:]
        if rc is None:
            return LayerVerification(
                layer="frontend", status="error",
                headline="ng build was cancelled or timed out.",
                details=details, return_code=None,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        status: LayerStatus = "ok" if rc == 0 else "error"
        headline = "ng build succeeded." if rc == 0 else f"ng build failed (rc={rc})."
        return LayerVerification(
            layer="frontend", status=status, headline=headline,
            details=details, return_code=rc,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    def _fe_build_cmd(self) -> list[str] | None:
        """Pick the most reliable build command available on this machine."""
        # 1. npm script `build`
        package_json = self.fe_root / "package.json"
        if package_json.exists():
            try:
                content = package_json.read_text()
                if '"build"' in content and shutil.which("npm"):
                    return ["npm", "run", "build", "--", "--configuration=development"]
            except OSError:
                pass
        # 2. npx ng directly
        if shutil.which("npx"):
            return ["npx", "ng", "build", "--configuration", "development"]
        if shutil.which("ng"):
            return ["ng", "build", "--configuration", "development"]
        return None

    # ── Backend ──────────────────────────────────────────────────────────────

    def _be_smoke(
        self,
        edits: list[dict[str, Any]],
        log: Callable[[str], None],
        is_cancelled: Callable[[], bool],
    ) -> LayerVerification:
        started = time.perf_counter()
        details: list[str] = []
        inspected: list[str] = []
        worst_status: LayerStatus = "ok"

        # ── 1. py_compile every committed Python file ────────────────────────
        for e in edits:
            if is_cancelled():
                break
            rel = e.get("file_path", "")
            if not rel or not rel.endswith(".py"):
                continue
            target = (PROJECT_ROOT / rel).resolve()
            if not target.exists():
                details.append(f"py_compile: {rel} missing on disk")
                worst_status = _worst(worst_status, "warning")
                continue
            try:
                py_compile.compile(str(target), doraise=True)
                details.append(f"py_compile OK  {rel}")
                inspected.append(rel)
            except py_compile.PyCompileError as exc:
                details.append(f"py_compile FAIL  {rel}: {str(exc.msg).strip()}")
                worst_status = "error"

        # ── 2. manage.py check ───────────────────────────────────────────────
        manage_py = self.be_root / "manage.py"
        if not manage_py.exists():
            details.append(f"manage.py not found at {manage_py}; skipping Django check.")
            worst_status = _worst(worst_status, "warning")
        elif is_cancelled():
            pass
        elif shutil.which("python") is None and shutil.which("python3") is None:
            details.append("python interpreter not in PATH; skipping manage.py check.")
            worst_status = _worst(worst_status, "warning")
        else:
            python = shutil.which("python") or shutil.which("python3")
            cmd = [python, "manage.py", "check"]
            log(f"[backend] running: {' '.join(cmd)}  (cwd={self.be_root})")
            rc, out_lines = self._stream_subprocess(
                cmd, cwd=self.be_root, timeout=self.manage_check_timeout,
                log=log, label="backend", is_cancelled=is_cancelled,
            )
            if rc is None:
                details.extend(out_lines[-20:])
                details.append("manage.py check cancelled or timed out.")
                worst_status = _worst(worst_status, "error")
            elif rc == 0:
                details.append("manage.py check OK")
                details.extend(out_lines[-10:])
            else:
                details.append(f"manage.py check failed (rc={rc})")
                details.extend(out_lines[-20:])
                worst_status = "error"

        headline = {
            "ok":      "Backend smoke checks passed.",
            "warning": "Backend smoke completed with warnings.",
            "error":   "Backend smoke detected errors.",
            "skipped": "Backend smoke was skipped.",
        }[worst_status]
        return LayerVerification(
            layer="backend", status=worst_status, headline=headline,
            details=details[-30:], inspected=inspected,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    # ── DB ───────────────────────────────────────────────────────────────────

    def _db_smoke(
        self,
        function_ids: list[str],
        log: Callable[[str], None],
    ) -> LayerVerification:
        started = time.perf_counter()
        details: list[str] = []
        sub_components: list[DBSubcomponent] = []
        for fid in function_ids:
            try:
                entry = get_entry(fid)
            except KeyError:
                continue
            sub_components.extend(list(entry.db))
        log(f"[db] verifying {len(sub_components)} table reference(s)")
        if not sub_components:
            return LayerVerification(
                layer="db", status="skipped",
                headline="No DB sub-components in routed functions.",
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            )

        result = DBInvestigator().investigate(sub_components)
        for f in result.findings:
            details.append(f"[{f.severity.upper()}] {f.title} {f.affected_subcomponent}")

        return LayerVerification(
            layer="db", status=result.status,
            headline={
                "ok":      f"All {len(sub_components)} DB table(s) reachable.",
                "warning": "DB checks completed with warnings.",
                "error":   "One or more DB checks failed.",
                "skipped": "DB checks were skipped.",
            }[result.status],
            details=details[-30:],
            inspected=list(result.inspected_subcomponents),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    # ── Registry rerun ───────────────────────────────────────────────────────

    def _rerun_functions(
        self,
        function_ids: list[str],
        log: Callable[[str], None],
    ) -> dict[str, Any]:
        agent = FunctionQAAgent()
        per: list[dict[str, Any]] = []
        passed = failed = 0
        for fid in function_ids:
            try:
                rep = agent.run_function(fid)
                per.append({"function_id": fid, "status": rep.get("status"), "summary": rep.get("summary")})
                if rep.get("status") == "passed":
                    passed += 1
                else:
                    failed += 1
                log(f"[qa] {fid} -> {rep.get('status')}")
            except KeyError as exc:
                log(f"[qa] {fid} -> SKIPPED ({exc})")
                per.append({"function_id": fid, "status": "skipped", "summary": str(exc)})
        return {
            "summary":     {"passed": passed, "failed": failed, "total": len(function_ids)},
            "per_function": per,
        }

    # ── Subprocess streaming ─────────────────────────────────────────────────

    def _stream_subprocess(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        timeout: int,
        log: Callable[[str], None],
        label: str,
        is_cancelled: Callable[[], bool],
    ) -> tuple[int | None, list[str]]:
        out_lines: list[str] = []
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except FileNotFoundError as exc:
            log(f"[{label}] failed to start: {exc}")
            return None, [f"FileNotFoundError: {exc}"]

        deadline = time.monotonic() + timeout
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                out_lines.append(line)
                log(f"[{label}] {line}")
                if is_cancelled():
                    proc.kill()
                    return None, out_lines + [f"{label} cancelled by user."]
                if time.monotonic() > deadline:
                    proc.kill()
                    return None, out_lines + [f"{label} timed out after {timeout}s."]
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            return None, out_lines + [f"{label} timed out after {timeout}s."]
        return proc.returncode, out_lines

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _layer_for_edit(edit: dict[str, Any]) -> str:
        agent = (edit.get("agent") or "").lower()
        if "frontend" in agent: return "frontend"
        if "migration" in agent: return "migration"
        return "backend"

    @staticmethod
    def _skipped(layer: str, reason: str) -> LayerVerification:
        return LayerVerification(layer=layer, status="skipped", headline=f"{layer.title()} skipped.", skipped_reason=reason)

    @staticmethod
    def _abort(result: VerificationResult, started_perf: float, msg: str) -> VerificationResult:
        result.status = "cancelled"
        result.error  = msg
        result.elapsed_ms = round((time.perf_counter() - started_perf) * 1000, 1)
        result.finished_at = _utc_now()
        return result
