from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aegis.research_lab.receipt_series import (
    ReceiptReturnObservation,
    receipt_cpcv_folds,
    receipt_validation_folds,
)


def _observations() -> tuple[ReceiptReturnObservation, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return tuple(
        ReceiptReturnObservation(
            prediction_run_id=f"prediction-{index}",
            prediction_digest="a" * 64,
            prediction_time=start + timedelta(days=index * 10),
            label_run_id=f"label-{index}",
            label_digest="b" * 64,
            label_time=start + timedelta(days=index * 10 + 5),
            quant_bundle_hash="c" * 64,
            snapshot_hash="d" * 64,
            entry_cost=1.0,
            fill_notional=100.0,
            gross_return=0.01,
            turnover=0.01,
        )
        for index in range(12)
    )


def test_receipt_intervals_drive_purged_walk_forward_and_cpcv() -> None:
    observations = _observations()
    walk_forward = receipt_validation_folds(
        observations, n_splits=3, minimum_train=4, embargo=timedelta(days=1), locked_holdout=(11,)
    )
    cpcv = receipt_cpcv_folds(
        observations, n_groups=4, n_test_groups=1, embargo=timedelta(days=1), locked_holdout=(11,)
    )
    assert walk_forward
    assert cpcv
    assert all(11 not in train and 11 not in test for train, test in (*walk_forward, *cpcv))
