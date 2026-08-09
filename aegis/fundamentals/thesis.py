"""Immutable, tamper-evident living investment-thesis ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from aegis.contracts import InvestmentThesis, canonical_json, canonical_sha256

from .hashing import build_hashed


class ThesisLedgerError(RuntimeError):
    pass


_ALLOWED_STATUS_TRANSITIONS = {
    "draft": {"draft", "active", "archived"},
    "active": {"active", "strengthened", "weakened", "invalidated", "resolved", "archived"},
    "strengthened": {"active", "strengthened", "weakened", "invalidated", "resolved", "archived"},
    "weakened": {"active", "strengthened", "weakened", "invalidated", "resolved", "archived"},
    "invalidated": {"archived"},
    "resolved": {"archived"},
    "archived": set(),
}


class ThesisLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS thesis_versions (
                    thesis_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    as_of TEXT NOT NULL,
                    thesis_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    UNIQUE(ticker, version)
                )"""
            )

    def append(self, thesis: InvestmentThesis) -> None:
        payload = canonical_json(thesis)
        digest = canonical_sha256(thesis)
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                "SELECT thesis_json, record_hash FROM thesis_versions WHERE thesis_id = ?",
                (thesis.thesis_id,),
            ).fetchone()
            if existing:
                if existing != (payload, digest):
                    raise ThesisLedgerError("thesis identity conflict")
                return
            latest_row = connection.execute(
                "SELECT thesis_json FROM thesis_versions WHERE ticker = ? "
                "ORDER BY version DESC LIMIT 1",
                (thesis.ticker,),
            ).fetchone()
            if latest_row is None:
                if thesis.version != 1 or thesis.supersedes_thesis_id is not None:
                    raise ThesisLedgerError("first thesis must be version one")
            else:
                latest = InvestmentThesis.model_validate_json(latest_row[0])
                if thesis.version != latest.version + 1:
                    raise ThesisLedgerError("thesis version must increment exactly once")
                if thesis.supersedes_thesis_id != latest.thesis_id:
                    raise ThesisLedgerError("thesis must supersede the latest version")
                if thesis.as_of <= latest.as_of:
                    raise ThesisLedgerError("thesis update must advance point-in-time")
                if thesis.status not in _ALLOWED_STATUS_TRANSITIONS[latest.status]:
                    raise ThesisLedgerError("illegal thesis status transition")
            connection.execute(
                "INSERT INTO thesis_versions VALUES (?, ?, ?, ?, ?, ?)",
                (
                    thesis.thesis_id,
                    thesis.ticker,
                    thesis.version,
                    thesis.as_of.isoformat(),
                    payload,
                    digest,
                ),
            )

    def history(self, ticker: str, as_of=None) -> tuple[InvestmentThesis, ...]:  # type: ignore[no-untyped-def]
        query = "SELECT thesis_json, record_hash FROM thesis_versions WHERE ticker = ?"
        params: list[object] = [ticker]
        if as_of is not None:
            query += " AND as_of <= ?"
            params.append(as_of.isoformat())
        query += " ORDER BY version"
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(query, params).fetchall()
        values = []
        for payload, expected in rows:
            thesis = InvestmentThesis.model_validate_json(payload)
            if canonical_sha256(thesis) != expected:
                raise ThesisLedgerError("thesis ledger tampering detected")
            values.append(thesis)
        return tuple(values)

    def latest(self, ticker: str, as_of=None) -> InvestmentThesis | None:  # type: ignore[no-untyped-def]
        history = self.history(ticker, as_of)
        return history[-1] if history else None


def build_thesis(**values: Any) -> InvestmentThesis:
    values.setdefault("contract_version", "3.0.0")
    return build_hashed(InvestmentThesis, **values)
