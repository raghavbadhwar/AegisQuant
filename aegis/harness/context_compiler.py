"""Bounded typed context packs; unrestricted session transcripts never enter nodes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from aegis.contracts import EvidenceBundle, ResearchCase, canonical_sha256
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
) -> ContextPack:
    payload = {
        "case": case,
        "task": task,
        "snapshot": snapshot,
        "evidence": evidence,
        "allowed_tools": allowed_tools,
        "budget": budget,
        "warnings": warnings,
    }
    return ContextPack(
        case=case,
        task=task,
        snapshot=snapshot,
        evidence=evidence,
        allowed_tools=allowed_tools,
        budget=budget,
        warnings=warnings,
        input_hash=canonical_sha256(payload),
    )
