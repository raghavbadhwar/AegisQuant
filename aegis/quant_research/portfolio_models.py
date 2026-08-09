"""Deterministic, dependency-free portfolio construction models for v3B."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.util import find_spec
from math import sqrt
from typing import ClassVar, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from aegis.contracts import PortfolioModelRequest, PortfolioModelResult
from aegis.contracts.quant import PortfolioMethod
from aegis.quant_research.hashing import build_hashed

FloatArray = NDArray[np.float64]
_TOLERANCE = 1e-12


class PortfolioModelError(ValueError):
    """The request cannot be evaluated without inventing portfolio inputs."""


class PortfolioDependencyError(PortfolioModelError):
    """An explicitly requested optional portfolio dependency is unavailable."""


@runtime_checkable
class PortfolioModel(Protocol):
    """Runtime-checkable seam for deterministic portfolio constructors."""

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult: ...


def _sorted_tickers(request: PortfolioModelRequest) -> tuple[str, ...]:
    return tuple(sorted(request.tickers))


def _require_method(request: PortfolioModelRequest, method: PortfolioMethod) -> None:
    if request.method != method:
        raise PortfolioModelError(f"{method} model cannot evaluate {request.method} request")


def _validate_bounds(request: PortfolioModelRequest) -> None:
    count = len(request.tickers)
    if request.lower_bound < 0.0:
        raise PortfolioModelError("dependency-free portfolio models are long-only")
    if count * request.lower_bound > request.gross_target + _TOLERANCE:
        raise PortfolioModelError("lower bound makes gross target infeasible")
    if count * request.upper_bound < request.gross_target - _TOLERANCE:
        raise PortfolioModelError("upper bound makes gross target infeasible")


def _bounded_simplex(values: FloatArray, lower: float, upper: float, target: float) -> FloatArray:
    """Euclidean projection onto identical box bounds and a fixed-sum simplex."""
    if values.ndim != 1 or values.size == 0 or not np.all(np.isfinite(values)):
        raise PortfolioModelError("portfolio scores must be a finite non-empty vector")
    count = values.size
    if count * lower > target + _TOLERANCE or count * upper < target - _TOLERANCE:
        raise PortfolioModelError("portfolio bounds and gross target are infeasible")
    low = float(np.min(values - upper))
    high = float(np.max(values - lower))
    for _ in range(100):
        midpoint = (low + high) / 2.0
        total = float(np.clip(values - midpoint, lower, upper).sum())
        if total > target:
            low = midpoint
        else:
            high = midpoint
    result = np.clip(values - ((low + high) / 2.0), lower, upper)
    residual = target - float(result.sum())
    if abs(residual) > _TOLERANCE:
        capacity = upper - result if residual > 0.0 else result - lower
        for index in np.flatnonzero(capacity > 0.0):
            adjustment = np.copysign(min(abs(residual), float(capacity[index])), residual)
            result[index] += adjustment
            residual -= adjustment
            if abs(residual) <= _TOLERANCE:
                break
    if abs(target - float(result.sum())) > 1e-10:
        raise PortfolioModelError("bounded portfolio projection did not converge")
    return result


def _score_weights(scores: FloatArray, request: PortfolioModelRequest) -> FloatArray:
    scores = np.asarray(scores, dtype=np.float64)
    if not np.all(np.isfinite(scores)):
        raise PortfolioModelError("portfolio model produced non-finite scores")
    if float(np.sum(scores)) <= _TOLERANCE or float(np.max(scores)) <= 0.0:
        scores = np.ones_like(scores)
    else:
        scores = np.maximum(scores, 0.0)
    normalized = scores * (request.gross_target / float(scores.sum()))
    return _bounded_simplex(
        normalized, request.lower_bound, request.upper_bound, request.gross_target
    )


def _complete_vector(values: dict[str, float], tickers: tuple[str, ...], label: str) -> FloatArray:
    missing = set(tickers).difference(values)
    if missing:
        raise PortfolioModelError(f"{label} missing tickers: {sorted(missing)}")
    return np.asarray([values[ticker] for ticker in tickers], dtype=np.float64)


def _expected_returns(request: PortfolioModelRequest, tickers: tuple[str, ...]) -> FloatArray:
    return np.asarray([request.expected_returns.get(ticker, 0.0) for ticker in tickers])


def _covariance(request: PortfolioModelRequest, tickers: tuple[str, ...]) -> FloatArray:
    if request.covariance:
        covariance = np.asarray(
            [[request.covariance[left][right] for right in tickers] for left in tickers],
            dtype=np.float64,
        )
    elif request.volatilities:
        volatility = _complete_vector(request.volatilities, tickers, "volatilities")
        covariance = np.diag(np.square(volatility))
    else:
        return np.zeros((len(tickers), len(tickers)), dtype=np.float64)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    scale = max(1.0, float(np.max(np.abs(eigenvalues))))
    if float(np.min(eigenvalues)) < -1e-10 * scale:
        raise PortfolioModelError("covariance must be positive semidefinite")
    clipped = np.maximum(eigenvalues, 0.0)
    return (eigenvectors * clipped) @ eigenvectors.T


def _require_covariance(request: PortfolioModelRequest, tickers: tuple[str, ...]) -> FloatArray:
    covariance = _covariance(request, tickers)
    if not request.covariance and not request.volatilities:
        raise PortfolioModelError("model requires covariance or complete volatilities")
    return covariance


def _regularize(covariance: FloatArray) -> FloatArray:
    count = covariance.shape[0]
    diagonal_scale = float(np.trace(covariance)) / count
    ridge = max(diagonal_scale, 1.0) * 1e-10
    return np.asarray(covariance + np.eye(count, dtype=np.float64) * ridge, dtype=np.float64)


def _positive_signal(values: FloatArray) -> FloatArray:
    shifted = values - float(np.min(values))
    scale = max(float(np.max(np.abs(values))), 1.0)
    shifted += scale * 1e-12
    return shifted


def _build_result(
    request: PortfolioModelRequest,
    tickers: tuple[str, ...],
    weights: FloatArray,
    calculation_id: str,
    *,
    adapter: str = "dependency_free",
    fallback_model_id: str | None = None,
) -> PortfolioModelResult:
    weights = np.asarray(weights, dtype=np.float64)
    covariance = _covariance(request, tickers)
    forecasts = _expected_returns(request, tickers)
    variance = float(weights @ covariance @ weights)
    if variance < -1e-10:
        raise PortfolioModelError("portfolio variance is negative")
    variance = max(0.0, variance)
    weight_map = {ticker: float(weight) for ticker, weight in zip(tickers, weights, strict=True)}
    gross = sum(abs(weight) for weight in weight_map.values())
    net = sum(weight_map.values())
    result_id = f"{request.method.replace('_', '-')}-result-v1"
    return build_hashed(
        PortfolioModelResult,
        result_id=result_id,
        request_id=request.request_id,
        model_id=request.model_id,
        method=request.method,
        weights=weight_map,
        expected_return=float(weights @ forecasts),
        expected_volatility=sqrt(variance),
        gross_exposure=gross,
        net_exposure=net,
        adapter=adapter,
        fallback_model_id=fallback_model_id,
        calculation_ids=(calculation_id,),
        input_hash=request.content_hash,
        as_of=request.as_of,
        available_at=request.as_of,
    )


class EqualWeightModel:
    method: ClassVar[PortfolioMethod] = "equal_weight"
    model_id: ClassVar[str] = "equal-weight-dependency-free-v1"

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        _require_method(request, self.method)
        _validate_bounds(request)
        tickers = _sorted_tickers(request)
        weights = np.full(len(tickers), request.gross_target / len(tickers))
        weights = _bounded_simplex(
            weights, request.lower_bound, request.upper_bound, request.gross_target
        )
        return _build_result(request, tickers, weights, "equal-weight-calculation-v1")


class InverseVolatilityModel:
    method: ClassVar[PortfolioMethod] = "inverse_volatility"
    model_id: ClassVar[str] = "inverse-volatility-dependency-free-v1"

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        _require_method(request, self.method)
        _validate_bounds(request)
        tickers = _sorted_tickers(request)
        if request.volatilities:
            volatility = _complete_vector(request.volatilities, tickers, "volatilities")
        else:
            covariance = _require_covariance(request, tickers)
            volatility = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        if np.any(volatility <= 0.0):
            raise PortfolioModelError(
                "inverse volatility requires strictly positive risk estimates"
            )
        weights = _score_weights(1.0 / volatility, request)
        return _build_result(request, tickers, weights, "inverse-volatility-calculation-v1")


class ForecastWeightedModel:
    method: ClassVar[PortfolioMethod] = "forecast_weighted"
    model_id: ClassVar[str] = "forecast-weighted-dependency-free-v1"

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        _require_method(request, self.method)
        _validate_bounds(request)
        tickers = _sorted_tickers(request)
        forecast = _complete_vector(request.expected_returns, tickers, "expected returns")
        weights = _score_weights(_positive_signal(forecast), request)
        return _build_result(request, tickers, weights, "forecast-weighted-calculation-v1")


class ShrinkageMeanRiskModel:
    method: ClassVar[PortfolioMethod] = "shrinkage_mean_risk"
    model_id: ClassVar[str] = "shrinkage-mean-risk-dependency-free-v1"

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        _require_method(request, self.method)
        _validate_bounds(request)
        tickers = _sorted_tickers(request)
        forecast = _complete_vector(request.expected_returns, tickers, "expected returns")
        covariance = _require_covariance(request, tickers)
        diagonal = np.diag(np.diag(covariance))
        shrunk = _regularize(0.5 * covariance + 0.5 * diagonal)
        scores = np.linalg.solve(shrunk, _positive_signal(forecast))
        weights = _score_weights(np.maximum(scores, 0.0), request)
        return _build_result(request, tickers, weights, "shrinkage-mean-risk-calculation-v1")


class RiskBudgetingModel:
    method: ClassVar[PortfolioMethod] = "risk_budgeting"
    model_id: ClassVar[str] = "risk-budgeting-dependency-free-v1"

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        _require_method(request, self.method)
        _validate_bounds(request)
        tickers = _sorted_tickers(request)
        covariance = _regularize(_require_covariance(request, tickers))
        count = len(tickers)
        weights = 1.0 / np.sqrt(np.diag(covariance))
        weights /= float(weights.sum())
        budget = 1.0 / count
        for _ in range(1_000):
            previous = weights.copy()
            for index in range(count):
                cross = (
                    float(covariance[index] @ weights) - covariance[index, index] * weights[index]
                )
                discriminant = cross * cross + 4.0 * covariance[index, index] * budget
                weights[index] = (-cross + sqrt(max(0.0, discriminant))) / (
                    2.0 * covariance[index, index]
                )
            if float(np.max(np.abs(weights - previous))) < 1e-12:
                break
        weights = _score_weights(weights, request)
        return _build_result(request, tickers, weights, "risk-budgeting-calculation-v1")


def _cluster_order(covariance: FloatArray, tickers: tuple[str, ...]) -> tuple[int, ...]:
    volatility = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    denominator = np.outer(volatility, volatility)
    correlation = np.divide(
        covariance,
        denominator,
        out=np.eye(len(tickers), dtype=np.float64),
        where=denominator > 0.0,
    )
    distance = np.sqrt(np.maximum(0.0, (1.0 - np.clip(correlation, -1.0, 1.0)) / 2.0))
    clusters: list[tuple[int, ...]] = [(index,) for index in range(len(tickers))]
    while len(clusters) > 1:
        candidates: list[tuple[float, tuple[str, ...], int, int]] = []
        for left in range(len(clusters)):
            for right in range(left + 1, len(clusters)):
                separation = float(np.mean(distance[np.ix_(clusters[left], clusters[right])]))
                names = tuple(sorted(tickers[index] for index in clusters[left] + clusters[right]))
                candidates.append((separation, names, left, right))
        _, _, left, right = min(candidates)
        first, second = clusters[left], clusters[right]
        if tuple(tickers[index] for index in first) > tuple(tickers[index] for index in second):
            first, second = second, first
        merged = first + second
        clusters = [cluster for index, cluster in enumerate(clusters) if index not in (left, right)]
        clusters.append(merged)
        clusters.sort(key=lambda cluster: tuple(tickers[index] for index in cluster))
    return clusters[0]


def _cluster_variance(covariance: FloatArray, indices: tuple[int, ...]) -> float:
    submatrix = covariance[np.ix_(indices, indices)]
    diagonal = np.maximum(np.diag(submatrix), 1e-16)
    inverse_variance = 1.0 / diagonal
    allocation = inverse_variance / float(inverse_variance.sum())
    return max(float(allocation @ submatrix @ allocation), 1e-16)


class HierarchicalRiskParityModel:
    method: ClassVar[PortfolioMethod] = "hierarchical_risk_parity"
    model_id: ClassVar[str] = "hierarchical-risk-parity-dependency-free-v1"

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        _require_method(request, self.method)
        _validate_bounds(request)
        tickers = _sorted_tickers(request)
        covariance = _require_covariance(request, tickers)
        if np.any(np.diag(covariance) <= 0.0):
            raise PortfolioModelError("hierarchical risk parity requires positive asset variances")
        order = _cluster_order(covariance, tickers)
        weights = np.ones(len(tickers), dtype=np.float64)
        groups: list[tuple[int, ...]] = [order]
        while groups:
            group = groups.pop(0)
            if len(group) <= 1:
                continue
            split = len(group) // 2
            left, right = group[:split], group[split:]
            left_variance = _cluster_variance(covariance, left)
            right_variance = _cluster_variance(covariance, right)
            left_allocation = right_variance / (left_variance + right_variance)
            weights[list(left)] *= left_allocation
            weights[list(right)] *= 1.0 - left_allocation
            groups.extend((left, right))
        weights = _score_weights(weights, request)
        return _build_result(request, tickers, weights, "hierarchical-risk-parity-calculation-v1")


class MaximumDiversificationModel:
    method: ClassVar[PortfolioMethod] = "maximum_diversification"
    model_id: ClassVar[str] = "maximum-diversification-dependency-free-v1"

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        _require_method(request, self.method)
        _validate_bounds(request)
        tickers = _sorted_tickers(request)
        covariance = _require_covariance(request, tickers)
        volatility = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        if np.any(volatility <= 0.0):
            raise PortfolioModelError("maximum diversification requires positive asset variances")
        scores = np.linalg.solve(_regularize(covariance), volatility)
        weights = _score_weights(np.maximum(scores, 0.0), request)
        return _build_result(request, tickers, weights, "maximum-diversification-calculation-v1")


class BenchmarkTrackingModel:
    method: ClassVar[PortfolioMethod] = "benchmark_tracking"
    model_id: ClassVar[str] = "benchmark-tracking-dependency-free-v1"

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        _require_method(request, self.method)
        _validate_bounds(request)
        tickers = _sorted_tickers(request)
        benchmark = _complete_vector(request.benchmark_weights, tickers, "benchmark weights")
        if np.any(benchmark < 0.0):
            raise PortfolioModelError("long-only benchmark tracking requires non-negative weights")
        if request.covariance or request.volatilities:
            covariance = _regularize(_require_covariance(request, tickers))
            direction = np.linalg.solve(covariance, np.ones(len(tickers)))
            denominator = float(direction.sum())
            if abs(denominator) <= _TOLERANCE:
                raise PortfolioModelError("benchmark tracking covariance is numerically singular")
            scores = benchmark + direction * (
                (request.gross_target - float(benchmark.sum())) / denominator
            )
        else:
            scores = benchmark
        weights = _bounded_simplex(
            scores, request.lower_bound, request.upper_bound, request.gross_target
        )
        return _build_result(request, tickers, weights, "benchmark-tracking-calculation-v1")


_DEPENDENCY_FREE_MODELS: tuple[PortfolioModel, ...] = (
    EqualWeightModel(),
    InverseVolatilityModel(),
    ForecastWeightedModel(),
    ShrinkageMeanRiskModel(),
    RiskBudgetingModel(),
    HierarchicalRiskParityModel(),
    MaximumDiversificationModel(),
    BenchmarkTrackingModel(),
)


class PortfolioModelRegistry:
    """One deterministic model per declared v3B portfolio method."""

    def __init__(self, models: Iterable[PortfolioModel] = _DEPENDENCY_FREE_MODELS) -> None:
        self._models: dict[PortfolioMethod, PortfolioModel] = {}
        for model in models:
            method = getattr(model, "method", None)
            if method is None:
                raise PortfolioModelError("registered portfolio model must declare a method")
            if method in self._models:
                raise PortfolioModelError(f"duplicate portfolio model method: {method}")
            self._models[method] = model

    def get(self, method: PortfolioMethod) -> PortfolioModel:
        try:
            return self._models[method]
        except KeyError as exc:
            raise PortfolioModelError(f"no portfolio model registered for {method}") from exc

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        return self.get(request.method).propose(request)


class SkfolioAdapter:
    """Optional adapter boundary; discovery never imports or installs skfolio."""

    model_id: ClassVar[str] = "skfolio-adapter-v1"

    def __init__(self, fallback: PortfolioModel | None = None) -> None:
        self.fallback = fallback

    @staticmethod
    def available() -> bool:
        return find_spec("skfolio") is not None

    def propose(self, request: PortfolioModelRequest) -> PortfolioModelResult:
        if self.available():
            raise PortfolioDependencyError(
                "skfolio execution is not enabled by the dependency-free v3B implementation"
            )
        if self.fallback is None:
            raise PortfolioDependencyError(
                "skfolio is unavailable and no explicit dependency-free fallback was supplied"
            )
        fallback_result = self.fallback.propose(request)
        fallback_model_id = getattr(self.fallback, "model_id", None)
        if not isinstance(fallback_model_id, str) or fallback_model_id == request.model_id:
            raise PortfolioModelError(
                "fallback must declare a model ID distinct from the request model"
            )
        payload = fallback_result.model_dump(
            exclude={"content_hash", "adapter", "fallback_model_id"}
        )
        return build_hashed(
            PortfolioModelResult,
            **payload,
            adapter="skfolio",
            fallback_model_id=fallback_model_id,
        )


DEFAULT_PORTFOLIO_MODELS = PortfolioModelRegistry()


def propose_portfolio(request: PortfolioModelRequest) -> PortfolioModelResult:
    """Dispatch a request through the default dependency-free registry."""
    return DEFAULT_PORTFOLIO_MODELS.propose(request)
