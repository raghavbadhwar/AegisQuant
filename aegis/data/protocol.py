"""Point-in-time data contracts. Infrastructure and integrity failures are never missing data."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DataError(RuntimeError):
    """Base error for data failures that must halt a run."""


class DataIntegrityError(DataError):
    """The provider returned malformed, inconsistent, or unsafe data."""


class PointInTimeViolation(DataIntegrityError):
    """Data was observed before its declared availability."""


class PriceBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ticker: str
    date: str
    available_at: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)
    dataset: str

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("ticker cannot be empty")
        return value

    @field_validator("available_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        return value


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: datetime
    bars: tuple[PriceBar, ...]
    content_hash: str


@runtime_checkable
class DataClient(Protocol):
    network_enabled: bool
    dataset_hash: str

    def latest_snapshot(self, tickers: list[str], as_of: datetime) -> MarketSnapshot: ...

    def price_history(
        self, ticker: str, start: datetime, end: datetime, *, as_of: datetime
    ) -> tuple[PriceBar, ...]: ...

    def sector_map(self, tickers: list[str], as_of: datetime) -> dict[str, str]: ...
