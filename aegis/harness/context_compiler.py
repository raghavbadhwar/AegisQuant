"""Bounded typed context packs; unrestricted session transcripts never enter nodes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from aegis.contracts import EvidenceBundle, MemoryHit, ResearchCase, canonical_sha256
from aegis.data import MarketSnapshot
from aegis.harness.budgets import Budget


class ContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case: ResearchCase
    task: str
    snapshot: MarketSnapshot
    evidence: EvidenceBundle
    allowed_tools: tuple[str, ...]
    budget: Budget
    memory_hits: tuple[MemoryHit, ...] = ()
    memory_snapshot_hash: str = canonical_sha256([])
    warnings: tuple[str, ...] = ()
    input_hash: str


def compile_context(
    case: ResearchCase,
    task: str,
    snapshot: MarketSnapshot,
    evidence: EvidenceBundle,
    allowed_tools: tuple[str, ...],
    budget: Budget,
    warnings: tuple[str, ...] = (),
    memory_hits: tuple[MemoryHit, ...] = (),
    memory_snapshot_hash: str = canonical_sha256([]),
) -> ContextPack:
    payload = {
        "case": case,
        "task": task,
        "snapshot": snapshot,
        "evidence": evidence,
        "allowed_tools": allowed_tools,
        "budget": budget,
        "memory_hits": memory_hits,
        "memory_snapshot_hash": memory_snapshot_hash,
        "warnings": warnings,
    }
    return ContextPack(
        case=case,
        task=task,
        snapshot=snapshot,
        evidence=evidence,
        allowed_tools=allowed_tools,
        budget=budget,
        memory_hits=memory_hits,
        memory_snapshot_hash=memory_snapshot_hash,
        warnings=warnings,
        input_hash=canonical_sha256(payload),
    )
