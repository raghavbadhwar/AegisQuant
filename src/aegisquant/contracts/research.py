"""Immutable point-in-time research and paper-trial contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import (
    FixedDecimal,
    Identifier,
    Sha256Digest,
    StrictModel,
    require_utc,
)
from aegisquant.contracts.risk import OrderSide


class CorporateActionKind(StrEnum):
    CASH_DIVIDEND = "CASH_DIVIDEND"
    SPLIT = "SPLIT"


class SecurityVersion(StrictModel):
    schema_version: Literal[1] = 1
    instrument_id: Identifier
    instrument_version: Identifier
    sector_id: Identifier
    valid_from: datetime
    valid_until: datetime | None = None

    @field_validator("valid_from", "valid_until")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def valid_interval(self) -> SecurityVersion:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("security version valid_until must be after valid_from")
        return self


class DataSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot_id: Identifier
    manifest_digest: Sha256Digest
    content_digest: Sha256Digest
    as_of: datetime
    frozen_at: datetime

    @field_validator("as_of", "frozen_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def chronology(self) -> DataSnapshot:
        if self.frozen_at < self.as_of:
            raise ValueError("snapshot cannot freeze before its as_of time")
        return self


class ResearchManifest(StrictModel):
    """All inputs necessary to deterministically reproduce a research case."""

    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot_id: Identifier
    snapshot_manifest_digest: Sha256Digest
    snapshot_content_digest: Sha256Digest
    data_manifest_digests: tuple[Sha256Digest, ...] = Field(min_length=1)
    rights_manifest_ids: tuple[Identifier, ...] = Field(min_length=1)
    relation_manifest_digests: tuple[Sha256Digest, ...] = ()
    model_fixture_digests: tuple[Sha256Digest, ...] = ()
    skill_manifest_digests: tuple[Sha256Digest, ...] = ()
    source_receipt_digests: tuple[Sha256Digest, ...] = ()
    frozen_at: datetime

    @field_validator(
        "data_manifest_digests",
        "rights_manifest_ids",
        "relation_manifest_digests",
        "model_fixture_digests",
        "skill_manifest_digests",
        "source_receipt_digests",
        mode="before",
    )
    @classmethod
    def json_arrays_are_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("frozen_at", mode="before")
    @classmethod
    def utc(cls, value: object) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("frozen_at must be a UTC datetime")
        return require_utc(value).astimezone(UTC)


class SourceReceipt(StrictModel):
    """Immutable receipt for content captured through the source gateway."""

    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    tool_id: Literal["last30days-public-research", "scrapling-public-fetch"]
    url: str
    content_digest: Sha256Digest
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class Last30DaysResearchRecord(StrictModel):
    """A 30-day research result bound to an immutable source capture."""

    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot_id: Identifier
    snapshot_manifest_digest: Sha256Digest
    source_receipt_digest: Sha256Digest
    source_content_digest: Sha256Digest
    available_at: datetime
    window_days: Literal[30] = 30

    @field_validator("available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class MarketBar(StrictModel):
    schema_version: Literal[1] = 1
    instrument_id: Identifier
    instrument_version: Identifier
    observed_at: datetime
    available_at: datetime
    tradable_at: datetime
    open_price: FixedDecimal
    close_price: FixedDecimal
    volume: FixedDecimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("observed_at", "available_at", "tradable_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("open_price", "close_price", "volume")
    @classmethod
    def positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("market prices and volume must be positive")
        return value

    @model_validator(mode="after")
    def availability_order(self) -> MarketBar:
        if not self.observed_at <= self.available_at <= self.tradable_at:
            raise ValueError("observed_at <= available_at <= tradable_at is required")
        return self


class CorporateAction(StrictModel):
    schema_version: Literal[1] = 1
    instrument_id: Identifier
    instrument_version: Identifier
    kind: CorporateActionKind
    effective_at: datetime
    available_at: datetime
    cash_per_share: FixedDecimal | None = None
    split_ratio: FixedDecimal | None = None

    @field_validator("effective_at", "available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def action_shape(self) -> CorporateAction:
        if self.available_at < self.effective_at:
            raise ValueError("corporate action cannot be available before effective_at")
        if self.kind == CorporateActionKind.CASH_DIVIDEND:
            if (
                self.cash_per_share is None
                or self.cash_per_share < 0
                or self.split_ratio is not None
            ):
                raise ValueError("cash dividend requires nonnegative cash_per_share only")
        elif self.split_ratio is None or self.split_ratio <= 0 or self.cash_per_share is not None:
            raise ValueError("split requires positive split_ratio only")
        return self


class CashLedgerEntry(StrictModel):
    schema_version: Literal[1] = 1
    entry_id: Identifier
    occurred_at: datetime
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: FixedDecimal
    reason_code: Identifier
    source_digest: Sha256Digest

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class PositionLedgerEntry(StrictModel):
    schema_version: Literal[1] = 1
    instrument_id: Identifier
    instrument_version: Identifier
    quantity: FixedDecimal
    mark_price: FixedDecimal
    marked_at: datetime
    source_digest: Sha256Digest

    @field_validator("marked_at", mode="before")
    @classmethod
    def parse_marked_at(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("quantity", "mark_price")
    @classmethod
    def nonnegative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("paper trial positions and marks must be nonnegative")
        return value

    @field_validator("marked_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class PaperFill(StrictModel):
    schema_version: Literal[1] = 1
    client_order_id: Identifier
    instrument_id: Identifier
    instrument_version: Identifier
    side: OrderSide
    quantity: FixedDecimal
    price: FixedDecimal
    transaction_cost: FixedDecimal
    filled_at: datetime
    market_data_digest: Sha256Digest

    @field_validator("filled_at", mode="before")
    @classmethod
    def parse_filled_at(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("quantity", "price", "transaction_cost")
    @classmethod
    def nonnegative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("paper fill values must be nonnegative")
        return value

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("paper fill quantity must be positive")
        return value

    @field_validator("filled_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class TrialManifest(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    case_id: UUID
    snapshot_id: Identifier
    snapshot_manifest_digest: Sha256Digest
    snapshot_content_digest: Sha256Digest
    strategy_id: Identifier
    policy_bundle_digest: Sha256Digest
    initial_nav: FixedDecimal
    created_at: datetime

    @field_validator("initial_nav")
    @classmethod
    def positive_nav(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("initial_nav must be positive")
        return value

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return require_utc(value)


class PerformanceReport(StrictModel):
    schema_version: Literal[1] = 1
    observations: int = Field(ge=0)
    annualization_periods: int = Field(ge=1)
    annualized_return: FixedDecimal | None = None
    annualized_volatility: FixedDecimal | None = None
    sortino_ratio: FixedDecimal | None = None
    probabilistic_sharpe_ratio: FixedDecimal | None = None
    deflated_sharpe_ratio: FixedDecimal | None = None
    probability_of_backtest_overfitting: FixedDecimal | None = None
    sufficient_evidence: bool

    @model_validator(mode="after")
    def insufficient_reports_are_explicit(self) -> PerformanceReport:
        values = (
            self.annualized_return,
            self.annualized_volatility,
            self.sortino_ratio,
            self.probabilistic_sharpe_ratio,
            self.deflated_sharpe_ratio,
            self.probability_of_backtest_overfitting,
        )
        if not self.sufficient_evidence and any(value is not None for value in values):
            raise ValueError("underpowered reports must not present performance statistics")
        return self
