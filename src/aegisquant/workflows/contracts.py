"""Small claim-check payloads for Temporal workflow history."""

from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import field_validator, model_validator

from aegisquant.contracts.artifact import BlobRef
from aegisquant.contracts.common import Identifier, Nonce, Sha256Digest, StrictModel
from aegisquant.contracts.research import ResearchManifest


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


class ReproducibleResearchWorkflowInput(StrictModel):
    """V2 history contains only a frozen manifest and immutable evidence reference."""

    schema_version: Literal[2] = 2
    tenant_id: Identifier
    case_id: UUID
    manifest: ResearchManifest
    fixture_evidence: BlobRef

    @model_validator(mode="after")
    def references_are_bound(self) -> "ReproducibleResearchWorkflowInput":
        if (
            self.manifest.tenant_id != self.tenant_id
            or self.fixture_evidence.tenant_id != self.tenant_id
        ):
            raise ValueError("manifest and fixture evidence must belong to the workflow tenant")
        if self.manifest.case_id != self.case_id:
            raise ValueError("manifest must belong to the workflow case")
        return self


class ReproducibleResearchWorkflowResult(StrictModel):
    schema_version: Literal[2] = 2
    tenant_id: Identifier
    case_id: UUID
    research_manifest_digest: Sha256Digest
    artifact_digest: Sha256Digest


class DurableOfflineCaseWorkflowInput(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    account_id: Literal["fixture-paper-account"]
    fixture_name: Identifier
    fixture_spec_digest: Sha256Digest
    initial_account_digest: Sha256Digest
    execution_id: UUID

    @model_validator(mode="after")
    def execution_is_bound_to_fixture(self) -> "DurableOfflineCaseWorkflowInput":
        expected = uuid5(NAMESPACE_URL, f"aegisquant:durable-execution:{self.fixture_spec_digest}")
        if self.execution_id != expected:
            raise ValueError("execution_id must bind the frozen fixture digest")
        return self


class DurablePreparedRef(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    state_sequence: Literal[0]
    snapshot_digest: Sha256Digest


class DurableExecutionWorkflowRef(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    execution_id: UUID
    nonce: Nonce
    decision_digest: Sha256Digest
    request_digest: Sha256Digest
    result_digest: Sha256Digest
    account_state_sequence: Literal[1]
    account_snapshot_digest: Sha256Digest
    fill_digests: tuple[Sha256Digest, ...]

    @field_validator("fill_digests", mode="before")
    @classmethod
    def parse_fill_digests(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReconcileDurableCaseInput(StrictModel):
    schema_version: Literal[1] = 1
    command: DurableOfflineCaseWorkflowInput
    execution: DurableExecutionWorkflowRef

    @model_validator(mode="after")
    def execution_belongs_to_command(self) -> "ReconcileDurableCaseInput":
        if (
            self.execution.tenant_id != self.command.tenant_id
            or self.execution.case_id != self.command.case_id
            or self.execution.account_id != self.command.account_id
            or self.execution.execution_id != self.command.execution_id
            or self.execution.request_digest != self.command.fixture_spec_digest
        ):
            raise ValueError("durable execution must belong to the workflow command")
        return self


class DurableReconciliationRef(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    execution_id: UUID
    result_digest: Sha256Digest
    account_snapshot_digest: Sha256Digest
    fill_digests: tuple[Sha256Digest, ...]
    reconciled: Literal[True]

    @field_validator("fill_digests", mode="before")
    @classmethod
    def parse_fill_digests(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class DurableOfflineCaseWorkflowResult(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    prepared: DurablePreparedRef
    execution: DurableExecutionWorkflowRef
    reconciliation: DurableReconciliationRef

    @model_validator(mode="after")
    def references_are_coherent(self) -> "DurableOfflineCaseWorkflowResult":
        if {
            self.prepared.tenant_id,
            self.execution.tenant_id,
            self.reconciliation.tenant_id,
        } != {self.tenant_id}:
            raise ValueError("all durable references must belong to the workflow tenant")
        if {
            self.prepared.case_id,
            self.execution.case_id,
            self.reconciliation.case_id,
        } != {self.case_id}:
            raise ValueError("all durable references must belong to the workflow case")
        if {
            self.prepared.account_id,
            self.execution.account_id,
            self.reconciliation.account_id,
        } != {self.execution.account_id}:
            raise ValueError("all durable references must belong to the same account")
        if self.execution.execution_id != self.reconciliation.execution_id:
            raise ValueError("reconciliation must belong to the same execution")
        if (
            self.execution.result_digest != self.reconciliation.result_digest
            or self.execution.account_snapshot_digest != self.reconciliation.account_snapshot_digest
            or self.execution.fill_digests != self.reconciliation.fill_digests
        ):
            raise ValueError("reconciliation must bind the exact stored execution")
        return self
