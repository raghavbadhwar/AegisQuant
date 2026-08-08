"""Typed LangGraph research-desk state and deterministic parallel reducers."""

from __future__ import annotations

from typing import Annotated, TypedDict

from aegis.contracts import (
    AlphaForecast,
    ClaimGraphSnapshot,
    EvidenceAuditResult,
    EvidenceBundle,
    MemoryHit,
    ResearchArtifact,
    ResearchCase,
)
from aegis.data import MarketSnapshot
from aegis.observability import GraphEvent


def merge_artifacts(
    left: dict[str, ResearchArtifact], right: dict[str, ResearchArtifact]
) -> dict[str, ResearchArtifact]:
    merged = {**left, **right}
    return {key: merged[key] for key in sorted(merged)}


def merge_events(
    left: dict[str, GraphEvent], right: dict[str, GraphEvent]
) -> dict[str, GraphEvent]:
    merged = {**left, **right}
    return {key: merged[key] for key in sorted(merged)}


def merge_roles(left: frozenset[str], right: frozenset[str]) -> frozenset[str]:
    return left | right


class DeskState(TypedDict, total=False):
    case: ResearchCase
    snapshot: MarketSnapshot
    evidence: EvidenceBundle
    artifacts: Annotated[dict[str, ResearchArtifact], merge_artifacts]
    events: Annotated[dict[str, GraphEvent], merge_events]
    failed_roles: Annotated[frozenset[str], merge_roles]
    approved_evidence_ids: tuple[str, ...]
    claim_graph: ClaimGraphSnapshot
    deterministic_audit: EvidenceAuditResult
    memory_hits: tuple[MemoryHit, ...]
    memory_snapshot_hash: str
    forecasts: tuple[AlphaForecast, ...]
    status: str
