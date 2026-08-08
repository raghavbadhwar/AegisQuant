"""Append-only tamper-detecting experiment ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from aegis.contracts import ExperimentRecord, canonical_json, canonical_sha256


class ExperimentIntegrityError(RuntimeError):
    pass


class ExperimentLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL
                )"""
            )

    def append(self, record: ExperimentRecord) -> None:
        payload = canonical_json(record)
        record_hash = canonical_sha256(record)
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT record_json, record_hash FROM experiments WHERE experiment_id = ?",
                (record.experiment_id,),
            ).fetchone()
            if row:
                if row != (payload, record_hash):
                    raise ExperimentIntegrityError("experiment ID already has different content")
                return
            connection.execute(
                "INSERT INTO experiments VALUES (?, ?, ?)",
                (record.experiment_id, payload, record_hash),
            )

    def get(self, experiment_id: str) -> ExperimentRecord:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT record_json, record_hash FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if not row:
            raise KeyError(experiment_id)
        record = ExperimentRecord.model_validate_json(row[0])
        if canonical_sha256(record) != row[1]:
            raise ExperimentIntegrityError("experiment ledger integrity failure")
        return record
