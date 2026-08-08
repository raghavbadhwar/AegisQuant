"""Content addressing helpers."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID

from aegisquant.contracts.common import canonical_json_bytes


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def digest_canonical(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


CASE_EVENT_CONTENT_DOMAIN = "AEGISQUANT_CASE_EVENT_CONTENT_V1"
CASE_EVENT_CHAIN_DOMAIN = "AEGISQUANT_CASE_EVENT_CHAIN_V1"


def _frame(value: str) -> str:
    return f"{len(value.encode('utf-8'))}:{value}"


def _utc_text(value: datetime) -> str:
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("case-event timestamps must be UTC")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def case_event_content_canonical(
    *,
    schema_version: int,
    tenant_id: str,
    case_id: UUID,
    event_id: UUID,
    sequence: int,
    event_type: str,
    occurred_at: datetime,
    recorded_at: datetime,
    actor_id: str,
    correlation_id: UUID,
    causation_id: UUID | None,
    idempotency_key: str,
    payload_canonical: str,
) -> str:
    """Versioned length-prefixed event preimage shared with PostgreSQL."""

    values = (
        str(schema_version),
        tenant_id,
        str(case_id),
        str(event_id),
        str(sequence),
        event_type,
        _utc_text(occurred_at),
        _utc_text(recorded_at),
        actor_id,
        str(correlation_id),
        str(causation_id) if causation_id is not None else "<NULL>",
        idempotency_key,
        payload_canonical,
    )
    return CASE_EVENT_CONTENT_DOMAIN + "".join(_frame(value) for value in values)


def case_event_chain_digest(previous_digest: str | None, event_content_digest: str) -> str:
    previous = previous_digest if previous_digest is not None else "ROOT"
    preimage = f"{CASE_EVENT_CHAIN_DOMAIN}|{previous}|{event_content_digest}".encode()
    return sha256_bytes(preimage)
