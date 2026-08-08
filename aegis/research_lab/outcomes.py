"""Append-only matured outcome and deterministic postmortem ledger."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from aegis.contracts import OutcomeRecord, PostmortemReport, canonical_json, canonical_sha256


class OutcomeIntegrityError(RuntimeError):
    pass


class OutcomeLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """CREATE TABLE IF NOT EXISTS outcomes (
                    outcome_id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS postmortems (
                    report_id TEXT PRIMARY KEY, payload TEXT NOT NULL, record_hash TEXT NOT NULL
                );"""
            )

    def _append(self, table: str, key_name: str, key: str, value: object) -> None:
        payload, digest = canonical_json(value), canonical_sha256(value)
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                f"SELECT payload, record_hash FROM {table} WHERE {key_name} = ?", (key,)
            ).fetchone()
            if row:
                if row != (payload, digest):
                    raise OutcomeIntegrityError(f"{table} identity conflict")
                return
            connection.execute(f"INSERT INTO {table} VALUES (?, ?, ?)", (key, payload, digest))

    def append_outcome(self, outcome: OutcomeRecord) -> None:
        if outcome.available_at < outcome.horizon_end:
            raise OutcomeIntegrityError("outcome is not mature at available_at")
        self._append("outcomes", "outcome_id", outcome.outcome_id, outcome)

    def append_postmortem(self, report: PostmortemReport) -> None:
        self._append("postmortems", "report_id", report.report_id, report)

    def outcomes(self) -> tuple[OutcomeRecord, ...]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT payload, record_hash FROM outcomes ORDER BY outcome_id"
            ).fetchall()
        result = []
        for payload, expected in rows:
            value = OutcomeRecord.model_validate_json(payload)
            if canonical_sha256(value) != expected:
                raise OutcomeIntegrityError("outcome ledger tampering detected")
            result.append(value)
        return tuple(result)


def build_postmortem(
    report_id: str,
    outcomes: list[OutcomeRecord],
    produced_at: datetime,
    candidate_ids: list[str] | None = None,
) -> PostmortemReport:
    if not outcomes or any(outcome.available_at > produced_at for outcome in outcomes):
        raise ValueError("postmortem requires matured point-in-time outcomes")
    attribution = {
        "mean_absolute_forecast_error": sum(abs(item.forecast_error) for item in outcomes)
        / len(outcomes),
        "total_realized_excess_return": sum(item.realized_excess_return for item in outcomes),
        "total_costs": sum(item.costs for item in outcomes),
    }
    diagnosis = (
        "Forecast error exceeded realized excess return."
        if attribution["mean_absolute_forecast_error"]
        > abs(attribution["total_realized_excess_return"]) / len(outcomes)
        else "Forecast error remained bounded relative to realized excess return."
    )
    outcome_ids = sorted(item.outcome_id for item in outcomes)
    sorted_candidate_ids = sorted(candidate_ids or [])
    values = {
        "report_id": report_id,
        "outcome_ids": outcome_ids,
        "diagnosis": diagnosis,
        "attribution": attribution,
        "candidate_ids": sorted_candidate_ids,
        "produced_at": produced_at,
    }
    return PostmortemReport(
        report_id=report_id,
        outcome_ids=outcome_ids,
        diagnosis=diagnosis,
        attribution=attribution,
        candidate_ids=sorted_candidate_ids,
        produced_at=produced_at,
        content_hash=canonical_sha256(values),
    )
