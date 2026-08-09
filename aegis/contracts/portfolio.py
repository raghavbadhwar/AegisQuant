"""Deterministic portfolio-construction output contracts."""

from __future__ import annotations

import math
from datetime import date
from typing import Annotated

from pydantic import Field, field_validator, model_validator

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
        try:
            return normalize_ticker_map(value)
        except TypeError as exc:
            raise ValueError("portfolio weights must be finite numbers") from exc

    @field_validator("input_hash")
    @classmethod
    def input_hash_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)

    @model_validator(mode="after")
    def exposures_match_weights(self) -> PortfolioProposal:
        gross = sum(abs(self.target_weights[ticker]) for ticker in sorted(self.target_weights))
        if not math.isclose(self.gross_exposure, gross, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("gross_exposure does not match target_weights")

        signed_exposure = sum(self.target_weights[ticker] for ticker in sorted(self.target_weights))
        expected_cash = max(0.0, 1.0 - signed_exposure)
        if not math.isclose(self.cash_weight, expected_cash, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("cash_weight does not match target_weights")
        return self
