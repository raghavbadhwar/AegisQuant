from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any
from uuid import UUID

import psycopg
import pytest
from pydantic import ValidationError

from aegisquant.case_ledger.postgres import (
    DurableCaseWrite,
    DurableExecutionWrite,
    PostgresCaseStore,
    digest_jsonb,
)
from aegisquant.case_ledger.store import IdempotencyConflict

CASE_ID = UUID("00000000-0000-0000-0000-000000000001")
EXECUTION_ID = UUID("00000000-0000-0000-0000-000000000030")


class FakeCursor:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


class FakeConnection(AbstractContextManager["FakeConnection"]):
    def __init__(self, outcomes: list[dict[str, Any] | Exception | None]) -> None:
        self.outcomes: Iterator[dict[str, Any] | Exception | None] = iter(outcomes)
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> FakeCursor:
        self.calls.append((query, params))
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeCursor(outcome)


class FakeConflict(psycopg.Error):
    @property
    def sqlstate(self) -> str:
        return "AQ001"


def test_jsonb_digest_matches_postgres_golden() -> None:
    assert digest_jsonb({"aaaa": 1, "b": 2, "cc": 3}) == (
        "sha256:ea883663873df15b8f03c891f1cbc754fa22515473ac26d0ad4a32e741238841"
    )


def case_write() -> DurableCaseWrite:
    payload = {"cash": "10000", "positions": []}
    return DurableCaseWrite(
        tenant_id="tenant-a",
        case_id=CASE_ID,
        account_id="paper-1",
        state_sequence=0,
        snapshot_digest=digest_jsonb(payload),
        snapshot_payload=payload,
    )


def execution_write() -> DurableExecutionWrite:
    nonce = "0123456789abcdef0123456789abcdef"
    decision_digest = "sha256:" + "2" * 64
    result_payload = {
        "fills": [{"fill_id": "fill-1"}],
        "risk_decision_nonce": nonce,
        "risk_decision_digest": decision_digest,
    }
    account_payload = {"cash": "9900", "positions": []}
    return DurableExecutionWrite(
        tenant_id="tenant-a",
        case_id=CASE_ID,
        account_id="paper-1",
        execution_id=EXECUTION_ID,
        idempotency_key="execute-1",
        nonce=nonce,
        decision_digest=decision_digest,
        request_digest="sha256:" + "3" * 64,
        result_digest=digest_jsonb(result_payload),
        result_payload=result_payload,
        account_state_sequence=1,
        account_snapshot_digest=digest_jsonb(account_payload),
        account_snapshot_payload=account_payload,
    )


def test_durable_writes_reject_unbound_payload_digests() -> None:
    with pytest.raises(ValidationError, match="snapshot_digest"):
        DurableCaseWrite.model_validate(
            case_write().model_dump() | {"snapshot_digest": "sha256:" + "a" * 64}
        )

    with pytest.raises(ValidationError, match="result_digest"):
        DurableExecutionWrite.model_validate(
            execution_write().model_dump() | {"result_digest": "sha256:" + "a" * 64}
        )

    with pytest.raises(ValidationError, match="risk decision"):
        DurableExecutionWrite.model_validate(
            execution_write().model_dump() | {"nonce": "abcdef0123456789abcdef0123456789"}
        )


def test_prepare_and_execute_return_the_same_stored_reference_on_exact_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = case_write()
    execution = execution_write()
    case_row = initial.model_dump()
    execution_row = execution.model_dump(exclude={"account_snapshot_payload"})
    connection = FakeConnection(
        [case_row, execution_row, execution_row, {"event_digest": "sha256:" + "f" * 64}]
    )
    monkeypatch.setattr(
        "aegisquant.case_ledger.postgres.psycopg.connect",
        lambda *_args, **_kwargs: connection,
    )
    store = PostgresCaseStore("postgresql:///fixture")

    prepared = store.prepare_case(initial)
    first = store.execute_once(execution)
    second = store.execute_once(execution)
    store.reconcile_once(
        tenant_id=execution.tenant_id,
        case_id=execution.case_id,
        account_id=execution.account_id,
        execution_id=execution.execution_id,
        result_digest=execution.result_digest,
    )

    assert prepared.snapshot_digest == initial.snapshot_digest
    assert first == second
    assert first.result_digest == execution.result_digest
    assert all(call[1][:2] == ("tenant-a", CASE_ID) for call in connection.calls)


def test_changed_execution_content_maps_database_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection([FakeConflict("different content")])
    monkeypatch.setattr(
        "aegisquant.case_ledger.postgres.psycopg.connect",
        lambda *_args, **_kwargs: connection,
    )

    with pytest.raises(IdempotencyConflict, match="different content"):
        PostgresCaseStore("postgresql:///fixture").execute_once(execution_write())


def test_inspect_is_bound_to_tenant_case_and_account(monkeypatch: pytest.MonkeyPatch) -> None:
    initial = case_write()
    execution = execution_write()
    row = {
        "tenant_id": initial.tenant_id,
        "case_id": initial.case_id,
        "account_id": initial.account_id,
        "state_sequence": execution.account_state_sequence,
        "snapshot_digest": execution.account_snapshot_digest,
        "snapshot_payload": execution.account_snapshot_payload,
        **execution.model_dump(exclude={"tenant_id", "case_id", "account_id"}),
    }
    connection = FakeConnection([row])
    monkeypatch.setattr(
        "aegisquant.case_ledger.postgres.psycopg.connect",
        lambda *_args, **_kwargs: connection,
    )

    snapshot = PostgresCaseStore("postgresql:///fixture").inspect(
        tenant_id="tenant-a", case_id=CASE_ID, account_id="paper-1"
    )

    assert snapshot.account.snapshot_payload == execution.account_snapshot_payload
    assert snapshot.latest_execution is not None
    assert snapshot.latest_execution.execution_id == EXECUTION_ID
    assert all(call[1] == ("tenant-a", CASE_ID, "paper-1") for call in connection.calls)


def test_inspect_rejects_incoherent_stored_payload_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = case_write()
    connection = FakeConnection([initial.model_dump() | {"snapshot_digest": "sha256:" + "a" * 64}])
    monkeypatch.setattr(
        "aegisquant.case_ledger.postgres.psycopg.connect",
        lambda *_args, **_kwargs: connection,
    )

    with pytest.raises(RuntimeError, match="digest"):
        PostgresCaseStore("postgresql:///fixture").inspect(
            tenant_id="tenant-a", case_id=CASE_ID, account_id="paper-1"
        )


def test_inspect_rejects_stored_risk_decision_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = case_write()
    execution = execution_write()
    result_payload = execution.result_payload | {
        "risk_decision_nonce": "abcdef0123456789abcdef0123456789"
    }
    row = {
        "tenant_id": initial.tenant_id,
        "case_id": initial.case_id,
        "account_id": initial.account_id,
        "state_sequence": execution.account_state_sequence,
        "snapshot_digest": execution.account_snapshot_digest,
        "snapshot_payload": execution.account_snapshot_payload,
        **execution.model_dump(exclude={"tenant_id", "case_id", "account_id"}),
        "result_payload": result_payload,
        "result_digest": digest_jsonb(result_payload),
    }
    connection = FakeConnection([row])
    monkeypatch.setattr(
        "aegisquant.case_ledger.postgres.psycopg.connect",
        lambda *_args, **_kwargs: connection,
    )

    with pytest.raises(ValidationError, match="stored risk decision"):
        PostgresCaseStore("postgresql:///fixture").inspect(
            tenant_id="tenant-a", case_id=CASE_ID, account_id="paper-1"
        )
