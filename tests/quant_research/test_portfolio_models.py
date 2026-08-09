from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from aegis.contracts import PortfolioModelRequest, canonical_sha256
from aegis.quant_research.hashing import build_hashed
from aegis.quant_research.portfolio_models import (
    DEFAULT_PORTFOLIO_MODELS,
    EqualWeightModel,
    PortfolioDependencyError,
    PortfolioModel,
    PortfolioModelError,
    SkfolioAdapter,
    propose_portfolio,
)

_METHODS = (
    "equal_weight",
    "inverse_volatility",
    "forecast_weighted",
    "shrinkage_mean_risk",
    "risk_budgeting",
    "hierarchical_risk_parity",
    "maximum_diversification",
    "benchmark_tracking",
)
_TICKERS = ("AAA", "BBB", "CCC")
_COVARIANCE = {
    "AAA": {"AAA": 0.04, "BBB": 0.006, "CCC": 0.004},
    "BBB": {"AAA": 0.006, "BBB": 0.09, "CCC": 0.012},
    "CCC": {"AAA": 0.004, "BBB": 0.012, "CCC": 0.16},
}


def _request(method: str, **overrides: Any) -> PortfolioModelRequest:
    payload: dict[str, Any] = {
        "request_id": f"{method.replace('_', '-')}-request-v1",
        "model_id": f"{method.replace('_', '-')}-model-v1",
        "method": method,
        "universe_snapshot_id": "test-universe-snapshot-v1",
        "tickers": _TICKERS,
        "expected_returns": {"AAA": 0.03, "BBB": 0.06, "CCC": 0.09},
        "volatilities": {"AAA": 0.2, "BBB": 0.3, "CCC": 0.4},
        "covariance": _COVARIANCE,
        "benchmark_weights": {"AAA": 0.5, "BBB": 0.3, "CCC": 0.2},
        "lower_bound": 0.05,
        "upper_bound": 0.8,
        "gross_target": 1.0,
        "constraints_hash": canonical_sha256({"lower": 0.05, "upper": 0.8}),
        "input_snapshot_hashes": (canonical_sha256({"snapshot": 1}),),
        "as_of": datetime(2024, 1, 31, tzinfo=UTC),
        "available_at": datetime(2024, 1, 30, tzinfo=UTC),
    }
    payload.update(overrides)
    return build_hashed(PortfolioModelRequest, **payload)


@pytest.mark.parametrize("method", _METHODS)
def test_all_dependency_free_models_are_bounded_deterministic_and_auditable(method: str) -> None:
    request = _request(method)

    result = propose_portfolio(request)
    repeated = DEFAULT_PORTFOLIO_MODELS.propose(request)

    assert result == repeated
    assert result.method == method
    assert result.model_id == request.model_id
    assert result.request_id == request.request_id
    assert result.input_hash == request.content_hash
    assert result.adapter == "dependency_free"
    assert result.fallback_model_id is None
    assert result.calculation_ids
    assert set(result.weights) == set(request.tickers)
    assert all(
        request.lower_bound - 1e-12 <= weight <= request.upper_bound + 1e-12
        for weight in result.weights.values()
    )
    assert result.gross_exposure == pytest.approx(request.gross_target, abs=1e-12)
    assert result.net_exposure == pytest.approx(request.gross_target, abs=1e-12)
    assert result.expected_return == pytest.approx(
        sum(result.weights[ticker] * request.expected_returns[ticker] for ticker in request.tickers)
    )
    variance = sum(
        result.weights[left] * request.covariance[left][right] * result.weights[right]
        for left in request.tickers
        for right in request.tickers
    )
    assert result.expected_volatility == pytest.approx(variance**0.5)


@pytest.mark.parametrize("method", _METHODS)
def test_models_are_invariant_to_request_permutation(method: str) -> None:
    original = propose_portfolio(_request(method))
    order = ("CCC", "AAA", "BBB")
    permuted_covariance = {
        left: {right: _COVARIANCE[left][right] for right in order} for left in order
    }
    permuted = propose_portfolio(
        _request(
            method,
            tickers=order,
            expected_returns={
                ticker: {"AAA": 0.03, "BBB": 0.06, "CCC": 0.09}[ticker] for ticker in order
            },
            volatilities={ticker: {"AAA": 0.2, "BBB": 0.3, "CCC": 0.4}[ticker] for ticker in order},
            covariance=permuted_covariance,
            benchmark_weights={
                ticker: {"AAA": 0.5, "BBB": 0.3, "CCC": 0.2}[ticker] for ticker in order
            },
        )
    )

    assert permuted.weights == pytest.approx(original.weights, abs=1e-12)
    assert permuted.expected_return == pytest.approx(original.expected_return, abs=1e-12)
    assert permuted.expected_volatility == pytest.approx(original.expected_volatility, abs=1e-12)


@pytest.mark.parametrize(
    "method",
    (
        "shrinkage_mean_risk",
        "risk_budgeting",
        "hierarchical_risk_parity",
        "maximum_diversification",
        "benchmark_tracking",
    ),
)
def test_covariance_models_handle_singular_inputs(method: str) -> None:
    singular = {
        "AAA": {"AAA": 0.04, "BBB": 0.04, "CCC": 0.02},
        "BBB": {"AAA": 0.04, "BBB": 0.04, "CCC": 0.02},
        "CCC": {"AAA": 0.02, "BBB": 0.02, "CCC": 0.01},
    }
    request = _request(method, covariance=singular)

    result = propose_portfolio(request)

    assert result.gross_exposure == pytest.approx(1.0)
    assert result.expected_volatility >= 0.0


def test_protocol_and_registry_dispatch() -> None:
    model = EqualWeightModel()

    assert isinstance(model, PortfolioModel)
    assert DEFAULT_PORTFOLIO_MODELS.get("equal_weight") is not None
    with pytest.raises(PortfolioModelError, match="cannot evaluate"):
        model.propose(_request("inverse_volatility"))


def test_infeasible_and_missing_inputs_fail_loudly() -> None:
    with pytest.raises(PortfolioModelError, match="infeasible"):
        propose_portfolio(_request("equal_weight", lower_bound=0.5))
    with pytest.raises(PortfolioModelError, match="missing tickers"):
        propose_portfolio(_request("forecast_weighted", expected_returns={"AAA": 0.03}))


def test_skfolio_absence_is_explicit_and_can_use_named_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("aegis.quant_research.portfolio_models.find_spec", lambda _name: None)
    request = _request("equal_weight", model_id="requested-skfolio-model-v1")

    assert not SkfolioAdapter.available()
    with pytest.raises(PortfolioDependencyError, match="no explicit"):
        SkfolioAdapter().propose(request)

    result = SkfolioAdapter(fallback=EqualWeightModel()).propose(request)
    assert result.adapter == "skfolio"
    assert result.fallback_model_id == EqualWeightModel.model_id
    assert result.model_id == request.model_id
    assert result.input_hash == request.content_hash
    assert result.gross_exposure == pytest.approx(1.0)
