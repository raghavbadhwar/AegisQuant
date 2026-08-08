"""Deterministic portfolio-construction output contracts."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import Field, field_validator

from ._base import ContractModel, normalize_ticker_map, validate_sha256


class PortfolioProposal(ContractModel):
    """Portfolio weights proposed for the deterministic risk gate."""

    as_of: date
    target_weights: dict[str, float] = Field(default_factory=dict)
    cash_weight: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    gross_exposure: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    turnover: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    input_hash: str

    @field_validator("target_weights", mode="before")
    @classmethod
    def normalize_weights(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return normalize_ticker_map(value)

    @field_validator("input_hash")
    @classmethod
    def input_hash_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)
