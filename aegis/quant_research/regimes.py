"""Deterministic six-axis regime classification from supplied numeric observations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from aegis.contracts import RegimeSnapshot, canonical_sha256

from .hashing import build_hashed

FactorFamilyName = Literal[
    "value",
    "quality",
    "profitability",
    "investment",
    "momentum",
    "reversal",
    "volatility",
    "liquidity",
    "earnings_revisions",
    "pead",
    "behavioral_attention",
    "expectations_gap",
    "graph_relationship_risk",
]
_ALLOWED_FACTORS: frozenset[str] = frozenset(
    {
        "value",
        "quality",
        "profitability",
        "investment",
        "momentum",
        "reversal",
        "volatility",
        "liquidity",
        "earnings_revisions",
        "pead",
        "behavioral_attention",
        "expectations_gap",
        "graph_relationship_risk",
    }
)


@dataclass(frozen=True, slots=True)
class NumericObservation:
    """One point-in-time numeric input to a regime axis."""

    observed_at: datetime
    available_at: datetime
    value: float
    source_id: str

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("regime observation timestamps must be timezone-aware")
        if self.observed_at > self.available_at:
            raise ValueError("a regime observation cannot be available before it is observed")
        if not math.isfinite(self.value):
            raise ValueError("regime observation value must be finite")
        if not self.source_id.strip():
            raise ValueError("regime observation source_id must not be empty")


@dataclass(frozen=True, slots=True)
class RegimeInputs:
    """Supplied series for each of the six required regime axes.

    ``rates_liquidity`` is a signed tightening score (positive means tightening), while
    ``risk_appetite`` is a signed risk-appetite score (positive means risk-on). ``correlations``
    contains pairwise correlation observations on their natural [-1, 1] scale.
    """

    as_of: datetime
    volatility: Sequence[NumericObservation]
    market_returns: Sequence[NumericObservation]
    rates_liquidity: Sequence[NumericObservation]
    risk_appetite: Sequence[NumericObservation]
    factor_returns: Mapping[FactorFamilyName, Sequence[NumericObservation]]
    correlations: Sequence[NumericObservation]
    model_id: str = "deterministic-regime-model-v1"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("regime as_of must be timezone-aware")
        if not self.model_id.strip():
            raise ValueError("regime model_id must not be empty")
        if not self.factor_returns:
            raise ValueError("factor_returns must contain at least one factor family")
        unknown = set(self.factor_returns) - _ALLOWED_FACTORS
        if unknown:
            raise ValueError(f"unknown factor families: {sorted(unknown)}")


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}-{canonical_sha256(payload)[:20]}-v1"


def _safe(
    values: Sequence[NumericObservation], *, as_of: datetime, label: str
) -> list[NumericObservation]:
    selected = sorted(
        (item for item in values if item.available_at <= as_of),
        key=lambda item: (item.observed_at, item.available_at, item.source_id),
    )
    if not selected:
        raise ValueError(f"{label} requires at least one cutoff-safe observation")
    identities = [(item.observed_at, item.source_id) for item in selected]
    if len(set(identities)) != len(identities):
        raise ValueError(f"{label} observations must be unique by timestamp and source")
    return selected


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _linear_quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def classify_regime(inputs: RegimeInputs) -> RegimeSnapshot:
    """Classify all six required axes using transparent deterministic rules."""
    volatility = _safe(inputs.volatility, as_of=inputs.as_of, label="volatility")
    market = _safe(inputs.market_returns, as_of=inputs.as_of, label="market_returns")
    rates = _safe(inputs.rates_liquidity, as_of=inputs.as_of, label="rates_liquidity")
    risk = _safe(inputs.risk_appetite, as_of=inputs.as_of, label="risk_appetite")
    correlations = _safe(inputs.correlations, as_of=inputs.as_of, label="correlations")
    factors = {
        name: _safe(values, as_of=inputs.as_of, label=f"factor_returns[{name}]")
        for name, values in sorted(inputs.factor_returns.items())
    }

    volatility_values = [item.value for item in volatility]
    latest_volatility = volatility[-1].value
    low_cutoff = _linear_quantile(volatility_values, 0.25)
    high_cutoff = _linear_quantile(volatility_values, 0.75)
    crisis_cutoff = _linear_quantile(volatility_values, 0.90)
    if latest_volatility >= crisis_cutoff and len(volatility_values) >= 4:
        volatility_regime = "crisis"
    elif latest_volatility >= high_cutoff:
        volatility_regime = "high"
    elif latest_volatility <= low_cutoff:
        volatility_regime = "low"
    else:
        volatility_regime = "normal"

    market_values = [item.value for item in market]
    market_mean = _mean(market_values)
    market_scale = math.sqrt(
        _mean([(item - market_mean) ** 2 for item in market_values])
    ) / math.sqrt(len(market_values))
    trend_threshold = 0.1 * market_scale
    if market_mean > trend_threshold:
        market_trend = "up"
    elif market_mean < -trend_threshold:
        market_trend = "down"
    else:
        market_trend = "sideways"

    rates_score = _mean([item.value for item in rates])
    if rates_score > 0.0:
        rates_context = "tightening"
    elif rates_score < 0.0:
        rates_context = "easing"
    else:
        rates_context = "neutral"

    risk_score = _mean([item.value for item in risk])
    if risk_score > 0.0:
        risk_state = "risk_on"
    elif risk_score < 0.0:
        risk_state = "risk_off"
    else:
        risk_state = "neutral"

    ranked_factors = sorted(
        (
            (_mean([item.value for item in observations]), name)
            for name, observations in factors.items()
        ),
        key=lambda item: (-item[0], item[1]),
    )
    factor_leadership = tuple(name for _, name in ranked_factors)

    correlation_score = _mean([item.value for item in correlations])
    if correlation_score < 0.25:
        correlation_regime = "low"
    elif correlation_score > 0.65:
        correlation_regime = "high"
    else:
        correlation_regime = "normal"

    safe_payload = {
        "as_of": inputs.as_of,
        "model_id": inputs.model_id,
        "volatility": [asdict(item) for item in volatility],
        "market_returns": [asdict(item) for item in market],
        "rates_liquidity": [asdict(item) for item in rates],
        "risk_appetite": [asdict(item) for item in risk],
        "factor_returns": {
            name: [asdict(item) for item in observations] for name, observations in factors.items()
        },
        "correlations": [asdict(item) for item in correlations],
    }
    calculation_ids = tuple(
        _stable_id(f"regime-{axis}-calculation", safe_payload)
        for axis in (
            "volatility",
            "trend",
            "rates-liquidity",
            "risk-state",
            "factor-leadership",
            "correlation",
        )
    )
    all_observations = (
        volatility
        + market
        + rates
        + risk
        + correlations
        + [item for observations in factors.values() for item in observations]
    )
    available_at = max(item.available_at for item in all_observations)
    result_payload = {
        "input": safe_payload,
        "volatility_regime": volatility_regime,
        "market_trend": market_trend,
        "rates_liquidity_context": rates_context,
        "risk_state": risk_state,
        "factor_leadership": factor_leadership,
        "correlation_regime": correlation_regime,
    }
    return build_hashed(
        RegimeSnapshot,
        snapshot_id=_stable_id("regime-snapshot", result_payload),
        as_of=inputs.as_of,
        available_at=available_at,
        volatility_regime=volatility_regime,
        market_trend=market_trend,
        rates_liquidity_context=rates_context,
        risk_state=risk_state,
        factor_leadership=factor_leadership,
        correlation_regime=correlation_regime,
        model_id=inputs.model_id,
        calculation_ids=calculation_ids,
    )
