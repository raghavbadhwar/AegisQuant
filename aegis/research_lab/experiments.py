"""Append-only, tamper-evident experiment ledger."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from aegis.contracts import ExperimentRecord, canonical_json, canonical_sha256

V6FixtureStatus = Literal["passed", "failed"]
_V6_FIXTURE_OUTCOMES: Mapping[str, V6FixtureStatus] = MappingProxyType(
    {
        "registered-fixture-1": "passed",
        "registered-fixture-failure-1": "failed",
    }
)


def deterministic_v6_fixture_outcome(
    run_payload: Mapping[str, Any],
) -> tuple[V6FixtureStatus, str]:
    """Compute the closed v6 fixture outcome from its canonical run inputs."""

    executor_id = run_payload.get("executor_id")
    plan = run_payload.get("plan")
    if not isinstance(executor_id, str) or executor_id not in _V6_FIXTURE_OUTCOMES:
        raise ValueError("registered fixture executor is unavailable")
    if not isinstance(plan, dict) or not isinstance(plan.get("content_hash"), str):
        raise ValueError("registered fixture requires a sealed plan")
    result_hash = canonical_sha256(
        {
            "executor_id": executor_id,
            "plan_hash": plan["content_hash"],
            "code_revision": run_payload.get("code_revision"),
            "tree_hash": run_payload.get("tree_hash"),
            "data_snapshot_hash": run_payload.get("data_snapshot_hash"),
            "seed": run_payload.get("seed"),
            "parameter_draw_hash": run_payload.get("parameter_draw_hash"),
            "trial_number": run_payload.get("trial_number"),
        }
    )
    return _V6_FIXTURE_OUTCOMES[executor_id], result_hash


class ExperimentIntegrityError(RuntimeError):
    pass


class ExperimentLedger:
    """SQLite experiment store with a verified, append-only hash chain.

    The ordinary record table is indexed for lookup; the commitment table is
    independently chained.  Missing/replaced records therefore fail verification
    even if an attacker can directly alter the ordinary SQLite rows.
    """

    _GENESIS = "0" * 64

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path).resolve()
        self.read_only = read_only
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            return sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)
        return sqlite3.connect(self.path)

    @staticmethod
    def _commitment_hash(
        sequence: int, experiment_id: str, record_hash: str, previous_hash: str
    ) -> str:
        return canonical_sha256(
            {
                "sequence": sequence,
                "experiment_id": experiment_id,
                "record_hash": record_hash,
                "previous_commitment_hash": previous_hash,
            }
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS experiment_commitments (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL UNIQUE,
                    record_hash TEXT NOT NULL UNIQUE,
                    previous_commitment_hash TEXT NOT NULL,
                    commitment_hash TEXT NOT NULL UNIQUE
                )"""
            )
            # Migrate a pre-chain development ledger deterministically once;
            # all subsequent records are chained at insertion time.
            rows = connection.execute(
                """SELECT experiment_id, record_hash FROM experiments
                   WHERE experiment_id NOT IN (SELECT experiment_id FROM experiment_commitments)
                   ORDER BY experiment_id"""
            ).fetchall()
            previous = connection.execute(
                "SELECT commitment_hash FROM experiment_commitments ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous[0] if previous else self._GENESIS
            for experiment_id, record_hash in rows:
                sequence = connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM experiment_commitments"
                ).fetchone()[0]
                commitment_hash = self._commitment_hash(
                    sequence, experiment_id, record_hash, previous_hash
                )
                connection.execute(
                    """INSERT INTO experiment_commitments
                       (sequence, experiment_id, record_hash,
                        previous_commitment_hash, commitment_hash)
                       VALUES (?, ?, ?, ?, ?)""",
                    (sequence, experiment_id, record_hash, previous_hash, commitment_hash),
                )
                previous_hash = commitment_hash
            connection.executescript(
                """CREATE TRIGGER IF NOT EXISTS experiments_no_update
                   BEFORE UPDATE ON experiments
                   BEGIN SELECT RAISE(ABORT, 'experiment ledger is append-only'); END;
                   CREATE TRIGGER IF NOT EXISTS experiments_no_delete
                   BEFORE DELETE ON experiments
                   BEGIN SELECT RAISE(ABORT, 'experiment ledger is append-only'); END;
                   CREATE TRIGGER IF NOT EXISTS commitments_no_update
                   BEFORE UPDATE ON experiment_commitments
                   BEGIN SELECT RAISE(ABORT, 'experiment ledger is append-only'); END;
                   CREATE TRIGGER IF NOT EXISTS commitments_no_delete
                   BEFORE DELETE ON experiment_commitments
                   BEGIN SELECT RAISE(ABORT, 'experiment ledger is append-only'); END;"""
            )

    def _verify_chain(self, connection: sqlite3.Connection) -> None:
        commitments = connection.execute(
            """SELECT sequence, experiment_id, record_hash,
                      previous_commitment_hash, commitment_hash
               FROM experiment_commitments ORDER BY sequence"""
        ).fetchall()
        previous_hash = self._GENESIS
        for expected_sequence, row in enumerate(commitments, start=1):
            sequence, experiment_id, record_hash, recorded_previous, commitment_hash = row
            if sequence != expected_sequence or recorded_previous != previous_hash:
                raise ExperimentIntegrityError("experiment commitment chain sequence mismatch")
            if commitment_hash != self._commitment_hash(
                sequence, experiment_id, record_hash, previous_hash
            ):
                raise ExperimentIntegrityError("experiment commitment hash mismatch")
            record = connection.execute(
                "SELECT record_hash FROM experiments WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            if record != (record_hash,):
                raise ExperimentIntegrityError("experiment record is missing or replaced")
            previous_hash = commitment_hash
        count = connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        if count != len(commitments):
            raise ExperimentIntegrityError("experiment records and commitments do not reconcile")

    def append(self, record: ExperimentRecord) -> None:
        if self.read_only:
            raise ExperimentIntegrityError("experiment ledger is read-only")
        run_payload = record.parameters.get("v6_run")
        if run_payload is not None:
            if not isinstance(run_payload, dict):
                raise ExperimentIntegrityError("v6 experiment run payload is malformed")
            try:
                expected = deterministic_v6_fixture_outcome(run_payload)
            except ValueError as exc:
                raise ExperimentIntegrityError(str(exc)) from exc
            if (run_payload.get("status"), run_payload.get("result_content_hash")) != expected:
                raise ExperimentIntegrityError(
                    "v6 experiment run does not match deterministic registered-fixture outcome"
                )
        payload = canonical_json(record)
        record_hash = canonical_sha256(record)
        with self._connect() as connection:
            self._verify_chain(connection)
            existing = connection.execute(
                "SELECT record_json, record_hash FROM experiments WHERE experiment_id = ?",
                (record.experiment_id,),
            ).fetchone()
            if existing is not None:
                if existing != (payload, record_hash):
                    raise ExperimentIntegrityError("experiment ID already has different content")
                return
            previous = connection.execute(
                "SELECT commitment_hash FROM experiment_commitments ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous[0] if previous else self._GENESIS
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM experiment_commitments"
            ).fetchone()[0]
            commitment_hash = self._commitment_hash(
                sequence, record.experiment_id, record_hash, previous_hash
            )
            connection.execute(
                "INSERT INTO experiments VALUES (?, ?, ?)",
                (record.experiment_id, payload, record_hash),
            )
            connection.execute(
                """INSERT INTO experiment_commitments
                   (sequence, experiment_id, record_hash, previous_commitment_hash, commitment_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (sequence, record.experiment_id, record_hash, previous_hash, commitment_hash),
            )

    def get(self, experiment_id: str) -> ExperimentRecord:
        with self._connect() as connection:
            self._verify_chain(connection)
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
