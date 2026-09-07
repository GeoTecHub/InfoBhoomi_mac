"""
InfoBhoomi — Agent Orchestrator
=================================
Coordinates all agents in a self-healing loop:

  1. MemoryAgent    — loads history of all previous cycles
  2. QA Agent       — functional + data-integrity tests (10 phases)
  3. Research Agent — (with your permission) analyses QA failures via Claude
  4. Change Review  — you approve/reject each proposed fix one-by-one
  5. Apply Changes  — approved snippets written to target files as comments
  6. Memory update  — records what was done this cycle
  7. → repeat from step 2 until QA is clean or you exit

Human-in-the-loop: NO change is ever written without your explicit Y approval.

Usage:
    python orchestrator.py              # full loop (QA → research → fix → repeat)
    python orchestrator.py --qa-only    # single QA run only, no research
    python orchestrator.py --perf-only  # API performance test only
    python orchestrator.py --resume     # resume from last checkpoint
    python orchestrator.py --clear      # clear session state, start fresh
    python orchestrator.py --show       # show pending changes from last run
    python orchestrator.py --approve    # go straight to change approval
    python orchestrator.py --memory     # print memory status and exit
"""

import sys
import json
import argparse
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent))

# ── Windows Unicode fix ────────────────────────────────────────────────────────
# Windows cmd/PowerShell defaults to cp1252 which can't print → ✔ ✘ ═ etc.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from agents.token_monitor  import TokenMonitor
from agents.gis_perf_agent import GISPerfAgent
from agents.research_agent import ResearchAgent
from agents.qa_agent       import QAAgent
from agents.memory_agent   import MemoryAgent

from config import (
    FINDINGS_FILE,
    PENDING_CHANGES_FILE,
    QA_REPORT_FILE,
    MEMORY_FILE,
    STATE_DIR,
)

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

MAX_AUTO_LOOPS = 5   # safety cap — orchestrator never loops more than this without asking


# ── Helpers ───────────────────────────────────────────────────────────────────

def _banner(title: str):
    print(f"\n{BOLD}{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}{RESET}")


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print(f"\n{YELLOW}Interrupted.{RESET}")
        return ""


# ── Change review ─────────────────────────────────────────────────────────────

def review_and_approve_changes(monitor: TokenMonitor) -> list[dict]:
    """Present each proposed change and collect Y/N/S decisions."""
    if not PENDING_CHANGES_FILE.exists():
        print(f"{YELLOW}No pending changes file found.{RESET}")
        return []

    with open(PENDING_CHANGES_FILE) as f:
        data = json.load(f)

    changes = data.get("changes", [])
    if not changes:
        print(f"{GREEN}No proposed changes to review.{RESET}")
        return []

    _banner(f"CHANGE REVIEW — {len(changes)} proposal(s)")
    print("  For each proposed change: Y = approve  N = reject  S = skip for now\n")

    approved = []

    for i, change in enumerate(changes, 1):
        conf_color = (
            GREEN  if change.get("confidence") == "high" else
            YELLOW if change.get("confidence") == "medium" else RED
        )

        print(f"\n{BOLD}─── Change {i}/{len(changes)} ─────────────────────────────────────{RESET}")
        print(f"  Title:      {change.get('title', 'Untitled')}")
        print(f"  File:       {change.get('file_path', '?')}")
        print(f"  Issue ref:  #{change.get('issue_ref', '?')}")
        print(f"  Confidence: {conf_color}{change.get('confidence', '?')}{RESET}")
        print(f"\n  Description:")
        for line in change.get("description", "").split("\n"):
            print(f"    {line}")
        print(f"\n  Code snippet:")
        print("  ┌" + "─" * 56)
        for line in change.get("code_snippet", "").split("\n"):
            print(f"  │ {line}")
        print("  └" + "─" * 56)

        answer = _ask(f"\n  Apply this change? [Y/n/s]: ")

        if answer in ("y", "yes", ""):
            change["approved"] = True
            approved.append(change)
            print(f"  {GREEN}✓ Approved{RESET}")
            monitor.mark_step_done(f"approved_change_{i}")
        elif answer in ("s", "skip"):
            change["approved"] = None
            print(f"  {YELLOW}○ Skipped (deferred){RESET}")
        else:
            change["approved"] = False
            print(f"  {RED}✗ Rejected{RESET}")

    data["changes"]     = changes
    data["reviewed_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    with open(PENDING_CHANGES_FILE, "w") as f:
        json.dump(data, f, indent=2)

    approved_count = len(approved)
    print(f"\n  {GREEN}{approved_count} change(s) approved{RESET}  "
          f"| {len(changes) - approved_count} rejected/deferred")
    return approved


# ── Apply changes ─────────────────────────────────────────────────────────────

def apply_changes(approved: list[dict]) -> list[str]:
    """
    Apply each approved change.
    Returns list of applied change titles.
    Appends code as a commented block — never silently overwrites.
    """
    if not approved:
        print(f"\n{YELLOW}No approved changes to apply.{RESET}")
        return []

    _banner(f"APPLYING {len(approved)} CHANGE(S)")
    project_root = pathlib.Path(__file__).parent.parent
    applied_titles: list[str] = []

    for i, change in enumerate(approved, 1):
        file_path = project_root / change.get("file_path", "")
        title     = change.get("title", "Untitled")
        snippet   = change.get("code_snippet", "")

        print(f"\n  [{i}] {title}")
        print(f"      File: {file_path}")

        if not snippet:
            print(f"      {YELLOW}No code snippet — skipping{RESET}")
            continue

        if file_path.exists():
            bak = file_path.with_suffix(file_path.suffix + ".bak")
            bak.write_text(file_path.read_text())
            print(f"      Backup → {bak.name}")
            with open(file_path, "a") as f:
                f.write(
                    f"\n\n# ── InfoBhoomi Agent Suggestion: {title} ──\n"
                    f"# Applied: {__import__('datetime').datetime.utcnow().isoformat()}Z\n"
                    f"# Review and integrate the following code:\n"
                )
                for line in snippet.split("\n"):
                    f.write(f"# {line}\n")
            print(f"      {GREEN}✓ Snippet appended as comment for review{RESET}")
        else:
            print(f"      {YELLOW}File not found — writing snippet to review folder{RESET}")
            review_dir  = STATE_DIR / "review"
            review_dir.mkdir(parents=True, exist_ok=True)
            safe_name   = change.get("file_path", "unknown").replace("/", "_").replace("\\", "_")
            review_file = review_dir / f"{i:02d}_{safe_name}"
            review_file.write_text(
                f"# InfoBhoomi Agent Suggestion: {title}\n"
                f"# Target file: {change.get('file_path', '?')}\n"
                f"# Description: {change.get('description', '')}\n\n"
                + snippet
            )
            print(f"      {CYAN}Snippet saved → {review_file}{RESET}")

        applied_titles.append(title)

    return applied_titles


# ── QA runner ─────────────────────────────────────────────────────────────────

def run_qa(token: str, layer_id: int) -> dict:
    """
    Run the full QA agent and persist the report.
    Returns the qa_report as a dict.
    """
    _banner("QA — Functional & Data-Integrity Tests")
    qa_agent  = QAAgent(token=token, layer_id=layer_id)
    qa_report = qa_agent.run()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    report_dict = qa_report.to_dict()
    with open(QA_REPORT_FILE, "w") as f:
        json.dump(report_dict, f, indent=2)
    print(f"\n  {CYAN}QA report saved → {QA_REPORT_FILE}{RESET}")

    # Surface QA failures into findings.json so research agent can see them
    if qa_report.issues:
        existing: dict = {}
        if FINDINGS_FILE.exists():
            with open(FINDINGS_FILE) as f:
                try:
                    existing = json.load(f)
                except json.JSONDecodeError:
                    existing = {}

        # Existing issues may be dicts (from QA agent) or strings (from perf agent)
        def _issue_label(i: Any) -> str:
            return i.get("label") or i.get("id") or "" if isinstance(i, dict) else str(i)

        existing_labels = {_issue_label(i) for i in existing.get("issues", [])}
        new_issues = [
            {
                "id":       iss.get("label", "?"),
                "label":    iss.get("label", "?"),
                "title":    f"[QA] {iss.get('message', '')}",
                "severity": "high",
                "detail":   iss.get("detail", ""),
                "source":   "qa_agent",
            }
            for iss in qa_report.issues
            if iss.get("label") not in existing_labels
        ]
        existing.setdefault("issues", []).extend(new_issues)
        existing["qa_summary"] = {
            "passed":   qa_report.passed,
            "failed":   qa_report.failed,
            "total":    qa_report.total,
            "warnings": qa_report.warnings,
        }
        with open(FINDINGS_FILE, "w") as f:
            json.dump(existing, f, indent=2)

        print(f"  {YELLOW}{len(qa_report.issues)} issue(s) merged into findings.json{RESET}")

    return report_dict


# ── Research runner ───────────────────────────────────────────────────────────

def run_research(monitor: TokenMonitor) -> list[str]:
    """
    Run the Research Agent against current findings.
    Returns list of action descriptions for memory recording.
    """
    _banner("Research Agent — Analysing QA Failures with Claude")

    try:
        research_agent   = ResearchAgent()
        perf_report_dict = {}
        if FINDINGS_FILE.exists():
            with open(FINDINGS_FILE) as f:
                perf_report_dict = json.load(f)

        issues = perf_report_dict.get("issues", [])
        result = research_agent.run(
            issues=issues,
            perf_report=perf_report_dict,
        )

        monitor.record(
            input_tokens=result.input_tokens_used,
            output_tokens=result.output_tokens_used,
            step="research",
        )
        monitor.check_and_warn()

        actions = [c.title for c in result.proposed_changes]
        return actions

    except ValueError as e:
        print(f"\n{YELLOW}[RESEARCH] Skipped: {e}{RESET}")
        print(f"  Set ANTHROPIC_API_KEY in your .env to enable AI research.")
        return []


# ── Main Orchestrator ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="InfoBhoomi Agent Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--perf-only",  action="store_true",
                        help="Run API performance test only (no research, no QA)")
    parser.add_argument("--qa-only",    action="store_true",
                        help="Run QA tests only — no perf test, no research")
    parser.add_argument("--resume",     action="store_true",
                        help="Resume from last checkpoint without prompting")
    parser.add_argument("--clear",      action="store_true",
                        help="Clear all session state and start fresh")
    parser.add_argument("--show",       action="store_true",
                        help="Show pending changes from last run and exit")
    parser.add_argument("--approve",    action="store_true",
                        help="Go straight to change approval flow")
    parser.add_argument("--memory",     action="store_true",
                        help="Print memory status (history of all cycles) and exit")
    args = parser.parse_args()

    # ── Memory Agent always loads first ──────────────────────────────────────
    memory = MemoryAgent()

    # ── --memory ─────────────────────────────────────────────────────────────
    if args.memory:
        _banner("Memory Agent — Cycle History")
        memory.print_status()
        return

    # ── --show ────────────────────────────────────────────────────────────────
    if args.show:
        if PENDING_CHANGES_FILE.exists():
            with open(PENDING_CHANGES_FILE) as f:
                print(json.dumps(json.load(f), indent=2))
        else:
            print("No pending changes file found.")
        return

    # ── Token monitor ─────────────────────────────────────────────────────────
    monitor = TokenMonitor()

    if args.clear:
        monitor.clear()
        print(f"{GREEN}Session state cleared.{RESET}")
        monitor.load()
    else:
        resumed = monitor.load()
        if resumed and not args.resume:
            ans = _ask(f"\n  {YELLOW}Previous session found.{RESET} Resume? [Y/n]: ")
            if ans in ("n", "no"):
                monitor.clear()
                monitor.load()

    # ── --approve only ────────────────────────────────────────────────────────
    if args.approve:
        run_id   = memory.start_run()
        approved = review_and_approve_changes(monitor)
        titles   = apply_changes(approved)
        skipped  = [c.get("title", "?") for c in
                    (json.load(open(PENDING_CHANGES_FILE)).get("changes", [])
                     if PENDING_CHANGES_FILE.exists() else [])
                    if not c.get("approved")]
        memory.record_implementations(run_id, approved=titles, skipped=skipped)
        memory.complete_run(run_id)
        monitor.save()
        return

    # ── --perf-only ───────────────────────────────────────────────────────────
    if args.perf_only:
        _banner("PHASE 1 — GIS Performance Test")
        token    = monitor.checkpoint.get("token", "")
        layer_id = int(monitor.checkpoint.get("layer_id", 0))
        perf_agent = GISPerfAgent(token=token, layer_id=layer_id)
        report     = perf_agent.run()
        if not perf_agent.token:
            print(f"\n{RED}Authentication failed.{RESET}")
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(FINDINGS_FILE, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        monitor.mark_step_done("perf_complete")
        monitor.save(checkpoint_data={
            "token":    perf_agent.token,
            "layer_id": report.layer_id or 0,
        })
        _banner("PERFORMANCE TEST COMPLETE")
        print(f"  Findings saved → {FINDINGS_FILE}")
        return

    # ── --qa-only ─────────────────────────────────────────────────────────────
    if args.qa_only:
        run_id   = memory.start_run()
        token    = monitor.checkpoint.get("token", "")
        layer_id = int(monitor.checkpoint.get("layer_id", 0))
        report   = run_qa(token, layer_id)
        memory.record_qa(run_id, report)
        memory.complete_run(run_id, status="qa_only")
        memory.print_status()
        monitor.save()
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # FULL LOOP: QA → Research (with permission) → Approve → Apply → repeat
    # ═══════════════════════════════════════════════════════════════════════════

    # ── First: GIS Performance Test (once per session) ────────────────────────
    if not monitor.is_step_done("perf_complete"):
        _banner("PHASE 1 — GIS Performance Test")
        token    = monitor.checkpoint.get("token", "")
        layer_id = int(monitor.checkpoint.get("layer_id", 0))

        perf_agent = GISPerfAgent(token=token, layer_id=layer_id)
        perf_report = perf_agent.run()

        if not perf_agent.token:
            print(f"\n{RED}Authentication failed — set credentials in agents/.env{RESET}")
            print(f"  Keys: IB_TOKEN  or  IB_USERNAME + IB_PASSWORD")
            monitor.save()
            return

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(FINDINGS_FILE, "w") as f:
            json.dump(perf_report.to_dict(), f, indent=2)

        monitor.mark_step_done("perf_complete")
        monitor.save(checkpoint_data={
            "token":    perf_agent.token,
            "layer_id": perf_report.layer_id or 0,
            "issues_count": len(perf_report.issues),
        })
    else:
        print(f"\n{CYAN}[ORCHESTRATOR]{RESET} Performance test already done — skipping.")

    token    = monitor.checkpoint.get("token", "")
    layer_id = int(monitor.checkpoint.get("layer_id", 0))

    # ── QA → Research → Fix loop ──────────────────────────────────────────────
    loop_number = 0

    while loop_number < MAX_AUTO_LOOPS:
        loop_number += 1
        _banner(f"QA CYCLE {loop_number}")

        # Show memory at start of each cycle
        memory.print_last_run_summary()

        # ── QA ────────────────────────────────────────────────────────────────
        run_id      = memory.start_run()
        qa_report   = run_qa(token, layer_id)
        memory.record_qa(run_id, qa_report)

        failed  = qa_report.get("failed", 0)
        total   = qa_report.get("total", 0)
        passed  = qa_report.get("passed", 0)
        issues  = qa_report.get("issues", [])

        print(f"\n  {BOLD}Cycle {loop_number} result: "
              f"{GREEN if failed == 0 else RED}{passed}/{total} passed  "
              f"{failed} failed{RESET}")

        # ── All clear? ────────────────────────────────────────────────────────
        if failed == 0:
            _banner("ALL QA CHECKS PASSED ✔")
            memory.resolve_issues(run_id, qa_report)
            memory.complete_run(run_id, status="clean")
            memory.print_status()
            print(f"\n  {GREEN}No issues remain — system is healthy.{RESET}")
            break

        # ── Issues found: ask permission to run Research Agent ────────────────
        print(f"\n  {RED}{failed} failure(s) detected.{RESET}")
        print(f"  Open issues in memory: {len(memory.open_issues)}")
        print()
        for iss in issues:
            print(f"    {RED}✘{RESET}  [{iss['label']}]  {iss['message']}")

        ans = _ask(
            f"\n  Run Research Agent to investigate these {failed} issue(s)? [Y/n]: "
        )

        if ans in ("n", "no"):
            memory.complete_run(run_id, status="issues_deferred")
            print(f"\n  {YELLOW}Research skipped. Issues recorded in memory.{RESET}")
            print(f"  Run again later to continue the loop.")
            break

        # ── Research Agent ────────────────────────────────────────────────────
        status = monitor.check_and_warn()
        if status == "critical":
            print(f"{RED}Token limit critical — saving state for next session.{RESET}")
            memory.complete_run(run_id, status="token_limit")
            monitor.save()
            break

        actions = run_research(monitor)
        memory.record_research(run_id, actions)

        if not actions:
            print(f"\n  {YELLOW}Research produced no actions — check ANTHROPIC_API_KEY.{RESET}")
            memory.complete_run(run_id, status="research_empty")
            break

        # ── Change review & apply ─────────────────────────────────────────────
        approved_changes = review_and_approve_changes(monitor)
        applied_titles   = apply_changes(approved_changes)

        skipped_titles = []
        if PENDING_CHANGES_FILE.exists():
            with open(PENDING_CHANGES_FILE) as f:
                all_changes = json.load(f).get("changes", [])
            skipped_titles = [
                c.get("title", "?") for c in all_changes
                if not c.get("approved")
            ]

        memory.record_implementations(run_id,
                                      approved=applied_titles,
                                      skipped=skipped_titles)
        memory.complete_run(run_id, status="cycle_complete")

        if not applied_titles:
            print(f"\n  {YELLOW}No changes were applied — exiting loop to avoid infinite retry.{RESET}")
            break

        # ── Ask before next loop iteration ────────────────────────────────────
        ans2 = _ask(
            f"\n  {GREEN}{len(applied_titles)} change(s) applied.{RESET} "
            f"Run QA again to verify fixes? [Y/n]: "
        )
        if ans2 in ("n", "no"):
            print(f"\n  {CYAN}Loop stopped. Run again to re-test.{RESET}")
            break

        # Clear QA findings so the next run starts fresh
        if FINDINGS_FILE.exists():
            existing = json.load(open(FINDINGS_FILE))
            existing["issues"] = []
            with open(FINDINGS_FILE, "w") as f:
                json.dump(existing, f, indent=2)

    else:
        print(f"\n{YELLOW}Safety cap reached ({MAX_AUTO_LOOPS} cycles). "
              f"Run again to continue.{RESET}")

    # ── Final status ──────────────────────────────────────────────────────────
    _banner("SESSION COMPLETE")
    memory.print_status()
    monitor.save()
    print(f"\n  Run {CYAN}python orchestrator.py --memory{RESET} to see full history.")
    print(f"  Run {CYAN}python orchestrator.py{RESET} to start the next cycle.\n")


if __name__ == "__main__":
    main()
