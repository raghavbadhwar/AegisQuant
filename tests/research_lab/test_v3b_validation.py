from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aegis.research_lab.validation import (
    combinatorial_purged_splits,
    interval_purged_walk_forward,
    probability_of_backtest_overfitting,
    purged_walk_forward,
    validation_statistics,
)


def test_index_walk_forward_applies_purge_and_embargo() -> None:
    assert purged_walk_forward(12, 3, minimum_train=6, purge=1, embargo=2) == (
        ((0, 1, 2), (6, 7)),
        ((0, 1, 2, 3, 4), (8, 9)),
        ((0, 1, 2, 3, 4, 5, 6), (10, 11)),
    )
    no_embargo = purged_walk_forward(12, 3, minimum_train=6, purge=1, embargo=0)
    embargoed = purged_walk_forward(12, 3, minimum_train=6, purge=1, embargo=2)
    assert all(
        set(with_gap[0]).issubset(no_gap[0])
        for no_gap, with_gap in zip(no_embargo, embargoed, strict=True)
    )
    with pytest.raises(ValueError, match="empty fold"):
        purged_walk_forward(8, 2, minimum_train=4, purge=4, embargo=1)


def test_interval_walk_forward_purges_overlapping_labels_and_locked_holdout() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    predictions = tuple(start + timedelta(days=index) for index in range(12))
    label_ends = tuple(value + timedelta(days=2) for value in predictions)
    assert interval_purged_walk_forward(
        predictions,
        label_ends,
        3,
        minimum_train=6,
        embargo=timedelta(days=1),
    ) == (
        ((0, 1, 2, 3), (6, 7)),
        ((0, 1, 2, 3, 4, 5), (8, 9)),
        ((0, 1, 2, 3, 4, 5, 6, 7), (10, 11)),
    )
    with pytest.raises(ValueError, match="locked final holdout"):
        interval_purged_walk_forward(
            predictions,
            label_ends,
            3,
            minimum_train=6,
            locked_holdout={11},
        )
    bad = list(predictions)
    bad[2] = bad[1]
    with pytest.raises(ValueError, match="strictly increasing"):
        interval_purged_walk_forward(bad, label_ends, 2, minimum_train=6)
    with pytest.raises(ValueError, match="timezone-aware"):
        interval_purged_walk_forward(
            tuple(value.replace(tzinfo=None) for value in predictions),
            tuple(value.replace(tzinfo=None) for value in label_ends),
            2,
            minimum_train=6,
        )


def test_cpcv_and_overfitting_statistics_have_frozen_goldens() -> None:
    splits = combinatorial_purged_splits(8, 4, 2, embargo_groups=1)
    assert len(splits) == 6
    assert all(not set(train).intersection(test) for train, test in splits)
    assert probability_of_backtest_overfitting(
        [[1.0, 1.0, -1.0, -1.0], [-1.0, -1.0, 1.0, 1.0], [0.5, -0.5, 0.5, -0.5]]
    ) == pytest.approx(1.0)
    stats = validation_statistics(
        [0.01, -0.01, 0.005, -0.005, 0.002, -0.002],
        trial_sharpes=[-0.2, 0.0, 0.2],
    )
    assert stats == pytest.approx(
        {
            "annualized_sharpe": 0.0,
            "probabilistic_sharpe_ratio": 0.5,
            "deflated_sharpe_ratio": 0.5853864007776856,
            "effective_trials": 3.0,
        }
    )
