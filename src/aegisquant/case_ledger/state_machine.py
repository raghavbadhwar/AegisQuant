"""Deterministic case-state transition policy."""

from aegisquant.contracts.case import CaseStatus


class InvalidCaseTransition(ValueError):
    pass


_ALLOWED: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.CASE_CREATED: frozenset({CaseStatus.MANDATE_VALIDATED}),
    CaseStatus.MANDATE_VALIDATED: frozenset({CaseStatus.DATA_SNAPSHOT_FROZEN}),
    CaseStatus.DATA_SNAPSHOT_FROZEN: frozenset({CaseStatus.RESEARCH_DEPTH_SELECTED}),
    CaseStatus.RESEARCH_DEPTH_SELECTED: frozenset({CaseStatus.RESEARCH_PLANNED}),
    CaseStatus.RESEARCH_PLANNED: frozenset({CaseStatus.SPECIALISTS_DISPATCHED}),
    CaseStatus.SPECIALISTS_DISPATCHED: frozenset({CaseStatus.EVIDENCE_AUDITED}),
    CaseStatus.EVIDENCE_AUDITED: frozenset({CaseStatus.FORECAST_PROPOSED}),
    CaseStatus.FORECAST_PROPOSED: frozenset({CaseStatus.FORECAST_VERIFIED}),
    CaseStatus.FORECAST_VERIFIED: frozenset({CaseStatus.STRATEGY_VALIDATED}),
    CaseStatus.STRATEGY_VALIDATED: frozenset({CaseStatus.PORTFOLIO_OPTIMIZED}),
    CaseStatus.PORTFOLIO_OPTIMIZED: frozenset({CaseStatus.RISK_APPROVED}),
    CaseStatus.RISK_APPROVED: frozenset({CaseStatus.HUMAN_APPROVED, CaseStatus.AUTO_APPROVED}),
    CaseStatus.HUMAN_APPROVED: frozenset({CaseStatus.EXECUTION_RELEASED}),
    CaseStatus.AUTO_APPROVED: frozenset({CaseStatus.EXECUTION_RELEASED}),
    CaseStatus.EXECUTION_RELEASED: frozenset({CaseStatus.RECONCILED}),
    CaseStatus.RECONCILED: frozenset({CaseStatus.OUTCOME_MATURED}),
    CaseStatus.OUTCOME_MATURED: frozenset({CaseStatus.LEARNING_REVIEWED}),
    CaseStatus.LEARNING_REVIEWED: frozenset(),
}


def validate_transition(current: CaseStatus, target: CaseStatus) -> None:
    if target not in _ALLOWED[current]:
        raise InvalidCaseTransition(f"illegal case transition: {current} -> {target}")
