import pytest

from aegis.research_planner import (
    MonteCarloVOISample,
    ResearchAction,
    ResearchLoopConstraints,
    ResearchLoopDecision,
    ResearchStopReason,
    estimate_monte_carlo_voi,
    plan_bounded_research,
)


def _action() -> ResearchAction:
    return ResearchAction(
        action_id="inspect-capacity-guidance",
        question_id="supplier-capacity",
        expected_information_value=0.0,
        research_cost=2.0,
        latency_cost=1.0,
        model_cost=1.0,
        assumption_ids=("candidate-utility",),
    ).sealed()


def test_monte_carlo_voi_is_computed_and_the_loop_selects_no_action_when_robust() -> None:
    action = _action()
    result = estimate_monte_carlo_voi(
        action,
        (
            MonteCarloVOISample(
                action_id=action.action_id,
                sample_index=0,
                current_utility=1.0,
                utility_after_information=11.0,
            ).sealed(),
            MonteCarloVOISample(
                action_id=action.action_id,
                sample_index=1,
                current_utility=2.0,
                utility_after_information=8.0,
            ).sealed(),
        ),
    )

    selected = plan_bounded_research(
        (result,),
        ResearchLoopConstraints(
            remaining_budget=10.0,
            deadline_reached=False,
            decision_robust=False,
            uncertainty_can_change_decision=True,
        ).sealed(),
    )
    stopped = plan_bounded_research(
        (result,),
        ResearchLoopConstraints(
            remaining_budget=10.0,
            deadline_reached=False,
            decision_robust=True,
            uncertainty_can_change_decision=True,
        ).sealed(),
    )

    assert result.expected_information_value == 8.0
    assert result.net_voi == 4.0
    assert selected.selected_action_id == action.action_id
    assert selected.stop_reason is None
    assert stopped.stop_reason == ResearchStopReason.DECISION_ROBUST


@pytest.mark.parametrize(
    ("constraints", "reason"),
    (
        (
            {
                "remaining_budget": 0.0,
                "deadline_reached": False,
                "decision_robust": False,
                "uncertainty_can_change_decision": True,
            },
            ResearchStopReason.BUDGET_EXHAUSTED,
        ),
        (
            {
                "remaining_budget": 10.0,
                "deadline_reached": True,
                "decision_robust": False,
                "uncertainty_can_change_decision": True,
            },
            ResearchStopReason.DEADLINE_REACHED,
        ),
        (
            {
                "remaining_budget": 10.0,
                "deadline_reached": False,
                "decision_robust": False,
                "uncertainty_can_change_decision": False,
            },
            ResearchStopReason.NON_DECISION_CHANGING_UNCERTAINTY,
        ),
    ),
)
def test_research_loop_exposes_required_non_execution_stop_reasons(
    constraints: dict[str, object], reason: ResearchStopReason
) -> None:
    action = _action()
    result = estimate_monte_carlo_voi(
        action,
        (
            MonteCarloVOISample(
                action_id=action.action_id,
                sample_index=0,
                current_utility=0.0,
                utility_after_information=10.0,
            ).sealed(),
        ),
    )

    decision = plan_bounded_research((result,), ResearchLoopConstraints(**constraints).sealed())

    assert decision.selected_action_id is None
    assert decision.stop_reason == reason


def test_research_loop_stops_for_non_positive_monte_carlo_voi() -> None:
    action = _action()
    result = estimate_monte_carlo_voi(
        action,
        (
            MonteCarloVOISample(
                action_id=action.action_id,
                sample_index=0,
                current_utility=1.0,
                utility_after_information=1.0,
            ).sealed(),
        ),
    )

    decision = plan_bounded_research(
        (result,),
        ResearchLoopConstraints(
            remaining_budget=10.0,
            deadline_reached=False,
            decision_robust=False,
            uncertainty_can_change_decision=True,
        ).sealed(),
    )

    assert decision.stop_reason == ResearchStopReason.NON_POSITIVE_VOI


def test_research_loop_decision_rejects_a_direct_selection_when_a_stop_applies() -> None:
    action = _action()
    result = estimate_monte_carlo_voi(
        action,
        (
            MonteCarloVOISample(
                action_id=action.action_id,
                sample_index=0,
                current_utility=0.0,
                utility_after_information=10.0,
            ).sealed(),
        ),
    )
    constraints = ResearchLoopConstraints(
        remaining_budget=2.0,
        deadline_reached=True,
        decision_robust=True,
        uncertainty_can_change_decision=False,
    ).sealed()

    with pytest.raises(ValueError, match="bounded inputs"):
        ResearchLoopDecision(
            voi_results=(result,),
            constraints=constraints,
            selected_action_id=action.action_id,
        ).sealed()


def test_research_loop_uses_reconciled_total_cost_for_the_budget_stop() -> None:
    action = _action()
    result = estimate_monte_carlo_voi(
        action,
        (
            MonteCarloVOISample(
                action_id=action.action_id,
                sample_index=0,
                current_utility=0.0,
                utility_after_information=10.0,
            ).sealed(),
        ),
    )

    decision = plan_bounded_research(
        (result,),
        ResearchLoopConstraints(
            remaining_budget=3.0,
            deadline_reached=False,
            decision_robust=False,
            uncertainty_can_change_decision=True,
        ).sealed(),
    )

    assert decision.selected_action_id is None
    assert decision.stop_reason == ResearchStopReason.BUDGET_EXHAUSTED
