"""
InfoBhoomi — Memory Agent
==========================
Maintains a persistent log of all agent actions, findings, and applied fixes
across every run cycle so progress is never lost between sessions.

Memory is stored in .agent_state/memory.json with one entry per full
QA → Research → Implementation cycle.

Usage:
    mem = MemoryAgent()
    run_id = mem.start_run()
    mem.record_qa(run_id, qa_report)
    mem.record_research(run_id, ["action 1", "action 2"])
    mem.record_implementations(run_id, approved=["fix A"], skipped=["fix B"])
    mem.resolve_issues(run_id, qa_report_after)   # marks issues resolved if they disappeared
    mem.complete_run(run_id)
    mem.print_status()
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from config import MEMORY_FILE, STATE_DIR

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


class MemoryAgent:
    """
    Persistent memory across agent run cycles.

    Schema of memory.json
    ─────────────────────
    {
      "runs": [
        {
          "run_id":               int,
          "started_at":           ISO datetime,
          "completed_at":         ISO datetime | null,
          "status":               "in_progress" | "completed" | "aborted",
          "qa_summary":           { total, passed, failed, warnings, issue_labels[] },
          "research_actions":     [ "action description", ... ],
          "implementations_approved": [ "change title", ... ],
          "implementations_skipped":  [ "change title", ... ],
        },
        ...
      ],
      "open_issues":    [ { label, message, detail, first_seen_run, last_seen_run }, ... ],
      "resolved_issues": [ { label, message, resolved_run, ... }, ... ],
      "summary":        "human-readable one-liner"
    }
    """

    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if MEMORY_FILE.exists():
            try:
                with open(MEMORY_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "runs":             [],
            "open_issues":      [],
            "resolved_issues":  [],
            "summary":          "No runs yet.",
        }

    def _save(self):
        with open(MEMORY_FILE, "w") as f:
            json.dump(self._data, f, indent=2, default=str)

    # ── Run lifecycle ─────────────────────────────────────────────────────────

    def start_run(self) -> int:
        """Create a new run entry and return its run_id."""
        run_id = (
            max((r["run_id"] for r in self._data["runs"]), default=0) + 1
        )
        self._data["runs"].append({
            "run_id":                   run_id,
            "started_at":               datetime.now().isoformat(),
            "completed_at":             None,
            "status":                   "in_progress",
            "qa_summary":               None,
            "research_actions":         [],
            "implementations_approved": [],
            "implementations_skipped":  [],
        })
        self._save()
        return run_id

    def complete_run(self, run_id: int, status: str = "completed"):
        """Mark a run as finished and update the summary."""
        run = self._get_run(run_id)
        if run:
            run["completed_at"] = datetime.now().isoformat()
            run["status"] = status
        self._refresh_summary()
        self._save()

    # ── QA recording ──────────────────────────────────────────────────────────

    def record_qa(self, run_id: int, qa_report: dict):
        """
        Store QA results for this run and merge new failures into open_issues.
        qa_report is the dict produced by QAReport.to_dict().
        """
        run = self._get_run(run_id)
        if not run:
            return

        issue_labels = [i.get("label", "") for i in qa_report.get("issues", [])]
        run["qa_summary"] = {
            "total":        qa_report.get("total", 0),
            "passed":       qa_report.get("passed", 0),
            "failed":       qa_report.get("failed", 0),
            "warnings":     qa_report.get("warnings", 0),
            "issue_labels": issue_labels,
        }

        # Merge failures into open_issues list
        existing_labels = {i["label"] for i in self._data["open_issues"]}
        for issue in qa_report.get("issues", []):
            label   = issue.get("label", "")
            message = issue.get("message", "")
            detail  = issue.get("detail", "")
            if label in existing_labels:
                # Update last_seen
                for oi in self._data["open_issues"]:
                    if oi["label"] == label:
                        oi["last_seen_run"] = run_id
            else:
                self._data["open_issues"].append({
                    "label":          label,
                    "message":        message,
                    "detail":         detail,
                    "first_seen_run": run_id,
                    "last_seen_run":  run_id,
                })
                existing_labels.add(label)

        self._refresh_summary()
        self._save()

    def resolve_issues(self, run_id: int, qa_report_after: dict):
        """
        Compare the current open_issues list against qa_report_after.
        Any issue not present in the new report is marked resolved.
        """
        still_failing = {i.get("label", "") for i in qa_report_after.get("issues", [])}
        remaining    = []
        for issue in self._data["open_issues"]:
            if issue["label"] not in still_failing:
                issue["resolved_run"] = run_id
                self._data["resolved_issues"].append(issue)
            else:
                remaining.append(issue)
        self._data["open_issues"] = remaining
        self._refresh_summary()
        self._save()

    # ── Research & implementation recording ──────────────────────────────────

    def record_research(self, run_id: int, actions: list[str]):
        run = self._get_run(run_id)
        if run:
            run["research_actions"] = actions
            self._save()

    def record_implementations(
        self, run_id: int,
        approved: list[str],
        skipped:  list[str],
    ):
        run = self._get_run(run_id)
        if run:
            run["implementations_approved"] = approved
            run["implementations_skipped"]  = skipped
            self._save()

    # ── Queries ───────────────────────────────────────────────────────────────

    @property
    def open_issues(self) -> list[dict]:
        return self._data["open_issues"]

    @property
    def resolved_issues(self) -> list[dict]:
        return self._data["resolved_issues"]

    @property
    def next_run_id(self) -> int:
        return max((r["run_id"] for r in self._data["runs"]), default=0) + 1

    def all_clear(self) -> bool:
        """True when there are no open issues — QA loop can stop."""
        return len(self._data["open_issues"]) == 0

    def run_count(self) -> int:
        return len(self._data["runs"])

    # ── Display ───────────────────────────────────────────────────────────────

    def print_status(self):
        open_n     = len(self._data["open_issues"])
        resolved_n = len(self._data["resolved_issues"])
        runs_n     = len(self._data["runs"])

        print(f"\n{BOLD}  ── Memory Agent Status ──{RESET}")
        print(f"  Total cycles run : {runs_n}")
        print(f"  Open issues      : {RED if open_n else GREEN}{open_n}{RESET}")
        print(f"  Resolved issues  : {GREEN}{resolved_n}{RESET}")
        print(f"  Summary          : {self._data['summary']}")

        if self._data["open_issues"]:
            print(f"\n  {YELLOW}Open issues:{RESET}")
            for oi in self._data["open_issues"]:
                since = oi.get("first_seen_run", "?")
                print(f"    {RED}✘{RESET}  [{oi['label']}]  {oi['message']}"
                      f"  {CYAN}(since run {since}){RESET}")

        if self._data["resolved_issues"]:
            print(f"\n  {GREEN}Resolved issues:{RESET}")
            for ri in self._data["resolved_issues"][-5:]:  # show last 5
                at = ri.get("resolved_run", "?")
                print(f"    {GREEN}✔{RESET}  [{ri['label']}]  (resolved run {at})")

    def print_last_run_summary(self):
        if not self._data["runs"]:
            print("  No runs recorded yet.")
            return
        last = self._data["runs"][-1]
        rid  = last["run_id"]
        print(f"\n  {BOLD}Last run: #{rid}  status={last['status']}{RESET}")
        qs = last.get("qa_summary")
        if qs:
            c = GREEN if qs["failed"] == 0 else RED
            print(f"  QA: {qs['passed']}/{qs['total']} passed  "
                  f"{c}{qs['failed']} failed{RESET}  {qs['warnings']} warnings")
        acts = last.get("research_actions", [])
        if acts:
            print(f"  Research actions proposed: {len(acts)}")
        appr = last.get("implementations_approved", [])
        if appr:
            print(f"  Changes approved: {len(appr)}")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_run(self, run_id: int) -> Optional[dict]:
        for run in self._data["runs"]:
            if run["run_id"] == run_id:
                return run
        return None

    def _refresh_summary(self):
        open_n     = len(self._data["open_issues"])
        resolved_n = len(self._data["resolved_issues"])
        runs_n     = len(self._data["runs"])
        self._data["summary"] = (
            f"{runs_n} cycle(s) run. "
            f"{open_n} open issue(s). "
            f"{resolved_n} resolved."
        )
