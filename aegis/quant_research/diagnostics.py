"""Deterministic, leakage-safe cross-sectional factor diagnostics."""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from aegis.contracts._base import normalize_ticker
from aegis.contracts.quant import FactorDiagnostics, FactorEvaluation
from aegis.quant_research.hashing import build_hashed


@dataclass(frozen=True, slots=True)
class DiagnosticObservation:
    """A signal paired with a strictly subsequent realized return.

    The feature must have been available by ``as_of`` and the realized-return window may
    not begin before ``as_of``.  Decay returns and comparison-factor values are explicit,
    preventing the diagnostics layer from reaching into a mutable future feature table.
    """

    observation_id: str
    universe_snapshot_id: str
    calculation_id: str
    ticker: str
    as_of: datetime
    feature_available_at: datetime
    return_start_at: datetime
    return_end_at: datetime
    factor_value: float
    forward_return: float
    sector: str | None
    market_cap: float
    average_daily_dollar_volume: float
    subperiod: str = "all"
    regime: str = "all"
    decay_returns: tuple[tuple[int, float], ...] = ()
    comparison_factors: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        timestamps = (
            self.as_of,
            self.feature_available_at,
            self.return_start_at,
            self.return_end_at,
        )
        if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
            raise ValueError("diagnostic timestamps must be timezone-aware")
        if self.feature_available_at > self.as_of:
            raise ValueError("factor feature was unavailable at its as_of cutoff")
        if self.return_start_at < self.as_of:
            raise ValueError("forward return starts before the factor as_of cutoff")
        if self.return_end_at < self.return_start_at:
            raise ValueError("forward return end precedes its start")
        numeric = (
            self.factor_value,
            self.forward_return,
            self.market_cap,
            self.average_daily_dollar_volume,
            *(value for _, value in self.decay_returns),
            *(value for _, value in self.comparison_factors),
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("diagnostic numeric inputs must be finite")
        if self.market_cap <= 0.0:
            raise ValueError("market_cap must be positive")
        if self.average_daily_dollar_volume < 0.0:
            raise ValueError("average_daily_dollar_volume cannot be negative")
        decay_lags = [lag for lag, _ in self.decay_returns]
        if any(lag <= 0 for lag in decay_lags) or len(set(decay_lags)) != len(decay_lags):
            raise ValueError("decay lags must be unique and positive")
        comparison_ids = [factor_id for factor_id, _ in self.comparison_factors]
        if len(set(comparison_ids)) != len(comparison_ids):
            raise ValueError("comparison factor IDs must be unique")
        if not self.subperiod or not self.regime:
            raise ValueError("subperiod and regime labels cannot be empty")


def _mean(values: Iterable[float]) -> float:
    materialized = tuple(values)
    return sum(materialized) / len(materialized) if materialized else 0.0


def _pearson(left: Iterable[float], right: Iterable[float]) -> float:
    xs, ys = tuple(left), tuple(right)
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    x_mean, y_mean = _mean(xs), _mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    x_ss = sum((x - x_mean) ** 2 for x in xs)
    y_ss = sum((y - y_mean) ** 2 for y in ys)
    denominator = math.sqrt(x_ss * y_ss)
    return numerator / denominator if denominator > 0.0 else 0.0


def _ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    """Average ranks for ties, using zero-based ranks (affine-equivalent to standard ranks)."""
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    result = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position + 1
        while end < len(order) and values[order[end]] == values[order[position]]:
            end += 1
        rank = (position + end - 1) / 2.0
        for ordered_index in order[position:end]:
            result[ordered_index] = rank
        position = end
    return tuple(result)


def _spearman(left: Iterable[float], right: Iterable[float]) -> float:
    xs, ys = tuple(left), tuple(right)
    if len(xs) != len(ys):
        return 0.0
    return _pearson(_ranks(xs), _ranks(ys))


def _group_by_date(
    observations: tuple[DiagnosticObservation, ...],
) -> dict[datetime, tuple[DiagnosticObservation, ...]]:
    grouped: dict[datetime, list[DiagnosticObservation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.as_of.astimezone(UTC)].append(observation)
    return {
        timestamp: tuple(sorted(rows, key=lambda row: row.ticker))
        for timestamp, rows in sorted(grouped.items())
    }


def _bucketed(
    rows: tuple[DiagnosticObservation, ...], quantiles: int
) -> tuple[tuple[DiagnosticObservation, ...], ...]:
    ordered = sorted(rows, key=lambda row: (row.factor_value, row.ticker))
    buckets: list[list[DiagnosticObservation]] = [[] for _ in range(quantiles)]
    for rank, row in enumerate(ordered):
        bucket = min(quantiles - 1, rank * quantiles // len(ordered))
        buckets[bucket].append(row)
    return tuple(tuple(bucket) for bucket in buckets)


def _long_short_by_date(
    grouped: dict[datetime, tuple[DiagnosticObservation, ...]], quantiles: int
) -> dict[datetime, float]:
    return {
        timestamp: _mean(row.forward_return for row in buckets[-1])
        - _mean(row.forward_return for row in buckets[0])
        for timestamp, rows in grouped.items()
        for buckets in (_bucketed(rows, quantiles),)
    }


def _turnover(grouped: dict[datetime, tuple[DiagnosticObservation, ...]], quantiles: int) -> float:
    weights: list[dict[str, float]] = []
    for rows in grouped.values():
        buckets = _bucketed(rows, quantiles)
        low, high = buckets[0], buckets[-1]
        current = {row.ticker: -1.0 / len(low) for row in low}
        current.update({row.ticker: 1.0 / len(high) for row in high})
        weights.append(current)
    changes = []
    for previous, current in itertools.pairwise(weights):
        tickers = set(previous) | set(current)
        changes.append(0.5 * sum(abs(current.get(t, 0.0) - previous.get(t, 0.0)) for t in tickers))
    return _mean(changes)


def _autocorrelation(
    grouped: dict[datetime, tuple[DiagnosticObservation, ...]],
) -> float:
    correlations: list[float] = []
    periods = list(grouped.values())
    for previous, current in itertools.pairwise(periods):
        old = {row.ticker: row.factor_value for row in previous}
        new = {row.ticker: row.factor_value for row in current}
        common = sorted(set(old) & set(new))
        if len(common) >= 2:
            correlations.append(_pearson((old[t] for t in common), (new[t] for t in common)))
    return _mean(correlations)


def _sector_neutrality(
    grouped: dict[datetime, tuple[DiagnosticObservation, ...]],
) -> float:
    exposures: list[float] = []
    for rows in grouped.values():
        values = tuple(row.factor_value for row in rows)
        mean = _mean(values)
        std = math.sqrt(_mean((value - mean) ** 2 for value in values))
        if std == 0.0:
            exposures.append(0.0)
            continue
        sectors: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            sectors[row.sector or "<missing>"].append((row.factor_value - mean) / std)
        exposures.append(_mean(abs(_mean(group)) for group in sectors.values()))
    return _mean(exposures)


def _size_neutrality(
    grouped: dict[datetime, tuple[DiagnosticObservation, ...]],
) -> float:
    return _mean(
        abs(
            _pearson(
                (row.factor_value for row in rows),
                (math.log(row.market_cap) for row in rows),
            )
        )
        for rows in grouped.values()
    )


def _labeled_returns(
    observations: tuple[DiagnosticObservation, ...],
    daily_long_short: dict[datetime, float],
    attribute: str,
) -> dict[str, float]:
    labels: dict[datetime, set[str]] = defaultdict(set)
    for row in observations:
        labels[row.as_of.astimezone(UTC)].add(str(getattr(row, attribute)))
    by_label: dict[str, list[float]] = defaultdict(list)
    for timestamp, values in labels.items():
        if len(values) != 1:
            raise ValueError(f"inconsistent {attribute} labels within one cross-section")
        by_label[next(iter(values))].append(daily_long_short[timestamp])
    return {label: _mean(by_label[label]) for label in sorted(by_label)}


def compute_factor_diagnostics(
    observations: tuple[DiagnosticObservation, ...],
    *,
    quantiles: int = 5,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    capacity_participation_rate: float = 0.01,
) -> FactorDiagnostics:
    """Compute all v3B diagnostic fields from causally paired cross-sections.

    IC and rank IC are the means of date-level cross-sectional correlations.  ICIR is
    mean IC divided by its population standard deviation (zero for one/constant period).
    Quantile and long-short returns are date-level means subsequently averaged through
    time.  Costs apply to measured one-way turnover.
    """
    if len(observations) < 2:
        raise ValueError("at least two diagnostic observations are required")
    if quantiles < 2:
        raise ValueError("quantiles must be at least two")
    if commission_bps < 0.0 or slippage_bps < 0.0:
        raise ValueError("cost assumptions cannot be negative")
    if not 0.0 <= capacity_participation_rate <= 1.0:
        raise ValueError("capacity_participation_rate must be in [0, 1]")
    ids = [row.observation_id for row in observations]
    if len(set(ids)) != len(ids):
        raise ValueError("diagnostic observation IDs must be unique")

    grouped = _group_by_date(observations)
    smallest_cross_section = min(len(rows) for rows in grouped.values())
    actual_quantiles = min(quantiles, smallest_cross_section)
    if actual_quantiles < 2:
        raise ValueError("every diagnostic cross-section needs at least two observations")

    pearson_ics = [
        _pearson(
            (row.factor_value for row in rows),
            (row.forward_return for row in rows),
        )
        for rows in grouped.values()
    ]
    rank_ics = [
        _spearman(
            (row.factor_value for row in rows),
            (row.forward_return for row in rows),
        )
        for rows in grouped.values()
    ]
    information_coefficient = _mean(pearson_ics)
    rank_information_coefficient = _mean(rank_ics)
    ic_std = math.sqrt(_mean((value - information_coefficient) ** 2 for value in pearson_ics))
    icir = information_coefficient / ic_std if ic_std > 0.0 else 0.0

    quantile_period_returns: list[list[float]] = [[] for _ in range(actual_quantiles)]
    for rows in grouped.values():
        for index, bucket in enumerate(_bucketed(rows, actual_quantiles)):
            quantile_period_returns[index].append(_mean(row.forward_return for row in bucket))
    quantile_returns = tuple(_mean(values) for values in quantile_period_returns)
    daily_long_short = _long_short_by_date(grouped, actual_quantiles)
    gross_return = _mean(daily_long_short.values())
    turnover = _turnover(grouped, actual_quantiles)
    cost_adjusted_return = gross_return - turnover * (commission_bps + slippage_bps) / 10_000.0

    selected_adv: list[float] = []
    for rows in grouped.values():
        buckets = _bucketed(rows, actual_quantiles)
        selected_adv.extend(row.average_daily_dollar_volume for row in (*buckets[0], *buckets[-1]))
    capacity = min(selected_adv) * capacity_participation_rate if selected_adv else 0.0

    decay_lags = sorted({lag for row in observations for lag, _ in row.decay_returns})
    decay: dict[int, float] = {}
    for lag in decay_lags:
        eligible = [
            (row.factor_value, dict(row.decay_returns)[lag])
            for row in observations
            if lag in dict(row.decay_returns)
        ]
        decay[lag] = _pearson((item[0] for item in eligible), (item[1] for item in eligible))

    comparison_ids = sorted(
        {factor_id for row in observations for factor_id, _ in row.comparison_factors}
    )
    factor_correlations: dict[str, float] = {}
    for factor_id in comparison_ids:
        eligible_comparisons = [
            (row.factor_value, dict(row.comparison_factors)[factor_id])
            for row in observations
            if factor_id in dict(row.comparison_factors)
        ]
        factor_correlations[factor_id] = _pearson(
            (item[0] for item in eligible_comparisons),
            (item[1] for item in eligible_comparisons),
        )
    crowding_score = _mean(abs(value) for value in factor_correlations.values())

    return FactorDiagnostics(
        information_coefficient=information_coefficient,
        rank_information_coefficient=rank_information_coefficient,
        icir=icir,
        quantile_returns=quantile_returns,
        long_short_return=gross_return,
        monotonicity=_spearman(
            tuple(float(index) for index in range(actual_quantiles)), quantile_returns
        ),
        turnover=turnover,
        autocorrelation=_autocorrelation(grouped),
        sector_neutrality=_sector_neutrality(grouped),
        size_neutrality=_size_neutrality(grouped),
        subperiod_returns=_labeled_returns(observations, daily_long_short, "subperiod"),
        regime_returns=_labeled_returns(observations, daily_long_short, "regime"),
        gross_return=gross_return,
        cost_adjusted_return=cost_adjusted_return,
        capacity=capacity,
        decay=decay,
        factor_correlations=factor_correlations,
        crowding_score=crowding_score,
    )


def build_factor_evaluation(
    *,
    evaluation_id: str,
    factor_id: str,
    observations: tuple[DiagnosticObservation, ...],
    evaluation_as_of: datetime,
    diagnostics: FactorDiagnostics,
) -> FactorEvaluation:
    """Bind diagnostics and complete lineage into the frozen evaluation contract."""
    if evaluation_as_of.tzinfo is None or evaluation_as_of.utcoffset() is None:
        raise ValueError("evaluation_as_of must be timezone-aware")
    if not observations:
        raise ValueError("factor evaluation requires observations")
    if any(row.return_end_at > evaluation_as_of for row in observations):
        raise ValueError("evaluation cannot be available before its realized returns")
    ordered = tuple(
        sorted(observations, key=lambda row: (row.as_of, row.ticker, row.observation_id))
    )
    return build_hashed(
        FactorEvaluation,
        evaluation_id=evaluation_id,
        factor_id=factor_id,
        universe_snapshot_ids=tuple(sorted({row.universe_snapshot_id for row in ordered})),
        observation_ids=tuple(row.observation_id for row in ordered),
        period_start=min(row.as_of.date() for row in ordered),
        period_end=max(row.return_end_at.date() for row in ordered),
        diagnostics=diagnostics,
        calculation_ids=tuple(sorted({row.calculation_id for row in ordered})),
        as_of=evaluation_as_of,
        available_at=evaluation_as_of,
    )
