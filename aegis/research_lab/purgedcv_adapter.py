"""Optional purgedcv adapter; Aegis retains holdout and release authority."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Sequence
from typing import Any, cast

import numpy as np
import pandas as pd


class PurgedCVAdapter:
    def available(self) -> bool:
        return importlib.util.find_spec("purgedcv") is not None

    def build_library_splits(
        self,
        n_samples: int,
        *,
        n_splits: int,
        purge_days: int,
        embargo_days: int,
    ) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
        """Invoke the pinned library splitter and normalize its output."""
        if not self.available():
            raise RuntimeError("purgedcv is unavailable; install the lab extra")
        module = importlib.import_module("purgedcv")
        times = pd.date_range("2000-01-01", periods=n_samples, freq="D", tz="UTC")
        splitter = module.PurgedKFold(
            n_splits=n_splits,
            prediction_times=times,
            evaluation_times=times + cast(Any, np.timedelta64(1, "D")),
            purge_horizon=np.timedelta64(purge_days, "D"),
            embargo=np.timedelta64(embargo_days, "D"),
        )
        values = np.arange(n_samples)
        return tuple(
            (tuple(map(int, train)), tuple(map(int, test)))
            for train, test in splitter.split(values)
        )

    def validate_indices(
        self,
        splits: Sequence[tuple[Sequence[int], Sequence[int]]],
        *,
        locked_holdout: set[int],
    ) -> None:
        for train, test in splits:
            if set(train).intersection(test):
                raise ValueError("purged split train/test overlap")
            if set(train).intersection(locked_holdout) or set(test).intersection(locked_holdout):
                raise ValueError("validation split touches the locked final holdout")
