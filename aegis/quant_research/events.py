"""Deterministic, point-in-time market-model event studies.

The engine deliberately consumes observations with both an observation timestamp and an
availability timestamp.  Calendar alignment, regression, bootstrap sampling, and identifiers are
all deterministic; observations unavailable at the requested cutoff are ignored.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from aegis.contracts import (
    BootstrapInterval,
    EventStudyResult,
    EventStudySpec,
    MarketEvent,
    canonical_sha256,
)

from .hashing import build_hashed

_EPSILON: Final = 1e-15


@dataclass(frozen=True, slots=True)
class ReturnObservation:
    """A sourced simple return known at ``available_at``.

    ``observed_at`` identifies the end of the return period.  The event day is the first supplied
    return period whose timestamp is not before the event occurrence timestamp.
    """

    ticker: str
    observed_at: datetime
    available_at: datetime
    value: float
    source_id: str

    def __post_init__(self) -> None:
        if not self.ticker.strip():
            raise ValueError("return ticker must not be empty")
        if self.observed_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("return timestamps must be timezone-aware")
        if self.observed_at > self.available_at:
            raise ValueError("a return cannot be available before it is observed")
        if not math.isfinite(self.value):
            raise ValueError("return value must be finite")
        if not self.source_id.strip():
            raise ValueError("return source_id must not be empty")


def car_window_key(start: int, end: int) -> str:
    """Return the stable external key for an inclusive CAR window."""
    return f"{start}:{end}"


def _stable_id(prefix: str, payload: object) -> str:
    return f"{prefix}-{canonical_sha256(payload)[:20]}-v1"


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _fit_market_model(asset: Sequence[float], market: Sequence[float]) -> tuple[float, float]:
    if len(asset) != len(market) or len(asset) < 2:
        raise ValueError("market-model estimation requires at least two aligned observations")
    market_mean = _mean(market)
    asset_mean = _mean(asset)
    market_ss = math.fsum((item - market_mean) ** 2 for item in market)
    if market_ss <= _EPSILON:
        raise ValueError("market-model benchmark variance must be positive")
    covariance = math.fsum(
        (market_item - market_mean) * (asset_item - asset_mean)
        for asset_item, market_item in zip(asset, market, strict=True)
    )
    beta = covariance / market_ss
    return asset_mean - beta * market_mean, beta


def _quantile(values: Sequence[float], probability: float) -> float:
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


def _bootstrap_interval(
    values: Sequence[float], *, samples: int, confidence: float, rng: random.Random
) -> BootstrapInterval:
    estimates = [
        _mean([values[rng.randrange(len(values))] for _ in range(len(values))])
        for _ in range(samples)
    ]
    tail = (1.0 - confidence) / 2.0
    return BootstrapInterval(
        lower=_quantile(estimates, tail),
        upper=_quantile(estimates, 1.0 - tail),
    )


def _linear_slope(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    if len(x_values) < 2 or len(x_values) != len(y_values):
        return None
    x_mean = _mean(x_values)
    denominator = math.fsum((item - x_mean) ** 2 for item in x_values)
    if denominator <= _EPSILON:
        return None
    y_mean = _mean(y_values)
    return (
        math.fsum(
            (x_item - x_mean) * (y_item - y_mean)
            for x_item, y_item in zip(x_values, y_values, strict=True)
        )
        / denominator
    )


def _validate_cutoff(as_of: datetime) -> None:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")


def _safe_returns(
    observations: Sequence[ReturnObservation], *, as_of: datetime
) -> dict[str, list[ReturnObservation]]:
    by_ticker: dict[str, list[ReturnObservation]] = defaultdict(list)
    seen: set[tuple[str, datetime]] = set()
    for observation in observations:
        if observation.available_at > as_of:
            continue
        ticker = observation.ticker.strip().upper()
        identity = (ticker, observation.observed_at)
        if identity in seen:
            raise ValueError("return observations must be unique by ticker and observed_at")
        seen.add(identity)
        by_ticker[ticker].append(observation)
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda item: (item.observed_at, item.source_id))
    return by_ticker


def run_event_study(
    spec: EventStudySpec,
    events: Sequence[MarketEvent],
    returns: Sequence[ReturnObservation],
    *,
    as_of: datetime,
    seed: int,
) -> EventStudyResult:
    """Run a market-model event study using only cutoff-safe supplied observations.

    Market-model alpha and beta are fitted independently for each event over the inclusive
    estimation offsets in ``spec``. CARs are event-level sums and the reported CAR is their mean.
    The percentile bootstrap resamples event CARs using the mandatory explicit ``seed``.
    """
    _validate_cutoff(as_of)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("bootstrap seed must be an integer")

    selected = sorted(
        (
            event
            for event in events
            if event.event_type in spec.event_types
            and event.as_of <= as_of
            and event.available_at <= as_of
            and event.occurred_at <= as_of
        ),
        key=lambda event: (event.occurred_at, event.event_id),
    )
    if not selected:
        raise ValueError("event study requires at least one cutoff-safe matching event")
    if len({event.event_id for event in selected}) != len(selected):
        raise ValueError("event IDs must be unique")

    by_ticker = _safe_returns(returns, as_of=as_of)
    benchmark_ticker = spec.benchmark_ticker.upper()
    benchmark = by_ticker.get(benchmark_ticker, [])
    if not benchmark:
        raise ValueError("event study requires cutoff-safe benchmark returns")
    benchmark_by_time = {item.observed_at: item for item in benchmark}

    event_cars: dict[str, dict[str, float]] = {}
    event_abnormal: dict[str, dict[int, float]] = {}
    event_residual_scale: dict[str, float] = {}
    used_returns: list[ReturnObservation] = []

    for event in selected:
        asset = by_ticker.get(event.ticker.upper(), [])
        aligned = [
            (asset_item, benchmark_by_time[asset_item.observed_at])
            for asset_item in asset
            if asset_item.observed_at in benchmark_by_time
        ]
        event_index = next(
            (
                index
                for index, pair in enumerate(aligned)
                if pair[0].observed_at >= event.occurred_at
            ),
            None,
        )
        if event_index is None:
            raise ValueError(f"event {event.event_id} has no aligned return on or after occurrence")
        by_offset = {index - event_index: pair for index, pair in enumerate(aligned)}
        estimation_offsets = range(spec.estimation_window_start, spec.estimation_window_end + 1)
        if any(offset not in by_offset for offset in estimation_offsets):
            raise ValueError(f"event {event.event_id} has an incomplete estimation window")
        estimation_pairs = [by_offset[offset] for offset in estimation_offsets]
        alpha, beta = _fit_market_model(
            [pair[0].value for pair in estimation_pairs],
            [pair[1].value for pair in estimation_pairs],
        )
        required_offsets = set(estimation_offsets)
        for start, end in spec.car_windows:
            required_offsets.update(range(start, end + 1))
        required_offsets.update(range(-spec.pre_event_leakage_days, 0))
        if any(offset not in by_offset for offset in required_offsets):
            raise ValueError(f"event {event.event_id} has an incomplete CAR or leakage window")
        abnormal = {
            offset: pair[0].value - (alpha + beta * pair[1].value)
            for offset, pair in by_offset.items()
            if offset in required_offsets
        }
        event_abnormal[event.event_id] = abnormal
        residuals = [pair[0].value - (alpha + beta * pair[1].value) for pair in estimation_pairs]
        event_residual_scale[event.event_id] = math.sqrt(
            math.fsum(value**2 for value in residuals) / max(1, len(residuals) - 2)
        )
        event_cars[event.event_id] = {
            car_window_key(start, end): math.fsum(
                abnormal[offset] for offset in range(start, end + 1)
            )
            for start, end in spec.car_windows
        }
        for offset in sorted(required_offsets):
            used_returns.extend(by_offset[offset])

    keys = [car_window_key(start, end) for start, end in spec.car_windows]
    aggregate_cars = {
        key: _mean([event_cars[event.event_id][key] for event in selected]) for key in keys
    }
    rng = random.Random(seed)
    intervals = {
        key: _bootstrap_interval(
            [event_cars[event.event_id][key] for event in selected],
            samples=spec.bootstrap_samples,
            confidence=spec.confidence_level,
            rng=rng,
        )
        for key in keys
    }

    segments: dict[str, float] = {}
    if spec.segment_by_source_type:
        source_types = sorted({event.source_type for event in selected})
        for source_type in source_types:
            source_events = [event for event in selected if event.source_type == source_type]
            for key in keys:
                segments[f"{source_type}|{key}"] = _mean(
                    [event_cars[event.event_id][key] for event in source_events]
                )

    surprise_slope: float | None = None
    if spec.include_surprise:
        with_surprise = [event for event in selected if event.surprise is not None]
        surprise_values: list[float] = []
        for event in with_surprise:
            if event.surprise is None:  # defensive narrowing for typed callers
                continue
            surprise_values.append(event.surprise)
        surprise_slope = _linear_slope(
            surprise_values,
            [event_cars[event.event_id][keys[0]] for event in with_surprise],
        )

    leakage_detected = False
    leakage_count = spec.pre_event_leakage_days
    for event in selected:
        leakage_car = math.fsum(
            event_abnormal[event.event_id][offset] for offset in range(-leakage_count, 0)
        )
        threshold = 2.0 * event_residual_scale[event.event_id] * math.sqrt(leakage_count)
        if abs(leakage_car) > max(threshold, _EPSILON):
            leakage_detected = True
            break

    unique_used = sorted(
        {
            (item.ticker.upper(), item.observed_at, item.available_at, item.value, item.source_id)
            for item in used_returns
        },
        key=lambda item: (item[0], item[1], item[4]),
    )
    input_payload = {
        "spec": spec,
        "events": selected,
        "returns": unique_used,
        "as_of": as_of,
        "seed": seed,
    }
    calculation_ids = tuple(
        [_stable_id("event-market-model-calculation", input_payload)]
        + [
            _stable_id("event-car-calculation", {"input": input_payload, "window": key})
            for key in keys
        ]
        + [_stable_id("event-bootstrap-calculation", {"input": input_payload, "seed": seed})]
    )
    available_at = max(
        [event.available_at for event in selected] + [item.available_at for item in used_returns]
    )
    result_payload = {
        "spec_id": spec.spec_id,
        "event_ids": tuple(event.event_id for event in selected),
        "cars": aggregate_cars,
        "intervals": intervals,
        "segments": segments,
        "surprise_slope": surprise_slope,
        "leakage": leakage_detected,
        "calculations": calculation_ids,
        "as_of": as_of,
        "available_at": available_at,
    }
    return build_hashed(
        EventStudyResult,
        result_id=_stable_id("event-study-result", result_payload),
        spec_id=spec.spec_id,
        event_ids=tuple(event.event_id for event in selected),
        as_of=as_of,
        available_at=available_at,
        cumulative_abnormal_returns=aggregate_cars,
        bootstrap_intervals=intervals,
        source_segment_cars=segments,
        surprise_slope=surprise_slope,
        pre_event_leakage_detected=leakage_detected,
        calculation_ids=calculation_ids,
    )
