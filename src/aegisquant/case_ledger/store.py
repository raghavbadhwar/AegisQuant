"""Local append-only, hash-chained case event store."""

from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from aegisquant.case_ledger.events import CaseEvent
from aegisquant.contracts.common import canonical_json_bytes, require_utc
from aegisquant.security.digests import (
    case_event_chain_digest,
    case_event_content_canonical,
    digest_canonical,
    sha256_bytes,
)


class IdempotencyConflict(ValueError):
    pass


class InMemoryCaseEventStore:
    """Reference semantics for the PostgreSQL ledger implementation."""

    def __init__(self) -> None:
        self._events: dict[tuple[str, UUID], list[CaseEvent]] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, CaseEvent]] = {}
        self._lock = Lock()

    def append(
        self,
        *,
        tenant_id: str,
        case_id: UUID,
        event_type: str,
        occurred_at: datetime,
        recorded_at: datetime,
        actor_id: str,
        correlation_id: UUID,
        idempotency_key: str,
        payload: dict[str, Any],
        causation_id: UUID | None = None,
    ) -> CaseEvent:
        occurred_at = require_utc(occurred_at)
        recorded_at = require_utc(recorded_at)
        request_fingerprint = digest_canonical(
            {
                "tenant_id": tenant_id,
                "case_id": case_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "actor_id": actor_id,
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "payload": payload,
            }
        )
        with self._lock:
            idem_key = (tenant_id, idempotency_key)
            existing = self._idempotency.get(idem_key)
            if existing is not None:
                prior_fingerprint, prior_event = existing
                if prior_fingerprint != request_fingerprint:
                    raise IdempotencyConflict("idempotency key was reused with different content")
                return prior_event
            stream = self._events.setdefault((tenant_id, case_id), [])
            previous = stream[-1].event_digest if stream else None
            event_id = uuid4()
            payload_canonical = canonical_json_bytes(payload).decode("utf-8")
            event_content_canonical = case_event_content_canonical(
                schema_version=1,
                tenant_id=tenant_id,
                case_id=case_id,
                event_id=event_id,
                sequence=len(stream) + 1,
                event_type=event_type,
                occurred_at=occurred_at,
                recorded_at=recorded_at,
                actor_id=actor_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                idempotency_key=idempotency_key,
                payload_canonical=payload_canonical,
            )
            event_content_digest = sha256_bytes(event_content_canonical.encode("utf-8"))
            event = CaseEvent(
                tenant_id=tenant_id,
                case_id=case_id,
                event_id=event_id,
                sequence=len(stream) + 1,
                event_type=event_type,
                occurred_at=occurred_at,
                recorded_at=recorded_at,
                actor_id=actor_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                idempotency_key=idempotency_key,
                payload=payload,
                payload_canonical=payload_canonical,
                event_content_canonical=event_content_canonical,
                event_content_digest=event_content_digest,
                previous_event_digest=previous,
                event_digest=case_event_chain_digest(previous, event_content_digest),
            )
            stream.append(event)
            self._idempotency[idem_key] = (request_fingerprint, event)
            return event

    def read(self, *, tenant_id: str, case_id: UUID) -> tuple[CaseEvent, ...]:
        with self._lock:
            return tuple(self._events.get((tenant_id, case_id), ()))

    def verify_chain(self, *, tenant_id: str, case_id: UUID) -> bool:
        events = self.read(tenant_id=tenant_id, case_id=case_id)
        previous: str | None = None
        for expected_sequence, event in enumerate(events, start=1):
            expected_payload = canonical_json_bytes(event.payload).decode("utf-8")
            expected_content = case_event_content_canonical(
                schema_version=event.schema_version,
                tenant_id=event.tenant_id,
                case_id=event.case_id,
                event_id=event.event_id,
                sequence=event.sequence,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
                actor_id=event.actor_id,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                idempotency_key=event.idempotency_key,
                payload_canonical=expected_payload,
            )
            if (
                event.sequence != expected_sequence
                or event.previous_event_digest != previous
                or expected_payload != event.payload_canonical
                or expected_content != event.event_content_canonical
                or sha256_bytes(expected_content.encode("utf-8")) != event.event_content_digest
                or case_event_chain_digest(previous, event.event_content_digest)
                != event.event_digest
            ):
                return False
            previous = event.event_digest
        return True
