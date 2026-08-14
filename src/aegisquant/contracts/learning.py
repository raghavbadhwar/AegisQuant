"""Immutable governed-learning records; none carries an automatic promotion path."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import field_validator, model_validator

from aegisquant.contracts.common import Identifier, Sha256Digest, StrictModel, require_utc


class LearningCandidate(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    candidate_id: Identifier
    candidate_type: Literal["PROMPT", "SKILL", "ROUTE", "FEATURE", "STRATEGY"]
    source_manifest_digest: Sha256Digest
    created_at: datetime
    matures_at: datetime

    @field_validator("created_at", "matures_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def requires_horizon(self) -> "LearningCandidate":
        if self.matures_at <= self.created_at:
            raise ValueError("learning candidate must have a future maturity time")
        return self


class LearningEvaluation(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    candidate_id: Identifier
    evaluation_manifest_digest: Sha256Digest
    evaluator_id: Identifier
    shadow_passed: bool
    canary_passed: bool
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class PromotionApproval(StrictModel):
    """A manual record, not an instruction to change a running system."""

    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    candidate_id: Identifier
    evaluation_manifest_digest: Sha256Digest
    approver_id: Identifier
    approval_digest: Sha256Digest
    rollback_manifest_digest: Sha256Digest
    approved_at: datetime

    @field_validator("approved_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)
