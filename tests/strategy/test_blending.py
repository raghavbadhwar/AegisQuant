from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aegis.contracts.forecasts import AlphaForecast
from aegis.contracts.strategy import (
    AlphaModelRef,
    ForecastBlendPolicy,
    ModelForecastBatch,
    PodPortfolioPolicy,
    PodRiskBudget,
    StrategyPod,
)
from aegis.quant_research.hashing import build_hashed
from aegis.strategy import blend_pod_forecasts

AS_OF = datetime(2025, 1, 15, 16, tzinfo=UTC)


def _model(
    model_id: str, *, weight: float, features: tuple[str, ...], horizon: int = 5
) -> AlphaModelRef:
    return build_hashed(
        AlphaModelRef,
        model_id=model_id,
        feature_ids=features,
        horizon_days=horizon,
        weight=weight,
        provider="fixture",
    )


def _pod(
    *,
    models: tuple[AlphaModelRef, ...] | None = None,
    overlap_penalty: float = 0.3,
    maximum_gap: int = 0,
) -> StrategyPod:
    selected = models or (
        _model("alpha-one-v1", weight=2.0, features=("feature-x-v1", "feature-y-v1")),
        _model("alpha-two-v1", weight=1.0, features=("feature-y-v1", "feature-z-v1")),
    )
    blend_policy = build_hashed(
        ForecastBlendPolicy,
        policy_id="blend-policy-v1",
        maximum_horizon_gap_days=maximum_gap,
        overlap_penalty=overlap_penalty,
        minimum_evidence_quality=0.5,
        minimum_calibration=0.5,
    )
    portfolio_policy = build_hashed(
        PodPortfolioPolicy,
        policy_id="portfolio-policy-v1",
        method="forecast_weighted",
        gross_target=0.8,
        market_neutral=False,
    )
    risk_budget = build_hashed(
        PodRiskBudget,
        budget_id="pod-budget-v1",
        maximum_gross=0.9,
        maximum_position=0.2,
        maximum_drawdown=0.1,
    )
    return build_hashed(
        StrategyPod,
        pod_id="quality-pod-v1",
        display_name="Quality pod",
        capital_weight=0.5,
        models=selected,
        blend_policy=blend_policy,
        portfolio_policy=portfolio_policy,
        risk_budget=risk_budget,
    )


def _forecast(
    forecast_id: str,
    model_name: str,
    *,
    ticker: str = "AAPL",
    expected_return: float = 0.12,
    volatility: float = 0.2,
    uncertainty: float = 0.2,
    horizon: int = 5,
    abstained: bool = False,
) -> AlphaForecast:
    return AlphaForecast(
        forecast_id=forecast_id,
        model_name=model_name,
        ticker=ticker,
        as_of=AS_OF,
        horizon_days=horizon,
        expected_excess_return=None if abstained else expected_return,
        expected_volatility=None if abstained else volatility,
        probability_positive=0.7,
        confidence=0.91,
        uncertainty=uncertainty,
        thesis="Narrative must not affect blending.",
        evidence_ids=[] if abstained else [f"evidence-{forecast_id}"],
        abstained=abstained,
        abstain_reason="No verified observation" if abstained else None,
    )


def _batch(
    model_id: str,
    forecast: AlphaForecast,
    *,
    calibration: float,
    regime: float,
    evidence_quality: float,
    features: tuple[str, ...],
) -> ModelForecastBatch:
    return build_hashed(
        ModelForecastBatch,
        batch_id=f"{model_id.removesuffix('-v1')}-batch-v1",
        pod_id="quality-pod-v1",
        model_id=model_id,
        as_of=AS_OF,
        available_at=AS_OF,
        forecasts=(forecast,),
        calibration_score=calibration,
        regime_score=regime,
        evidence_quality=evidence_quality,
        feature_ids=features,
    )


def _batches(
    *,
    uncertainty_one: float = 0.2,
    features_two: tuple[str, ...] = ("feature-y-v1", "feature-z-v1"),
) -> tuple[ModelForecastBatch, ModelForecastBatch]:
    return (
        _batch(
            "alpha-one-v1",
            _forecast("forecast-one", "model one", uncertainty=uncertainty_one),
            calibration=0.8,
            regime=0.5,
            evidence_quality=1.0,
            features=("feature-x-v1", "feature-y-v1"),
        ),
        _batch(
            "alpha-two-v1",
            _forecast(
                "forecast-two",
                "model two",
                expected_return=0.04,
                volatility=0.3,
                uncertainty=0.4,
            ),
            calibration=0.9,
            regime=0.8,
            evidence_quality=0.8,
            features=features_two,
        ),
    )


def test_blend_has_golden_numeric_attribution_and_hashes() -> None:
    result = blend_pod_forecasts(_pod(), _batches())

    assert len(result) == 1
    blend = result[0]
    assert blend.ticker == "AAPL"
    assert blend.horizon_days == 5
    assert [item.model_id for item in blend.contributions] == ["alpha-one-v1", "alpha-two-v1"]
    assert [item.overlap_penalty_applied for item in blend.contributions] == pytest.approx(
        [0.1, 0.1]
    )
    assert [item.blend_weight for item in blend.contributions] == pytest.approx(
        [0.7352941176470589, 0.2647058823529412]
    )
    assert blend.expected_excess_return == pytest.approx(0.09882352941176471)
    assert blend.expected_volatility == pytest.approx(0.22647058823529412)
    assert sum(item.expected_return_contribution for item in blend.contributions) == pytest.approx(
        blend.expected_excess_return
    )
    assert blend.blended_id == "blended-forecast-ff60953a8aa0eea4ab51-v1"
    assert blend.content_hash == "478d73637a0d58e6ca23ea19e0bfcecb828dd79cdb69c836ccc56be6db28676f"


def test_overlap_and_uncertainty_are_monotonic() -> None:
    baseline = blend_pod_forecasts(_pod(), _batches())[0]
    less_uncertain = blend_pod_forecasts(_pod(), _batches(uncertainty_one=0.1))[0]
    no_overlap = blend_pod_forecasts(_pod(), _batches(features_two=("feature-z-v1",)))[0]

    assert less_uncertain.contributions[0].blend_weight > baseline.contributions[0].blend_weight
    assert no_overlap.contributions[0].overlap_penalty_applied == 0.0
    assert (
        no_overlap.contributions[0].overlap_penalty_applied
        < baseline.contributions[0].overlap_penalty_applied
    )


def test_reordering_models_and_batches_is_invariant() -> None:
    pod = _pod()
    batches = _batches()
    reordered_pod = _pod(models=tuple(reversed(pod.models)))

    assert blend_pod_forecasts(pod, batches) == blend_pod_forecasts(
        reordered_pod, tuple(reversed(batches))
    )


def test_thesis_and_source_confidence_do_not_affect_blend() -> None:
    pod = _pod()
    batches = _batches()
    changed: list[ModelForecastBatch] = []
    for batch in batches:
        source = batch.forecasts[0]
        forecast = source.model_copy(
            update={"thesis": "Completely different prose.", "confidence": 0.01}
        )
        values = batch.model_dump(exclude={"content_hash", "forecasts"})
        changed.append(build_hashed(ModelForecastBatch, **values, forecasts=(forecast,)))

    assert blend_pod_forecasts(pod, batches) == blend_pod_forecasts(pod, tuple(changed))


def test_incompatible_declared_horizons_are_rejected() -> None:
    models = (
        _model("alpha-one-v1", weight=2.0, features=("feature-x-v1",), horizon=5),
        _model("alpha-two-v1", weight=1.0, features=("feature-y-v1",), horizon=8),
    )
    pod = _pod(models=models, maximum_gap=2)
    batches = (
        _batch(
            "alpha-one-v1",
            _forecast("forecast-one", "one", horizon=5),
            calibration=0.8,
            regime=0.8,
            evidence_quality=0.8,
            features=("feature-x-v1",),
        ),
        _batch(
            "alpha-two-v1",
            _forecast("forecast-two", "two", horizon=8),
            calibration=0.8,
            regime=0.8,
            evidence_quality=0.8,
            features=("feature-y-v1",),
        ),
    )

    with pytest.raises(ValueError, match="horizons exceed"):
        blend_pod_forecasts(pod, batches)


def test_all_abstentions_return_typed_empty_tuple() -> None:
    batches = tuple(
        _batch(
            model_id,
            _forecast(f"forecast-{index}", model_id, abstained=True),
            calibration=0.8,
            regime=0.8,
            evidence_quality=0.8,
            features=(f"feature-{index}-v1",),
        )
        for index, model_id in enumerate(("alpha-one-v1", "alpha-two-v1"), start=1)
    )

    result = blend_pod_forecasts(_pod(), batches)

    assert result == ()
    assert isinstance(result, tuple)
