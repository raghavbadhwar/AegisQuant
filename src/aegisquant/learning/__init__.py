"""Governed-learning helpers with approval-only promotion records."""

from aegisquant.learning.governance import (
    approve_candidate,
    approve_candidate_v2,
    evaluate_candidate,
    evaluate_candidate_v2,
)
from aegisquant.learning.loop import (
    apply_approved_strategy_candidate,
    propose_candidate,
    verify_approved_candidate,
    verify_learning_records,
)

__all__ = [
    "apply_approved_strategy_candidate",
    "approve_candidate",
    "approve_candidate_v2",
    "evaluate_candidate",
    "evaluate_candidate_v2",
    "propose_candidate",
    "verify_approved_candidate",
    "verify_learning_records",
]
