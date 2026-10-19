"""Pure V2 replay activities; all source data is already frozen in fixtures."""

from temporalio import activity

from aegisquant.security.digests import digest_canonical
from aegisquant.workflows.contracts import ReproducibleResearchWorkflowInput


@activity.defn(name="verify_reproducible_manifest_v1")
async def verify_reproducible_manifest(command: ReproducibleResearchWorkflowInput) -> str:
    return digest_canonical(command.manifest)


@activity.defn(name="emit_reproducible_artifact_v1")
async def emit_reproducible_artifact(command: ReproducibleResearchWorkflowInput) -> str:
    return digest_canonical(
        {
            "tenant_id": command.tenant_id,
            "case_id": command.case_id,
            "manifest": command.manifest,
            "fixture_evidence": command.fixture_evidence,
        }
    )


REPRODUCIBLE_ACTIVITIES = (verify_reproducible_manifest, emit_reproducible_artifact)
