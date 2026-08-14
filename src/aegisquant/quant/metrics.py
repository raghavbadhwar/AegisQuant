"""Small deterministic performance statistics for fixture research reports."""

from __future__ import annotations

from decimal import Decimal
from random import Random

from aegisquant.contracts.research import PerformanceReport


def walk_forward_windows(
    observations: int, *, training_observations: int, test_observations: int, step: int
) -> tuple[tuple[int, int, int, int], ...]:
    """Deterministic, non-overlapping out-of-sample windows for fixture trials."""

    if min(observations, training_observations, test_observations, step) < 1:
        raise ValueError("walk-forward dimensions must be positive")
    if step < test_observations:
        raise ValueError("walk-forward step must not overlap out-of-sample observations")
    windows: list[tuple[int, int, int, int]] = []
    train_start = 0
    while train_start + training_observations + test_observations <= observations:
        train_end = train_start + training_observations
        windows.append((train_start, train_end, train_end, train_end + test_observations))
        train_start += step
    if not windows:
        raise ValueError("insufficient observations for one walk-forward window")
    return tuple(windows)


def placebo_returns(returns: tuple[Decimal, ...], *, shift: int) -> tuple[Decimal, ...]:
    """A deterministic rotation baseline with no fitted parameters."""

    if not returns:
        raise ValueError("placebo requires at least one return")
    offset = shift % len(returns)
    return returns[offset:] + returns[:offset]


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def _sample_standard_deviation(values: tuple[Decimal, ...]) -> Decimal:
    if len(values) < 2:
        return Decimal(0)
    average = _mean(values)
    return (
        sum(((item - average) ** 2 for item in values), Decimal(0)) / Decimal(len(values) - 1)
    ).sqrt()


def stationary_block_bootstrap_indices(
    observations: int, *, block_length: int, seed: int, samples: int
) -> tuple[tuple[int, ...], ...]:
    """Fixed-seed moving blocks preserve local dependence without a new dependency."""

    if observations < 1 or block_length < 1 or samples < 1:
        raise ValueError("observations, block_length, and samples must be positive")
    random = Random(seed)  # noqa: S311 - deterministic bootstrap sampling, never security-sensitive
    result: list[tuple[int, ...]] = []
    for _ in range(samples):
        indices: list[int] = []
        while len(indices) < observations:
            start = random.randrange(observations)
            indices.extend((start + offset) % observations for offset in range(block_length))
        result.append(tuple(indices[:observations]))
    return tuple(result)


def performance_report(
    returns: tuple[Decimal, ...],
    *,
    annualization_periods: int,
    strategy_trials: int = 1,
    out_of_sample_fold_returns: tuple[tuple[Decimal, ...], ...] = (),
) -> PerformanceReport:
    """Report only when a minimal sample supports a descriptive statistic."""

    if annualization_periods < 1 or strategy_trials < 1:
        raise ValueError("annualization_periods and strategy_trials must be positive")
    if any(not fold for fold in out_of_sample_fold_returns):
        raise ValueError("out-of-sample folds must not be empty")
    if len(returns) < 30:
        return PerformanceReport(
            observations=len(returns),
            annualization_periods=annualization_periods,
            sufficient_evidence=False,
        )
    mean = _mean(returns)
    volatility = _sample_standard_deviation(returns)
    if volatility == 0:
        return PerformanceReport(
            observations=len(returns),
            annualization_periods=annualization_periods,
            sufficient_evidence=False,
        )
    downside = tuple(min(item, Decimal(0)) for item in returns)
    downside_deviation = (
        sum((item * item for item in downside), Decimal(0)) / Decimal(len(returns))
    ).sqrt()
    scale = Decimal(annualization_periods).sqrt()
    annualized_return = mean * Decimal(annualization_periods)
    annualized_volatility = volatility * scale
    sortino = None if downside_deviation == 0 else mean / downside_deviation * scale
    return PerformanceReport(
        observations=len(returns),
        annualization_periods=annualization_periods,
        annualized_return=annualized_return,
        annualized_volatility=annualized_volatility,
        sortino_ratio=sortino,
        sufficient_evidence=True,
    )
