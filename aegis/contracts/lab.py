"""Research-lab, outcome, validation, shadow, and promotion contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from ._base import ContractModel
from .artifacts import canonical_sha256


class OutcomeRecord(ContractModel):
    outcome_id: Annotated[str, Field(min_length=1)]
    case_id: Annotated[str, Field(min_length=1)]
    forecast_id: Annotated[str, Field(min_length=1)]
    ticker: Annotated[str, Field(min_length=1)]
    horizon_end: AwareDatetime
    realized_excess_return: float = Field(allow_inf_nan=False)
    forecast_error: float = Field(allow_inf_nan=False)
    costs: float = Field(ge=0, allow_inf_nan=False)
    available_at: AwareDatetime


class PostmortemReport(ContractModel):
    report_id: Annotated[str, Field(min_length=1)]
    outcome_ids: list[str] = Field(min_length=1)
    diagnosis: Annotated[str, Field(min_length=1)]
    attribution: dict[str, float] = Field(default_factory=dict)
    candidate_ids: list[str] = Field(default_factory=list)
    produced_at: AwareDatetime
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def hash_matches(self) -> PostmortemReport:
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("postmortem hash mismatch")
        return self


class HypothesisDeclaration(ContractModel):
    hypothesis_id: Annotated[str, Field(min_length=1)]
    candidate_id: Annotated[str, Field(min_length=1)]
    statement: Annotated[str, Field(min_length=1)]
    primary_metric: Annotated[str, Field(min_length=1)]
    minimum_delta: float = Field(allow_inf_nan=False)
    baseline_id: Annotated[str, Field(min_length=1)]
    declared_at: AwareDatetime
    declared_by: Annotated[str, Field(min_length=1)]


class CandidatePatchMetadata(ContractModel):
    candidate_id: Annotated[str, Field(min_length=1)]
    target_path: Annotated[str, Field(min_length=1)]
    base_revision: Annotated[str, Field(min_length=1)]
    base_tree_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    patch_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    candidate_tree_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


ValidationStage = Literal[
    "preflight",
    "replay",
    "historical_dev",
    "holdback",
    "purged_cv",
    "overfitting",
    "cost_stress",
    "shadow",
]


class HoldoutUnlock(ContractModel):
    unlock_id: Annotated[str, Field(min_length=1)]
    suite_id: Annotated[str, Field(min_length=1)]
    human_approver_id: Annotated[str, Field(min_length=1)]
    reason: Annotated[str, Field(min_length=1)]
    unlocked_at: AwareDatetime
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def unlock_hash_matches(self) -> HoldoutUnlock:
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("holdout unlock hash mismatch")
        return self


class ValidationReport(ContractModel):
    report_id: Annotated[str, Field(min_length=1)]
    candidate_id: Annotated[str, Field(min_length=1)]
    candidate_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    evaluator_id: Annotated[str, Field(min_length=1)]
    stages: list[ValidationStage] = Field(min_length=1)
    stage_passes: dict[str, bool]
    metrics: dict[str, float] = Field(default_factory=dict)
    baseline_metrics: dict[str, float] = Field(default_factory=dict)
    ablation_metrics: dict[str, float] = Field(default_factory=dict)
    trial_count: int = Field(gt=0)
    holdout_unlock_id: str | None = None
    passed: bool
    evaluated_at: AwareDatetime
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def report_is_complete_and_hashed(self) -> ValidationReport:
        required_stages = {
            "preflight",
            "replay",
            "historical_dev",
            "holdback",
            "purged_cv",
            "overfitting",
            "cost_stress",
            "shadow",
        }
        required_metrics = {"pbo", "psr", "dsr", "turnover", "capacity", "costs", "max_drawdown"}
        if self.passed and (
            set(self.stages) != required_stages
            or not all(self.stage_passes.get(stage, False) for stage in self.stages)
            or not required_metrics.issubset(self.metrics)
            or not self.baseline_metrics
            or not self.ablation_metrics
            or self.holdout_unlock_id is None
        ):
            raise ValueError("passed report is missing mandatory validation evidence")
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("validation report hash mismatch")
        return self


class ExperimentRecord(ContractModel):
    experiment_id: Annotated[str, Field(min_length=1)]
    candidate_id: Annotated[str, Field(min_length=1)]
    hypothesis_id: Annotated[str, Field(min_length=1)]
    parent_experiment_id: str | None = None
    code_revision: Annotated[str, Field(min_length=1)]
    tree_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    data_snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    parameters: dict[str, Any] = Field(default_factory=dict)
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    trial_number: int = Field(gt=0)
    status: Literal["declared", "running", "passed", "failed", "rejected"]
    created_at: AwareDatetime
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def record_hash_matches(self) -> ExperimentRecord:
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("experiment record hash mismatch")
        return self


class ShadowResult(ContractModel):
    shadow_id: Annotated[str, Field(min_length=1)]
    candidate_id: Annotated[str, Field(min_length=1)]
    baseline_run_ids: list[str] = Field(min_length=1)
    candidate_run_ids: list[str] = Field(min_length=1)
    metrics: dict[str, float]
    passed: bool
    completed_at: AwareDatetime
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PromotionDecision(ContractModel):
    promotion_id: Annotated[str, Field(min_length=1)]
    candidate_id: Annotated[str, Field(min_length=1)]
    candidate_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    validation_report_id: Annotated[str, Field(min_length=1)]
    validation_report_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    evaluator_id: Annotated[str, Field(min_length=1)]
    human_approver_id: Annotated[str, Field(min_length=1)]
    decision: Literal["promote", "reject"]
    reason: Annotated[str, Field(min_length=1)]
    decided_at: AwareDatetime
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def decision_hash_matches(self) -> PromotionDecision:
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("promotion decision hash mismatch")
        return self
