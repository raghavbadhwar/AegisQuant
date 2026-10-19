"""Immutable governed-learning records; none carries an automatic promotion path."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import (
    FixedDecimal,
    Identifier,
    Sha256Digest,
    StrictModel,
    require_utc,
)


def _parse_utc(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("learning timestamps must be UTC datetimes")
    return require_utc(value)


class LearningCandidate(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    candidate_id: Identifier
    candidate_type: Literal["PROMPT", "SKILL", "ROUTE", "FEATURE", "STRATEGY"]
    source_manifest_digest: Sha256Digest
    created_at: datetime
    matures_at: datetime

    @field_validator("created_at", "matures_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def requires_horizon(self) -> LearningCandidate:
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

    @field_validator("evaluated_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)


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

    @field_validator("approved_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)


class LearningEvaluationV2(StrictModel):
    schema_version: Literal[2] = 2
    tenant_id: Identifier
    case_id: UUID
    candidate_id: Identifier
    proposal_manifest_digest: Sha256Digest
    evaluation_manifest_digest: Sha256Digest
    evaluator_id: Identifier
    shadow_passed: bool
    canary_passed: bool
    evaluated_at: datetime

    @field_validator("evaluated_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)


class PromotionApprovalV2(StrictModel):
    schema_version: Literal[2] = 2
    tenant_id: Identifier
    case_id: UUID
    candidate_id: Identifier
    proposal_manifest_digest: Sha256Digest
    proposal_digest: Sha256Digest
    evaluation_digest: Sha256Digest
    evaluation_manifest_digest: Sha256Digest
    approver_id: Identifier
    approver_kind: Literal["HUMAN"] = "HUMAN"
    approval_digest: Sha256Digest
    rollback_manifest_digest: Sha256Digest
    approved_at: datetime
    not_before: datetime
    expires_at: datetime

    @field_validator("approved_at", "not_before", "expires_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def validity_window(self) -> PromotionApprovalV2:
        if not self.approved_at <= self.not_before < self.expires_at:
            raise ValueError("promotion approval time window is invalid")
        return self


class LearningAttestationHeader(StrictModel):
    typ: Literal["AQ-LEARNING-ATTESTATION"] = "AQ-LEARNING-ATTESTATION"
    schema_version: Literal[1] = 1
    alg: Literal["Ed25519"] = "Ed25519"
    key_id: Identifier


class SignedLearningEvaluation(StrictModel):
    protected: LearningAttestationHeader
    payload: LearningEvaluationV2
    signature_b64url: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")


class SignedPromotionApproval(StrictModel):
    protected: LearningAttestationHeader
    payload: PromotionApprovalV2
    signature_b64url: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")


class LearningProposalManifest(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    source_case_id: UUID
    candidate_id: Identifier
    candidate_type: Literal["STRATEGY"] = "STRATEGY"
    source_actor_id: Identifier
    independent_evaluator_id: Identifier
    source_outcome_digest: Sha256Digest
    baseline_digest: Sha256Digest
    proposal_digest: Sha256Digest
    evaluation_plan_digest: Sha256Digest
    rollback_manifest_digest: Sha256Digest
    locked_holdout_digest: Sha256Digest
    strategy_parameter: Literal["portfolio_policy.uncertainty_floor"]
    proposed_value: FixedDecimal
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def created_is_utc(cls, value: object) -> datetime:
        return _parse_utc(value)

    @model_validator(mode="after")
    def independent_and_valid(self) -> LearningProposalManifest:
        if self.source_actor_id == self.independent_evaluator_id:
            raise ValueError("learning proposal requires an independent evaluator")
        if self.proposed_value <= Decimal(0):
            raise ValueError("uncertainty floor proposal must be positive")
        return self


class LearningCycleResult(StrictModel):
    schema_version: Literal[1] = 1
    outcome: Literal["ABSTAIN", "CANDIDATE"]
    reason_code: Identifier
    candidate: LearningCandidate | None = None
    proposal: LearningProposalManifest | None = None

    @model_validator(mode="after")
    def candidate_presence_matches_outcome(self) -> LearningCycleResult:
        has_candidate = self.candidate is not None and self.proposal is not None
        if (self.outcome == "CANDIDATE") != has_candidate:
            raise ValueError("learning cycle candidate artifacts do not match its outcome")
        return self
