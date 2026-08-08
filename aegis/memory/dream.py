"""Deterministic maintenance cycle that emits candidates, never approvals."""

from __future__ import annotations

from datetime import datetime, timedelta

from aegis.contracts import MemoryCandidate, MemoryItem, canonical_sha256

from .governance import build_memory_candidate


def propose_duplicate_consolidations(
    items: list[MemoryItem], now: datetime
) -> tuple[MemoryCandidate, ...]:
    groups: dict[str, list[MemoryItem]] = {}
    for item in items:
        if (
            item.status != "approved"
            or item.available_at > now
            or (item.expires_at is not None and item.expires_at <= now)
        ):
            continue
        normalized = " ".join(item.statement.lower().split())
        groups.setdefault(normalized, []).append(item)
    candidates = []
    for normalized, duplicates in sorted(groups.items()):
        if len(duplicates) < 2:
            continue
        duplicates.sort(key=lambda item: (item.memory_id, item.version))
        candidate_id = f"dream-{canonical_sha256(normalized)[:20]}"
        first = duplicates[0]
        candidates.append(
            build_memory_candidate(
                candidate_id=candidate_id,
                memory_id=f"consolidated-{canonical_sha256(normalized)[:16]}",
                proposer_id="deterministic-dream-cycle-v1",
                memory_type=first.memory_type,
                title=f"Consolidated: {first.title}",
                statement=first.statement,
                evidence_ids=sorted({value for item in duplicates for value in item.evidence_ids}),
                source_case_ids=sorted(
                    {value for item in duplicates for value in item.source_case_ids}
                ),
                entity_ids=sorted({value for item in duplicates for value in item.entity_ids}),
                strategy_ids=sorted({value for item in duplicates for value in item.strategy_ids}),
                regime_ids=sorted({value for item in duplicates for value in item.regime_ids}),
                scope=first.scope,
                confidence=min(item.confidence for item in duplicates),
                utility_score=max(item.utility_score for item in duplicates),
                created_at=now,
                expires_at=min(
                    (item.expires_at for item in duplicates if item.expires_at is not None),
                    default=now + timedelta(days=365),
                ),
                review_by=now + timedelta(days=7),
                supersedes=[item.memory_id for item in duplicates],
                duplicate_of=first.memory_id,
            )
        )
    return tuple(candidates)
