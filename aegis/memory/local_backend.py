"""Authoritative append-only SQLite memory with deterministic PIT retrieval."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from aegis.contracts import (
    MemoryCandidate,
    MemoryGovernanceDecision,
    MemoryHit,
    MemoryItem,
    MemoryQuery,
    MemorySnapshot,
    MemorySnapshotEntry,
    canonical_json,
    canonical_sha256,
)


class MemoryGovernanceError(RuntimeError):
    pass


_TOKEN = re.compile(r"[A-Za-z0-9_.-]+")


class LocalMemoryBackend:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    candidate_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_decisions (
                    decision_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    decision_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_items (
                    memory_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    item_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    PRIMARY KEY(memory_id, version)
                );
                """
            )

    def stage(self, candidate: MemoryCandidate) -> None:
        payload = canonical_json(candidate)
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                "SELECT candidate_json FROM memory_candidates WHERE candidate_id = ?",
                (candidate.candidate_id,),
            ).fetchone()
            if existing:
                if existing[0] != payload:
                    raise MemoryGovernanceError("candidate ID already has different content")
                return
            connection.execute(
                "INSERT INTO memory_candidates VALUES (?, ?, ?)",
                (candidate.candidate_id, payload, candidate.content_hash),
            )

    def _candidate(self, candidate_id: str) -> MemoryCandidate:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT candidate_json, content_hash FROM memory_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if not row:
            raise MemoryGovernanceError("unknown memory candidate")
        candidate = MemoryCandidate.model_validate_json(row[0])
        if candidate.content_hash != row[1]:
            raise MemoryGovernanceError("memory candidate hash mismatch")
        return candidate

    def decide(self, decision: MemoryGovernanceDecision) -> MemoryItem | None:
        candidate = self._candidate(decision.candidate_id)
        if candidate.content_hash != decision.candidate_hash:
            raise MemoryGovernanceError("decision is not bound to the candidate hash")
        if candidate.proposer_id == decision.evaluator_id:
            raise MemoryGovernanceError("memory proposer cannot approve its own candidate")
        if decision.decided_at < candidate.created_at:
            raise MemoryGovernanceError("decision cannot predate the candidate")
        if candidate.expires_at is not None and decision.decided_at >= candidate.expires_at:
            raise MemoryGovernanceError("expired memory candidate cannot be approved")
        with sqlite3.connect(self.path) as connection:
            if connection.execute(
                "SELECT 1 FROM memory_decisions WHERE candidate_id = ?",
                (candidate.candidate_id,),
            ).fetchone():
                raise MemoryGovernanceError("memory candidate already has a decision")
            item: MemoryItem | None = None
            if decision.decision in {"approve", "quarantine"}:
                previous = connection.execute(
                    "SELECT MAX(version) FROM memory_items WHERE memory_id = ?",
                    (candidate.memory_id,),
                ).fetchone()[0]
                version = int(previous or 0) + 1
                item = MemoryItem(
                    memory_id=candidate.memory_id,
                    memory_type=candidate.memory_type,
                    title=candidate.title,
                    statement=candidate.statement,
                    evidence_ids=candidate.evidence_ids,
                    source_case_ids=candidate.source_case_ids,
                    entity_ids=candidate.entity_ids,
                    strategy_ids=candidate.strategy_ids,
                    regime_ids=candidate.regime_ids,
                    scope=candidate.scope,
                    confidence=candidate.confidence,
                    utility_score=candidate.utility_score,
                    available_at=decision.decided_at,
                    expires_at=candidate.expires_at,
                    supersedes=candidate.supersedes,
                    contradicted_by=candidate.contradicted_by,
                    status="approved" if decision.decision == "approve" else "quarantined",
                    version=version,
                )
                item_json = canonical_json(item)
                connection.execute(
                    "INSERT INTO memory_items VALUES (?, ?, ?, ?)",
                    (item.memory_id, item.version, item_json, canonical_sha256(item)),
                )
            connection.execute(
                "INSERT INTO memory_decisions VALUES (?, ?, ?, ?)",
                (
                    decision.decision_id,
                    decision.candidate_id,
                    canonical_json(decision),
                    decision.content_hash,
                ),
            )
            return item

    def _items(self) -> list[MemoryItem]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT item_json, record_hash FROM memory_items ORDER BY memory_id, version"
            ).fetchall()
        items: list[MemoryItem] = []
        for item_json, record_hash in rows:
            item = MemoryItem.model_validate_json(item_json)
            if canonical_sha256(item) != record_hash:
                raise MemoryGovernanceError("memory item integrity failure")
            items.append(item)
        return items

    @staticmethod
    def _eligible(item: MemoryItem, query: MemoryQuery) -> bool:
        if item.status != "approved" or item.available_at > query.as_of:
            return False
        if item.expires_at is not None and item.expires_at <= query.as_of:
            return False
        if query.memory_types and item.memory_type not in query.memory_types:
            return False
        if query.entity_ids and not set(query.entity_ids).intersection(item.entity_ids):
            return False
        if query.strategy_ids and not set(query.strategy_ids).intersection(item.strategy_ids):
            return False
        return not (query.regime_ids and not set(query.regime_ids).intersection(item.regime_ids))

    def search(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        terms = {token.lower() for token in _TOKEN.findall(query.text)}
        hits: list[MemoryHit] = []
        for item in self._items():
            if not self._eligible(item, query):
                continue
            item_terms = {
                token.lower() for token in _TOKEN.findall(f"{item.title} {item.statement}")
            }
            lexical = len(terms.intersection(item_terms)) / max(len(terms), 1)
            entity_bonus = 0.25 if set(query.entity_ids).intersection(item.entity_ids) else 0.0
            score = lexical + entity_bonus + item.utility_score * 0.1
            reasons = ["point-in-time eligible", "approved memory"]
            if item.contradicted_by:
                reasons.append(f"contradicted by: {','.join(sorted(item.contradicted_by))}")
            hits.append(MemoryHit(item=item, score=score, reasons=reasons))
        hits.sort(key=lambda hit: (-hit.score, hit.item.memory_id, -hit.item.version))
        return tuple(hits[: query.top_k])

    def snapshot(self, as_of: datetime) -> MemorySnapshot:
        entries = [
            MemorySnapshotEntry(
                memory_id=item.memory_id,
                version=item.version,
                available_at=item.available_at,
            )
            for item in self._items()
            if item.status == "approved"
            and item.available_at <= as_of
            and (item.expires_at is None or item.expires_at > as_of)
        ]
        entries.sort(key=lambda entry: (entry.memory_id, entry.version))
        payload = {"as_of": as_of, "entries": entries}
        return MemorySnapshot(
            as_of=as_of,
            entries=entries,
            content_hash=canonical_sha256(payload),
        )
