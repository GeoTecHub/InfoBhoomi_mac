from __future__ import annotations

from agent_center.function_qa_agent import FunctionQAAgent


class RegressionAgent:
    """Reruns affected function checks after a fix is approved/applied."""

    def __init__(self, qa_agent: FunctionQAAgent | None = None):
        self.qa_agent = qa_agent or FunctionQAAgent()

    def rerun_for_fix(self, fix: dict) -> dict:
        tests = [item for item in fix.get("tests_to_rerun", []) if item]
        if not tests:
            return self.qa_agent.run_all()

        # Prefer exact function ids, then category names.
        first = tests[0]
        if "." in first:
            return self.qa_agent.run_function(first)
        return self.qa_agent.run_category(first)

