"""Governed self-improvement candidate contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ._base import ContractModel

CandidateType = Literal[
    "memory", "skill", "prompt", "model_route", "source_route", "feature", "strategy"
]
EvaluationStatus = Literal["candidate_only", "evaluating", "shadow", "rejected"]


class LearningCandidate(ContractModel):
    """A proposal that cannot promote itself by construction."""

    candidate_id: Annotated[str, Field(min_length=1)]
    candidate_type: CandidateType
    target_id: str | None = None
    proposed_patch: Annotated[str, Field(min_length=1)]
    trigger_case_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    diagnosis: Annotated[str, Field(min_length=1)]
    expected_improvement: Annotated[str, Field(min_length=1)]
    falsifiable_metric: Annotated[str, Field(min_length=1)]
    minimum_required_delta: float = Field(allow_inf_nan=False)
    applicable_entities: list[str] = Field(default_factory=list)
    applicable_strategies: list[str] = Field(default_factory=list)
    applicable_regimes: list[str] = Field(default_factory=list)
    risk_class: Literal["low", "medium", "high", "critical"]
    evaluation_suite_id: Annotated[str, Field(min_length=1)]
    proposer_model: Annotated[str, Field(min_length=1)]
    proposer_id: Annotated[str, Field(min_length=1)]
    status: EvaluationStatus = "candidate_only"
