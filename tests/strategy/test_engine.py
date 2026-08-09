from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aegis.contracts import (
    AlphaForecast,
    AlphaModelRef,
    ForecastBlendPolicy,
    FundAllocatorPolicy,
    FundMandate,
    ModelForecastBatch,
    PodPortfolioPolicy,
    PodRiskBudget,
    RiskPolicy,
    StrategyPod,
    canonical_sha256,
)
from aegis.quant_research.hashing import build_hashed
from aegis.strategy.engine import PodMarketContext, build_master_portfolio

AS_OF = datetime(2025, 1, 15, 16, tzinfo=UTC)
SNAPSHOT_HASH = canonical_sha256({"snapshot": "v3b"})


def model(model_id: str) -> AlphaModelRef:
    return build_hashed(
        AlphaModelRef, model_id=model_id, horizon_days=5, weight=1.0, provider="fixture"
    )


def pod(pod_id: str, model_id: str, *, market_neutral: bool = False) -> StrategyPod:
    base = pod_id.removesuffix("-v1")
    return build_hashed(
        StrategyPod,
        pod_id=pod_id,
        display_name=base,
        capital_weight=0.5,
        models=(model(model_id),),
        blend_policy=build_hashed(
            ForecastBlendPolicy,
            policy_id=f"{base}-blend-v1",
            maximum_horizon_gap_days=0,
            overlap_penalty=0.5,
            minimum_evidence_quality=0.5,
            minimum_calibration=0.5,
        ),
        portfolio_policy=build_hashed(
            PodPortfolioPolicy,
            policy_id=f"{base}-portfolio-v1",
            method="forecast_weighted",
            gross_target=0.8,
            market_neutral=market_neutral,
        ),
        risk_budget=build_hashed(
            PodRiskBudget,
            budget_id=f"{base}-budget-v1",
            maximum_gross=0.8,
            maximum_position=0.6,
            maximum_drawdown=0.2,
        ),
    )


def mandate() -> FundMandate:
    return build_hashed(
        FundMandate,
        mandate_id="mandate-demo-v1",
        display_name="Demo",
        capital=Decimal("100000"),
        pods=(
            pod("pod-alpha-v1", "model-alpha-v1"),
            pod("pod-beta-v1", "model-beta-v1", market_neutral=True),
        ),
        allocator_policy=build_hashed(
            FundAllocatorPolicy,
            policy_id="allocator-static-v1",
            method="static",
            maximum_pod_weight=0.6,
            preserve_unallocated_cash=True,
        ),
        master_risk=RiskPolicy(version="risk-v1"),
        benchmark="SPY",
    )


def forecast(
    model_id: str, ticker: str, expected: float, *, abstained: bool = False
) -> AlphaForecast:
    return AlphaForecast(
        forecast_id=f"forecast-{model_id.removesuffix('-v1')}-{ticker.lower()}",
        model_name=model_id,
        ticker=ticker,
        as_of=AS_OF,
        horizon_days=5,
        expected_excess_return=None if abstained else expected,
        expected_volatility=None if abstained else 0.2,
        probability_positive=0.6,
        confidence=0.7,
        uncertainty=0.3,
        thesis="numeric fixture",
        evidence_ids=[] if abstained else [f"evidence-{ticker.lower()}"],
        abstained=abstained,
        abstain_reason="unavailable" if abstained else None,
    )


def batch(
    pod_id: str, model_id: str, values: tuple[tuple[str, float], ...], *, abstained: bool = False
) -> ModelForecastBatch:
    return build_hashed(
        ModelForecastBatch,
        batch_id=f"batch-{model_id.removesuffix('-v1')}-v1",
        pod_id=pod_id,
        model_id=model_id,
        quant_bundle_id="quant-bundle-demo-v1",
        quant_bundle_hash=SNAPSHOT_HASH,
        universe_snapshot_id="universe-demo-v1",
        as_of=AS_OF,
        available_at=AS_OF,
        forecasts=tuple(
            forecast(model_id, ticker, value, abstained=abstained) for ticker, value in values
        ),
        calibration_score=0.8,
        regime_score=0.8,
        evidence_quality=0.9,
    )


def context(*, attributed_drawdown: float | None = None) -> PodMarketContext:
    return PodMarketContext(
        universe_snapshot_id="universe-demo-v1",
        as_of=AS_OF,
        available_at=AS_OF,
        covariance={"AAPL": {"AAPL": 0.04, "MSFT": 0.01}, "MSFT": {"AAPL": 0.01, "MSFT": 0.09}},
        benchmark_weights={"AAPL": 0.5, "MSFT": 0.5},
        covariance_training_start=AS_OF,
        covariance_training_end=AS_OF,
        covariance_observation_hash=SNAPSHOT_HASH,
        attributed_drawdown=attributed_drawdown,
        attributed_nav_hash=SNAPSHOT_HASH if attributed_drawdown is not None else None,
        input_snapshot_hashes=(SNAPSHOT_HASH,),
    )


def inputs(
    *, abstained: bool = False
) -> tuple[dict[str, tuple[ModelForecastBatch, ...]], dict[str, PodMarketContext]]:
    batches = {
        "pod-alpha-v1": (
            batch(
                "pod-alpha-v1",
                "model-alpha-v1",
                (("AAPL", 0.08), ("MSFT", 0.02)),
                abstained=abstained,
            ),
        ),
        "pod-beta-v1": (
            batch(
                "pod-beta-v1",
                "model-beta-v1",
                (("AAPL", 0.01), ("MSFT", 0.10)),
                abstained=abstained,
            ),
        ),
    }
    return batches, {"pod-alpha-v1": context(), "pod-beta-v1": context()}


def test_engine_nets_pods_preserves_opposing_contributions_and_uses_existing_proposal() -> None:
    batches, contexts = inputs()
    master = build_master_portfolio(mandate(), batches, contexts, {"AAPL": 0.1})
    assert len(master.pod_targets) == 2
    assert len(master.contributions) == 4
    assert any(item.ticker == "AAPL" and item.allocated_weight < 0 for item in master.contributions)
    for ticker, weight in master.target_weights.items():
        assert sum(
            item.allocated_weight for item in master.contributions if item.ticker == ticker
        ) == pytest.approx(weight)
    proposal = master.to_portfolio_proposal({"AAPL": 0.1})
    assert proposal.target_weights == master.target_weights
    assert proposal.gross_exposure == pytest.approx(
        sum(abs(value) for value in proposal.target_weights.values())
    )


def test_engine_is_mapping_and_batch_order_invariant_and_pod_isolated() -> None:
    batches, contexts = inputs()
    first = build_master_portfolio(mandate(), batches, contexts, {})
    reordered_batches = {
        key: tuple(reversed(value)) for key, value in reversed(tuple(batches.items()))
    }
    second = build_master_portfolio(
        mandate(), reordered_batches, dict(reversed(tuple(contexts.items()))), {}
    )
    assert first == second
    changed = dict(batches)
    changed["pod-alpha-v1"] = (
        batch("pod-alpha-v1", "model-alpha-v1", (("AAPL", 0.2), ("MSFT", 0.01))),
    )
    changed_master = build_master_portfolio(mandate(), changed, contexts, {})
    beta_before = next(item for item in first.pod_targets if item.pod_id == "pod-beta-v1")
    beta_after = next(item for item in changed_master.pod_targets if item.pod_id == "pod-beta-v1")
    assert beta_before == beta_after


def test_all_pod_abstention_preserves_capital_as_cash_without_redistribution() -> None:
    batches, contexts = inputs(abstained=True)
    master = build_master_portfolio(mandate(), batches, contexts, {})
    assert master.target_weights == {}
    assert master.contributions == ()
    assert master.cash_weight == 1.0
    assert master.allocator_weights == {"pod-alpha-v1": 0.5, "pod-beta-v1": 0.5}
    with pytest.raises(ValueError, match="exactly the declared pod IDs"):
        build_master_portfolio(mandate(), {"pod-alpha-v1": batches["pod-alpha-v1"]}, contexts, {})


def test_drawdown_breaching_pod_abstains_to_cash_without_redistribution() -> None:
    batches, contexts = inputs()
    contexts["pod-alpha-v1"] = context(attributed_drawdown=0.2)
    master = build_master_portfolio(mandate(), batches, contexts, {})
    alpha = next(item for item in master.pod_targets if item.pod_id == "pod-alpha-v1")
    beta = next(item for item in master.pod_targets if item.pod_id == "pod-beta-v1")
    assert alpha.target_weights == {}
    assert alpha.cash_weight == 1.0
    assert master.allocator_weights["pod-alpha-v1"] == 0.5
    assert master.allocator_weights["pod-beta-v1"] == 0.5
    assert all(item.pod_id == "pod-beta-v1" for item in master.contributions)
    assert master.gross_exposure == pytest.approx(beta.gross_exposure * 0.5)
