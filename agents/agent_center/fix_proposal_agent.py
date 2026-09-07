from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import AGENT_FIX_PROPOSALS_FILE, STATE_DIR
from agent_center.ai_provider import AIProviderError, GeminiProvider, build_fix_prompt
from agent_center.structured_memory import StructuredMemory, utc_now


class FixProposalAgent:
    """Creates approval-gated fix proposals and validates patch paths."""

    def __init__(self, workspace_root: Path | None = None, memory: StructuredMemory | None = None):
        self.workspace_root = (workspace_root or Path(__file__).resolve().parents[2]).resolve()
        self.memory = memory or StructuredMemory()
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def propose_from_issue(self, issue: dict[str, Any], provider: str = "local") -> dict[str, Any]:
        category = issue.get("function_category", "Unknown")
        sub_function = issue.get("sub_function", "Unknown")
        symptom = issue.get("symptom", "")
        evidence = {
            "api": issue.get("api_evidence", {}),
            "db": issue.get("db_evidence", {}),
        }

        proposal = self._local_proposal(issue, category, sub_function, symptom, evidence)
        if provider == "gemini":
            proposal = self._gemini_proposal(issue, proposal)

        stored = self.memory.record_fix(proposal)
        self._save_all()
        return stored

    def _local_proposal(
        self,
        issue: dict[str, Any],
        category: str,
        sub_function: str,
        symptom: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "title": f"Investigate {category}: {sub_function}",
            "issue_id": issue.get("issue_id", ""),
            "summary": symptom,
            "root_cause": issue.get("root_cause") or "Needs source-level investigation based on the failing function evidence.",
            "risk_notes": [
                "Do not apply changes directly to production without rerunning the targeted function test.",
                "Validate API behavior and read-only DB evidence after the patch is applied.",
            ],
            "implementation_plan": [
                "Open the backend view/service tied to the failing endpoint.",
                "Reproduce with the captured API payload and database evidence.",
                "Patch the smallest code path that explains the failing function.",
                "Rerun the affected function test and relevant regression checks.",
            ],
            "patch_preview": "",
            "suspected_files": self._suspected_files(category),
            "tests_to_rerun": [issue.get("sub_function", ""), category],
            "evidence": evidence,
            "status": "planned",
            "created_at": utc_now(),
            "ai_provider": "local",
        }

    def _gemini_proposal(self, issue: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        provider = GeminiProvider()
        try:
            generated = provider.generate_json(build_fix_prompt(issue))
            proposal = dict(fallback)
            for key in (
                "title",
                "summary",
                "root_cause",
                "risk_notes",
                "implementation_plan",
                "patch_preview",
                "suspected_files",
                "tests_to_rerun",
            ):
                if key in generated and generated[key]:
                    proposal[key] = generated[key]
            proposal["ai_provider"] = "gemini"
            proposal["ai_model"] = provider.model
            return proposal
        except AIProviderError as exc:
            proposal = dict(fallback)
            proposal["ai_provider"] = "gemini"
            proposal["ai_error"] = str(exc)
            proposal["risk_notes"] = list(proposal.get("risk_notes", [])) + [
                "Gemini proposal generation failed; local fallback proposal was used."
            ]
            return proposal

    def approve(self, fix_id: str) -> dict[str, Any]:
        fix = self.memory.update_fix(fix_id, status="approved", approved_at=utc_now())
        self._save_all()
        return fix

    def reject(self, fix_id: str) -> dict[str, Any]:
        fix = self.memory.update_fix(fix_id, status="rejected", rejected_at=utc_now())
        self._save_all()
        return fix

    def validate_workspace_path(self, relative_path: str) -> Path:
        candidate = (self.workspace_root / relative_path).resolve()
        if self.workspace_root not in candidate.parents and candidate != self.workspace_root:
            raise ValueError(f"Patch path escapes workspace: {relative_path}")
        return candidate

    def list_fixes(self) -> list[dict[str, Any]]:
        return self.memory.data.get("fixes", [])

    def _save_all(self) -> None:
        AGENT_FIX_PROPOSALS_FILE.write_text(
            json.dumps({"fixes": self.list_fixes()}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _suspected_files(self, category: str) -> list[str]:
        mapping = {
            "Auth": ["InfoBhoomi_Backend_dev2/user/views/auth.py", "infoBhoomi-frontedend-div2/src/app/services/auth.service.ts"],
            "Layers": ["InfoBhoomi_Backend_dev2/user/views/layers.py", "infoBhoomi-frontedend-div2/src/app/services/layer.service.ts"],
            "Survey Geometry": ["InfoBhoomi_Backend_dev2/user/views/survey.py", "infoBhoomi-frontedend-div2/src/app/services/draw.service.ts"],
            "Land": ["InfoBhoomi_Backend_dev2/user/views/land.py", "infoBhoomi-frontedend-div2/src/app/components/side-panel/land-info-panel"],
            "Building": ["InfoBhoomi_Backend_dev2/user/views/building.py", "infoBhoomi-frontedend-div2/src/app/components/side-panel/building-info-panel"],
            "RRR": ["InfoBhoomi_Backend_dev2/user/views/rrr.py", "InfoBhoomi_Backend_dev2/user/models/rrr.py"],
            "Parties": ["InfoBhoomi_Backend_dev2/user/views/party.py", "InfoBhoomi_Backend_dev2/user/models/party.py"],
            "Search/Query/Export": ["InfoBhoomi_Backend_dev2/user/views/search.py"],
        }
        return mapping.get(category, ["InfoBhoomi_Backend_dev2/user/views", "infoBhoomi-frontedend-div2/src/app"])
