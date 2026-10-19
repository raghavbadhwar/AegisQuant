"""Deterministic source-health aggregation; health is routing input, not truth."""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Literal

from aegis.contracts import SourceAttempt, SourceHealthSnapshot


def source_health(
    source_id: str, as_of: datetime, attempts: list[SourceAttempt]
) -> SourceHealthSnapshot:
    eligible = sorted(
        (item for item in attempts if item.source_id == source_id and item.attempted_at <= as_of),
        key=lambda item: item.attempted_at,
    )
    count = len(eligible)
    if not count:
        return SourceHealthSnapshot(
            source_id=source_id,
            as_of=as_of,
            attempts=0,
            success_rate=0.0,
            median_latency_ms=0.0,
            stale_frequency=0.0,
            parser_failure_rate=0.0,
            block_rate=0.0,
            citation_usefulness=0.0,
            contradiction_rate=0.0,
            status="unavailable",
        )

    def rate(field: str) -> float:
        return sum(bool(getattr(item, field)) for item in eligible) / count

    success = rate("success")
    status: Literal["healthy", "degraded", "unavailable"] = (
        "healthy" if success >= 0.9 else "degraded" if success >= 0.5 else "unavailable"
    )
    return SourceHealthSnapshot(
        source_id=source_id,
        as_of=as_of,
        attempts=count,
        success_rate=success,
        median_latency_ms=statistics.median(item.latency_ms for item in eligible),
        stale_frequency=rate("stale"),
        parser_failure_rate=rate("parser_failed"),
        block_rate=rate("blocked"),
        citation_usefulness=rate("citation_useful"),
        contradiction_rate=rate("contradicted"),
        status=status,
    )
