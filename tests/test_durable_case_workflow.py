from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from aegisquant.case_ledger.postgres import (
    DurableAccountSnapshot,
    DurableCaseRef,
    DurableCaseSnapshot,
    DurableCaseWrite,
    DurableExecutionRef,
    DurableExecutionWrite,
    digest_jsonb,
)
from aegisquant.fixture_case import FixtureCaseReport, FixtureCaseSpec, run_fixture_case
from aegisquant.security.digests import digest_canonical
from aegisquant.workflows.contracts import (
    DurableExecutionWorkflowRef,
    DurableOfflineCaseWorkflowInput,
    DurableOfflineCaseWorkflowResult,
    DurablePreparedRef,
    DurableReconciliationRef,
    ReconcileDurableCaseInput,
)
from aegisquant.workflows.durable_activities import DurableCaseActivities
from aegisquant.workflows.durable_case import DurableOfflineCaseWorkflow

FIXTURE_ROOT = Path("data/fixtures/cases")
CASE_ID = UUID("00000000-0000-0000-0000-000000000101")


class FaultPoint(StrEnum):
    BEFORE_COMMIT = "before_commit"
    AFTER_COMMIT = "after_commit"
    AFTER_RECONCILE_COMMIT = "after_reconcile_commit"


class RecoveryStore:
    def __init__(self, fault: FaultPoint) -> None:
        self.fault = fault
        self.attempts = 0
        self.reconcile_attempts = 0
        self.prepared: DurableCaseWrite | None = None
        self.execution: DurableExecutionWrite | None = None
        self.reconciliation: tuple[str, UUID, str, UUID, str] | None = None

    def prepare_case(self, write: DurableCaseWrite) -> DurableCaseRef:
        self.prepared = write
        return DurableCaseRef.model_validate(write.model_dump(exclude={"snapshot_payload"}))

    def execute_once(self, write: DurableExecutionWrite) -> DurableExecutionRef:
        self.attempts += 1
        if self.fault is FaultPoint.BEFORE_COMMIT and self.attempts == 1:
            raise RuntimeError("injected failure before commit")
        if self.execution is None:
            self.execution = write
            if self.fault is FaultPoint.AFTER_COMMIT and self.attempts == 1:
                raise RuntimeError("injected failure after commit")
        elif self.execution != write:
            raise AssertionError("retry changed the durable execution write")
        return DurableExecutionRef.model_validate(
            self.execution.model_dump(exclude={"account_snapshot_payload"})
        )

    def reconcile_once(
        self,
        *,
        tenant_id: str,
        case_id: UUID,
        account_id: str,
        execution_id: UUID,
        result_digest: str,
    ) -> None:
        self.reconcile_attempts += 1
        value = (tenant_id, case_id, account_id, execution_id, result_digest)
        if self.reconciliation is None:
            self.reconciliation = value
            if self.fault is FaultPoint.AFTER_RECONCILE_COMMIT:
                raise RuntimeError("injected failure after reconciliation commit")
        elif self.reconciliation != value:
            raise AssertionError("retry changed the durable reconciliation write")

    def inspect(self, *, tenant_id: str, case_id: UUID, account_id: str) -> DurableCaseSnapshot:
        assert self.execution is not None
        account = DurableAccountSnapshot(
            tenant_id=tenant_id,
            case_id=case_id,
            account_id=account_id,
            state_sequence=self.execution.account_state_sequence,
            snapshot_digest=self.execution.account_snapshot_digest,
            snapshot_payload=self.execution.account_snapshot_payload,
        )
        return DurableCaseSnapshot(
            account=account,
            latest_execution=DurableExecutionRef.model_validate(
                self.execution.model_dump(exclude={"account_snapshot_payload"})
            ),
        )


def command() -> DurableOfflineCaseWorkflowInput:
    fixture = FixtureCaseSpec.model_validate_json(
        (FIXTURE_ROOT / "multi_asset_control.json").read_bytes()
    )
    initial_account = {
        "tenant_id": fixture.manifest.tenant_id,
        "case_id": str(fixture.manifest.case_id),
        "account_id": "fixture-paper-account",
        "cash": str(fixture.initial_cash),
        "positions": [],
        "state_sequence": 0,
    }
    fixture_digest = digest_canonical(fixture)
    return DurableOfflineCaseWorkflowInput(
        tenant_id=fixture.manifest.tenant_id,
        case_id=fixture.manifest.case_id,
        account_id="fixture-paper-account",
        fixture_name="multi_asset_control.json",
        fixture_spec_digest=fixture_digest,
        initial_account_digest=digest_jsonb(initial_account),
        execution_id=uuid5(NAMESPACE_URL, f"aegisquant:durable-execution:{fixture_digest}"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", list(FaultPoint))
async def test_durable_workflow_recovers_one_execution_across_activity_retry(
    fault: FaultPoint,
) -> None:
    store = RecoveryStore(fault)
    activities = DurableCaseActivities(store, fixture_root=FIXTURE_ROOT)
    value = command()
    task_queue = f"durable-recovery-{fault.value}"
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[DurableOfflineCaseWorkflow],
            activities=activities.definitions,
        ):
            result = await environment.client.execute_workflow(
                DurableOfflineCaseWorkflow.run,
                value,
                id=f"aegisquant:durable:{value.tenant_id}:{value.case_id}",
                task_queue=task_queue,
            )

    assert store.attempts == (1 if fault is FaultPoint.AFTER_RECONCILE_COMMIT else 2)
    assert store.reconcile_attempts == (2 if fault is FaultPoint.AFTER_RECONCILE_COMMIT else 1)
    assert store.reconciliation is not None
    assert store.execution is not None
    assert result.execution.result_digest == store.execution.result_digest
    assert result.reconciliation.result_digest == result.execution.result_digest
    assert result.reconciliation.reconciled is True
    assert len(store.execution.result_payload["fills"]) == len(result.execution.fill_digests)


def test_durable_workflow_contract_rejects_nested_case_or_digest_mismatch() -> None:
    value = command()
    with pytest.raises(ValueError, match="fixture"):
        DurableOfflineCaseWorkflowInput.model_validate(
            value.model_dump() | {"fixture_spec_digest": "sha256:" + "f" * 64}
        )
    execution = DurableExecutionWorkflowRef(
        tenant_id=value.tenant_id,
        case_id=UUID("00000000-0000-0000-0000-000000000999"),
        account_id=value.account_id,
        execution_id=value.execution_id,
        nonce="0123456789abcdef0123456789abcdef",
        decision_digest="sha256:" + "9" * 64,
        request_digest=value.fixture_spec_digest,
        result_digest="sha256:" + "a" * 64,
        account_state_sequence=1,
        account_snapshot_digest="sha256:" + "b" * 64,
        fill_digests=(),
    )
    with pytest.raises(ValueError, match="workflow command"):
        ReconcileDurableCaseInput(command=value, execution=execution)


def test_fixture_report_round_trips_through_durable_json() -> None:
    spec = FixtureCaseSpec.model_validate_json(
        (FIXTURE_ROOT / "multi_asset_control.json").read_bytes()
    )
    report = run_fixture_case(spec)
    assert len(report.risk_decision_nonce) >= 32
    assert FixtureCaseReport.model_validate_json(report.model_dump_json()) == report


def test_workflow_result_rejects_cross_account_or_execution_composition() -> None:
    value = command()
    execution = DurableExecutionWorkflowRef(
        tenant_id=value.tenant_id,
        case_id=value.case_id,
        account_id=value.account_id,
        execution_id=value.execution_id,
        nonce="0123456789abcdef0123456789abcdef",
        decision_digest="sha256:" + "1" * 64,
        request_digest=value.fixture_spec_digest,
        result_digest="sha256:" + "2" * 64,
        account_state_sequence=1,
        account_snapshot_digest="sha256:" + "3" * 64,
        fill_digests=(),
    )
    prepared = DurablePreparedRef(
        tenant_id=value.tenant_id,
        case_id=value.case_id,
        account_id="different-account",
        state_sequence=0,
        snapshot_digest=value.initial_account_digest,
    )
    reconciliation = DurableReconciliationRef(
        tenant_id=value.tenant_id,
        case_id=value.case_id,
        account_id=value.account_id,
        execution_id=UUID("00000000-0000-0000-0000-000000000998"),
        result_digest=execution.result_digest,
        account_snapshot_digest=execution.account_snapshot_digest,
        fill_digests=(),
        reconciled=True,
    )
    with pytest.raises(ValueError, match=r"account|execution"):
        DurableOfflineCaseWorkflowResult(
            tenant_id=value.tenant_id,
            case_id=value.case_id,
            prepared=prepared,
            execution=execution,
            reconciliation=reconciliation,
        )


def test_durable_activity_ids_are_stable_and_tenant_bound() -> None:
    value = command()
    assert DurableOfflineCaseWorkflow.activity_ids(value) == (
        f"prepare-durable-v1:{value.tenant_id}:{value.case_id}",
        f"execute-durable-v1:{value.tenant_id}:{value.case_id}",
        f"reconcile-durable-v1:{value.tenant_id}:{value.case_id}",
    )


@pytest.mark.asyncio
async def test_execute_activity_recomputes_identical_write() -> None:
    store = RecoveryStore(FaultPoint.AFTER_COMMIT)
    activities = DurableCaseActivities(store, fixture_root=FIXTURE_ROOT)
    value = command()
    await activities.prepare(value)
    with pytest.raises(RuntimeError, match="after commit"):
        await activities.execute(value)
    first = store.execution
    await asyncio.sleep(0)
    second = await activities.execute(value)
    assert store.execution == first
    assert second.result_digest == first.result_digest  # type: ignore[union-attr]
