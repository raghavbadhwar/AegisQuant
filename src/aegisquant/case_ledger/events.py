"""Append-only business event contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import field_validator

from aegisquant.contracts.common import Identifier, Sha256Digest, StrictModel, require_utc


class CaseEvent(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    event_id: UUID
    sequence: int
    event_type: Identifier
    occurred_at: datetime
    recorded_at: datetime
    actor_id: Identifier
    correlation_id: UUID
    causation_id: UUID | None = None
    idempotency_key: Identifier
    payload: dict[str, Any]
    payload_canonical: str
    event_content_canonical: str
    event_content_digest: Sha256Digest
    previous_event_digest: Sha256Digest | None = None
    event_digest: Sha256Digest

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        return require_utc(value)
