"""
DBInvestigator — uses the existing DBVerificationAgent and adds key_field
verification (Decision: actual evidence, not just COUNT(*)).

Behaviour:
  - For each DBSubcomponent: run the registered DBVerificationAgent table
    check (always available; no-op when DB connection isn't configured).
  - When key_fields are present and the DB is available, perform a sample
    SELECT to confirm at least one row exists with non-null key_fields.
  - Wildcard tables (e.g. ``lst_*``) are reported as "skipped".
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable

from agent_center.component_map import DBSubcomponent
from agent_center.db_verification_agent import DBVerificationAgent
from agent_center.function_registry import DbCheck
from agent_center.investigators.base import (
    BaseInvestigator,
    InvestigationFinding,
    InvestigationResult,
)


class DBInvestigator(BaseInvestigator):
    layer = "db"

    def __init__(self, agent: DBVerificationAgent | None = None):
        self.agent = agent or DBVerificationAgent()

    def investigate(self, subcomponents: Iterable[DBSubcomponent]) -> InvestigationResult:
        started = time.perf_counter()
        findings: list[InvestigationFinding] = []
        inspected: list[str] = []

        for sc in subcomponents:
            inspected.append(sc.table)

            if "*" in sc.table:
                findings.append(InvestigationFinding(
                    layer="db",
                    severity="info",
                    title="Wildcard DB check skipped",
                    detail=f"{sc.table} is a multi-table marker; no per-table check executed.",
                    affected_subcomponent=sc.table,
                    evidence={"model": sc.model, "key_fields": list(sc.key_fields)},
                ))
                continue

            check = DbCheck(model=sc.model, table=sc.table, key_fields=sc.key_fields)
            result = self.agent.verify_registered_table(check).to_dict()
            findings.append(self._finding_from_result(sc, result))

            # Optional: deeper key_fields probe when DB is available.
            if result.get("enabled") and result.get("passed") and sc.key_fields:
                probe = self._probe_key_fields(sc)
                if probe is not None:
                    findings.append(probe)

        return InvestigationResult(
            layer="db",
            status=self._worst(findings) if findings else "ok",
            findings=findings,
            inspected_subcomponents=inspected,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    def _finding_from_result(
        self,
        sc: DBSubcomponent,
        result: dict,
    ) -> InvestigationFinding:
        if not result.get("enabled"):
            return InvestigationFinding(
                layer="db",
                severity="info",
                title="DB verification skipped",
                detail=result.get("message", ""),
                affected_subcomponent=sc.table,
                evidence={"model": sc.model, "key_fields": list(sc.key_fields)},
            )
        if not result.get("passed"):
            return InvestigationFinding(
                layer="db",
                severity="error",
                title="DB table check failed",
                detail=result.get("message", "Read-only DB check failed."),
                affected_subcomponent=sc.table,
                evidence={
                    "model":      sc.model,
                    "key_fields": list(sc.key_fields),
                    "raw":        result.get("evidence", {}),
                },
            )
        return InvestigationFinding(
            layer="db",
            severity="ok",
            title="DB table reachable",
            detail=result.get("message", ""),
            affected_subcomponent=sc.table,
            evidence={
                "model":      sc.model,
                "key_fields": list(sc.key_fields),
                "row_count":  result.get("evidence", {}).get("row_count"),
            },
        )

    def _probe_key_fields(self, sc: DBSubcomponent) -> InvestigationFinding | None:
        """
        Confirm a sample row has all key_fields populated. Only runs when the
        underlying DBVerificationAgent has a working connection.
        """
        if not self.agent.available:
            return None
        try:
            import psycopg2
            from psycopg2 import sql
        except Exception:
            return None

        try:
            conn = self.agent._connect(psycopg2)
        except Exception as exc:
            return InvestigationFinding(
                layer="db",
                severity="warning",
                title="DB connection failed during key_field probe",
                detail=f"{type(exc).__name__}: {exc}",
                affected_subcomponent=sc.table,
                evidence={"model": sc.model, "key_fields": list(sc.key_fields)},
            )
        try:
            with conn.cursor() as cur:
                # Build a parameterised SELECT that asks for the key_fields.
                col_sql = sql.SQL(", ").join(sql.Identifier(c) for c in sc.key_fields)
                stmt = sql.SQL("SELECT {} FROM {} LIMIT 1").format(
                    col_sql, sql.Identifier(sc.table.split(",", 1)[0].strip()),
                )
                cur.execute(stmt)
                row = cur.fetchone()
            if row is None:
                return InvestigationFinding(
                    layer="db",
                    severity="warning",
                    title="Table is empty",
                    detail=f"{sc.table} has no rows; key_field verification cannot proceed.",
                    affected_subcomponent=sc.table,
                    evidence={"key_fields": list(sc.key_fields)},
                )
            null_fields = [
                col for col, val in zip(sc.key_fields, row) if val is None
            ]
            if null_fields:
                return InvestigationFinding(
                    layer="db",
                    severity="error",
                    title="Key field NULL in sample row",
                    detail=f"key_field(s) {null_fields} are NULL in the first row of {sc.table}.",
                    affected_subcomponent=sc.table,
                    evidence={"key_fields": list(sc.key_fields), "null_fields": null_fields},
                )
            return InvestigationFinding(
                layer="db",
                severity="ok",
                title="Key fields populated in sample row",
                affected_subcomponent=sc.table,
                evidence={"key_fields": list(sc.key_fields)},
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
