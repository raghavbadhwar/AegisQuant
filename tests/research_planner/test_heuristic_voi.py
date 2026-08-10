import pytest
from pydantic import ValidationError

from aegis.research_planner import ResearchAction
from aegis.research_planner.heuristic_voi import rank_research_actions, should_stop_research


def test_ranker_returns_candidate_only_net_voi_with_explicit_assumptions() -> None:
    action = ResearchAction(
        action_id="filing-gap",
        question_id="revenue-guidance",
        expected_information_value=10.0,
        research_cost=2.0,
        latency_cost=1.0,
        model_cost=1.0,
        assumption_ids=("assumption-1",),
    )

    result = rank_research_actions((action,))[0]

    assert result.action_id == "filing-gap"
    assert result.total_cost == 4.0
    assert result.net_voi == 6.0
    assert result.assumption_ids == ("assumption-1",)
    assert result.authority == "candidate_only"


def test_ranker_uses_latency_and_model_costs_with_deterministic_tie_breaking() -> None:
    higher_cost = ResearchAction(
        action_id="z-high-cost",
        question_id="guidance",
        expected_information_value=10.0,
        research_cost=1.0,
        latency_cost=3.0,
        model_cost=2.0,
        assumption_ids=("assumption-high",),
    )
    tie_break_first = ResearchAction(
        action_id="a-tie-break-first",
        question_id="guidance",
        expected_information_value=10.0,
        research_cost=1.0,
        latency_cost=2.0,
        model_cost=2.0,
        assumption_ids=("assumption-a",),
    )
    tie_break_second = ResearchAction(
        action_id="b-tie-break-second",
        question_id="guidance",
        expected_information_value=10.0,
        research_cost=1.0,
        latency_cost=2.0,
        model_cost=2.0,
        assumption_ids=("assumption-b",),
    )

    ranked = rank_research_actions((higher_cost, tie_break_second, tie_break_first))

    assert [result.action_id for result in ranked] == [
        "a-tie-break-first",
        "b-tie-break-second",
        "z-high-cost",
    ]
    assert [result.net_voi for result in ranked] == [5.0, 5.0, 4.0]
    assert [result.rank for result in ranked] == [1, 2, 3]


def test_stop_rule_stops_when_best_net_voi_is_not_positive() -> None:
    no_value = ResearchAction(
        action_id="no-value",
        question_id="guidance",
        expected_information_value=3.0,
        research_cost=1.0,
        latency_cost=1.0,
        model_cost=1.0,
        assumption_ids=("assumption-1",),
    )

    ranked = rank_research_actions((no_value,))

    assert ranked[0].stop_research is True
    assert should_stop_research(ranked) is True
    assert should_stop_research(()) is True


def test_voi_contracts_are_frozen_and_forbid_extra_fields() -> None:
    action = ResearchAction(
        action_id="frozen",
        question_id="guidance",
        expected_information_value=1.0,
        research_cost=0.0,
        latency_cost=0.0,
        model_cost=0.0,
        assumption_ids=("assumption-1",),
    )

    with pytest.raises(ValidationError):
        ResearchAction.model_validate(
            {
                "action_id": "extra",
                "question_id": "guidance",
                "expected_information_value": 1.0,
                "research_cost": 0.0,
                "latency_cost": 0.0,
                "model_cost": 0.0,
                "assumption_ids": ("assumption-1",),
                "external_research": True,
            }
        )
    with pytest.raises(ValidationError):
        action.action_id = "mutated"
