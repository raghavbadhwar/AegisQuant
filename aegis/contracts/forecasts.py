"""Evidence-linked forecast contracts."""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ._base import ContractModel, normalize_ticker

Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class AlphaForecast(ContractModel):
    """A calibrated, horizon-specific alpha forecast or explicit abstention."""

    forecast_id: Annotated[str, Field(min_length=1)]
    model_name: Annotated[str, Field(min_length=1)]
    ticker: str
    as_of: AwareDatetime
    horizon_days: Annotated[int, Field(gt=0)]
    expected_excess_return: float | None
    expected_volatility: float | None
    probability_positive: Probability
    confidence: Probability
    uncertainty: Probability
    downside_case: float | None = None
    base_case: float | None = None
    upside_case: float | None = None
    thesis: str
    evidence_ids: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    catalyst_dates: list[AwareDatetime] = Field(default_factory=list)
    thesis_expiry: AwareDatetime | None = None
    abstained: bool = False
    abstain_reason: str | None = None
    components: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)

    @field_validator("expected_excess_return", "downside_case", "base_case", "upside_case")
    @classmethod
    def optional_returns_are_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("forecast return values must be finite")
        return value

    @field_validator("expected_volatility")
    @classmethod
    def volatility_is_nonnegative(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or value < 0.0):
            raise ValueError("expected_volatility must be finite and nonnegative")
        return value

    @field_validator("components")
    @classmethod
    def component_values_are_finite(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(component) for component in value.values()):
            raise ValueError("forecast components must be finite")
        return value

    @model_validator(mode="after")
    def enforce_forecast_contract(self) -> AlphaForecast:
        scenarios = (self.downside_case, self.base_case, self.upside_case)
        if all(value is not None for value in scenarios):
            downside, base, upside = scenarios
            if not (downside <= base <= upside):  # type: ignore[operator]
                raise ValueError("scenario returns must be downside <= base <= upside")
        if self.thesis_expiry is not None and self.thesis_expiry <= self.as_of:
            raise ValueError("thesis_expiry must be after as_of")
        if self.abstained:
            if self.abstain_reason is None or not self.abstain_reason.strip():
                raise ValueError("abstained forecasts require abstain_reason")
            return self
        if not self.evidence_ids:
            raise ValueError("non-abstained material forecasts require evidence IDs")
        if self.expected_excess_return is None or self.expected_volatility is None:
            raise ValueError("non-abstained forecasts require expected return and volatility")
        if not self.thesis.strip():
            raise ValueError("non-abstained forecasts require a thesis")
        if self.abstain_reason is not None:
            raise ValueError("non-abstained forecasts cannot include abstain_reason")
        return self
