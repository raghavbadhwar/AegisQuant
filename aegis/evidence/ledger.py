"""Append-only SQLite evidence, claim-graph, and audit ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from aegis.contracts import (
    ClaimGraphSnapshot,
    EvidenceAuditResult,
    EvidenceBundle,
    canonical_json,
    canonical_sha256,
)


class EvidenceLedgerError(RuntimeError):
    pass


class EvidenceLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS evidence_cases (
                    case_id TEXT PRIMARY KEY,
                    bundle_json TEXT NOT NULL,
                    graph_json TEXT NOT NULL,
                    audit_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL
                )"""
            )

    def append(
        self,
        bundle: EvidenceBundle,
        graph: ClaimGraphSnapshot,
        audit: EvidenceAuditResult,
    ) -> str:
        if bundle.case_id != graph.case_id or bundle.case_id != audit.case_id:
            raise EvidenceLedgerError("evidence case IDs do not match")
        payload = {"bundle": bundle, "graph": graph, "audit": audit}
        digest = canonical_sha256(payload)
        row = (
            canonical_json(bundle),
            canonical_json(graph),
            canonical_json(audit),
            digest,
        )
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                "SELECT bundle_json, graph_json, audit_json, record_hash "
                "FROM evidence_cases WHERE case_id = ?",
                (bundle.case_id,),
            ).fetchone()
            if existing:
                if existing != row:
                    raise EvidenceLedgerError("evidence case already has different content")
                return digest
            connection.execute(
                "INSERT INTO evidence_cases VALUES (?, ?, ?, ?, ?)",
                (bundle.case_id, *row),
            )
        return digest

    def get(self, case_id: str) -> tuple[EvidenceBundle, ClaimGraphSnapshot, EvidenceAuditResult]:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT bundle_json, graph_json, audit_json, record_hash "
                "FROM evidence_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        if not row:
            raise KeyError(case_id)
        bundle = EvidenceBundle.model_validate_json(row[0])
        graph = ClaimGraphSnapshot.model_validate_json(row[1])
        audit = EvidenceAuditResult.model_validate_json(row[2])
        if canonical_sha256({"bundle": bundle, "graph": graph, "audit": audit}) != row[3]:
            raise EvidenceLedgerError("evidence ledger integrity failure")
        return bundle, graph, audit
