"""Governed research lab; candidates never self-promote."""

from .boundaries import CandidateBoundaryError, validate_candidate_target
from .experiments import ExperimentLedger
from .outcomes import OutcomeIntegrityError, OutcomeLedger, build_postmortem
from .promotion import authorize_promotion
from .validation import combinatorial_purged_splits, purged_walk_forward, validation_statistics

__all__ = [
    "CandidateBoundaryError",
    "ExperimentLedger",
    "OutcomeIntegrityError",
    "OutcomeLedger",
    "authorize_promotion",
    "build_postmortem",
    "combinatorial_purged_splits",
    "purged_walk_forward",
    "validate_candidate_target",
    "validation_statistics",
]
