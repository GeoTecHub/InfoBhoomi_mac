"""
InfoBhoomi — Research Agent
=============================
Given a list of performance issues found by GISPerfAgent, uses Claude
to research root causes and propose concrete, actionable fixes.

Each proposed change includes:
  - file path
  - description of the change
  - code diff / snippet
  - confidence level

Changes are written to pending_changes.json and presented to the user
for approval before anything is modified in the actual codebase.
"""

import json
import sys
import anthropic
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Windows Unicode fix ────────────────────────────────────────────────────────
# Windows consoles default to cp1252 which can't encode → ✔ ✘ etc.
# Reconfigure stdout/stderr to UTF-8 with replacement for any remaining gaps.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    PENDING_CHANGES_FILE,
    STATE_DIR,
    BASE_URL,
)

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ── Data structures ───────────────────────────────────────────────────────────

class ProposedChange:
    def __init__(
        self,
        title: str,
        file_path: str,
        description: str,
        code_snippet: str,
        confidence: str,  # "high" | "medium" | "low"
        issue_ref: str = "",
    ):
        self.title = title
        self.file_path = file_path
        self.description = description
        self.code_snippet = code_snippet
        self.confidence = confidence
        self.issue_ref = issue_ref
        self.approved: Optional[bool] = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "file_path": self.file_path,
            "description": self.description,
            "code_snippet": self.code_snippet,
            "confidence": self.confidence,
            "issue_ref": self.issue_ref,
            "approved": self.approved,
        }


class ResearchResult:
    def __init__(self):
        self.researched_at = datetime.utcnow().isoformat() + "Z"
        self.analysis: str = ""
        self.proposed_changes: list[ProposedChange] = []
        self.input_tokens_used: int = 0
        self.output_tokens_used: int = 0

    def to_dict(self) -> dict:
        return {
            "researched_at": self.researched_at,
            "analysis": self.analysis,
            "proposed_changes": [c.to_dict() for c in self.proposed_changes],
            "tokens": {
                "input": self.input_tokens_used,
                "output": self.output_tokens_used,
                "total": self.input_tokens_used + self.output_tokens_used,
            },
        }


# ── Main Agent Class ──────────────────────────────────────────────────────────

class ResearchAgent:
    """
    Uses Claude to analyse performance issues from GISPerfAgent and
    propose specific, code-level fixes for the InfoBhoomi Django/PostGIS stack.
    """

    # Project context injected into every Claude prompt so it understands
    # the InfoBhoomi stack without needing to read files itself.
    PROJECT_CONTEXT = """
You are analysing InfoBhoomi — a web-GIS land administration system for Sri Lanka.

Stack:
  - Frontend: Angular 21 + Angular Material
  - Backend: Django 5.1 + Django REST Framework + djangorestframework-gis
  - Database: PostgreSQL + PostGIS
  - Auth: DRF Token Authentication

Key API endpoints:
  POST /api/user/survey_rep_data/         → save polygon/point/line spatial features
  POST /api/user/survey_rep_data_user/    → retrieve user features (GeoJSON)
  PATCH /api/user/survey_rep_data/update/id=<pk>/ → update feature attributes
  GET  /api/user/layerdata_get_user/      → get user layers
  POST /api/user/search/                  → spatial search
  GET  /api/user/rrr_data_get/            → RRR (Rights, Restrictions, Responsibilities)
  GET  /api/user/sl-party-data/           → party (owner) data
  GET  /api/user/org_area/               → organisation boundary area

Backend models include: SpatialUnit (geometry), Layer, BAUnit (RRR), Party,
Organization, Survey, Assessment. Geometry stored using PostGIS.

The existing codebase is in:
  Backend: InfoBhoomi_Backend_dev2/
  Frontend: infoBhoomi-frontedend-div2/
"""

    def __init__(self, api_key: str = ""):
        key = api_key or ANTHROPIC_API_KEY
        if not key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Add it to config.py or set the env var."
            )
        self.client = anthropic.Anthropic(api_key=key)
        self.result = ResearchResult()

    def run(self, issues: list[str], perf_report: Optional[dict] = None) -> ResearchResult:
        """
        Main entry point. Analyses the given issues list and returns a ResearchResult
        with proposed code-level fixes.

        Args:
            issues:      List of issue strings from GISPerfAgent.
            perf_report: Full performance report dict (optional, for richer context).
        """
        if not issues:
            print(f"\n{GREEN}[RESEARCH AGENT]{RESET} No issues to research — all clear!")
            return self.result

        print(f"\n{BOLD}{'='*60}")
        print("  InfoBhoomi Research Agent")
        print(f"  Analysing {len(issues)} issue(s)...")
        print(f"{'='*60}{RESET}")

        try:
            # Step 1: Root cause analysis
            self._analyse_issues(issues, perf_report)

            # Step 2: Generate specific fix proposals
            self._generate_fixes(issues)

            # Step 3: Save to pending_changes.json
            self._save_pending_changes()

        except anthropic.BadRequestError as e:
            if "credit balance is too low" in str(e):
                print(f"\n{YELLOW}{'='*60}")
                print(f"  ⚠  ANTHROPIC CREDITS EXHAUSTED")
                print(f"{'='*60}{RESET}")
                print(f"  The Research Agent needs Anthropic API credits to run.")
                print(f"  Add credits at: {CYAN}https://console.anthropic.com{RESET}")
                print(f"  → Plans & Billing → Add credits (a few dollars is enough)\n")
                print(f"  In the meantime, the performance report was saved to:")
                print(f"  {CYAN}.agent_state/findings.json{RESET}")
                print(f"  Run again after adding credits — no need to re-run the perf test.\n")
            else:
                print(f"\n{RED}[RESEARCH AGENT] API error: {e}{RESET}")

        except anthropic.AuthenticationError:
            print(f"\n{RED}[RESEARCH AGENT] Invalid API key.{RESET}")
            print(f"  Check ANTHROPIC_API_KEY in your .env file.")
            print(f"  Get a key at: {CYAN}https://console.anthropic.com{RESET}\n")

        except anthropic.APIConnectionError:
            print(f"\n{YELLOW}[RESEARCH AGENT] No internet connection — skipping research phase.{RESET}\n")

        except Exception as e:
            print(f"\n{RED}[RESEARCH AGENT] Unexpected error: {type(e).__name__}: {e}{RESET}\n")

        return self.result

    # ── Step 1: Root cause analysis ───────────────────────────────────────────

    def _analyse_issues(self, issues: list[str], perf_report: Optional[dict]):
        print(f"\n{CYAN}[RESEARCH]{RESET} Step 1 — Root cause analysis...")

        issues_text = "\n".join(f"  {i+1}. {issue}" for i, issue in enumerate(issues))
        perf_text = ""
        if perf_report:
            slow = [
                r for r in perf_report.get("results", [])
                if r.get("elapsed_ms", 0) >= 1000
            ]
            if slow:
                perf_text = "\n\nSlow endpoint timings:\n" + "\n".join(
                    f"  {r['method']} {r['url']} → {r['elapsed_ms']:.0f}ms"
                    for r in slow
                )

        prompt = f"""{self.PROJECT_CONTEXT}

The GIS Performance Agent found the following issues:

{issues_text}{perf_text}

Please provide:
1. A concise root-cause analysis for each issue (2-3 sentences each)
2. Which layer of the stack is most likely responsible (Django ORM, PostGIS query,
   DRF serializer, Angular, network, etc.)
3. Priority ranking: which issues have the biggest user impact

Keep the analysis technical and specific to the InfoBhoomi stack.
"""

        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        self.result.analysis = response.content[0].text
        self.result.input_tokens_used  += response.usage.input_tokens
        self.result.output_tokens_used += response.usage.output_tokens

        print(f"\n{BOLD}Root Cause Analysis:{RESET}")
        # Safe-print: replace any character the console can't encode (e.g. → on Windows cp1252)
        safe_analysis = self.result.analysis.encode(
            sys.stdout.encoding or "utf-8", errors="replace"
        ).decode(sys.stdout.encoding or "utf-8", errors="replace")
        print(safe_analysis)

    # ── Step 2: Propose fixes ─────────────────────────────────────────────────

    # Tool schema for structured fix proposals — using tool_use guarantees valid
    # JSON serialisation even when code_snippet contains { } characters.
    _FIX_TOOL = {
        "name": "submit_fix_proposals",
        "description": (
            "Submit a list of concrete, implementable fix proposals for the "
            "InfoBhoomi performance/backend issues."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "proposals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title":        {"type": "string", "description": "Short title of the fix"},
                            "file_path":    {"type": "string", "description": "Relative path to the file to change"},
                            "description":  {"type": "string", "description": "What the change does and why it helps"},
                            "code_snippet": {"type": "string", "description": "The actual code to add or change"},
                            "confidence":   {"type": "string", "enum": ["high", "medium", "low"]},
                            "issue_ref":    {"type": "string", "description": "Which issue number(s) this addresses"},
                        },
                        "required": ["title", "file_path", "description", "code_snippet", "confidence", "issue_ref"],
                    },
                }
            },
            "required": ["proposals"],
        },
    }

    def _generate_fixes(self, issues: list[str]):
        print(f"\n{CYAN}[RESEARCH]{RESET} Step 2 — Generating fix proposals...")

        issues_text = "\n".join(f"  {i+1}. {issue}" for i, issue in enumerate(issues))

        prompt = f"""{self.PROJECT_CONTEXT}

Based on this analysis of InfoBhoomi's performance/backend issues:

{issues_text}

Call the submit_fix_proposals tool with specific, implementable fix proposals.

Focus on:
- PostGIS spatial index additions (GIST indexes on geometry columns)
- Django select_related / prefetch_related for N+1 query patterns
- DRF serializer optimisation (only_fields, deferred geometry)
- ST_Simplify for large geometry rendering
- Django query caching (django-cacheops or per-view cache)
- Pagination on large feature responses
- Missing get_or_create patterns in update views
- Role-permission field filtering issues in admin info endpoint
"""

        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=5000,
            tools=[self._FIX_TOOL],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}],
        )

        self.result.input_tokens_used  += response.usage.input_tokens
        self.result.output_tokens_used += response.usage.output_tokens

        # Extract tool_use block — guaranteed valid, no manual JSON parsing needed
        changes_data: list[dict] = []
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_fix_proposals":
                changes_data = block.input.get("proposals", [])
                break

        if not changes_data:
            print(f"{YELLOW}[RESEARCH]{RESET} No fix proposals returned by the model.")

        for c in changes_data:
            change = ProposedChange(
                title=c.get("title", "Untitled fix"),
                file_path=c.get("file_path", ""),
                description=c.get("description", ""),
                code_snippet=c.get("code_snippet", ""),
                confidence=c.get("confidence", "medium"),
                issue_ref=str(c.get("issue_ref", "")),
            )
            self.result.proposed_changes.append(change)

    # ── Step 3: Save pending changes ──────────────────────────────────────────

    def _save_pending_changes(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "generated_at": self.result.researched_at,
            "analysis": self.result.analysis,
            "changes": [c.to_dict() for c in self.result.proposed_changes],
            "tokens_used": {
                "input": self.result.input_tokens_used,
                "output": self.result.output_tokens_used,
                "total": self.result.input_tokens_used + self.result.output_tokens_used,
            },
        }
        with open(PENDING_CHANGES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"\n{CYAN}[RESEARCH]{RESET} {len(self.result.proposed_changes)} fix proposal(s) saved")
        print(f"  → {PENDING_CHANGES_FILE}")

        # Print summary of proposals
        print(f"\n{BOLD}Proposed Changes:{RESET}")
        for i, c in enumerate(self.result.proposed_changes, 1):
            conf_color = GREEN if c.confidence == "high" else YELLOW if c.confidence == "medium" else RED
            print(f"\n  {BOLD}[{i}]{RESET} {c.title}")
            print(f"       File:       {c.file_path}")
            print(f"       Confidence: {conf_color}{c.confidence}{RESET}")
            print(f"       Issue:      #{c.issue_ref}")
            desc = c.description[:120] + ("..." if len(c.description) > 120 else "")
            safe_desc = desc.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                sys.stdout.encoding or "utf-8", errors="replace"
            )
            print(f"       {safe_desc}")

        print(f"\n  Tokens used this research run: "
              f"{self.result.input_tokens_used + self.result.output_tokens_used:,} "
              f"(input: {self.result.input_tokens_used:,}  output: {self.result.output_tokens_used:,})")
