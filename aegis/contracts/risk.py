"""Deterministic risk policy and decision contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field, field_validator, model_validator

from ._base import ContractModel, normalize_ticker_map, validate_sha256

Fraction = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class RiskPolicy(ContractModel):
    """Versioned, immutable limits used by the hard risk gate."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    max_position_pct: Fraction = 0.15
    max_gross_exposure: Annotated[float, Field(gt=0.0, allow_inf_nan=False)] = 0.90
    max_net_exposure: Fraction = 0.90
    max_turnover_pct: Fraction = 0.30
    minimum_cash_pct: Fraction = 0.10
    minimum_confidence: Fraction = 0.55
    maximum_sector_pct: Fraction = 0.35
    maximum_single_strategy_pct: Fraction = 0.60
    stale_price_minutes: Annotated[int, Field(ge=0)] = 10_080
    allow_shorting: bool = False
    allow_leverage: bool = False
    commission_bps: Annotated[float, Field(gt=0.0, allow_inf_nan=False)] = 5.0
    slippage_bps: Annotated[float, Field(gt=0.0, allow_inf_nan=False)] = 5.0
    version: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def policy_is_coherent(self) -> RiskPolicy:
        if not self.allow_leverage and self.max_gross_exposure > 1.0:
            raise ValueError("max_gross_exposure cannot exceed 1 when leverage is disabled")
        if self.max_position_pct > self.max_gross_exposure:
            raise ValueError("max_position_pct cannot exceed max_gross_exposure")
        if self.minimum_cash_pct + self.max_net_exposure > 1.0 + 1e-12:
            raise ValueError("minimum cash and maximum net exposure are incoherent")
        return self


class RiskDecision(ContractModel):
    """Fully logged output of deterministic policy evaluation."""

    approved: bool
    final_weights: dict[str, float] = Field(default_factory=dict)
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    policy_version: Annotated[str, Field(min_length=1)]
    input_hash: str

    @field_validator("final_weights", mode="before")
    @classmethod
    def normalize_weights(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return normalize_ticker_map(value)

    @field_validator("input_hash")
    @classmethod
    def input_hash_is_sha256(cls, value: str) -> str:
        return validate_sha256(value)

    @model_validator(mode="after")
    def approval_matches_violations(self) -> RiskDecision:
        if self.approved and self.violations:
            raise ValueError("approved decisions cannot contain violations")
        if not self.approved and not self.violations:
            raise ValueError("rejected decisions must record at least one violation")
        return self
