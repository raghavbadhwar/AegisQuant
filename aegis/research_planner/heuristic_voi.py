"""Deterministic candidate-only value-of-information scoring with no I/O."""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import ResearchAction, ValueOfInformationResult


def score_research_action(action: ResearchAction) -> ValueOfInformationResult:
    """Score a descriptor only; this function never initiates research or any other action."""
    total_cost = action.research_cost + action.latency_cost + action.model_cost
    net_voi = action.expected_information_value - total_cost
    return ValueOfInformationResult(
        action_id=action.action_id,
        expected_information_value=action.expected_information_value,
        research_cost=action.research_cost,
        latency_cost=action.latency_cost,
        model_cost=action.model_cost,
        total_cost=total_cost,
        net_voi=net_voi,
        assumption_ids=action.assumption_ids,
        rank=1,
        stop_research=net_voi <= 0.0,
    )


def rank_research_actions(
    actions: Sequence[ResearchAction],
) -> tuple[ValueOfInformationResult, ...]:
    """Rank candidate descriptors by net VOI, breaking ties lexically by action ID."""
    action_ids = [action.action_id for action in actions]
    if len(action_ids) != len(set(action_ids)):
        raise ValueError("research action IDs must be unique")
    scored = sorted(
        (score_research_action(action) for action in actions),
        key=lambda result: (-result.net_voi, result.action_id),
    )
    stop_research = not scored or scored[0].net_voi <= 0.0
    return tuple(
        result.model_copy(update={"rank": rank, "stop_research": stop_research})
        for rank, result in enumerate(scored, start=1)
    )


def should_stop_research(results: Sequence[ValueOfInformationResult]) -> bool:
    """Stop when no ranked candidate has strictly positive net value of information."""
    return not results or max(result.net_voi for result in results) <= 0.0
