"""Deterministic M0 fixture-only research-case workflow."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from aegisquant.workflows.contracts import (
        FixtureArtifactRef,
        RegisteredEvidenceRef,
        ResearchCaseWorkflowInput,
        ResearchCaseWorkflowResult,
        SnapshotRef,
    )

_ACTIVITY_RETRY = RetryPolicy(maximum_attempts=2)
_ACTIVITY_TIMEOUT = timedelta(seconds=30)


@workflow.defn(name="ResearchCaseWorkflowV1", sandboxed=True)
class ResearchCaseWorkflow:
    @workflow.run
    async def run(self, command: ResearchCaseWorkflowInput) -> ResearchCaseWorkflowResult:
        snapshot = await workflow.execute_activity(
            "freeze_fixture_snapshot_v1",
            command,
            result_type=SnapshotRef,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )
        evidence = await workflow.execute_activity(
            "register_fixture_evidence_v1",
            command,
            result_type=RegisteredEvidenceRef,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )
        artifact = await workflow.execute_activity(
            "emit_fixture_artifact_v1",
            command,
            result_type=FixtureArtifactRef,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )
        return ResearchCaseWorkflowResult(
            tenant_id=command.tenant_id,
            case_id=command.case_id,
            snapshot=snapshot,
            evidence=evidence,
            artifact=artifact,
        )
