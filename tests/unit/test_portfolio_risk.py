from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aegis.contracts import AlphaForecast, RiskPolicy
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
        policy.max_position_pct = 0.5  # type: ignore[misc]
