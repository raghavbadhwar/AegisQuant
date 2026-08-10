"""Candidate-only, side-effect-free research planning contracts and heuristics."""

from .contracts import ResearchAction, ValueOfInformationResult
from .heuristic_voi import rank_research_actions, score_research_action, should_stop_research
from .monte_carlo import (
    MonteCarloVOIResult,
    MonteCarloVOISample,
    ResearchLoopConstraints,
    ResearchLoopDecision,
    ResearchStopReason,
    estimate_monte_carlo_voi,
    plan_bounded_research,
)

__all__ = [
    "MonteCarloVOIResult",
    "MonteCarloVOISample",
    "ResearchAction",
    "ResearchLoopConstraints",
    "ResearchLoopDecision",
    "ResearchStopReason",
    "ValueOfInformationResult",
    "estimate_monte_carlo_voi",
    "plan_bounded_research",
    "rank_research_actions",
    "score_research_action",
    "should_stop_research",
]
