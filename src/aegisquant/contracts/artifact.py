"""Immutable artifact bus contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import Identifier, Sha256Digest, StrictModel, require_utc


class DataClassification(StrEnum):
    PUBLIC = "public"
    LICENSED = "licensed"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class BlobRef(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    uri: str = Field(min_length=1, max_length=2048)
    content_digest: Sha256Digest
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=255)
    retention_class: Identifier


class EvidenceRef(StrictModel):
    evidence_id: UUID
    evidence_digest: Sha256Digest
    coordinate: str | None = Field(default=None, max_length=512)


class ProducerStamp(StrictModel):
    agent_id: Identifier
    agent_version: Identifier
    prompt_bundle_digest: Sha256Digest
    skill_bundle_digest: Sha256Digest
    route_decision_id: UUID | None = None
    actual_provider: Identifier | None = None
    actual_model: Identifier | None = None


class ArtifactEnvelope(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    artifact_id: UUID
    case_id: UUID
    schema_id: Identifier
    artifact_schema_version: Identifier
    payload: BlobRef
    payload_digest: Sha256Digest
    producer: ProducerStamp
    data_snapshot_id: Identifier
    parent_artifact_ids: tuple[UUID, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    classification: DataClassification
    created_at: datetime
    idempotency_key: Identifier

    @model_validator(mode="after")
    def payload_belongs_to_tenant(self) -> "ArtifactEnvelope":
        if self.payload.tenant_id != self.tenant_id:
            raise ValueError("artifact payload must belong to the artifact tenant")
        return self

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class ValidationReceipt(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    receipt_id: UUID
    artifact_id: UUID
    artifact_digest: Sha256Digest
    validator_id: Identifier
    validator_version: Identifier
    policy_id: Identifier
    checks: tuple[Identifier, ...]
    accepted: bool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return require_utc(value)
