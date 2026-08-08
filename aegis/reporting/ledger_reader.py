"""Strict read-only cycle-ledger access for dashboards and reports."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from aegis.fund.ledger import CycleRecord, LedgerIntegrityError


class ReadOnlyRunLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with tempfile.TemporaryDirectory(prefix="aegis-ledger-snapshot-") as directory:
            snapshot = Path(directory) / "ledger.sqlite"
            shutil.copy2(self.path, snapshot)
            for suffix in ("-wal", "-shm"):
                source = Path(f"{self.path}{suffix}")
                if source.exists():
                    shutil.copy2(source, Path(f"{snapshot}{suffix}"))
            connection = sqlite3.connect(snapshot)
            connection.execute("PRAGMA query_only = ON")
            try:
                yield connection
            finally:
                connection.close()

    @staticmethod
    def _validate(run_id: str, expected: str, payload: str) -> CycleRecord:
        try:
            record = CycleRecord.model_validate_json(payload)
        except Exception as exc:
            raise LedgerIntegrityError(f"invalid cycle JSON for {run_id}") from exc
        if record.run_id != run_id or record.digest() != expected:
            raise LedgerIntegrityError(f"cycle hash mismatch: {run_id}")
        return record

    def get(self, run_id: str) -> CycleRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_hash, record_json FROM cycles WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._validate(run_id, str(row[0]), str(row[1]))

    def list_records(self) -> tuple[CycleRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id, record_hash, record_json FROM cycles ORDER BY rowid DESC"
            ).fetchall()
        return tuple(
            self._validate(str(run_id), str(record_hash), str(record_json))
            for run_id, record_hash, record_json in rows
        )
