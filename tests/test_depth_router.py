from aegisquant.contracts.case import ResearchMode
from aegisquant.intelligence.depth_router import DepthRoutingInput, route_depth


def test_router_uses_smallest_requested_team_when_confident() -> None:
    decision = route_depth(
        DepthRoutingInput(
            requested_mode=ResearchMode.STANDARD,
            evidence_completeness="0.95",
            specialist_disagreement="0.1",
            uncertainty="0.1",
            novelty="0.1",
            potential_capital_impact="0.1",
            instrument_count=1,
        )
    )
    assert decision.selected_mode == "standard"


def test_router_escalates_novel_material_case_to_exceptional() -> None:
    decision = route_depth(
        DepthRoutingInput(
            requested_mode=ResearchMode.STANDARD,
            evidence_completeness="0.9",
            specialist_disagreement="0.2",
            uncertainty="0.4",
            novelty="0.95",
            potential_capital_impact="0.95",
            instrument_count=1,
        )
    )
    assert decision.selected_mode == "exceptional"
