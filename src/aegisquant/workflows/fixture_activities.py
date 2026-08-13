"""Fixture-only M0 Temporal Activities.

These Activities are pure reference implementations: no network, database, broker, or
mutable external effects. Production write Activities remain feature-disabled until
transactional idempotency and uncertain-outcome tests pass.
"""

from uuid import NAMESPACE_URL, uuid5

from temporalio import activity

from aegisquant.security.digests import digest_canonical
from aegisquant.workflows.contracts import (
    EmitFixtureArtifactInput,
    FixtureArtifactRef,
    RegisteredEvidenceRef,
    RegisterFixtureEvidenceInput,
    ResearchCaseWorkflowInput,
    SnapshotRef,
)


@activity.defn(name="freeze_fixture_snapshot_v1")
async def freeze_fixture_snapshot(command: ResearchCaseWorkflowInput) -> SnapshotRef:
    return SnapshotRef(
        tenant_id=command.tenant_id,
        snapshot_id=command.data_snapshot_id,
        manifest_digest=digest_canonical(
            {
                "schema_version": 1,
                "tenant_id": command.tenant_id,
                "snapshot_id": command.data_snapshot_id,
                "fixture_digest": command.fixture_evidence.content_digest,
            }
        ),
    )


@activity.defn(name="register_fixture_evidence_v1")
async def register_fixture_evidence(
    command: RegisterFixtureEvidenceInput,
) -> RegisteredEvidenceRef:
    evidence_id = uuid5(
        NAMESPACE_URL,
        f"{command.tenant_id}:{command.case_id}:{command.fixture_evidence.content_digest}",
    )
    evidence_digest = digest_canonical(
        {
            "schema_version": 1,
            "tenant_id": command.tenant_id,
            "case_id": command.case_id,
            "evidence_id": evidence_id,
            "source_content_digest": command.fixture_evidence.content_digest,
        }
    )
    return RegisteredEvidenceRef(
        tenant_id=command.tenant_id,
        case_id=command.case_id,
        evidence_id=evidence_id,
        source_content_digest=command.fixture_evidence.content_digest,
        evidence_digest=evidence_digest,
    )


@activity.defn(name="emit_fixture_artifact_v1")
async def emit_fixture_artifact(command: EmitFixtureArtifactInput) -> FixtureArtifactRef:
    artifact_id = uuid5(NAMESPACE_URL, f"{command.case_id}:fixture-artifact")
    return FixtureArtifactRef(
        tenant_id=command.tenant_id,
        case_id=command.case_id,
        snapshot_id=command.snapshot.snapshot_id,
        evidence_digest=command.evidence.evidence_digest,
        artifact_id=artifact_id,
        artifact_digest=digest_canonical(
            {
                "schema_version": 1,
                "tenant_id": command.tenant_id,
                "case_id": command.case_id,
                "snapshot_id": command.snapshot.snapshot_id,
                "evidence_digest": command.evidence.evidence_digest,
                "artifact_id": artifact_id,
            }
        ),
    )


FIXTURE_ACTIVITIES = (
    freeze_fixture_snapshot,
    register_fixture_evidence,
    emit_fixture_artifact,
)
