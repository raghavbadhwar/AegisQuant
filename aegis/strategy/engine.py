"""Deterministic pod construction, allocation, netting, and attribution."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from typing import Any, Self

from pydantic import AwareDatetime, Field, FiniteFloat, field_validator, model_validator

from aegis.contracts._base import normalize_ticker, normalize_ticker_map
from aegis.contracts.artifacts import canonical_sha256
from aegis.contracts.quant import FrozenContractModel, SemanticId, Sha256
from aegis.contracts.strategy import (
    BlendedForecast,
    FundMandate,
    MasterPortfolio,
    ModelForecastBatch,
    PodContribution,
    PodTarget,
    StrategyPod,
)
from aegis.quant_research.hashing import build_hashed
from aegis.quant_research.portfolio_models import DEFAULT_PORTFOLIO_MODELS, propose_portfolio
from aegis.strategy.blending import blend_pod_forecasts


class PodMarketContext(FrozenContractModel):
    """Immutable, point-in-time market inputs isolated to one strategy pod."""

    universe_snapshot_id: SemanticId
    as_of: AwareDatetime
    available_at: AwareDatetime
    covariance: dict[str, dict[str, FiniteFloat]] = Field(default_factory=dict)
    benchmark_weights: dict[str, FiniteFloat] = Field(default_factory=dict)
    input_snapshot_hashes: tuple[Sha256, ...] = Field(min_length=1)

    @field_validator("covariance", mode="before")
    @classmethod
    def normalize_covariance(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {
            normalize_ticker(row): {
                normalize_ticker(column): item for column, item in columns.items()
            }
            for row, columns in value.items()
        }

    @field_validator("benchmark_weights", mode="before")
    @classmethod
    def normalize_benchmark(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {normalize_ticker(ticker): weight for ticker, weight in value.items()}

    @model_validator(mode="after")
    def context_is_point_in_time_and_complete(self) -> Self:
        if self.available_at > self.as_of:
            raise ValueError("pod market context available_at must not be after as_of")
        names = set(self.covariance)
        if self.covariance and any(set(row) != names for row in self.covariance.values()):
            raise ValueError("pod covariance must be a complete square ticker matrix")
        for left in names:
            for right in names:
                if abs(self.covariance[left][right] - self.covariance[right][left]) > 1e-12:
                    raise ValueError("pod covariance must be symmetric")
        if len(set(self.input_snapshot_hashes)) != len(self.input_snapshot_hashes):
            raise ValueError("pod input snapshot hashes must be unique")
        return self


def _semantic_id(kind: str, payload: object) -> str:
    return f"{kind}-{canonical_sha256(payload)[:20]}-v1"


def _exact_keys(label: str, supplied: Mapping[str, object], expected: set[str]) -> None:
    actual = set(supplied)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            f"{label} must contain exactly the declared pod IDs; missing={missing}, extra={extra}"
        )


def _canonical_batch_payload(batch: ModelForecastBatch) -> dict[str, Any]:
    payload = batch.model_dump(mode="python", exclude={"content_hash"})
    payload["forecasts"] = tuple(
        sorted(payload["forecasts"], key=lambda item: (item["ticker"], item["forecast_id"]))
    )
    payload["feature_ids"] = tuple(sorted(payload["feature_ids"]))
    return payload


def _canonical_pod_payload(pod: StrategyPod) -> dict[str, Any]:
    payload = pod.model_dump(mode="python", exclude={"content_hash"})
    payload["models"] = tuple(sorted(payload["models"], key=lambda item: item["model_id"]))
    return payload


def _canonical_mandate_payload(mandate: FundMandate) -> dict[str, Any]:
    payload = mandate.model_dump(mode="python", exclude={"content_hash", "pods"})
    payload["pods"] = tuple(
        _canonical_pod_payload(pod) for pod in sorted(mandate.pods, key=lambda item: item.pod_id)
    )
    return payload


def _portfolio_model_id(pod: StrategyPod) -> str:
    model = DEFAULT_PORTFOLIO_MODELS.get(pod.portfolio_policy.method)
    model_id = getattr(model, "model_id", None)
    if not isinstance(model_id, str):
        raise ValueError(
            f"portfolio model for {pod.portfolio_policy.method} has no declared model ID"
        )
    return model_id


def _pod_request(
    pod: StrategyPod,
    batches: tuple[ModelForecastBatch, ...],
    context: PodMarketContext,
    blended: tuple[BlendedForecast, ...],
) -> tuple[dict[str, float], float]:
    if not blended:
        return {}, 0.0
    if any(item.as_of != context.as_of for item in blended):
        raise ValueError(f"pod {pod.pod_id} forecasts and market context must share one as_of")

    tickers = tuple(sorted(item.ticker for item in blended))
    missing_covariance = set(tickers) - set(context.covariance)
    if missing_covariance:
        raise ValueError(
            f"pod {pod.pod_id} covariance missing tickers: {sorted(missing_covariance)}"
        )
    covariance = {
        left: {right: context.covariance[left][right] for right in tickers} for left in tickers
    }
    expected_returns = {item.ticker: item.expected_excess_return for item in blended}
    volatilities = {item.ticker: item.expected_volatility for item in blended}
    benchmark = {
        ticker: context.benchmark_weights[ticker]
        for ticker in tickers
        if ticker in context.benchmark_weights
    }
    batch_hashes = tuple(
        canonical_sha256(_canonical_batch_payload(batch))
        for batch in sorted(batches, key=lambda item: item.model_id)
    )
    snapshots = tuple(sorted(set(context.input_snapshot_hashes) | set(batch_hashes)))
    constraints_hash = canonical_sha256(
        {
            "portfolio_policy": pod.portfolio_policy.model_dump(mode="python"),
            "risk_budget": pod.risk_budget.model_dump(mode="python"),
        }
    )
    request_payload = {
        "pod_id": pod.pod_id,
        "method": pod.portfolio_policy.method,
        "as_of": context.as_of,
        "tickers": tickers,
        "input_snapshot_hashes": snapshots,
    }

    from aegis.contracts.quant import PortfolioModelRequest

    request = build_hashed(
        PortfolioModelRequest,
        request_id=_semantic_id("pod-portfolio-request", request_payload),
        model_id=_portfolio_model_id(pod),
        method=pod.portfolio_policy.method,
        universe_snapshot_id=context.universe_snapshot_id,
        tickers=tickers,
        expected_returns=expected_returns,
        volatilities=volatilities,
        covariance=covariance,
        benchmark_weights=benchmark,
        lower_bound=0.0,
        upper_bound=1.0,
        gross_target=pod.portfolio_policy.gross_target,
        constraints_hash=constraints_hash,
        input_snapshot_hashes=snapshots,
        as_of=context.as_of,
        available_at=max(context.available_at, *(batch.available_at for batch in batches)),
    )
    result = propose_portfolio(request)
    weights = dict(sorted(result.weights.items()))

    if pod.portfolio_policy.market_neutral:
        missing_benchmark = set(tickers) - set(benchmark)
        if missing_benchmark:
            raise ValueError(
                f"market-neutral pod {pod.pod_id} benchmark missing tickers: "
                f"{sorted(missing_benchmark)}"
            )
        benchmark_total = math.fsum(benchmark.values())
        if not math.isfinite(benchmark_total) or benchmark_total <= 0.0:
            raise ValueError("market-neutral benchmark weights must have a positive total")
        net = math.fsum(weights.values())
        weights = {
            ticker: weights[ticker] - net * benchmark[ticker] / benchmark_total
            for ticker in tickers
        }

    gross = math.fsum(abs(value) for value in weights.values())
    maximum_position = max((abs(value) for value in weights.values()), default=0.0)
    gross_limit = min(pod.portfolio_policy.gross_target, pod.risk_budget.maximum_gross)
    scale = 1.0
    if gross > gross_limit and gross > 0.0:
        scale = min(scale, gross_limit / gross)
    if maximum_position > pod.risk_budget.maximum_position and maximum_position > 0.0:
        scale = min(scale, pod.risk_budget.maximum_position / maximum_position)
    if scale < 1.0:
        weights = {ticker: value * scale for ticker, value in weights.items()}

    variance = math.fsum(
        weights[left] * covariance[left][right] * weights[right]
        for left in tickers
        for right in tickers
    )
    if variance < -1e-12:
        raise ValueError(f"pod {pod.pod_id} covariance implies negative portfolio variance")
    return dict(sorted(weights.items())), math.sqrt(max(0.0, variance))


def _allocator_weights(
    mandate: FundMandate, pod_volatilities: Mapping[str, float], active: set[str]
) -> dict[str, float]:
    declared = {pod.pod_id: pod.capital_weight for pod in mandate.pods}
    if mandate.allocator_policy.method == "static":
        return dict(sorted(declared.items()))

    positive = [pod_volatilities[pod_id] for pod_id in active]
    if any(not math.isfinite(value) or value <= 0.0 for value in positive):
        raise ValueError("inverse-volatility allocator requires positive active pod volatility")
    floor = min(positive) if positive else None
    result: dict[str, float] = {}
    for pod_id in sorted(declared):
        if pod_id not in active or floor is None:
            result[pod_id] = declared[pod_id]
        else:
            result[pod_id] = declared[pod_id] * floor / pod_volatilities[pod_id]
    return result


def build_master_portfolio(
    mandate: FundMandate,
    batches: Mapping[str, tuple[ModelForecastBatch, ...]],
    contexts: Mapping[str, PodMarketContext],
    current_weights: Mapping[str, float],
) -> MasterPortfolio:
    """Build a replay-stable master target without risk, order, or broker authority."""
    if not isinstance(batches, Mapping) or not isinstance(contexts, Mapping):
        raise TypeError("pod batches and contexts must be mappings")
    declared_ids = {pod.pod_id for pod in mandate.pods}
    _exact_keys("forecast batches", batches, declared_ids)
    _exact_keys("market contexts", contexts, declared_ids)
    current = dict(sorted(normalize_ticker_map(dict(current_weights)).items()))

    pods = tuple(sorted(mandate.pods, key=lambda item: item.pod_id))
    as_of_values = {contexts[pod.pod_id].as_of for pod in pods}
    if len(as_of_values) != 1:
        raise ValueError("all pod market contexts must share one as_of cutoff")
    as_of = next(iter(as_of_values))

    raw_targets: dict[str, dict[str, float]] = {}
    pod_volatilities: dict[str, float] = {}
    blended_ids: dict[str, tuple[str, ...]] = {}
    for pod in pods:
        pod_batches = batches[pod.pod_id]
        if not isinstance(pod_batches, tuple):
            raise TypeError(f"forecast batches for pod {pod.pod_id} must be a tuple")
        batch_model_ids = [batch.model_id for batch in pod_batches]
        declared_model_ids = {model.model_id for model in pod.models}
        if (
            len(batch_model_ids) != len(set(batch_model_ids))
            or set(batch_model_ids) != declared_model_ids
        ):
            raise ValueError(
                f"pod {pod.pod_id} batches must contain each declared model exactly once"
            )
        if any(batch.pod_id != pod.pod_id for batch in pod_batches):
            raise ValueError(f"pod {pod.pod_id} received a batch belonging to another pod")
        if any(batch.as_of != as_of for batch in pod_batches):
            raise ValueError(f"pod {pod.pod_id} batches and market context must share one as_of")

        blends = blend_pod_forecasts(pod, pod_batches)
        blended_ids[pod.pod_id] = tuple(item.blended_id for item in blends)
        weights, volatility = _pod_request(pod, pod_batches, contexts[pod.pod_id], blends)
        raw_targets[pod.pod_id] = weights
        pod_volatilities[pod.pod_id] = volatility

    active = {pod_id for pod_id, weights in raw_targets.items() if weights}
    allocator_weights = _allocator_weights(mandate, pod_volatilities, active)

    pod_targets: list[PodTarget] = []
    contributions: list[PodContribution] = []
    for pod in pods:
        weights = raw_targets[pod.pod_id]
        target_payload = {
            "pod_id": pod.pod_id,
            "as_of": as_of,
            "target_weights": weights,
            "blended_forecast_ids": blended_ids[pod.pod_id],
        }
        target = build_hashed(
            PodTarget,
            target_id=_semantic_id("pod-target", target_payload),
            pod_id=pod.pod_id,
            as_of=as_of,
            target_weights=weights,
            cash_weight=max(0.0, 1.0 - math.fsum(weights.values())),
            gross_exposure=math.fsum(abs(value) for value in weights.values()),
            blended_forecast_ids=blended_ids[pod.pod_id],
        )
        pod_targets.append(target)
        allocator_weight = allocator_weights[pod.pod_id]
        for ticker, pod_weight in sorted(weights.items()):
            contribution_payload = {
                "pod_id": pod.pod_id,
                "ticker": ticker,
                "pod_target_id": target.target_id,
                "allocator_weight": allocator_weight,
            }
            contributions.append(
                build_hashed(
                    PodContribution,
                    contribution_id=_semantic_id("pod-contribution", contribution_payload),
                    pod_id=pod.pod_id,
                    ticker=ticker,
                    pod_weight=pod_weight,
                    allocator_weight=allocator_weight,
                    allocated_weight=pod_weight * allocator_weight,
                )
            )

    by_ticker: defaultdict[str, list[float]] = defaultdict(list)
    for item in contributions:
        by_ticker[item.ticker].append(item.allocated_weight)
    target_weights = {
        ticker: math.fsum(by_ticker[ticker])
        for ticker in sorted(by_ticker)
        if abs(math.fsum(by_ticker[ticker])) > 1e-15
    }
    net = math.fsum(target_weights.values())
    gross = math.fsum(abs(value) for value in target_weights.values())
    normalized_inputs = {
        "mandate": _canonical_mandate_payload(mandate),
        "batches": {
            pod_id: tuple(
                _canonical_batch_payload(batch)
                for batch in sorted(batches[pod_id], key=lambda item: item.model_id)
            )
            for pod_id in sorted(batches)
        },
        "contexts": {
            pod_id: contexts[pod_id].model_dump(mode="python") for pod_id in sorted(contexts)
        },
        "current_weights": current,
    }
    input_hash = canonical_sha256(normalized_inputs)
    return build_hashed(
        MasterPortfolio,
        master_id=_semantic_id(
            "master-portfolio",
            {"mandate_id": mandate.mandate_id, "input_hash": input_hash},
        ),
        mandate_id=mandate.mandate_id,
        as_of=as_of,
        target_weights=target_weights,
        cash_weight=max(0.0, 1.0 - net),
        gross_exposure=gross,
        net_exposure=net,
        allocator_weights=allocator_weights,
        pod_targets=tuple(pod_targets),
        contributions=tuple(contributions),
        input_hash=input_hash,
    )
