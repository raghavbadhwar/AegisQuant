"""Data-only contracts for simulated execution."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator

from ._base import ContractModel, normalize_ticker

OrderSide = Literal["buy", "sell"]
OrderStatus = Literal["created", "partially_filled", "filled", "cancelled", "rejected"]
SimulationMode = Literal["replay", "historical", "paper"]
PositiveFinite = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
NonnegativeFinite = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


class Order(ContractModel):
    """A deterministic simulated-market order record; it has no placement method."""

    order_id: Annotated[str, Field(min_length=1)]
    case_id: Annotated[str, Field(min_length=1)]
    ticker: str
    side: OrderSide
    quantity: PositiveFinite
    reference_price: PositiveFinite
    created_at: AwareDatetime
    status: OrderStatus = "created"
    execution_mode: SimulationMode

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)


class Fill(ContractModel):
    """A deterministic simulated fill with explicit cost components."""

    fill_id: Annotated[str, Field(min_length=1)]
    order_id: Annotated[str, Field(min_length=1)]
    ticker: str
    side: OrderSide
    quantity: PositiveFinite
    price: PositiveFinite
    fee: NonnegativeFinite
    slippage: NonnegativeFinite
    filled_at: AwareDatetime
    execution_mode: SimulationMode

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)


class Position(ContractModel):
    """A marked simulated position at an aware point in time."""

    ticker: str
    quantity: float
    average_cost: NonnegativeFinite
    market_price: NonnegativeFinite
    market_value: float
    unrealized_pnl: float
    as_of: AwareDatetime

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)

    @field_validator("quantity", "market_value", "unrealized_pnl")
    @classmethod
    def values_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("position values must be finite")
        return value
