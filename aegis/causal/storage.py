"""Deterministic local storage for sealed, candidate-only causal graph versions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from aegis.contracts import canonical_json

from .contracts import CausalEdge, CausalGraphSnapshot


class CausalGraphIntegrityError(RuntimeError):
    pass


class CausalGraphStore:
    """Append one hash-linked graph history per domain to a local SQLite file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS causal_graphs (
                    domain_pack TEXT NOT NULL,
                    graph_version INTEGER NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    parent_snapshot_hash TEXT,
                    content_hash TEXT NOT NULL UNIQUE,
                    graph_json TEXT NOT NULL,
                    PRIMARY KEY (domain_pack, graph_version),
                    UNIQUE (domain_pack, snapshot_id)
                )"""
            )

    @staticmethod
    def _decode(row: tuple[object, ...]) -> CausalGraphSnapshot:
        domain_pack, graph_version, snapshot_id, parent_hash, content_hash, payload = row
        try:
            graph = CausalGraphSnapshot.model_validate_json(str(payload))
        except ValueError as exc:
            raise CausalGraphIntegrityError("stored causal graph is invalid") from exc
        metadata = (
            graph.domain_pack,
            graph.graph_version,
            graph.snapshot_id,
            graph.parent_snapshot_hash,
            graph.content_hash,
        )
        if metadata != (domain_pack, graph_version, snapshot_id, parent_hash, content_hash):
            raise CausalGraphIntegrityError("stored causal graph metadata mismatch")
        if canonical_json(graph) != payload:
            raise CausalGraphIntegrityError("stored causal graph is not canonical")
        return graph

    @staticmethod
    def _validate_edge_versions(
        predecessor: CausalGraphSnapshot, successor: CausalGraphSnapshot
    ) -> None:
        previous_edges = {edge.edge_id: edge for edge in predecessor.edges}
        successor_ids = {edge.edge_id for edge in successor.edges}
        if removed_ids := set(previous_edges).difference(successor_ids):
            raise CausalGraphIntegrityError(
                "causal graph successor removes a prior edge: " + ", ".join(sorted(removed_ids))
            )
        for edge in successor.edges:
            previous = previous_edges.get(edge.edge_id)
            if previous is None:
                if edge.version != 1:
                    raise CausalGraphIntegrityError("new causal edge version must begin at 1")
                continue
            changed = CausalGraphStore._edge_payload(previous) != CausalGraphStore._edge_payload(
                edge
            )
            expected = previous.version + int(changed)
            if edge.version != expected:
                raise CausalGraphIntegrityError("causal edge version does not match its content")

    @classmethod
    def _validate_successor(
        cls, predecessor: CausalGraphSnapshot, successor: CausalGraphSnapshot
    ) -> None:
        if successor.graph_version != predecessor.graph_version + 1:
            raise CausalGraphIntegrityError("causal graph version is not the next version")
        if successor.parent_snapshot_hash != predecessor.content_hash:
            raise CausalGraphIntegrityError("causal graph parent does not match latest")
        if successor.as_of < predecessor.as_of:
            raise CausalGraphIntegrityError("causal graph versions cannot travel backward")
        cls._validate_edge_versions(predecessor, successor)

    @staticmethod
    def _edge_payload(edge: CausalEdge) -> dict[str, object]:
        return edge.model_dump(mode="json", exclude={"version"})

    def append(self, snapshot: CausalGraphSnapshot) -> CausalGraphSnapshot:
        """Idempotently append one exact sealed successor; forks fail closed."""
        try:
            graph = CausalGraphSnapshot.model_validate(snapshot.model_dump(mode="json"))
        except ValueError as exc:
            raise CausalGraphIntegrityError("causal graph validation failed") from exc
        if graph.content_hash is None:
            raise CausalGraphIntegrityError("causal graph must be sealed before storage")
        payload = canonical_json(graph)
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """SELECT domain_pack, graph_version, snapshot_id, parent_snapshot_hash,
                          content_hash, graph_json
                   FROM causal_graphs WHERE content_hash = ?""",
                (graph.content_hash,),
            ).fetchone()
            if existing is not None:
                stored = self._decode(existing)
                if stored != graph:
                    raise CausalGraphIntegrityError("causal graph hash collision")
                return stored

            latest = connection.execute(
                """SELECT domain_pack, graph_version, snapshot_id, parent_snapshot_hash,
                          content_hash, graph_json
                   FROM causal_graphs WHERE domain_pack = ?
                   ORDER BY graph_version DESC LIMIT 1""",
                (graph.domain_pack,),
            ).fetchone()
            if latest is None:
                if graph.graph_version != 1 or graph.parent_snapshot_hash is not None:
                    raise CausalGraphIntegrityError("causal graph history must begin at version 1")
                if any(edge.version != 1 for edge in graph.edges):
                    raise CausalGraphIntegrityError("root causal edge version must begin at 1")
            else:
                predecessor = self._decode(latest)
                self._validate_successor(predecessor, graph)
            try:
                connection.execute(
                    "INSERT INTO causal_graphs VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        graph.domain_pack,
                        graph.graph_version,
                        graph.snapshot_id,
                        graph.parent_snapshot_hash,
                        graph.content_hash,
                        payload,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CausalGraphIntegrityError(
                    "causal graph version conflicts with stored history"
                ) from exc
        return graph

    def get(self, domain_pack: str, graph_version: int) -> CausalGraphSnapshot:
        for graph in self.history(domain_pack):
            if graph.graph_version == graph_version:
                return graph
        raise CausalGraphIntegrityError("causal graph version not found")

    def latest(self, domain_pack: str) -> CausalGraphSnapshot:
        history = self.history(domain_pack)
        if not history:
            raise CausalGraphIntegrityError("causal graph history not found")
        return history[-1]

    def history(self, domain_pack: str) -> tuple[CausalGraphSnapshot, ...]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """SELECT domain_pack, graph_version, snapshot_id, parent_snapshot_hash,
                          content_hash, graph_json
                   FROM causal_graphs WHERE domain_pack = ? ORDER BY graph_version""",
                (domain_pack,),
            ).fetchall()
        graphs = tuple(self._decode(row) for row in rows)
        for graph_version, graph in enumerate(graphs, start=1):
            expected_parent = None if graph_version == 1 else graphs[graph_version - 2].content_hash
            if (
                graph.graph_version != graph_version
                or graph.parent_snapshot_hash != expected_parent
            ):
                raise CausalGraphIntegrityError("stored causal graph history is not a single chain")
            if graph_version > 1:
                self._validate_successor(graphs[graph_version - 2], graph)
        return graphs
