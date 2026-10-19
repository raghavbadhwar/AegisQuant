"""Point-in-time governed memory contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from ._base import ContractModel
from .artifacts import canonical_sha256

MemoryStatus = Literal["candidate", "approved", "quarantined", "retired"]


class MemoryItem(ContractModel):
    memory_id: Annotated[str, Field(min_length=1)]
    memory_type: Annotated[str, Field(min_length=1)]
    title: Annotated[str, Field(min_length=1)]
    statement: Annotated[str, Field(min_length=1)]
    evidence_ids: list[str] = Field(min_length=1)
    source_case_ids: list[str] = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    strategy_ids: list[str] = Field(default_factory=list)
    regime_ids: list[str] = Field(default_factory=list)
    scope: Literal["case", "entity", "strategy", "project", "global"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    utility_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    available_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    supersedes: list[str] = Field(default_factory=list)
    contradicted_by: list[str] = Field(default_factory=list)
    status: MemoryStatus
    version: int = Field(gt=0)

    @model_validator(mode="after")
    def expiry_follows_availability(self) -> MemoryItem:
        if self.expires_at is not None and self.expires_at <= self.available_at:
            raise ValueError("expires_at must be after available_at")
        return self


class MemoryQuery(ContractModel):
    text: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    entity_ids: list[str] = Field(default_factory=list)
    strategy_ids: list[str] = Field(default_factory=list)
    regime_ids: list[str] = Field(default_factory=list)
    memory_types: list[str] = Field(default_factory=list)
    top_k: int = Field(gt=0, le=100)


class MemoryHit(ContractModel):
    item: MemoryItem
    score: float = Field(ge=0, allow_inf_nan=False)
    reasons: list[str] = Field(default_factory=list)


class MemoryCandidate(ContractModel):
    candidate_id: Annotated[str, Field(min_length=1)]
    memory_id: Annotated[str, Field(min_length=1)]
    proposer_id: Annotated[str, Field(min_length=1)]
    memory_type: Annotated[str, Field(min_length=1)]
    title: Annotated[str, Field(min_length=1)]
    statement: Annotated[str, Field(min_length=1)]
    evidence_ids: list[str] = Field(min_length=1)
    source_case_ids: list[str] = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list)
    strategy_ids: list[str] = Field(default_factory=list)
    regime_ids: list[str] = Field(default_factory=list)
    scope: Literal["case", "entity", "strategy", "project", "global"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    utility_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    created_at: AwareDatetime
    expires_at: AwareDatetime
    review_by: AwareDatetime
    supersedes: list[str] = Field(default_factory=list)
    contradicted_by: list[str] = Field(default_factory=list)
    duplicate_of: str | None = None
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    def hash_payload(self) -> dict[str, object]:
        return self.model_dump(exclude={"content_hash"})

    @model_validator(mode="after")
    def candidate_is_causal_and_hashed(self) -> MemoryCandidate:
        if self.review_by <= self.created_at:
            raise ValueError("review_by must follow candidate creation")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("candidate expiry must follow creation")
        if self.content_hash != canonical_sha256(self.hash_payload()):
            raise ValueError("memory candidate hash mismatch")
        return self


class MemoryGovernanceDecision(ContractModel):
    decision_id: Annotated[str, Field(min_length=1)]
    candidate_id: Annotated[str, Field(min_length=1)]
    candidate_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    evaluator_id: Annotated[str, Field(min_length=1)]
    decision: Literal["approve", "quarantine", "reject"]
    reason: Annotated[str, Field(min_length=1)]
    decided_at: AwareDatetime
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    def hash_payload(self) -> dict[str, object]:
        return self.model_dump(exclude={"content_hash"})

    @model_validator(mode="after")
    def decision_hash_matches(self) -> MemoryGovernanceDecision:
        if self.content_hash != canonical_sha256(self.hash_payload()):
            raise ValueError("memory governance decision hash mismatch")
        return self


class MemorySnapshotEntry(ContractModel):
    memory_id: Annotated[str, Field(min_length=1)]
    version: int = Field(gt=0)
    available_at: AwareDatetime


class MemorySnapshot(ContractModel):
    as_of: AwareDatetime
    entries: list[MemorySnapshotEntry] = Field(default_factory=list)
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def snapshot_hash_matches(self) -> MemorySnapshot:
        if self.content_hash != canonical_sha256({"as_of": self.as_of, "entries": self.entries}):
            raise ValueError("memory snapshot hash mismatch")
        return self


class TypedRelation(ContractModel):
    relation_id: Annotated[str, Field(min_length=1)]
    source_id: Annotated[str, Field(min_length=1)]
    relation_type: Annotated[str, Field(min_length=1)]
    target_id: Annotated[str, Field(min_length=1)]
    evidence_ids: list[str] = Field(min_length=1)
    available_at: AwareDatetime
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    status: Literal["candidate", "approved", "quarantined", "retired"]
