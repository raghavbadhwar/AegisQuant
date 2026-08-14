"""Narrow PostgreSQL adapter for durable offline paper execution."""

from __future__ import annotations

import json
import unicodedata
from typing import Any, NoReturn
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from aegisquant.case_ledger.store import IdempotencyConflict
from aegisquant.contracts.common import Identifier, Nonce, Sha256Digest, StrictModel
from aegisquant.security.digests import sha256_bytes


def _jsonb_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_jsonb_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSONB payload keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("duplicate JSONB key after Unicode normalization")
            normalized[normalized_key] = _jsonb_value(item)
        return {
            key: normalized[key]
            for key in sorted(normalized, key=lambda item: (len(item.encode()), item.encode()))
        }
    raise TypeError("JSONB payloads accept only null, booleans, integers, strings, lists, and maps")


def digest_jsonb(value: dict[str, Any]) -> str:
    """Match PostgreSQL 16's stable ``jsonb::text`` representation for accepted payloads."""

    text = json.dumps(
        _jsonb_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(", ", ": "),
    )
    return sha256_bytes(text.encode())


class DurableCaseWrite(StrictModel):
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    state_sequence: int = Field(ge=0)
    snapshot_digest: Sha256Digest
    snapshot_payload: dict[str, Any]

    @model_validator(mode="after")
    def payload_is_bound(self) -> DurableCaseWrite:
        if digest_jsonb(self.snapshot_payload) != self.snapshot_digest:
            raise ValueError("snapshot_digest does not bind snapshot_payload")
        return self


class DurableExecutionWrite(StrictModel):
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    execution_id: UUID
    idempotency_key: Identifier
    nonce: Nonce
    decision_digest: Sha256Digest
    request_digest: Sha256Digest
    result_digest: Sha256Digest
    result_payload: dict[str, Any]
    account_state_sequence: int = Field(gt=0)
    account_snapshot_digest: Sha256Digest
    account_snapshot_payload: dict[str, Any]

    @model_validator(mode="after")
    def payloads_are_bound(self) -> DurableExecutionWrite:
        if digest_jsonb(self.result_payload) != self.result_digest:
            raise ValueError("result_digest does not bind result_payload")
        if digest_jsonb(self.account_snapshot_payload) != self.account_snapshot_digest:
            raise ValueError("account_snapshot_digest does not bind account_snapshot_payload")
        return self


class DurableCaseRef(StrictModel):
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    state_sequence: int = Field(ge=0)
    snapshot_digest: Sha256Digest


class DurableExecutionRef(StrictModel):
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    execution_id: UUID
    idempotency_key: Identifier
    request_digest: Sha256Digest
    result_digest: Sha256Digest
    result_payload: dict[str, Any]
    account_state_sequence: int = Field(gt=0)
    account_snapshot_digest: Sha256Digest


class DurableAccountSnapshot(StrictModel):
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    state_sequence: int = Field(ge=0)
    snapshot_digest: Sha256Digest
    snapshot_payload: dict[str, Any]


class DurableCaseSnapshot(StrictModel):
    account: DurableAccountSnapshot
    latest_execution: DurableExecutionRef | None


def _case_ref(row: dict[str, Any]) -> DurableCaseRef:
    return DurableCaseRef.model_validate({key: row[key] for key in DurableCaseRef.model_fields})


def _execution_ref(row: dict[str, Any]) -> DurableExecutionRef:
    return DurableExecutionRef.model_validate(
        {key: row[key] for key in DurableExecutionRef.model_fields}
    )


class PostgresCaseStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def prepare_case(self, write: DurableCaseWrite) -> DurableCaseRef:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    """
                    SELECT (aq_prepare_paper_account(%s,%s,%s,%s,%s,%s)).*
                    """,
                    (
                        write.tenant_id,
                        write.case_id,
                        write.account_id,
                        write.state_sequence,
                        write.snapshot_digest,
                        Jsonb(write.snapshot_payload),
                    ),
                ).fetchone()
        except psycopg.Error as error:
            self._raise_domain_error(error)
        if row is None:
            raise RuntimeError("paper account preparation returned no durable row")
        result = _case_ref(row)
        if (
            result.tenant_id != write.tenant_id
            or result.case_id != write.case_id
            or result.account_id != write.account_id
            or result.state_sequence != write.state_sequence
            or result.snapshot_digest != write.snapshot_digest
        ):
            raise RuntimeError("prepared durable case does not match its authenticated input")
        return result

    def execute_once(self, write: DurableExecutionWrite) -> DurableExecutionRef:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    """
                    SELECT (aq_record_paper_execution(
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    )).*
                    """,
                    (
                        write.tenant_id,
                        write.case_id,
                        write.account_id,
                        write.execution_id,
                        write.idempotency_key,
                        write.nonce,
                        write.decision_digest,
                        write.request_digest,
                        write.result_digest,
                        Jsonb(write.result_payload),
                        write.account_state_sequence,
                        write.account_snapshot_digest,
                        Jsonb(write.account_snapshot_payload),
                    ),
                ).fetchone()
        except psycopg.Error as error:
            self._raise_domain_error(error)
        if row is None:
            raise RuntimeError("paper execution returned no durable row")
        result = _execution_ref(row)
        if (
            result.tenant_id != write.tenant_id
            or result.case_id != write.case_id
            or result.account_id != write.account_id
            or result.execution_id != write.execution_id
            or result.idempotency_key != write.idempotency_key
            or result.request_digest != write.request_digest
            or result.result_digest != write.result_digest
            or result.account_state_sequence != write.account_state_sequence
            or result.account_snapshot_digest != write.account_snapshot_digest
        ):
            raise RuntimeError("durable execution result does not match its authenticated input")
        return result

    def inspect(self, *, tenant_id: str, case_id: UUID, account_id: str) -> DurableCaseSnapshot:
        params = (tenant_id, case_id, account_id)
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                WITH latest_account AS (
                    SELECT tenant_id, case_id, account_id, state_sequence,
                           snapshot_digest, snapshot_payload
                    FROM paper_account_snapshots
                    WHERE tenant_id = %s AND case_id = %s AND account_id = %s
                    ORDER BY state_sequence DESC LIMIT 1
                )
                SELECT account.*,
                       execution.execution_id, execution.idempotency_key,
                       execution.request_digest, execution.result_digest,
                       execution.result_payload, execution.account_state_sequence,
                       execution.account_snapshot_digest
                FROM latest_account AS account
                LEFT JOIN paper_execution_results AS execution
                  ON execution.tenant_id = account.tenant_id
                 AND execution.case_id = account.case_id
                 AND execution.account_id = account.account_id
                 AND execution.account_state_sequence = account.state_sequence
                """,
                params,
            ).fetchone()
        if row is None:
            raise LookupError("durable case is absent or outside the authenticated tenant")
        account = DurableAccountSnapshot.model_validate(
            {key: row[key] for key in DurableAccountSnapshot.model_fields}
        )
        if digest_jsonb(account.snapshot_payload) != account.snapshot_digest:
            raise RuntimeError("stored account payload digest is incoherent")
        latest_execution = _execution_ref(row) if row.get("execution_id") is not None else None
        if latest_execution is not None and (
            latest_execution.account_state_sequence != account.state_sequence
            or latest_execution.account_snapshot_digest != account.snapshot_digest
            or digest_jsonb(latest_execution.result_payload) != latest_execution.result_digest
        ):
            raise RuntimeError("stored execution and account state are incoherent")
        return DurableCaseSnapshot(account=account, latest_execution=latest_execution)

    @staticmethod
    def _raise_domain_error(error: psycopg.Error) -> NoReturn:
        if error.sqlstate in {"AQ001", "AQ002", "AQ003"}:
            raise IdempotencyConflict(str(error)) from error
        raise error
