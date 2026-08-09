"""Deterministic, numeric-only forecast blending for a strategy pod.

The horizon policy is deliberately strict: every source forecast must use its
model's declared horizon, declared model horizons must be within the policy's
maximum gap, and a blend is labelled with the longest contributing horizon.
Nearby horizon returns are blended without annualisation or prose-derived
adjustments.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Final, cast

from aegis.contracts.artifacts import canonical_sha256
from aegis.contracts.forecasts import AlphaForecast
from aegis.contracts.strategy import (
    AlphaModelRef,
    BlendedForecast,
    ForecastContribution,
    ModelForecastBatch,
    StrategyPod,
)
from aegis.quant_research.hashing import build_hashed

# A declared, stable floor prevents a zero-uncertainty forecast from receiving
# an infinite raw weight. It is an implementation constant, not prose confidence.
_MIN_UNCERTAINTY: Final[float] = 1e-6


@dataclass(frozen=True, slots=True)
class _EligibleForecast:
    model: AlphaModelRef
    batch: ModelForecastBatch
    forecast: AlphaForecast
    features: frozenset[str]


def _semantic_id(kind: str, payload: object) -> str:
    """Build a compact semantic ID from numeric/identity inputs only."""
    return f"{kind}-{canonical_sha256(payload)[:20]}-v1"


def _validate_inputs(
    pod: StrategyPod, batches: tuple[ModelForecastBatch, ...]
) -> tuple[dict[str, AlphaModelRef], dict[str, ModelForecastBatch]]:
    if not isinstance(batches, tuple):
        raise TypeError("forecast batches must be supplied as a tuple")

    models = {model.model_id: model for model in pod.models}
    batch_ids = [batch.model_id for batch in batches]
    if len(batch_ids) != len(set(batch_ids)):
        raise ValueError("forecast batches must contain each declared model exactly once")
    if set(batch_ids) != set(models) or len(batch_ids) != len(models):
        raise ValueError("forecast batches must contain exactly the pod's declared model IDs")
    if any(batch.pod_id != pod.pod_id for batch in batches):
        raise ValueError("forecast batch pod does not match the strategy pod")

    cutoffs = {batch.as_of for batch in batches}
    if len(cutoffs) != 1:
        raise ValueError("forecast batches must share one as_of cutoff")

    declared_horizons = [model.horizon_days for model in pod.models]
    if max(declared_horizons) - min(declared_horizons) > (
        pod.blend_policy.maximum_horizon_gap_days
    ):
        raise ValueError("declared model horizons exceed the blend policy's maximum gap")

    by_model = {batch.model_id: batch for batch in batches}
    for model_id, batch in by_model.items():
        forecast_ids = [forecast.forecast_id for forecast in batch.forecasts]
        tickers = [forecast.ticker for forecast in batch.forecasts]
        if len(forecast_ids) != len(set(forecast_ids)):
            raise ValueError(f"duplicate forecast ID in model batch {model_id}")
        if len(tickers) != len(set(tickers)):
            raise ValueError(f"duplicate ticker in model batch {model_id}")
        if any(forecast.as_of != batch.as_of for forecast in batch.forecasts):
            raise ValueError(f"forecast cutoff does not match model batch {model_id}")
        if any(
            forecast.horizon_days != models[model_id].horizon_days for forecast in batch.forecasts
        ):
            raise ValueError(f"forecast horizon does not match declared model {model_id}")

    return models, by_model


def _verified_numeric(forecast: AlphaForecast) -> bool:
    """Return whether a non-abstention can populate the stricter blend contract."""
    if forecast.abstained:
        return False
    expected_return = forecast.expected_excess_return
    expected_volatility = forecast.expected_volatility
    if expected_return is None or expected_volatility is None:
        raise ValueError("non-abstaining forecasts require numeric return and volatility")
    if not math.isfinite(expected_return) or not math.isfinite(expected_volatility):
        raise ValueError("non-abstaining forecast numerics must be finite")
    if expected_volatility <= 0.0:
        raise ValueError("non-abstaining forecasts require positive expected volatility")
    if not forecast.evidence_ids:
        raise ValueError("non-abstaining forecasts require verified evidence IDs")
    return True


def _feature_overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard overlap; missing feature provenance never creates a penalty."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _overlap_penalties(
    forecasts: tuple[_EligibleForecast, ...], penalty_strength: float
) -> dict[str, float]:
    """Return order-invariant mean pairwise penalties keyed by model ID."""
    if len(forecasts) < 2 or penalty_strength == 0.0:
        return {item.model.model_id: 0.0 for item in forecasts}

    penalties: dict[str, float] = {}
    for item in forecasts:
        overlaps = [
            _feature_overlap(item.features, peer.features)
            for peer in forecasts
            if peer.model.model_id != item.model.model_id
        ]
        penalties[item.model.model_id] = penalty_strength * math.fsum(overlaps) / len(overlaps)
    return penalties


def _normalized_weights(
    forecasts: tuple[_EligibleForecast, ...], penalties: dict[str, float]
) -> dict[str, float]:
    raw: list[tuple[str, float]] = []
    for item in forecasts:
        uncertainty = max(item.forecast.uncertainty, _MIN_UNCERTAINTY)
        weight = (
            item.model.weight
            * (1.0 / uncertainty)
            * item.batch.calibration_score
            * item.batch.regime_score
            * item.batch.evidence_quality
            * (1.0 - penalties[item.model.model_id])
        )
        if not math.isfinite(weight):
            raise ValueError("forecast raw weight is not finite")
        if weight > 0.0:
            raw.append((item.model.model_id, weight))

    if not raw:
        return {}
    total = math.fsum(weight for _, weight in raw)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("forecast raw weight total is not finite and positive")

    normalized = {model_id: weight / total for model_id, weight in raw}
    # Reconcile deterministic floating-point residue onto the final sorted model.
    final_model = raw[-1][0]
    normalized[final_model] += 1.0 - math.fsum(normalized.values())
    return normalized


def blend_pod_forecasts(
    pod: StrategyPod, batches: tuple[ModelForecastBatch, ...]
) -> tuple[BlendedForecast, ...]:
    """Blend eligible forecasts using only declared, auditable numeric inputs.

    A batch is eligible only when its calibration and evidence quality meet the
    pod policy. Abstentions are not redistributed into synthetic forecasts. A
    ticker for which every source is ineligible is omitted; consequently an
    entirely ineligible input returns the typed empty tuple.
    """
    models, by_model = _validate_inputs(pod, batches)

    by_ticker: defaultdict[str, list[_EligibleForecast]] = defaultdict(list)
    for model_id in sorted(models):
        model = models[model_id]
        batch = by_model[model_id]
        if (
            batch.calibration_score < pod.blend_policy.minimum_calibration
            or batch.evidence_quality < pod.blend_policy.minimum_evidence_quality
        ):
            continue
        features = frozenset(batch.feature_ids or model.feature_ids)
        for forecast in batch.forecasts:
            if _verified_numeric(forecast):
                by_ticker[forecast.ticker].append(
                    _EligibleForecast(
                        model=model,
                        batch=batch,
                        forecast=forecast,
                        features=features,
                    )
                )

    blended: list[BlendedForecast] = []
    for ticker in sorted(by_ticker):
        eligible = tuple(
            sorted(
                by_ticker[ticker],
                key=lambda item: (item.model.model_id, item.forecast.forecast_id),
            )
        )
        penalties = _overlap_penalties(eligible, pod.blend_policy.overlap_penalty)
        weights = _normalized_weights(eligible, penalties)
        contributing = tuple(item for item in eligible if item.model.model_id in weights)
        if not contributing:
            continue

        horizon = max(item.forecast.horizon_days for item in contributing)
        contribution_items: list[ForecastContribution] = []
        for item in contributing:
            weight = weights[item.model.model_id]
            expected_return = item.forecast.expected_excess_return
            expected_volatility = item.forecast.expected_volatility
            assert expected_return is not None and expected_volatility is not None
            contribution_id = _semantic_id(
                "forecast-contribution",
                {
                    "pod_id": pod.pod_id,
                    "model_id": item.model.model_id,
                    "forecast_id": item.forecast.forecast_id,
                    "ticker": ticker,
                    "as_of": item.batch.as_of,
                    "horizon_days": item.forecast.horizon_days,
                },
            )
            contribution_items.append(
                build_hashed(
                    ForecastContribution,
                    contribution_id=contribution_id,
                    pod_id=pod.pod_id,
                    model_id=item.model.model_id,
                    forecast_id=item.forecast.forecast_id,
                    ticker=ticker,
                    blend_weight=weight,
                    expected_return_contribution=weight * expected_return,
                    uncertainty=item.forecast.uncertainty,
                    calibration_score=item.batch.calibration_score,
                    regime_score=item.batch.regime_score,
                    evidence_quality=item.batch.evidence_quality,
                    overlap_penalty_applied=penalties[item.model.model_id],
                )
            )

        contributions = tuple(contribution_items)
        expected_excess_return = math.fsum(
            item.expected_return_contribution for item in contributions
        )
        expected_volatility = math.fsum(
            weights[item.model.model_id] * cast(float, item.forecast.expected_volatility)
            for item in contributing
        )
        probability_positive = math.fsum(
            weights[item.model.model_id] * item.forecast.probability_positive
            for item in contributing
        )
        uncertainty = math.fsum(
            weights[item.model.model_id] * item.forecast.uncertainty for item in contributing
        )
        blended_id = _semantic_id(
            "blended-forecast",
            {
                "pod_id": pod.pod_id,
                "ticker": ticker,
                "as_of": contributing[0].batch.as_of,
                "horizon_days": horizon,
                "forecast_ids": tuple(item.forecast.forecast_id for item in contributing),
                "model_ids": tuple(item.model.model_id for item in contributing),
            },
        )
        blended.append(
            build_hashed(
                BlendedForecast,
                blended_id=blended_id,
                pod_id=pod.pod_id,
                ticker=ticker,
                as_of=contributing[0].batch.as_of,
                horizon_days=horizon,
                expected_excess_return=expected_excess_return,
                expected_volatility=expected_volatility,
                probability_positive=probability_positive,
                uncertainty=uncertainty,
                contributions=contributions,
            )
        )

    return tuple(blended)
