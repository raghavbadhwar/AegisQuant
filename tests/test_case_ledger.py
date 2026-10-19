from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aegisquant.case_ledger.state_machine import InvalidCaseTransition, validate_transition
from aegisquant.case_ledger.store import IdempotencyConflict, InMemoryCaseEventStore
from aegisquant.contracts.case import CaseStatus


def test_ledger_is_hash_chained_and_idempotent() -> None:
    store = InMemoryCaseEventStore()
    case_id = uuid4()
    correlation = uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    args = dict(
        tenant_id="tenant-a",
        case_id=case_id,
        event_type="CASE_CREATED",
        occurred_at=now,
        recorded_at=now,
        actor_id="control-api",
        correlation_id=correlation,
        idempotency_key="create-case-1",
        payload={"status": "CASE_CREATED"},
    )
    first = store.append(**args)
    repeated = store.append(**args)
    assert first == repeated
    assert len(store.read(tenant_id="tenant-a", case_id=case_id)) == 1
    assert store.verify_chain(tenant_id="tenant-a", case_id=case_id)


def test_idempotency_key_conflict_fails_closed() -> None:
    store = InMemoryCaseEventStore()
    case_id = uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = dict(
        tenant_id="tenant-a",
        case_id=case_id,
        event_type="CASE_CREATED",
        occurred_at=now,
        recorded_at=now,
        actor_id="control-api",
        correlation_id=uuid4(),
        idempotency_key="same-key",
    )
    store.append(**base, payload={"value": 1})
    with pytest.raises(IdempotencyConflict):
        store.append(**base, payload={"value": 2})


def test_state_machine_rejects_skips() -> None:
    validate_transition(CaseStatus.CASE_CREATED, CaseStatus.MANDATE_VALIDATED)
    with pytest.raises(InvalidCaseTransition):
        validate_transition(CaseStatus.CASE_CREATED, CaseStatus.RISK_APPROVED)
