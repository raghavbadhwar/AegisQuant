from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aegis.contracts import MemoryQuery, TypedRelation
from aegis.memory import (
    LocalMemoryBackend,
    MemoryGovernanceError,
    build_memory_candidate,
    build_memory_decision,
)
from aegis.memory.dream import propose_duplicate_consolidations
from aegis.memory.gbrain_adapter import GBrainMemoryAdapter
from aegis.memory.relations import RelationStore

BASE = datetime(2024, 2, 20, 12, 0, tzinfo=UTC)


def candidate(**updates):  # type: ignore[no-untyped-def]
    payload = {
        "candidate_id": "candidate-1",
        "memory_id": "memory-nvda-demand",
        "proposer_id": "postmortem-agent",
        "memory_type": "thesis-pattern",
        "title": "NVDA demand surprise",
        "statement": "NVDA demand surprises can persist after earnings.",
        "evidence_ids": ["demo-nvda-20240223-price"],
        "source_case_ids": ["prior-case"],
        "entity_ids": ["NVDA"],
        "strategy_ids": [],
        "regime_ids": [],
        "scope": "entity",
        "confidence": 0.75,
        "utility_score": 0.7,
        "created_at": BASE,
        "expires_at": BASE + timedelta(days=365),
        "review_by": BASE + timedelta(days=7),
        "supersedes": [],
        "contradicted_by": ["memory-nvda-reversal"],
    }
    payload.update(updates)
    return build_memory_candidate(**payload)


def decision(item, **updates):  # type: ignore[no-untyped-def]
    payload = {
        "decision_id": f"decision-{item.candidate_id}",
        "candidate_id": item.candidate_id,
        "candidate_hash": item.content_hash,
        "evaluator_id": "human-reviewer",
        "decision": "approve",
        "reason": "Evidence-linked and bounded.",
        "decided_at": BASE + timedelta(days=1),
    }
    payload.update(updates)
    return build_memory_decision(**payload)


def test_stage_approve_retrieve_and_snapshot_are_point_in_time(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "memory.sqlite")
    staged = candidate()
    backend.stage(staged)
    approved = backend.decide(decision(staged))
    assert approved is not None
    assert approved.available_at == BASE + timedelta(days=1)
    before = backend.search(
        MemoryQuery(text="NVDA demand", as_of=BASE, entity_ids=["NVDA"], top_k=5)
    )
    assert before == ()
    after = backend.search(
        MemoryQuery(
            text="NVDA demand earnings",
            as_of=BASE + timedelta(days=2),
            entity_ids=["NVDA"],
            top_k=5,
        )
    )
    assert [hit.item.memory_id for hit in after] == [staged.memory_id]
    assert any("contradicted by" in reason for reason in after[0].reasons)
    first = backend.snapshot(BASE + timedelta(days=2))
    second = backend.snapshot(BASE + timedelta(days=2))
    assert first == second
    assert first.entries[0].available_at == approved.available_at


def test_governance_separation_quarantine_and_expiry(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "memory.sqlite")
    own = candidate(candidate_id="own")
    backend.stage(own)
    with pytest.raises(MemoryGovernanceError, match="cannot approve"):
        backend.decide(decision(own, evaluator_id=own.proposer_id))
    quarantined = candidate(candidate_id="quarantine", memory_id="memory-quarantine")
    backend.stage(quarantined)
    item = backend.decide(
        decision(
            quarantined,
            decision_id="decision-quarantine",
            decision="quarantine",
        )
    )
    assert item is not None and item.status == "quarantined"
    assert backend.search(MemoryQuery(text="NVDA", as_of=BASE + timedelta(days=2), top_k=5)) == ()


class BrokenGBrain:
    def project(self, item):  # type: ignore[no-untyped-def]
        raise RuntimeError("offline")

    def search_ids(self, query, top_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("offline")


class FutureIdGBrain(BrokenGBrain):
    def search_ids(self, query, top_k):  # type: ignore[no-untyped-def]
        return ["future-memory", "memory-nvda-demand"]


def test_gbrain_outage_and_future_ids_cannot_bypass_local_filters(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "memory.sqlite")
    staged = candidate()
    backend.stage(staged)
    backend.decide(decision(staged))
    query = MemoryQuery(
        text="NVDA demand",
        as_of=BASE + timedelta(days=2),
        entity_ids=["NVDA"],
        top_k=5,
    )
    local = backend.search(query)
    assert GBrainMemoryAdapter(backend, BrokenGBrain()).search(query) == local
    assert GBrainMemoryAdapter(backend, FutureIdGBrain()).search(query) == local


def test_relation_store_and_dream_cycle_remain_pit_candidate_only(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "memory.sqlite")
    first_candidate = candidate()
    backend.stage(first_candidate)
    first = backend.decide(decision(first_candidate))
    assert first is not None
    second_candidate = candidate(
        candidate_id="candidate-2",
        memory_id="memory-nvda-demand-duplicate",
    )
    backend.stage(second_candidate)
    second = backend.decide(decision(second_candidate, decision_id="decision-candidate-2"))
    assert second is not None
    proposals = propose_duplicate_consolidations([first, second], BASE + timedelta(days=2))
    assert len(proposals) == 1
    assert proposals[0].proposer_id == "deterministic-dream-cycle-v1"
    relation_store = RelationStore(tmp_path / "relations.sqlite")
    relation = TypedRelation(
        relation_id="nvda-supplies-dc",
        source_id="NVDA",
        relation_type="supplies",
        target_id="DATA_CENTRE",
        evidence_ids=["evidence"],
        available_at=BASE + timedelta(days=2),
        confidence=0.8,
        status="approved",
    )
    relation_store.append(relation)
    assert relation_store.search("NVDA", BASE + timedelta(days=1)) == ()
    assert relation_store.search("NVDA", BASE + timedelta(days=3)) == (relation,)
