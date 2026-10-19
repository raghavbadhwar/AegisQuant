"""Append-only typed relation store with point-in-time retrieval."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from aegis.contracts import TypedRelation, canonical_json, canonical_sha256


class RelationIntegrityError(RuntimeError):
    pass


class RelationStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS relations (
                    relation_id TEXT PRIMARY KEY,
                    relation_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL
                )"""
            )

    def append(self, relation: TypedRelation) -> None:
        payload = canonical_json(relation)
        digest = canonical_sha256(relation)
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT relation_json, record_hash FROM relations WHERE relation_id = ?",
                (relation.relation_id,),
            ).fetchone()
            if row:
                if row != (payload, digest):
                    raise RelationIntegrityError("relation ID conflict")
                return
            connection.execute(
                "INSERT INTO relations VALUES (?, ?, ?)",
                (relation.relation_id, payload, digest),
            )

    def search(self, entity_id: str, as_of: datetime) -> tuple[TypedRelation, ...]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT relation_json, record_hash FROM relations ORDER BY relation_id"
            ).fetchall()
        results = []
        for payload, expected in rows:
            relation = TypedRelation.model_validate_json(payload)
            if canonical_sha256(relation) != expected:
                raise RelationIntegrityError("relation integrity failure")
            if (
                relation.status == "approved"
                and relation.available_at <= as_of
                and entity_id in {relation.source_id, relation.target_id}
            ):
                results.append(relation)
        return tuple(results)
