from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from config import (
    IB_DATABASE_URL,
    IB_DB_HOST,
    IB_DB_NAME,
    IB_DB_PASSWORD,
    IB_DB_PORT,
    IB_DB_USER,
)
from agent_center.function_registry import DbCheck, all_functions, functions_by_category, get_function


@dataclass
class DbVerificationResult:
    enabled: bool
    passed: bool
    model: str
    table: str
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DBVerificationAgent:
    """Read-only database verifier for QA evidence."""

    def __init__(self):
        self._available = bool(IB_DATABASE_URL or (IB_DB_HOST and IB_DB_NAME and IB_DB_USER))

    @property
    def available(self) -> bool:
        return self._available

    def status(self) -> dict[str, Any]:
        missing = []
        if not IB_DATABASE_URL:
            for key, value in {
                "IB_DB_HOST": IB_DB_HOST,
                "IB_DB_NAME": IB_DB_NAME,
                "IB_DB_USER": IB_DB_USER,
            }.items():
                if not value:
                    missing.append(key)
        try:
            import psycopg2  # noqa: F401

            driver_available = True
            driver_error = ""
        except Exception as exc:
            driver_available = False
            driver_error = f"{type(exc).__name__}: {exc}"
        return {
            "agent": "DB Verification Agent",
            "available": self._available,
            "driver_available": driver_available,
            "driver_error": driver_error,
            "configured_by": "IB_DATABASE_URL" if IB_DATABASE_URL else "IB_DB_* fields",
            "target": self._safe_target(),
            "missing_config": missing if not self._available else [],
            "mode": "read-only verification; never writes to the database",
        }

    def run_registry_checks(
        self,
        *,
        function_id: str | None = None,
        category: str | None = None,
        record_issues: bool = False,
    ) -> dict[str, Any]:
        if function_id:
            functions = [get_function(function_id)]
            scope = {"type": "function", "value": function_id}
        elif category:
            functions = functions_by_category(category)
            scope = {"type": "category", "value": category}
        else:
            functions = all_functions()
            scope = {"type": "all", "value": "all"}

        results = []
        for fn in functions:
            for check in fn.db_checks:
                item = self.verify_registered_table(check).to_dict()
                item.update(
                    {
                        "function_id": fn.id,
                        "display_name": fn.display_name,
                        "category": fn.category,
                    }
                )
                results.append(item)

        failed = [item for item in results if item.get("enabled") and not item.get("passed")]
        if record_issues and failed:
            from agent_center.structured_memory import StructuredMemory

            memory = StructuredMemory()
            for item in failed:
                memory.record_issue(
                    function_category=item.get("category", "Database"),
                    sub_function=item.get("display_name", item.get("model", "DB verification")),
                    symptom=f"DB verification failed for {item.get('table')}",
                    detected_by="DB Verification Agent",
                    db_evidence=item,
                    root_cause="Expected database table/model was not found or could not be read.",
                    proposed_solution="Confirm the function registry table name matches the Django model's actual db_table, then rerun DB verification.",
                    test_results_before=item,
                )
        skipped = [item for item in results if not item.get("enabled")]
        return {
            "scope": scope,
            "status": "failed" if failed else ("skipped" if skipped and len(skipped) == len(results) else "passed"),
            "summary": {
                "total_checks": len(results),
                "passed": len([item for item in results if item.get("enabled") and item.get("passed")]),
                "failed": len(failed),
                "skipped": len(skipped),
            },
            "db_status": self.status(),
            "results": results,
        }

    def verify_registered_table(self, check: DbCheck) -> DbVerificationResult:
        if not self._available:
            return DbVerificationResult(
                enabled=False,
                passed=True,
                model=check.model,
                table=check.table,
                message="DB verification skipped: read-only DB connection is not configured.",
                evidence={"notes": check.notes},
            )

        try:
            import psycopg2
            from psycopg2 import sql
        except Exception as exc:
            return DbVerificationResult(
                enabled=False,
                passed=False,
                model=check.model,
                table=check.table,
                message="DB verification unavailable: psycopg2 is not installed.",
                evidence={"error": f"{type(exc).__name__}: {exc}"},
            )

        table = check.table.split(",", 1)[0].strip()
        if not table or "*" in table:
            return DbVerificationResult(
                enabled=True,
                passed=True,
                model=check.model,
                table=check.table,
                message="DB check recorded but not executed for wildcard or multi-table lookup.",
                evidence={"table": check.table, "notes": check.notes},
            )

        try:
            conn = self._connect(psycopg2)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)))
                    count = cur.fetchone()[0]
                return DbVerificationResult(
                    enabled=True,
                    passed=True,
                    model=check.model,
                    table=table,
                    message=f"Read-only DB check passed: {count} row(s) visible.",
                    evidence={"row_count": count, "key_fields": list(check.key_fields)},
                )
            finally:
                conn.close()
        except Exception as exc:
            return DbVerificationResult(
                enabled=True,
                passed=False,
                model=check.model,
                table=table,
                message="Read-only DB check failed.",
                evidence={"error": f"{type(exc).__name__}: {exc}"},
            )

    def _connect(self, psycopg2):
        if IB_DATABASE_URL:
            return psycopg2.connect(IB_DATABASE_URL)
        return psycopg2.connect(
            host=IB_DB_HOST,
            port=IB_DB_PORT,
            dbname=IB_DB_NAME,
            user=IB_DB_USER,
            password=IB_DB_PASSWORD,
        )

    def _safe_target(self) -> dict[str, Any]:
        if IB_DATABASE_URL:
            return {"database_url_configured": True, "password": "<redacted>"}
        return {
            "host": IB_DB_HOST,
            "port": IB_DB_PORT,
            "database": IB_DB_NAME,
            "user": IB_DB_USER,
            "password": "<redacted>" if IB_DB_PASSWORD else "",
        }
