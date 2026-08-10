"""Bounded candidate-only Monte Carlo VOI and no-I/O research stopping."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from statistics import fmean

from pydantic import ConfigDict, Field, model_validator

from aegis.contracts import canonical_sha256
from aegis.contracts._base import CandidateContractModel

from .contracts import ResearchAction


class ResearchStopReason(StrEnum):
    """Explicit reasons the candidate planner takes no further research action."""

    NON_POSITIVE_VOI = "non_positive_voi"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_REACHED = "deadline_reached"
    DECISION_ROBUST = "decision_robust"
    NON_DECISION_CHANGING_UNCERTAINTY = "non_decision_changing_uncertainty"


class MonteCarloVOISample(CandidateContractModel):
    """One supplied candidate simulation draw for the value of an information action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)
    sample_index: int = Field(ge=0)
    current_utility: float
    utility_after_information: float
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_finite_candidate_utilities(self) -> MonteCarloVOISample:
        if not isfinite(self.current_utility) or not isfinite(self.utility_after_information):
            raise ValueError("Monte Carlo VOI sample utilities must be finite")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("Monte Carlo VOI sample content hash mismatch")
        return self

    def sealed(self) -> MonteCarloVOISample:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MonteCarloVOISample.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class MonteCarloVOIResult(CandidateContractModel):
    """Sealed candidate VOI estimate; it cannot perform, approve, or send research."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: ResearchAction
    samples: tuple[MonteCarloVOISample, ...] = Field(min_length=1)
    expected_information_value: float
    total_cost: float = Field(ge=0.0)
    net_voi: float
    authority: str = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_computed_from_one_sealed_action_and_samples(self) -> MonteCarloVOIResult:
        action = ResearchAction.model_validate(self.action.model_dump(mode="json"))
        samples = tuple(
            MonteCarloVOISample.model_validate(sample.model_dump(mode="json"))
            for sample in self.samples
        )
        if action.content_hash is None or any(sample.content_hash is None for sample in samples):
            raise ValueError("Monte Carlo VOI result requires sealed action and samples")
        if self.authority != "candidate_only":
            raise ValueError("Monte Carlo VOI result cannot gain authority")
        if any(sample.action_id != action.action_id for sample in samples):
            raise ValueError("Monte Carlo VOI samples must match the action")
        if [sample.sample_index for sample in samples] != list(range(len(samples))):
            raise ValueError("Monte Carlo VOI samples must have contiguous indexes")
        information_value = fmean(
            sample.utility_after_information - sample.current_utility for sample in samples
        )
        total_cost = action.research_cost + action.latency_cost + action.model_cost
        if self.expected_information_value != information_value:
            raise ValueError("Monte Carlo VOI information value must match its samples")
        if self.total_cost != total_cost:
            raise ValueError("Monte Carlo VOI total cost must match its action")
        if self.net_voi != information_value - total_cost:
            raise ValueError("Monte Carlo VOI net value must reconcile")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("Monte Carlo VOI result content hash mismatch")
        return self

    def sealed(self) -> MonteCarloVOIResult:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = MonteCarloVOIResult.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class ResearchLoopConstraints(CandidateContractModel):
    """Pure planner bounds; they contain no research executor or external capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    remaining_budget: float = Field(ge=0.0)
    deadline_reached: bool
    decision_robust: bool
    uncertainty_can_change_decision: bool
    authority: str = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_finite_candidate_only_and_content_addressed(self) -> ResearchLoopConstraints:
        if not isfinite(self.remaining_budget):
            raise ValueError("research loop budget must be finite")
        if self.authority != "candidate_only":
            raise ValueError("research loop constraints cannot gain authority")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("research loop constraints content hash mismatch")
        return self

    def sealed(self) -> ResearchLoopConstraints:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ResearchLoopConstraints.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def _expected_decision(
    results: tuple[MonteCarloVOIResult, ...], constraints: ResearchLoopConstraints
) -> tuple[str | None, ResearchStopReason | None]:
    reason = _stop_reason(results, constraints)
    if reason is not None:
        return None, reason
    eligible = sorted(
        (
            result
            for result in results
            if result.net_voi > 0.0 and result.total_cost <= constraints.remaining_budget
        ),
        key=lambda result: (-result.net_voi, result.action.action_id),
    )
    if not eligible:
        return None, ResearchStopReason.BUDGET_EXHAUSTED
    return eligible[0].action.action_id, None


class ResearchLoopDecision(CandidateContractModel):
    """A read-only candidate selection or explicit stop; it never initiates research."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    voi_results: tuple[MonteCarloVOIResult, ...]
    constraints: ResearchLoopConstraints
    selected_action_id: str | None = Field(default=None, min_length=1)
    stop_reason: ResearchStopReason | None = None
    authority: str = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def is_bound_to_sealed_inputs_and_nonexecuting(self) -> ResearchLoopDecision:
        results = tuple(
            MonteCarloVOIResult.model_validate(result.model_dump(mode="json"))
            for result in self.voi_results
        )
        constraints = ResearchLoopConstraints.model_validate(
            self.constraints.model_dump(mode="json")
        )
        if constraints.content_hash is None or any(
            result.content_hash is None for result in results
        ):
            raise ValueError("research loop decision requires sealed constraints and VOI results")
        if self.authority != "candidate_only":
            raise ValueError("research loop decision cannot gain authority")
        action_ids = [result.action.action_id for result in results]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("research loop action IDs must be unique")
        if (self.selected_action_id is None) == (self.stop_reason is None):
            raise ValueError("research loop decision requires exactly one selection or stop reason")
        expected_action_id, expected_stop_reason = _expected_decision(results, constraints)
        if (
            self.selected_action_id != expected_action_id
            or self.stop_reason != expected_stop_reason
        ):
            raise ValueError("research loop decision does not match its bounded inputs")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("research loop decision content hash mismatch")
        return self

    def sealed(self) -> ResearchLoopDecision:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = ResearchLoopDecision.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def estimate_monte_carlo_voi(
    action: ResearchAction, samples: tuple[MonteCarloVOISample, ...]
) -> MonteCarloVOIResult:
    """Estimate no-I/O candidate VOI from supplied sealed simulation outcomes."""
    validated_action = ResearchAction.model_validate(action.model_dump(mode="json"))
    validated_samples = tuple(
        MonteCarloVOISample.model_validate(sample.model_dump(mode="json")) for sample in samples
    )
    if validated_action.content_hash is None or any(
        sample.content_hash is None for sample in validated_samples
    ):
        raise ValueError("Monte Carlo VOI estimator requires sealed action and samples")
    information_value = fmean(
        sample.utility_after_information - sample.current_utility for sample in validated_samples
    )
    total_cost = (
        validated_action.research_cost + validated_action.latency_cost + validated_action.model_cost
    )
    return MonteCarloVOIResult(
        action=validated_action,
        samples=validated_samples,
        expected_information_value=information_value,
        total_cost=total_cost,
        net_voi=information_value - total_cost,
    ).sealed()


def plan_bounded_research(
    results: tuple[MonteCarloVOIResult, ...], constraints: ResearchLoopConstraints
) -> ResearchLoopDecision:
    """Select one candidate descriptor or explain why no research is warranted; no I/O occurs."""
    validated_results = tuple(
        MonteCarloVOIResult.model_validate(result.model_dump(mode="json")) for result in results
    )
    validated_constraints = ResearchLoopConstraints.model_validate(
        constraints.model_dump(mode="json")
    )
    if validated_constraints.content_hash is None or any(
        result.content_hash is None for result in validated_results
    ):
        raise ValueError("bounded research loop requires sealed inputs")
    action_id, stop_reason = _expected_decision(validated_results, validated_constraints)
    return ResearchLoopDecision(
        voi_results=validated_results,
        constraints=validated_constraints,
        selected_action_id=action_id,
        stop_reason=stop_reason,
    ).sealed()


def _stop_reason(
    results: tuple[MonteCarloVOIResult, ...], constraints: ResearchLoopConstraints
) -> ResearchStopReason | None:
    if constraints.deadline_reached:
        return ResearchStopReason.DEADLINE_REACHED
    if constraints.remaining_budget <= 0.0:
        return ResearchStopReason.BUDGET_EXHAUSTED
    if constraints.decision_robust:
        return ResearchStopReason.DECISION_ROBUST
    if not constraints.uncertainty_can_change_decision:
        return ResearchStopReason.NON_DECISION_CHANGING_UNCERTAINTY
    if not results or max(result.net_voi for result in results) <= 0.0:
        return ResearchStopReason.NON_POSITIVE_VOI
    return None
