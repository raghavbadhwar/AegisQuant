"""Governed research lab; candidates never self-promote."""

from .boundaries import CandidateBoundaryError, validate_candidate_target
from .experiments import ExperimentLedger
from .outcomes import OutcomeIntegrityError, OutcomeLedger, build_postmortem
from .promotion import authorize_promotion
from .receipt_series import (
    ReceiptReturnObservation,
    ReceiptSeriesError,
    derive_receipt_observations,
    derive_receipt_observations_from_ledger,
    receipt_series_hash,
)
from .strategy_evaluation import (
    StrategyEvaluationError,
    StrategyReturnSeries,
    common_sample_hash,
    evaluate_predeclared_strategies,
    strategy_series_from_receipts,
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
    "ReceiptReturnObservation",
    "ReceiptSeriesError",
    "StrategyEvaluationError",
    "StrategyReturnSeries",
    "authorize_promotion",
    "build_postmortem",
    "combinatorial_purged_splits",
    "common_sample_hash",
    "derive_receipt_observations",
    "derive_receipt_observations_from_ledger",
    "evaluate_predeclared_strategies",
    "interval_combinatorial_purged_splits",
    "interval_purged_walk_forward",
    "purged_walk_forward",
    "receipt_series_hash",
    "strategy_series_from_receipts",
    "strategy_series_hash",
    "validate_candidate_target",
    "validation_statistics",
]
