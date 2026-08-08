"""Confidence- and volatility-aware deterministic portfolio construction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from aegis.contracts import AlphaForecast, PortfolioProposal, canonical_sha256
from aegis.fund.spec import PortfolioPolicy

_VOLATILITY_FLOOR = 0.05


def _turnover(target: Mapping[str, float], current: Mapping[str, float]) -> float:
    names = set(target) | set(current)
    return 0.5 * sum(abs(target.get(name, 0.0) - current.get(name, 0.0)) for name in names)


def construct_portfolio(
    forecasts: tuple[AlphaForecast, ...],
    policy: PortfolioPolicy,
    minimum_confidence: float,
    current_weights: Mapping[str, float] | None = None,
) -> PortfolioProposal:
    """Convert forecasts to weights without any model or I/O calls.

    If every forecast abstains or is ineligible, the existing book is held rather
    than liquidated because of a transient research failure.
    """
    current = dict(sorted((current_weights or {}).items()))
    scores: dict[str, float] = {}
    for forecast in sorted(forecasts, key=lambda item: item.ticker):
        if forecast.abstained or forecast.confidence < minimum_confidence:
            continue
        expected = forecast.expected_excess_return
        volatility = forecast.expected_volatility
        if expected is None or volatility is None:
            continue
        probability_edge = 2.0 * forecast.probability_positive - 1.0
        raw = expected * probability_edge * forecast.confidence / max(volatility, _VOLATILITY_FLOOR)
        if not policy.market_neutral:
            raw = max(raw, 0.0)
        if raw != 0.0:
            scores[forecast.ticker] = raw

    if not scores:
        weights = current
    elif policy.market_neutral:
        mean = sum(scores.values()) / len(scores)
        centered = {ticker: score - mean for ticker, score in scores.items()}
        gross_score = sum(abs(score) for score in centered.values())
        weights = (
            {
                ticker: score / gross_score * policy.gross_target
                for ticker, score in centered.items()
            }
            if gross_score > 1e-12
            else current
        )
    else:
        total = sum(scores.values())
        weights = {ticker: score / total * policy.gross_target for ticker, score in scores.items()}

    weights = {ticker: weight for ticker, weight in sorted(weights.items()) if abs(weight) > 1e-15}
    gross = sum(abs(weight) for weight in weights.values())
    cash = max(0.0, 1.0 - sum(weights.values()))
    input_payload = {
        "forecasts": [forecast.model_dump(mode="json") for forecast in forecasts],
        "portfolio_policy": policy.model_dump(mode="json"),
        "minimum_confidence": minimum_confidence,
        "current_weights": current,
    }
    as_of = forecasts[0].as_of.date() if forecasts else date.min
    return PortfolioProposal(
        as_of=as_of,
        target_weights=weights,
        cash_weight=cash,
        gross_exposure=gross,
        turnover=_turnover(weights, current),
        input_hash=canonical_sha256(input_payload),
    )
