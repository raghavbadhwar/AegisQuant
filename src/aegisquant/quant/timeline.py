"""Time ordering and next-bar selection for fixture-only fills."""

from datetime import datetime

from pydantic import field_validator, model_validator

from aegisquant.contracts.common import Identifier, StrictModel, require_utc


class ExecutionTimeline(StrictModel):
    information_cutoff: datetime
    decision_at: datetime
    order_submitted_at: datetime
    fill_at: datetime

    @field_validator("information_cutoff", "decision_at", "order_submitted_at", "fill_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def ordered(self) -> "ExecutionTimeline":
        if not self.information_cutoff < self.decision_at <= self.order_submitted_at < self.fill_at:
            raise ValueError("information_cutoff < decision_at <= order_submitted_at < fill_at")
        return self


class TradableBar(StrictModel):
    instrument_id: Identifier
    observed_at: datetime
    tradable_at: datetime

    @field_validator("observed_at", "tradable_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def not_before_observed(self) -> "TradableBar":
        if self.tradable_at < self.observed_at:
            raise ValueError("bar cannot trade before it is observed")
        return self


def next_tradable_bar(
    bars: tuple[TradableBar, ...], *, instrument_id: str, after: datetime
) -> TradableBar:
    after = require_utc(after)
    eligible = sorted(
        (bar for bar in bars if bar.instrument_id == instrument_id and bar.tradable_at > after),
        key=lambda bar: (bar.tradable_at, bar.observed_at),
    )
    if not eligible:
        raise ValueError("no later tradable bar exists")
    return eligible[0]
