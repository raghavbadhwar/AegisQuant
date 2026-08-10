import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from aegis.causal import (
    CausalEdge,
    CausalEdgeKind,
    CausalGraphIntegrityError,
    CausalGraphSnapshot,
    CausalGraphStore,
    CausalSupportLevel,
    EdgeStatus,
)
from aegis.contracts import canonical_json

NOW = datetime(2024, 1, 1, tzinfo=UTC)
DOMAIN = "ai-infrastructure-v1"


def edge(**updates: object) -> CausalEdge:
    values: dict[str, object] = {
        "edge_id": "ai-capex-to-revenue",
        "source_variable_id": "ai-capex",
        "target_variable_id": "supplier-revenue",
        "kind": CausalEdgeKind.HYPOTHESIZED_CAUSE,
        "status": EdgeStatus.DRAFT,
        "support_level": CausalSupportLevel.C0_NARRATIVE,
        "mechanism_description": "Candidate demand transmission mechanism.",
        "sign": 1,
        "evidence_ids": ("filing-1",),
        "assumption_ids": ("capacity-available",),
        "domain_pack": DOMAIN,
        "known_from": NOW,
        "confidence": 0.2,
        "version": 1,
    }
    values.update(updates)
    return CausalEdge(**values)


def graph(**updates: object) -> CausalGraphSnapshot:
    values: dict[str, object] = {
        "snapshot_id": "causal-graph-1",
        "graph_version": 1,
        "as_of": NOW,
        "domain_pack": DOMAIN,
        "edges": (edge(),),
        "evidence_ids": ("filing-1",),
    }
    values.update(updates)
    return CausalGraphSnapshot(**values)


def test_graph_store_round_trips_exact_version_history_deterministically(tmp_path) -> None:
    store = CausalGraphStore(tmp_path / "causal.sqlite")
    initial = graph().sealed()
    assert initial.content_hash is not None
    successor = graph(
        snapshot_id="causal-graph-2",
        graph_version=2,
        as_of=NOW + timedelta(days=1),
        parent_snapshot_hash=initial.content_hash,
        edges=(edge(status=EdgeStatus.SUPPORTED, confidence=0.4, version=2),),
    ).sealed()

    assert store.append(initial) == initial
    assert store.append(initial) == initial
    assert store.append(successor) == successor
    assert store.get(DOMAIN, 1) == initial
    assert store.latest(DOMAIN) == successor
    assert CausalGraphStore(store.path).history(DOMAIN) == (initial, successor)


def test_graph_store_rejects_unsealed_and_forked_snapshots(tmp_path) -> None:
    store = CausalGraphStore(tmp_path / "causal.sqlite")
    with pytest.raises(CausalGraphIntegrityError, match="sealed"):
        store.append(graph())

    initial = store.append(graph().sealed())
    assert initial.content_hash is not None
    fork = graph(
        snapshot_id="causal-graph-fork",
        graph_version=2,
        as_of=NOW + timedelta(days=1),
        parent_snapshot_hash="f" * 64,
        edges=(edge(version=2),),
    ).sealed()
    with pytest.raises(CausalGraphIntegrityError, match="parent"):
        store.append(fork)


def test_graph_store_requires_root_edges_to_begin_at_version_one(tmp_path) -> None:
    store = CausalGraphStore(tmp_path / "causal.sqlite")

    with pytest.raises(CausalGraphIntegrityError, match="edge version"):
        store.append(graph(edges=(edge(version=2),)).sealed())


def test_graph_store_requires_edge_version_bump_when_content_changes(tmp_path) -> None:
    store = CausalGraphStore(tmp_path / "causal.sqlite")
    initial = store.append(graph().sealed())
    assert initial.content_hash is not None
    stale_edge_version = graph(
        snapshot_id="causal-graph-2",
        graph_version=2,
        as_of=NOW + timedelta(days=1),
        parent_snapshot_hash=initial.content_hash,
        edges=(edge(status=EdgeStatus.SUPPORTED),),
    ).sealed()

    with pytest.raises(CausalGraphIntegrityError, match="edge version"):
        store.append(stale_edge_version)


def test_graph_store_rejects_a_successor_that_erases_a_prior_edge(tmp_path) -> None:
    store = CausalGraphStore(tmp_path / "causal.sqlite")
    initial = store.append(graph().sealed())
    assert initial.content_hash is not None
    erased = graph(
        snapshot_id="causal-graph-2",
        graph_version=2,
        as_of=NOW + timedelta(days=1),
        parent_snapshot_hash=initial.content_hash,
        edges=(),
    ).sealed()

    with pytest.raises(CausalGraphIntegrityError, match="removes a prior edge"):
        store.append(erased)


def test_graph_store_history_rejects_a_manually_persisted_pit_reversal(tmp_path) -> None:
    store = CausalGraphStore(tmp_path / "causal.sqlite")
    initial = store.append(graph().sealed())
    assert initial.content_hash is not None
    reversed_time = graph(
        snapshot_id="causal-graph-2",
        graph_version=2,
        as_of=NOW - timedelta(days=1),
        parent_snapshot_hash=initial.content_hash,
        edges=(edge(version=1),),
    ).sealed()
    assert reversed_time.content_hash is not None

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO causal_graphs VALUES (?, ?, ?, ?, ?, ?)",
            (
                reversed_time.domain_pack,
                reversed_time.graph_version,
                reversed_time.snapshot_id,
                reversed_time.parent_snapshot_hash,
                reversed_time.content_hash,
                canonical_json(reversed_time),
            ),
        )

    with pytest.raises(CausalGraphIntegrityError, match="travel backward"):
        store.history(DOMAIN)

    with pytest.raises(CausalGraphIntegrityError, match="travel backward"):
        store.get(DOMAIN, 2)
