"""Read-only construction of evaluation returns from governed cycle receipts.

This module intentionally accepts no return or turnover vectors.  It derives
period observations only from adjacent, validated institutional CycleRecords.
"""

from __future__ import annotations

import itertools
import math
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aegis.contracts import FundMandate, canonical_sha256
from aegis.fund.ledger import CycleRecord


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
