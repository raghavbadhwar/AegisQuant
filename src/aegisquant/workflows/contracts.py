"""Small claim-check payloads for Temporal workflow history."""

from typing import Literal
from uuid import UUID

from pydantic import model_validator

from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.common import Identifier, Sha256Digest, StrictModel


class ResearchCaseWorkflowInput(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    data_snapshot_id: Identifier
    fixture_evidence: BlobRef

    @model_validator(mode="after")
    def evidence_belongs_to_tenant(self) -> "ResearchCaseWorkflowInput":
        if self.fixture_evidence.tenant_id != self.tenant_id:
            raise ValueError("fixture evidence must belong to the workflow tenant")
        return self


class SnapshotRef(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    snapshot_id: Identifier
    manifest_digest: Sha256Digest


class RegisteredEvidenceRef(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    evidence_id: UUID
    source_content_digest: Sha256Digest
    evidence_digest: Sha256Digest


class FixtureArtifactRef(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot_id: Identifier
    evidence_digest: Sha256Digest
    artifact_id: UUID
    artifact_digest: Sha256Digest


class RegisterFixtureEvidenceInput(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    fixture_evidence: BlobRef
    snapshot: SnapshotRef

    @model_validator(mode="after")
    def references_are_coherent(self) -> "RegisterFixtureEvidenceInput":
        if self.fixture_evidence.tenant_id != self.tenant_id:
            raise ValueError("fixture evidence must belong to the activity tenant")
        if self.snapshot.tenant_id != self.tenant_id:
            raise ValueError("snapshot must belong to the activity tenant")
        return self


class EmitFixtureArtifactInput(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot: SnapshotRef
    evidence: RegisteredEvidenceRef

    @model_validator(mode="after")
    def references_are_coherent(self) -> "EmitFixtureArtifactInput":
        if {self.snapshot.tenant_id, self.evidence.tenant_id} != {self.tenant_id}:
            raise ValueError("artifact inputs must belong to the activity tenant")
        if self.evidence.case_id != self.case_id:
            raise ValueError("registered evidence must belong to the activity case")
        return self


class ResearchCaseWorkflowResult(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot: SnapshotRef
    evidence: RegisteredEvidenceRef
    artifact: FixtureArtifactRef

    @model_validator(mode="after")
    def all_references_belong_to_tenant(self) -> "ResearchCaseWorkflowResult":
        nested_tenants = {
            self.snapshot.tenant_id,
            self.evidence.tenant_id,
            self.artifact.tenant_id,
        }
        if nested_tenants != {self.tenant_id}:
            raise ValueError("all workflow result references must belong to the result tenant")
        if self.evidence.case_id != self.case_id or self.artifact.case_id != self.case_id:
            raise ValueError("workflow references must belong to the result case")
        if self.artifact.snapshot_id != self.snapshot.snapshot_id:
            raise ValueError("artifact must bind the result snapshot")
        if self.artifact.evidence_digest != self.evidence.evidence_digest:
            raise ValueError("artifact must bind the registered evidence")
        return self
