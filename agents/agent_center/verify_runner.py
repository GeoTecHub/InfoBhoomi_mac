"""
Background runner for VerificationQAAgent.
==========================================
The dashboard wants to start a long-running verification (ng build can take
30s–5min), poll for status + log lines, and cancel if needed. We don't want
to keep the HTTP request open the whole time, so this runner spawns a daemon
thread per queue_id and exposes a simple state cache the dashboard polls.

Public API:
    runner = VerifyRunner.singleton()
    runner.start(queue_id, edit_ids, function_ids, run_id)
    runner.snapshot(queue_id) -> dict
    runner.cancel(queue_id)
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

from agent_center.verification_qa_agent import VerificationQAAgent, VerificationResult


_LOG_BUFFER_LINES = 1000


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class _RunSlot:
    __slots__ = ("queue_id", "thread", "log", "result", "started_at",
                 "finished_at", "cancel_event", "log_lock")

    def __init__(self, queue_id: str):
        self.queue_id:    str = queue_id
        self.thread:      threading.Thread | None = None
        self.log:         deque[str] = deque(maxlen=_LOG_BUFFER_LINES)
        self.result:      VerificationResult | None = None
        self.started_at:  str = _utc_now()
        self.finished_at: str = ""
        self.cancel_event = threading.Event()
        self.log_lock     = threading.Lock()


class VerifyRunner:
    _instance: "VerifyRunner | None" = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._slots: dict[str, _RunSlot] = {}
        self._slots_lock = threading.Lock()

    @classmethod
    def singleton(cls) -> "VerifyRunner":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Public API ────────────────────────────────────────────────────────────

    def start(
        self,
        *,
        queue_id: str,
        committed_edit_ids: list[str],
        function_ids_to_rerun: list[str],
        agent: VerificationQAAgent | None = None,
    ) -> dict[str, Any]:
        """
        Begin a verification run on a daemon thread. If a previous run for
        ``queue_id`` is still active, refuse to start a new one.
        """
        with self._slots_lock:
            existing = self._slots.get(queue_id)
            if existing and existing.thread and existing.thread.is_alive():
                return {"ok": False, "error": "verification already running for this queue_id"}
            slot = _RunSlot(queue_id)
            self._slots[queue_id] = slot

        agent = agent or VerificationQAAgent()

        def _log(line: str) -> None:
            with slot.log_lock:
                slot.log.append(f"{_utc_now()}  {line}")

        def _is_cancelled() -> bool:
            return slot.cancel_event.is_set()

        def _target() -> None:
            try:
                slot.result = agent.verify(
                    queue_id=queue_id,
                    committed_edit_ids=committed_edit_ids,
                    function_ids_to_rerun=function_ids_to_rerun,
                    log=_log,
                    is_cancelled=_is_cancelled,
                )
            except Exception as exc:  # pragma: no cover - safety net
                _log(f"FATAL: {type(exc).__name__}: {exc}")
                slot.result = VerificationResult(
                    queue_id=queue_id, started_at=slot.started_at,
                    status="failed", error=f"{type(exc).__name__}: {exc}",
                )
            finally:
                slot.finished_at = _utc_now()

        slot.thread = threading.Thread(target=_target, daemon=True, name=f"verify-{queue_id}")
        slot.thread.start()
        return {"ok": True, "queue_id": queue_id, "started_at": slot.started_at}

    def snapshot(self, queue_id: str, *, log_offset: int = 0) -> dict[str, Any]:
        """
        Return the current state of a verification run.
        ``log_offset`` is the number of lines the caller has already seen,
        so we can return only newer lines.
        """
        with self._slots_lock:
            slot = self._slots.get(queue_id)
        if slot is None:
            return {"queue_id": queue_id, "found": False}

        # Snapshot log
        with slot.log_lock:
            log_list = list(slot.log)
        new_lines = log_list[log_offset:] if log_offset < len(log_list) else []
        next_offset = len(log_list)

        running = bool(slot.thread and slot.thread.is_alive())
        result_dict = slot.result.to_dict() if slot.result else None
        status = (result_dict or {}).get("status") if result_dict else ("running" if running else "pending")

        return {
            "queue_id":    queue_id,
            "found":       True,
            "running":     running,
            "started_at":  slot.started_at,
            "finished_at": slot.finished_at,
            "status":      status,
            "result":      result_dict,
            "log":         new_lines,
            "log_offset":  next_offset,
        }

    def cancel(self, queue_id: str) -> dict[str, Any]:
        with self._slots_lock:
            slot = self._slots.get(queue_id)
        if slot is None:
            return {"ok": False, "error": "no verification slot for this queue_id"}
        slot.cancel_event.set()
        return {"ok": True, "queue_id": queue_id}

    def clear(self, queue_id: str) -> bool:
        """Drop the slot from memory (used by tests/teardown)."""
        with self._slots_lock:
            return self._slots.pop(queue_id, None) is not None
