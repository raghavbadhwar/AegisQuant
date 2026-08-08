"""Canonical cycle receipts and append-only SQLite run ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aegis.contracts import (
    AlphaForecast,
    EvidenceBundle,
    Fill,
    Order,
    PortfolioProposal,
    Position,
    ResearchCase,
    canonical_json,
    canonical_sha256,
)
from aegis.data import MarketSnapshot
from aegis.fund.spec import FundSpec
from aegis.observability import ReproducibilityManifest
from aegis.risk import RiskEvaluation


class LedgerIntegrityError(RuntimeError):
    """A persisted cycle conflicts with or fails its content hash."""


class CycleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "aegis-cycle-v1"
    run_id: str
    case: ResearchCase
    fund: FundSpec
    reproducibility: ReproducibilityManifest
    snapshot: MarketSnapshot
    evidence: EvidenceBundle
    forecasts: tuple[AlphaForecast, ...]
    portfolio: PortfolioProposal
    risk: RiskEvaluation
    marks: dict[str, float]
    equity_before: float
    cash_before: float
    orders: tuple[Order, ...]
    fills: tuple[Fill, ...]
    positions: tuple[Position, ...]
    cash_after: float
    nav_after: float

    def canonical(self) -> str:
        return canonical_json(self)

    def digest(self) -> str:
        return canonical_sha256(self)


class SQLiteRunLedger:
    """Small append-only cycle ledger with idempotent run IDs and hash verification."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cycles (
                    run_id TEXT PRIMARY KEY,
                    record_hash TEXT NOT NULL UNIQUE,
                    record_json TEXT NOT NULL,
                    inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def append(self, record: CycleRecord) -> str:
        payload = record.canonical()
        digest = record.digest()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT record_hash, record_json FROM cycles WHERE run_id = ?",
                (record.run_id,),
            ).fetchone()
            if existing is not None:
                if existing != (digest, payload):
                    raise LedgerIntegrityError(f"run ID conflict: {record.run_id}")
                return digest
            connection.execute(
                "INSERT INTO cycles (run_id, record_hash, record_json) VALUES (?, ?, ?)",
                (record.run_id, digest, payload),
            )
        return digest

    def get(self, run_id: str) -> CycleRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_hash, record_json FROM cycles WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        expected, payload = row
        try:
            record = CycleRecord.model_validate_json(payload)
        except Exception as exc:
            raise LedgerIntegrityError(f"invalid cycle JSON for {run_id}") from exc
        if record.digest() != expected:
            raise LedgerIntegrityError(f"cycle hash mismatch: {run_id}")
        return record

    def list_run_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT run_id FROM cycles ORDER BY rowid").fetchall()
        return [str(row[0]) for row in rows]
