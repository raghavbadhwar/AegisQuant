"""Read-only construction of evaluation returns from governed cycle receipts.

This module intentionally accepts no return or turnover vectors.  It derives
period observations only from adjacent, validated institutional CycleRecords.
"""

from __future__ import annotations

import itertools
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aegis.contracts import PREDECLARED_STRATEGY_IDS, FundMandate, canonical_sha256
from aegis.fund.ledger import CycleRecord, SQLiteRunLedger
from aegis.research_lab.validation import (
    interval_combinatorial_purged_splits,
    interval_purged_walk_forward,
)


class ReceiptComparisonRow(BaseModel):
    """One predeclared strategy's ordered ledger receipts; never return vectors."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str
    mandate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_ids: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def run_ids_are_unique(self) -> Self:
        if self.strategy_id not in PREDECLARED_STRATEGY_IDS:
            raise ValueError("receipt row is not a predeclared strategy")
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("receipt row run IDs must be unique")
        return self


class ReceiptComparisonSpec(BaseModel):
    """Frozen six-way eligibility input that carries only governed receipt IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["aegis-receipt-comparison-v1"]
    declared_at: datetime
    evaluated_at: datetime
    rows: tuple[ReceiptComparisonRow, ...]

    @model_validator(mode="after")
    def is_predeclared_and_temporal(self) -> Self:
        if self.declared_at.tzinfo is None or self.evaluated_at.tzinfo is None:
            raise ValueError("receipt comparison times must be timezone-aware")
        if self.declared_at > self.evaluated_at:
            raise ValueError("receipt comparison must be declared before evaluation")
        ids = [row.strategy_id for row in self.rows]
        if len(self.rows) != len(PREDECLARED_STRATEGY_IDS) or set(ids) != set(
            PREDECLARED_STRATEGY_IDS
        ):
            raise ValueError("receipt comparison requires exactly six predeclared strategies")
        return self


class ReceiptSeriesError(ValueError):
    """Receipt streams cannot safely support a strategy comparison."""


class ReceiptReturnObservation(BaseModel):
    """One prediction/label receipt pair and only its deterministically derived values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prediction_run_id: str = Field(min_length=1)
    prediction_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    prediction_time: datetime
    label_run_id: str = Field(min_length=1)
    label_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_time: datetime
    quant_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_cost: float = Field(ge=0.0)
    fill_notional: float = Field(ge=0.0)
    gross_return: float
    turnover: float = Field(ge=0.0)

    @model_validator(mode="after")
    def is_causal_and_finite(self) -> Self:
        if self.prediction_time.tzinfo is None or self.label_time.tzinfo is None:
            raise ValueError("receipt observation times must be timezone-aware")
        if self.label_time <= self.prediction_time:
            raise ValueError("label receipt must follow prediction receipt")
        if not all(
            math.isfinite(value)
            for value in (self.entry_cost, self.fill_notional, self.gross_return, self.turnover)
        ):
            raise ValueError("receipt observation values must be finite")
        if self.gross_return <= -1.0:
            raise ValueError("derived gross return must exceed -100 percent")
        return self


def _require_institutional(record: CycleRecord) -> FundMandate:
    if not isinstance(record.fund, FundMandate) or record.schema_version != "aegis-cycle-v2":
        raise ReceiptSeriesError("receipt comparison requires institutional v2 cycle receipts")
    if record.quant_research_bundle is None or record.master_portfolio is None:
        raise ReceiptSeriesError("institutional receipt lacks sealed bundle or master trace")
    if record.case.mode != "historical" or record.evidence.mode != "historical":
        raise ReceiptSeriesError("receipt comparison requires historical-mode provenance")
    return record.fund


def derive_receipt_observations(
    records: tuple[CycleRecord, ...], *, expected_mandate_hash: str
) -> tuple[ReceiptReturnObservation, ...]:
    """Derive adjacent-label observations; never accept a user-supplied return.

    The label is the next governed receipt's pre-rebalance equity.  Entry costs
    from the prediction receipt are restored before calculating gross return so
    downstream base/2x/5x cost tests do not double count them.
    """
    if len(records) < 2:
        raise ReceiptSeriesError("at least two governed receipts are required")
    mandate_hashes = []
    for record in records:
        mandate = _require_institutional(record)
        mandate_hashes.append(mandate.content_hash)
    if any(value != expected_mandate_hash for value in mandate_hashes):
        raise ReceiptSeriesError("receipt stream mandate hash mismatch")
    if any(
        later.case.as_of <= earlier.case.as_of for earlier, later in itertools.pairwise(records)
    ):
        raise ReceiptSeriesError("receipt cutoffs must be strictly increasing")

    output: list[ReceiptReturnObservation] = []
    for prediction, label in itertools.pairwise(records):
        entry_cost = sum(fill.fee + fill.slippage for fill in prediction.fills)
        fill_notional = sum(fill.price * fill.quantity for fill in prediction.fills)
        denominator = prediction.nav_after + entry_cost
        if not math.isfinite(denominator) or denominator <= 0.0 or prediction.equity_before <= 0.0:
            raise ReceiptSeriesError("receipt has invalid capital denominator")
        gross_return = label.equity_before / denominator - 1.0
        output.append(
            ReceiptReturnObservation(
                prediction_run_id=prediction.run_id,
                prediction_digest=prediction.digest(),
                prediction_time=prediction.case.as_of,
                label_run_id=label.run_id,
                label_digest=label.digest(),
                label_time=label.case.as_of,
                quant_bundle_hash=prediction.quant_research_bundle.content_hash,  # type: ignore[union-attr]
                snapshot_hash=prediction.snapshot.content_hash,
                entry_cost=entry_cost,
                fill_notional=fill_notional,
                gross_return=gross_return,
                turnover=fill_notional / prediction.equity_before,
            )
        )
    return tuple(output)


def receipt_series_hash(
    observations: tuple[ReceiptReturnObservation, ...], mandate_hash: str
) -> str:
    """Commit every receipt pair, derived value, and governing mandate."""
    return canonical_sha256({"mandate_hash": mandate_hash, "observations": observations})


def derive_receipt_observations_from_ledger(
    ledger: SQLiteRunLedger,
    run_ids: tuple[str, ...],
    *,
    expected_mandate_hash: str,
) -> tuple[ReceiptReturnObservation, ...]:
    """Load receipt records through the append-only ledger before derivation.

    ``SQLiteRunLedger.get`` revalidates canonical receipt bytes and digest;
    callers therefore cannot supply model-constructed or mutable receipt data.
    """
    if len(run_ids) < 2 or len(set(run_ids)) != len(run_ids):
        raise ReceiptSeriesError("comparison requires unique ordered ledger run IDs")
    records: list[CycleRecord] = []
    for run_id in run_ids:
        try:
            records.append(ledger.get(run_id))
        except KeyError as exc:
            raise ReceiptSeriesError("comparison references a missing governed receipt") from exc
    return derive_receipt_observations(tuple(records), expected_mandate_hash=expected_mandate_hash)


def receipt_validation_folds(
    observations: tuple[ReceiptReturnObservation, ...],
    *,
    n_splits: int,
    minimum_train: int,
    embargo: timedelta,
    locked_holdout: tuple[int, ...] = (),
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    """Build label-aware walk-forward folds directly from receipt-pair clocks."""
    if len(observations) < 4:
        raise ReceiptSeriesError("receipt validation requires at least four observations")
    try:
        return interval_purged_walk_forward(
            tuple(item.prediction_time for item in observations),
            tuple(item.label_time for item in observations),
            n_splits,
            minimum_train=minimum_train,
            embargo=embargo,
            locked_holdout=locked_holdout,
        )
    except ValueError as exc:
        raise ReceiptSeriesError(f"receipt walk-forward validation failed: {exc}") from exc


def receipt_cpcv_folds(
    observations: tuple[ReceiptReturnObservation, ...],
    *,
    n_groups: int,
    n_test_groups: int,
    embargo: timedelta,
    locked_holdout: tuple[int, ...] = (),
) -> tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]:
    """Build label-aware CPCV folds directly from receipt-pair clocks."""
    if len(observations) < 4:
        raise ReceiptSeriesError("receipt validation requires at least four observations")
    try:
        return interval_combinatorial_purged_splits(
            tuple(item.prediction_time for item in observations),
            tuple(item.label_time for item in observations),
            n_groups,
            n_test_groups,
            embargo=embargo,
            locked_holdout=locked_holdout,
        )
    except ValueError as exc:
        raise ReceiptSeriesError(f"receipt CPCV validation failed: {exc}") from exc


def load_receipt_comparison_spec(path: str | Path) -> ReceiptComparisonSpec:
    """Load a receipt-only comparison declaration; reject malformed external input."""
    try:
        return ReceiptComparisonSpec.model_validate_json(Path(path).read_bytes())
    except Exception as exc:
        raise ReceiptSeriesError(f"invalid receipt comparison specification: {path}") from exc
