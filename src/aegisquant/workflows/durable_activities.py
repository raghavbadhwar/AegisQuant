"""Idempotent Activities for the durable offline fixture workflow."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from temporalio import activity

from aegisquant.case_ledger.postgres import (
    DurableCaseWrite,
    DurableExecutionRef,
    DurableExecutionWrite,
    PostgresCaseStore,
    digest_jsonb,
)
from aegisquant.fixture_case import FixtureCaseReport, FixtureCaseSpec, run_fixture_case
from aegisquant.quant.paper import PaperAccountState
from aegisquant.security.digests import digest_canonical
from aegisquant.workflows.contracts import (
    DurableExecutionWorkflowRef,
    DurableOfflineCaseWorkflowInput,
    DurablePreparedRef,
    DurableReconciliationRef,
    ReconcileDurableCaseInput,
)


class DurableCaseActivities:
    def __init__(self, store: PostgresCaseStore, *, fixture_root: Path) -> None:
        self._store = store
        self._fixture_root = fixture_root.resolve()

    @property
    def definitions(self) -> tuple[object, ...]:
        return (self.prepare, self.execute, self.reconcile)

    def _load(self, command: DurableOfflineCaseWorkflowInput) -> FixtureCaseSpec:
        path = (self._fixture_root / command.fixture_name).resolve()
        if self._fixture_root not in path.parents:
            raise ValueError("fixture reference escapes the configured fixture root")
        spec = FixtureCaseSpec.model_validate_json(path.read_bytes())
        if (
            spec.manifest.tenant_id != command.tenant_id
            or spec.manifest.case_id != command.case_id
            or digest_canonical(spec) != command.fixture_spec_digest
        ):
            raise ValueError("fixture does not match the durable workflow command")
        return spec

    @activity.defn(name="prepare_durable_case_v1")
    async def prepare(self, command: DurableOfflineCaseWorkflowInput) -> DurablePreparedRef:
        return await asyncio.to_thread(self._prepare, command)

    def _prepare(self, command: DurableOfflineCaseWorkflowInput) -> DurablePreparedRef:
        spec = self._load(command)
        account = PaperAccountState(
            tenant_id=command.tenant_id,
            case_id=command.case_id,
            account_id=command.account_id,
            cash=spec.initial_cash,
            positions=(),
            state_sequence=0,
        )
        payload = account.model_dump(mode="json")
        write = DurableCaseWrite(
            tenant_id=command.tenant_id,
            case_id=command.case_id,
            account_id=command.account_id,
            state_sequence=0,
            snapshot_digest=digest_jsonb(payload),
            snapshot_payload=payload,
        )
        if write.snapshot_digest != command.initial_account_digest:
            raise ValueError("initial account digest does not match the frozen fixture")
        stored = self._store.prepare_case(write)
        return DurablePreparedRef.model_validate(stored.model_dump())

    @activity.defn(name="execute_durable_case_v1")
    async def execute(
        self, command: DurableOfflineCaseWorkflowInput
    ) -> DurableExecutionWorkflowRef:
        return await asyncio.to_thread(self._execute, command)

    def _execute(self, command: DurableOfflineCaseWorkflowInput) -> DurableExecutionWorkflowRef:
        spec = self._load(command)
        report = run_fixture_case(spec)
        result_payload = report.model_dump(mode="json")
        account_payload = report.final_account.model_dump(mode="json")
        manifest_digest = digest_canonical(spec.manifest)
        nonce = hashlib.sha256(
            f"aegisquant:nonce:{command.case_id}:{manifest_digest}".encode()
        ).hexdigest()[:32]
        stored = self._store.execute_once(
            DurableExecutionWrite(
                tenant_id=command.tenant_id,
                case_id=command.case_id,
                account_id=command.account_id,
                execution_id=command.execution_id,
                idempotency_key=f"fixture-exec:{command.case_id}",
                nonce=nonce,
                decision_digest=report.risk_decision_digest,
                request_digest=command.fixture_spec_digest,
                result_digest=digest_jsonb(result_payload),
                result_payload=result_payload,
                account_state_sequence=report.final_account.state_sequence,
                account_snapshot_digest=digest_jsonb(account_payload),
                account_snapshot_payload=account_payload,
            )
        )
        return self._workflow_execution_ref(stored)

    @activity.defn(name="reconcile_durable_case_v1")
    async def reconcile(self, value: ReconcileDurableCaseInput) -> DurableReconciliationRef:
        return await asyncio.to_thread(self._reconcile, value)

    def _reconcile(self, value: ReconcileDurableCaseInput) -> DurableReconciliationRef:
        spec = self._load(value.command)
        snapshot = self._store.inspect(
            tenant_id=value.command.tenant_id,
            case_id=value.command.case_id,
            account_id=value.command.account_id,
        )
        stored = snapshot.latest_execution
        if stored is None or self._workflow_execution_ref(stored) != value.execution:
            raise ValueError("stored execution does not match the workflow execution reference")
        report = FixtureCaseReport.model_validate_json(json.dumps(stored.result_payload))
        account_payload = report.final_account.model_dump(mode="json")
        manifest_digest = digest_canonical(spec.manifest)
        expected_nonce = hashlib.sha256(
            f"aegisquant:nonce:{value.command.case_id}:{manifest_digest}".encode()
        ).hexdigest()[:32]
        if (
            not report.reconciled
            or report.tenant_id != value.command.tenant_id
            or report.case_id != value.command.case_id
            or report.final_account.account_id != value.command.account_id
            or report.risk_decision_nonce != expected_nonce
            or stored.nonce != report.risk_decision_nonce
            or stored.decision_digest != report.risk_decision_digest
            or digest_jsonb(stored.result_payload) != stored.result_digest
            or digest_jsonb(account_payload) != snapshot.account.snapshot_digest
            or snapshot.account.snapshot_digest != stored.account_snapshot_digest
        ):
            raise ValueError("durable execution failed independent stored-state reconciliation")
        self._store.reconcile_once(
            tenant_id=value.command.tenant_id,
            case_id=value.command.case_id,
            account_id=value.command.account_id,
            execution_id=value.command.execution_id,
            result_digest=stored.result_digest,
        )
        return DurableReconciliationRef(
            tenant_id=value.command.tenant_id,
            case_id=value.command.case_id,
            account_id=value.command.account_id,
            execution_id=value.command.execution_id,
            result_digest=stored.result_digest,
            account_snapshot_digest=stored.account_snapshot_digest,
            fill_digests=self._fill_digests(stored),
            reconciled=True,
        )

    @staticmethod
    def _fill_digests(stored: DurableExecutionRef) -> tuple[str, ...]:
        fills = stored.result_payload.get("fills")
        if not isinstance(fills, list) or any(not isinstance(item, dict) for item in fills):
            raise ValueError("stored execution fills are malformed")
        return tuple(digest_jsonb(item) for item in fills)

    @classmethod
    def _workflow_execution_ref(cls, stored: DurableExecutionRef) -> DurableExecutionWorkflowRef:
        if stored.account_state_sequence != 1:
            raise ValueError("offline fixture execution must produce account state sequence 1")
        return DurableExecutionWorkflowRef(
            tenant_id=stored.tenant_id,
            case_id=stored.case_id,
            account_id=stored.account_id,
            execution_id=stored.execution_id,
            nonce=stored.nonce,
            decision_digest=stored.decision_digest,
            request_digest=stored.request_digest,
            result_digest=stored.result_digest,
            account_state_sequence=1,
            account_snapshot_digest=stored.account_snapshot_digest,
            fill_digests=cls._fill_digests(stored),
        )
