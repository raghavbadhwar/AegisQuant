"""Deterministic M0 fixture-only research-case workflow."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, VersioningBehavior
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from aegisquant.workflows.contracts import (
        EmitFixtureArtifactInput,
        FixtureArtifactRef,
        RegisteredEvidenceRef,
        RegisterFixtureEvidenceInput,
        ResearchCaseWorkflowInput,
        ResearchCaseWorkflowResult,
        SnapshotRef,
    )

_ACTIVITY_RETRY = RetryPolicy(maximum_attempts=2)
_ACTIVITY_START_TO_CLOSE = timedelta(seconds=30)
_ACTIVITY_SCHEDULE_TO_CLOSE = timedelta(seconds=45)
_ACTIVITY_SCHEDULE_TO_START = timedelta(seconds=10)
_ACTIVITY_HEARTBEAT = timedelta(seconds=10)


@workflow.defn(
    name="ResearchCaseWorkflowV1",
    sandboxed=True,
    versioning_behavior=VersioningBehavior.PINNED,
)
class ResearchCaseWorkflow:
    @workflow.run
    async def run(self, command: ResearchCaseWorkflowInput) -> ResearchCaseWorkflowResult:
        snapshot = await workflow.execute_activity(
            "freeze_fixture_snapshot_v1",
            command,
            result_type=SnapshotRef,
            activity_id=f"freeze-v1:{command.tenant_id}:{command.case_id}",
            start_to_close_timeout=_ACTIVITY_START_TO_CLOSE,
            schedule_to_close_timeout=_ACTIVITY_SCHEDULE_TO_CLOSE,
            schedule_to_start_timeout=_ACTIVITY_SCHEDULE_TO_START,
            heartbeat_timeout=_ACTIVITY_HEARTBEAT,
            retry_policy=_ACTIVITY_RETRY,
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if (
            snapshot.tenant_id != command.tenant_id
            or snapshot.snapshot_id != command.data_snapshot_id
        ):
            raise ApplicationError(
                "snapshot result does not match workflow command",
                type="REFERENCE_MISMATCH",
                non_retryable=True,
            )

        evidence = await workflow.execute_activity(
            "register_fixture_evidence_v1",
            RegisterFixtureEvidenceInput(
                tenant_id=command.tenant_id,
                case_id=command.case_id,
                fixture_evidence=command.fixture_evidence,
                snapshot=snapshot,
            ),
            result_type=RegisteredEvidenceRef,
            activity_id=f"evidence-v1:{command.tenant_id}:{command.case_id}",
            start_to_close_timeout=_ACTIVITY_START_TO_CLOSE,
            schedule_to_close_timeout=_ACTIVITY_SCHEDULE_TO_CLOSE,
            schedule_to_start_timeout=_ACTIVITY_SCHEDULE_TO_START,
            heartbeat_timeout=_ACTIVITY_HEARTBEAT,
            retry_policy=_ACTIVITY_RETRY,
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if (
            evidence.tenant_id != command.tenant_id
            or evidence.case_id != command.case_id
            or evidence.source_content_digest != command.fixture_evidence.content_digest
        ):
            raise ApplicationError(
                "evidence result does not match workflow command",
                type="REFERENCE_MISMATCH",
                non_retryable=True,
            )

        artifact = await workflow.execute_activity(
            "emit_fixture_artifact_v1",
            EmitFixtureArtifactInput(
                tenant_id=command.tenant_id,
                case_id=command.case_id,
                snapshot=snapshot,
                evidence=evidence,
            ),
            result_type=FixtureArtifactRef,
            activity_id=f"artifact-v1:{command.tenant_id}:{command.case_id}",
            start_to_close_timeout=_ACTIVITY_START_TO_CLOSE,
            schedule_to_close_timeout=_ACTIVITY_SCHEDULE_TO_CLOSE,
            schedule_to_start_timeout=_ACTIVITY_SCHEDULE_TO_START,
            heartbeat_timeout=_ACTIVITY_HEARTBEAT,
            retry_policy=_ACTIVITY_RETRY,
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if (
            artifact.tenant_id != command.tenant_id
            or artifact.case_id != command.case_id
            or artifact.snapshot_id != snapshot.snapshot_id
            or artifact.evidence_digest != evidence.evidence_digest
        ):
            raise ApplicationError(
                "artifact result does not match workflow inputs",
                type="REFERENCE_MISMATCH",
                non_retryable=True,
            )
        return ResearchCaseWorkflowResult(
            tenant_id=command.tenant_id,
            case_id=command.case_id,
            snapshot=snapshot,
            evidence=evidence,
            artifact=artifact,
        )
