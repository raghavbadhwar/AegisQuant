"""Pinned durable orchestration for the deterministic offline fixture runner."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, VersioningBehavior
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from aegisquant.workflows.contracts import (
        DurableExecutionWorkflowRef,
        DurableOfflineCaseWorkflowInput,
        DurableOfflineCaseWorkflowResult,
        DurablePreparedRef,
        DurableReconciliationRef,
        ReconcileDurableCaseInput,
    )


@workflow.defn(
    name="DurableOfflineCaseWorkflowV1",
    sandboxed=True,
    versioning_behavior=VersioningBehavior.PINNED,
)
class DurableOfflineCaseWorkflow:
    @staticmethod
    def activity_ids(command: DurableOfflineCaseWorkflowInput) -> tuple[str, str, str]:
        suffix = f"{command.tenant_id}:{command.case_id}"
        return (
            f"prepare-durable-v1:{suffix}",
            f"execute-durable-v1:{suffix}",
            f"reconcile-durable-v1:{suffix}",
        )

    @staticmethod
    def _mismatch(message: str) -> ApplicationError:
        return ApplicationError(
            message,
            type="REFERENCE_MISMATCH",
            non_retryable=True,
        )

    @workflow.run
    async def run(
        self, command: DurableOfflineCaseWorkflowInput
    ) -> DurableOfflineCaseWorkflowResult:
        prepare_id, execute_id, reconcile_id = self.activity_ids(command)
        prepared = await workflow.execute_activity(
            "prepare_durable_case_v1",
            command,
            result_type=DurablePreparedRef,
            activity_id=prepare_id,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=45),
            retry_policy=RetryPolicy(maximum_attempts=2),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if (
            prepared.tenant_id != command.tenant_id
            or prepared.case_id != command.case_id
            or prepared.account_id != command.account_id
            or prepared.state_sequence != 0
            or prepared.snapshot_digest != command.initial_account_digest
        ):
            raise self._mismatch("prepare activity returned an incoherent durable reference")

        execution = await workflow.execute_activity(
            "execute_durable_case_v1",
            command,
            result_type=DurableExecutionWorkflowRef,
            activity_id=execute_id,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=45),
            retry_policy=RetryPolicy(maximum_attempts=2),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if (
            execution.tenant_id != command.tenant_id
            or execution.case_id != command.case_id
            or execution.account_id != command.account_id
            or execution.execution_id != command.execution_id
            or execution.request_digest != command.fixture_spec_digest
            or execution.account_state_sequence != 1
        ):
            raise self._mismatch("execute activity returned an incoherent durable reference")

        reconciliation = await workflow.execute_activity(
            "reconcile_durable_case_v1",
            ReconcileDurableCaseInput(command=command, execution=execution),
            result_type=DurableReconciliationRef,
            activity_id=reconcile_id,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=45),
            retry_policy=RetryPolicy(maximum_attempts=2),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if (
            reconciliation.tenant_id != command.tenant_id
            or reconciliation.case_id != command.case_id
            or reconciliation.account_id != command.account_id
            or reconciliation.execution_id != command.execution_id
            or reconciliation.result_digest != execution.result_digest
            or reconciliation.account_snapshot_digest != execution.account_snapshot_digest
            or reconciliation.fill_digests != execution.fill_digests
            or not reconciliation.reconciled
        ):
            raise self._mismatch("reconcile activity returned an incoherent durable reference")
        return DurableOfflineCaseWorkflowResult(
            tenant_id=command.tenant_id,
            case_id=command.case_id,
            prepared=prepared,
            execution=execution,
            reconciliation=reconciliation,
        )
