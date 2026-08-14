"""Versioned offline research workflow; V1 remains replayable without modification."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, VersioningBehavior
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from aegisquant.security.digests import digest_canonical
    from aegisquant.workflows.contracts import (
        ReproducibleResearchWorkflowInput,
        ReproducibleResearchWorkflowResult,
    )


@workflow.defn(
    name="ResearchCaseWorkflowV2",
    sandboxed=True,
    versioning_behavior=VersioningBehavior.PINNED,
)
class ReproducibleResearchCaseWorkflow:
    @workflow.run
    async def run(
        self, command: ReproducibleResearchWorkflowInput
    ) -> ReproducibleResearchWorkflowResult:
        manifest_digest = await workflow.execute_activity(
            "verify_reproducible_manifest_v1",
            command,
            result_type=str,
            activity_id=f"manifest-v2:{command.tenant_id}:{command.case_id}",
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=45),
            retry_policy=RetryPolicy(maximum_attempts=2),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if manifest_digest != digest_canonical(command.manifest):
            raise ApplicationError(
                "manifest activity result does not match frozen manifest",
                type="REFERENCE_MISMATCH",
                non_retryable=True,
            )
        artifact_digest = await workflow.execute_activity(
            "emit_reproducible_artifact_v1",
            command,
            result_type=str,
            activity_id=f"artifact-v2:{command.tenant_id}:{command.case_id}",
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=45),
            retry_policy=RetryPolicy(maximum_attempts=2),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        expected_artifact_digest = digest_canonical(
            {
                "tenant_id": command.tenant_id,
                "case_id": command.case_id,
                "manifest": command.manifest,
                "fixture_evidence": command.fixture_evidence,
            }
        )
        if artifact_digest != expected_artifact_digest:
            raise ApplicationError(
                "artifact activity result does not match frozen inputs",
                type="REFERENCE_MISMATCH",
                non_retryable=True,
            )
        return ReproducibleResearchWorkflowResult(
            tenant_id=command.tenant_id,
            case_id=command.case_id,
            research_manifest_digest=manifest_digest,
            artifact_digest=artifact_digest,
        )
