from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import permutations

import pytest
from pydantic import ValidationError

from aegis.contracts import AlphaForecast, PortfolioProposal, RiskPolicy
from aegis.fund.spec import PortfolioPolicy
from aegis.quant import construct_portfolio
from aegis.risk import evaluate_risk


def forecast(
    ticker: str,
    expected: float,
    volatility: float,
    probability: float,
    confidence: float,
    *,
    abstained: bool = False,
) -> AlphaForecast:
    return AlphaForecast(
        forecast_id=f"forecast-{ticker}",
        model_name="test",
        ticker=ticker,
        as_of=datetime(2024, 2, 23, 21, 5, tzinfo=UTC),
        horizon_days=20,
        expected_excess_return=None if abstained else expected,
        expected_volatility=None if abstained else volatility,
        probability_positive=probability,
        confidence=confidence,
        uncertainty=1 - confidence,
        thesis="" if abstained else "fixture thesis",
        evidence_ids=[] if abstained else [f"e-{ticker}"],
        invalidation_conditions=[],
        abstained=abstained,
        abstain_reason="model unavailable" if abstained else None,
    )


def test_confidence_volatility_weighting_is_hand_calculable() -> None:
    forecasts = (
        forecast("AAPL", 0.10, 0.20, 0.75, 0.80),
        forecast("MSFT", 0.10, 0.40, 0.75, 0.80),
    )
    result = construct_portfolio(
        forecasts,
        PortfolioPolicy(gross_target=0.80),
        0.5,
    )
    assert result.target_weights["AAPL"] == pytest.approx(0.8 * 2 / 3)
    assert result.target_weights["MSFT"] == pytest.approx(0.8 * 1 / 3)
    assert result.gross_exposure == pytest.approx(0.8)
    assert result.cash_weight == pytest.approx(0.2)


def test_abstention_and_low_confidence_are_excluded() -> None:
    result = construct_portfolio(
        (
            forecast("AAPL", 0.1, 0.2, 0.7, 0.4),
            forecast("MSFT", 0.1, 0.2, 0.7, 0.8, abstained=True),
        ),
        PortfolioPolicy(),
        0.55,
        {"NVDA": 0.10},
    )
    assert result.target_weights == {"NVDA": 0.10}


def test_risk_clamps_position_gross_turnover_and_is_deterministic() -> None:
    forecasts = tuple(
        forecast(ticker, 0.1, 0.2, 0.7, 0.8) for ticker in ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA"]
    )
    proposal = construct_portfolio(forecasts, PortfolioPolicy(gross_target=0.85), 0.55)
    policy = RiskPolicy(version="test-v1")
    sectors = {
        "AAPL": "Technology",
        "MSFT": "Technology",
        "NVDA": "Technology",
        "AMZN": "Consumer",
        "GOOGL": "Communication",
    }
    strategies = {"pod-a": 0.5, "pod-b": 0.5}
    first = evaluate_risk(
        proposal, policy, sector_by_ticker=sectors, strategy_allocations=strategies
    )
    second = evaluate_risk(
        proposal, policy, sector_by_ticker=sectors, strategy_allocations=strategies
    )
    assert first == second
    assert first.decision.approved
    assert max(first.decision.final_weights.values()) <= 0.15
    assert sum(abs(value) for value in first.decision.final_weights.values()) <= 0.9
    assert any(clamp.rule == "max_position_pct" for clamp in first.clamps)
    assert any(clamp.rule in {"max_turnover_pct", "maximum_sector_pct"} for clamp in first.clamps)


def test_risk_policy_is_frozen() -> None:
    policy = RiskPolicy(version="test-v1")
    with pytest.raises(ValidationError):
        policy.max_position_pct = 0.5


HASH = "a" * 64


def proposal(weights: dict[str, float], *, turnover: float = 0.0) -> PortfolioProposal:
    return PortfolioProposal(
        as_of=date(2025, 1, 3),
        target_weights=weights,
        cash_weight=max(0.0, 1.0 - sum(weights.values())),
        gross_exposure=sum(abs(weight) for weight in weights.values()),
        turnover=turnover,
        input_hash=HASH,
    )


def test_concentrated_current_book_cannot_be_reintroduced_by_low_turnover() -> None:
    desired = proposal({"AAPL": 0.05})
    policy = RiskPolicy(
        version="v3b",
        max_position_pct=0.15,
        max_gross_exposure=0.50,
        max_net_exposure=0.50,
        max_turnover_pct=0.01,
        maximum_sector_pct=0.20,
    )

    result = evaluate_risk(
        desired,
        policy,
        current_weights={"AAPL": 0.80},
        sector_by_ticker={"AAPL": "Technology"},
    )

    assert result.decision.approved
    assert result.decision.final_weights == {"AAPL": pytest.approx(0.05)}
    assert any(clamp.rule == "de_risk_overrides_turnover" for clamp in result.clamps)
    assert result.decision.warnings == [
        "turnover limit overridden to preserve de-risking and hard safety constraints"
    ]
    assert 0.5 * abs(result.decision.final_weights["AAPL"] - 0.80) > policy.max_turnover_pct


def test_sector_constraint_is_rechecked_after_turnover_handling() -> None:
    desired = proposal({"AAPL": 0.10, "MSFT": 0.10, "XOM": 0.10})
    policy = RiskPolicy(
        version="v3b",
        max_position_pct=0.20,
        max_gross_exposure=0.60,
        max_net_exposure=0.60,
        max_turnover_pct=0.01,
        maximum_sector_pct=0.15,
    )
    sectors = {"AAPL": "Technology", "MSFT": "Technology", "XOM": "Energy"}

    result = evaluate_risk(
        desired,
        policy,
        current_weights={"AAPL": 0.30, "MSFT": 0.30},
        sector_by_ticker=sectors,
    )

    technology = sum(
        weight
        for ticker, weight in result.decision.final_weights.items()
        if sectors[ticker] == "Technology" and weight > 0.0
    )
    assert result.decision.approved
    assert technology <= policy.maximum_sector_pct + 1e-12
    assert all(
        abs(weight) <= policy.max_position_pct + 1e-12
        for weight in result.decision.final_weights.values()
    )
    gross = sum(abs(weight) for weight in result.decision.final_weights.values())
    signed_net = sum(result.decision.final_weights.values())
    assert gross <= policy.max_gross_exposure + 1e-12
    assert abs(signed_net) <= policy.max_net_exposure + 1e-12
    assert 1.0 - signed_net >= policy.minimum_cash_pct - 1e-12
    assert all(weight >= -1e-12 for weight in result.decision.final_weights.values())
    assert any(clamp.rule == "maximum_sector_pct" for clamp in result.clamps)
    assert any(clamp.rule == "max_turnover_pct" for clamp in result.clamps)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"gross_exposure": 0.19}, "gross_exposure does not match"),
        ({"cash_weight": 0.79}, "cash_weight does not match"),
        ({"target_weights": {"AAPL": float("nan")}}, "must be finite"),
        ({"target_weights": {"AAPL": float("inf")}}, "must be finite"),
        ({"target_weights": {"AAPL": "not-a-number"}}, "finite numbers"),
        ({"cash_weight": float("nan")}, "finite number"),
        ({"gross_exposure": float("inf")}, "finite number"),
        ({"turnover": float("nan")}, "finite number"),
    ],
)
def test_malformed_portfolio_proposals_are_rejected(
    override: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "as_of": date(2025, 1, 3),
        "target_weights": {"AAPL": 0.20},
        "cash_weight": 0.80,
        "gross_exposure": 0.20,
        "turnover": 0.0,
        "input_hash": HASH,
    }
    values.update(override)
    with pytest.raises(ValidationError, match=message):
        PortfolioProposal.model_validate(values)


@pytest.mark.parametrize(
    ("current", "strategies"),
    [({"AAPL": float("nan")}, {}), ({}, {"pod-a": float("inf")})],
)
def test_risk_context_rejects_non_finite_values(
    current: dict[str, float], strategies: dict[str, float]
) -> None:
    with pytest.raises(ValueError, match="finite numbers"):
        evaluate_risk(
            proposal({"AAPL": 0.10}),
            RiskPolicy(version="v3b"),
            current_weights=current,
            sector_by_ticker={"AAPL": "Technology"},
            strategy_allocations=strategies,
        )


def test_risk_evaluation_is_invariant_to_mapping_permutations() -> None:
    proposed_items = [("MSFT", 0.11), ("XOM", 0.08), ("AAPL", 0.12)]
    current_items = [("XOM", 0.02), ("AAPL", 0.20), ("MSFT", 0.18)]
    sector_items = [("XOM", "Energy"), ("MSFT", "Technology"), ("AAPL", "Technology")]
    strategy_items = [("pod-b", 0.40), ("pod-a", 0.60)]
    policy = RiskPolicy(
        version="v3b",
        max_position_pct=0.15,
        max_gross_exposure=0.50,
        max_net_exposure=0.50,
        max_turnover_pct=0.03,
        maximum_sector_pct=0.20,
    )

    evaluations = []
    for proposed_order in permutations(proposed_items):
        for current_order in permutations(current_items):
            for sector_order in permutations(sector_items):
                for strategy_order in permutations(strategy_items):
                    evaluations.append(
                        evaluate_risk(
                            proposal(dict(proposed_order)),
                            policy,
                            current_weights=dict(current_order),
                            sector_by_ticker=dict(sector_order),
                            strategy_allocations=dict(strategy_order),
                        )
                    )

    assert evaluations
    assert all(evaluation == evaluations[0] for evaluation in evaluations[1:])
