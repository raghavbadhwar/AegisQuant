"""Deterministic leakage-aware splits and overfitting statistics."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from statistics import NormalDist

import numpy as np


class ValidationOrderError(RuntimeError):
    pass


def purged_walk_forward(
    n_samples: int,
    n_splits: int,
    *,
    minimum_train: int,
    purge: int = 0,
    embargo: int = 0,
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    if n_samples <= minimum_train or n_splits <= 0 or purge < 0 or embargo < 0:
        raise ValueError("invalid purged walk-forward parameters")
    test_size = max(1, (n_samples - minimum_train) // n_splits)
    folds = []
    for split in range(n_splits):
        test_start = minimum_train + split * test_size
        test_end = n_samples if split == n_splits - 1 else min(n_samples, test_start + test_size)
        train_end = max(0, test_start - purge)
        train = tuple(range(train_end))
        test = tuple(range(test_start, test_end))
        if train and test:
            folds.append((train, test))
    return tuple(folds)


def combinatorial_purged_splits(
    n_samples: int,
    n_groups: int,
    n_test_groups: int,
    *,
    embargo_groups: int = 0,
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    if not (1 <= n_test_groups < n_groups <= n_samples) or embargo_groups < 0:
        raise ValueError("invalid CPCV parameters")
    groups = [tuple(map(int, part)) for part in np.array_split(np.arange(n_samples), n_groups)]
    folds = []
    for test_group_ids in itertools.combinations(range(n_groups), n_test_groups):
        excluded = set(test_group_ids)
        for group_id in test_group_ids:
            excluded.update(range(group_id + 1, min(n_groups, group_id + 1 + embargo_groups)))
        train = tuple(
            index
            for group_id, group in enumerate(groups)
            if group_id not in excluded
            for index in group
        )
        test = tuple(index for group_id in test_group_ids for index in groups[group_id])
        folds.append((train, test))
    return tuple(folds)


def validation_statistics(returns: list[float], *, trial_sharpes: list[float]) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    if len(values) < 3 or not np.all(np.isfinite(values)):
        raise ValueError("validation requires at least three finite returns")
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    if std <= 0:
        raise ValueError("validation returns require nonzero variance")
    sharpe = mean / std * math.sqrt(252)
    centered = (values - mean) / std
    skew = float(np.mean(centered**3))
    kurtosis = float(np.mean(centered**4))
    denominator = max(
        1e-12,
        1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe**2,
    )
    psr = NormalDist().cdf(sharpe * math.sqrt(len(values) - 1) / math.sqrt(denominator))
    trials = max(1, len(trial_sharpes))
    trial_std = float(np.std(trial_sharpes, ddof=1)) if trials > 1 else 0.0
    deflated_benchmark = max(trial_sharpes, default=0.0) - trial_std * math.sqrt(
        2 * math.log(trials)
    )
    dsr = NormalDist().cdf(
        (sharpe - deflated_benchmark) * math.sqrt(len(values) - 1) / math.sqrt(denominator)
    )
    return {
        "annualized_sharpe": sharpe,
        "probabilistic_sharpe_ratio": psr,
        "deflated_sharpe_ratio": dsr,
        "effective_trials": float(trials),
    }


def probability_of_backtest_overfitting(performance: list[list[float]]) -> float:
    matrix = np.asarray(performance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 4:
        raise ValueError("PBO requires at least two trials and four splits")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("PBO performance must be finite")
    split_ids = range(matrix.shape[1])
    overfit = 0
    total = 0
    for in_sample in itertools.combinations(split_ids, matrix.shape[1] // 2):
        out_sample = [index for index in split_ids if index not in in_sample]
        best = int(np.argmax(np.mean(matrix[:, in_sample], axis=1)))
        out_ranks = np.argsort(np.argsort(np.mean(matrix[:, out_sample], axis=1)))
        overfit += int(out_ranks[best] < matrix.shape[0] / 2)
        total += 1
    return overfit / total


class ValidationPipeline:
    stages = (
        "preflight",
        "replay",
        "historical_dev",
        "holdback",
        "purged_cv",
        "overfitting",
        "cost_stress",
        "shadow",
    )

    def run(self, runners: dict[str, Callable[[], bool]]) -> dict[str, bool]:
        if "preflight" not in runners:
            raise ValidationOrderError("preflight stage is mandatory")
        results: dict[str, bool] = {}
        for stage in self.stages:
            runner = runners.get(stage)
            if runner is None:
                continue
            if stage != "preflight" and not results.get("preflight", False):
                raise ValidationOrderError("backtest stages cannot run before preflight passes")
            results[stage] = bool(runner())
            if stage == "preflight" and not results[stage]:
                return results
        return results
