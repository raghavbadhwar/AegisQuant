"""Governed research lab; candidates never self-promote."""

from .boundaries import CandidateBoundaryError, validate_candidate_target
from .experiments import ExperimentLedger
from .outcomes import OutcomeIntegrityError, OutcomeLedger, build_postmortem
from .promotion import authorize_promotion
from .strategy_evaluation import (
    StrategyEvaluationError,
    StrategyReturnSeries,
    common_sample_hash,
    evaluate_predeclared_strategies,
    strategy_series_hash,
)
from .validation import (
    combinatorial_purged_splits,
    interval_combinatorial_purged_splits,
    interval_purged_walk_forward,
    purged_walk_forward,
    validation_statistics,
)

__all__ = [
    "CandidateBoundaryError",
    "ExperimentLedger",
    "OutcomeIntegrityError",
    "OutcomeLedger",
    "StrategyEvaluationError",
    "StrategyReturnSeries",
    "authorize_promotion",
    "build_postmortem",
    "combinatorial_purged_splits",
    "common_sample_hash",
    "evaluate_predeclared_strategies",
    "interval_combinatorial_purged_splits",
    "interval_purged_walk_forward",
    "purged_walk_forward",
    "strategy_series_hash",
    "validate_candidate_target",
    "validation_statistics",
]
