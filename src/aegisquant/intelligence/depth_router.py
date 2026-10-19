"""Deterministic adaptive research-depth router."""

from decimal import Decimal

from pydantic import Field

from aegisquant.contracts.case import ResearchMode
from aegisquant.contracts.common import FixedDecimal, StrictModel

_DEPTH = {
    ResearchMode.SCREEN: 0,
    ResearchMode.STANDARD: 1,
    ResearchMode.DEEP: 2,
    ResearchMode.EXCEPTIONAL: 3,
}
_BY_DEPTH = {value: key for key, value in _DEPTH.items()}


class DepthRoutingInput(StrictModel):
    requested_mode: ResearchMode
    evidence_completeness: FixedDecimal
    specialist_disagreement: FixedDecimal
    uncertainty: FixedDecimal
    novelty: FixedDecimal
    potential_capital_impact: FixedDecimal
    risk_gate_requested_deepening: bool = False
    instrument_count: int = Field(ge=1, le=10000)


class DepthRoutingDecision(StrictModel):
    selected_mode: ResearchMode
    reason_codes: tuple[str, ...]


def route_depth(request: DepthRoutingInput) -> DepthRoutingDecision:
    selected = _DEPTH[request.requested_mode]
    reasons = [f"REQUESTED_{request.requested_mode.value.upper()}"]
    metrics = (
        ("INCOMPLETE_EVIDENCE", Decimal(1) - request.evidence_completeness),
        ("HIGH_DISAGREEMENT", request.specialist_disagreement),
        ("HIGH_UNCERTAINTY", request.uncertainty),
        ("NOVEL_EVENT", request.novelty),
        ("MATERIAL_CAPITAL_IMPACT", request.potential_capital_impact),
    )
    if any(value >= Decimal("0.70") for _, value in metrics):
        selected = max(selected, 2)
        reasons.extend(name for name, value in metrics if value >= Decimal("0.70"))
    if request.risk_gate_requested_deepening:
        selected = max(selected, 2)
        reasons.append("RISK_GATE_REQUEST")
    if request.novelty >= Decimal("0.90") and request.potential_capital_impact >= Decimal("0.90"):
        selected = 3
        reasons.append("EXCEPTIONAL_NOVELTY_AND_IMPACT")
    if request.instrument_count >= 1000 and selected == 0:
        reasons.append("BULK_DETERMINISTIC_SCREEN")
    return DepthRoutingDecision(
        selected_mode=_BY_DEPTH[selected], reason_codes=tuple(dict.fromkeys(reasons))
    )
