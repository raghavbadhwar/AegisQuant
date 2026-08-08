"""Point-in-time governed memory contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from ._base import ContractModel

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
