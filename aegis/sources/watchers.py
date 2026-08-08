"""One-shot source change detection that emits events, never trades."""

from __future__ import annotations

from datetime import datetime

from aegis.contracts import EventCandidate, canonical_sha256


def changed_event(
    *,
    source_id: str,
    entity_ids: list[str],
    previous_hash: str | None,
    current_hash: str,
    detected_at: datetime,
    evidence_ids: list[str],
) -> EventCandidate | None:
    if previous_hash is None or previous_hash == current_hash:
        return None
    event_id = canonical_sha256(
        {"source_id": source_id, "previous": previous_hash, "current": current_hash}
    )[:32]
    return EventCandidate(
        event_id=event_id,
        entity_ids=entity_ids,
        detected_at=detected_at,
        event_type="source-content-change",
        source_evidence_ids=evidence_ids,
        novelty_score=1.0,
        urgency_score=0.5,
        requires_case=True,
    )
