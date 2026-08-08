"""Canonical candidate and decision builders."""

from __future__ import annotations

from typing import Any

from aegis.contracts import MemoryCandidate, MemoryGovernanceDecision, canonical_sha256


def build_memory_candidate(**values: Any) -> MemoryCandidate:
    payload = dict(values)
    draft = MemoryCandidate.model_construct(**payload, content_hash="0" * 64)
    return MemoryCandidate(**payload, content_hash=canonical_sha256(draft.hash_payload()))


def build_memory_decision(**values: Any) -> MemoryGovernanceDecision:
    payload = dict(values)
    draft = MemoryGovernanceDecision.model_construct(**payload, content_hash="0" * 64)
    return MemoryGovernanceDecision(**payload, content_hash=canonical_sha256(draft.hash_payload()))
