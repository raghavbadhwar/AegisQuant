"""Deterministic leakage-aware splits and overfitting statistics."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Collection, Sequence
from datetime import datetime, timedelta
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
    """Build expanding walk-forward folds with index purge and embargo.

    Both buffers are measured in observations immediately before the test
    block: ``purge`` represents the label-overlap allowance and ``embargo``
    is an additional pre-test gap.  Thus training always precedes testing and
    increasing either buffer can only remove training observations.
    """
    if (
        minimum_train <= 0
        or n_samples <= minimum_train
        or not 1 <= n_splits <= n_samples - minimum_train
        or purge < 0
        or embargo < 0
    ):
        raise ValueError("invalid purged walk-forward parameters")
    test_size = max(1, (n_samples - minimum_train) // n_splits)
    folds = []
    for split in range(n_splits):
        test_start = minimum_train + split * test_size
        test_end = n_samples if split == n_splits - 1 else min(n_samples, test_start + test_size)
        train_end = max(0, test_start - purge - embargo)
        train = tuple(range(train_end))
        test = tuple(range(test_start, test_end))
        if not train or not test:
            raise ValueError("purge and embargo leave an empty fold")
        folds.append((train, test))
    return tuple(folds)


def interval_purged_walk_forward(
    prediction_times: Sequence[datetime],
    label_end_times: Sequence[datetime],
    n_splits: int,
    *,
    minimum_train: int,
    embargo: timedelta = timedelta(0),
    locked_holdout: Collection[int] = (),
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    """Build label-interval-aware expanding walk-forward folds.

    An observation's label interval is inclusive:
    ``[prediction_time, label_end_time]``.  Training candidates always occur
    before the test block.  A candidate is purged if its label interval
    overlaps any test label interval, and the embargo adds a pre-test time
    gap by requiring ``train prediction_time < test_start - embargo``.

    All timestamps must be timezone-aware.  Prediction times must be strictly
    increasing (therefore sorted and duplicate-free), label ends may not
    precede predictions, and locked holdout indices may not touch a fold.
    """
    n_samples = len(prediction_times)
    if (
        len(label_end_times) != n_samples
        or minimum_train <= 0
        or n_samples <= minimum_train
        or not 1 <= n_splits <= n_samples - minimum_train
        or embargo < timedelta(0)
    ):
        raise ValueError("invalid interval purged walk-forward parameters")
    all_times = (*prediction_times, *label_end_times)
    if any(value.tzinfo is None or value.utcoffset() is None for value in all_times):
        raise ValueError("interval purged walk-forward requires timezone-aware timestamps")
    if any(current <= previous for previous, current in itertools.pairwise(prediction_times)):
        raise ValueError("prediction times must be strictly increasing")
    if any(
        label_end < prediction
        for prediction, label_end in zip(prediction_times, label_end_times, strict=True)
    ):
        raise ValueError("label end times may not precede prediction times")

    holdout = set(locked_holdout)
    if any(index < 0 or index >= n_samples for index in holdout):
        raise ValueError("locked holdout index is out of range")

    test_size = max(1, (n_samples - minimum_train) // n_splits)
    folds: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for split in range(n_splits):
        test_start = minimum_train + split * test_size
        test_end = n_samples if split == n_splits - 1 else min(n_samples, test_start + test_size)
        test = tuple(range(test_start, test_end))
        if not test:
            raise ValueError("interval split contains an empty test fold")

        test_prediction_start = prediction_times[test_start]
        embargo_cutoff = test_prediction_start - embargo

        train = tuple(
            index
            for index in range(test_start)
            if prediction_times[index] < embargo_cutoff
            and label_end_times[index] < test_prediction_start
        )
        if not train:
            raise ValueError("purge and embargo leave an empty interval fold")
        if holdout.intersection(train) or holdout.intersection(test):
            raise ValueError("validation split touches the locked final holdout")
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
    # PSR/DSR are sampling statistics of the *period* Sharpe.  Annualizing it
    # before inserting it into the higher-moment denominator materially
    # overstates significance (particularly for short-horizon research).
    period_sharpe = mean / std
    annualized_sharpe = period_sharpe * math.sqrt(252)
    centered = (values - mean) / std
    skew = float(np.mean(centered**3))
    kurtosis = float(np.mean(centered**4))
    denominator = max(
        1e-12,
        1 - skew * period_sharpe + ((kurtosis - 1) / 4) * period_sharpe**2,
    )
    psr = NormalDist().cdf(period_sharpe * math.sqrt(len(values) - 1) / math.sqrt(denominator))
    trials = max(1, len(trial_sharpes))
    # Evaluation callers record comparable trial Sharpes as annualized display
    # values; convert them back to the statistic's period units here.
    trial_period_sharpes = [value / math.sqrt(252) for value in trial_sharpes]
    trial_std = float(np.std(trial_period_sharpes, ddof=1)) if trials > 1 else 0.0
    deflated_benchmark = max(trial_period_sharpes, default=0.0) - trial_std * math.sqrt(
        2 * math.log(trials)
    )
    dsr = NormalDist().cdf(
        (period_sharpe - deflated_benchmark) * math.sqrt(len(values) - 1) / math.sqrt(denominator)
    )
    return {
        "annualized_sharpe": annualized_sharpe,
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
