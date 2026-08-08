"""Optional purgedcv semantic adapter; Aegis retains split/holdout authority."""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence


class PurgedCVAdapter:
    def available(self) -> bool:
        return importlib.util.find_spec("purgedcv") is not None

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
