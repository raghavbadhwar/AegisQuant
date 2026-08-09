"""Fund -> strategy pod -> alpha model mandate hierarchy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aegis.contracts import FundMandate, RiskPolicy


class AlphaModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    provider: str = Field(default="replay", min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    display_name: str | None = None
    weight: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    models: tuple[AlphaModelSpec, ...] = Field(min_length=1)


class PortfolioPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gross_target: float = Field(default=0.85, gt=0, le=1, allow_inf_nan=False)
    market_neutral: bool = False


class FundSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    strategies: tuple[StrategySpec, ...] = Field(min_length=1)
    risk: RiskPolicy
    portfolio: PortfolioPolicy = Field(default_factory=PortfolioPolicy)
    capital: float = Field(default=100_000.0, gt=0, allow_inf_nan=False)
    rebalance: Literal["daily", "weekly", "monthly"] = "weekly"
    benchmark: str = "SPY"

    @field_validator("benchmark")
    @classmethod
    def normalize_benchmark(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("benchmark cannot be empty")
        return value

    @field_validator("strategies")
    @classmethod
    def unique_strategy_names(
        cls, strategies: tuple[StrategySpec, ...]
    ) -> tuple[StrategySpec, ...]:
        names = [strategy.name for strategy in strategies]
        if len(names) != len(set(names)):
            raise ValueError("strategy names must be unique")
        return strategies


def load_fund_spec(path: str | Path) -> FundSpec:
    with Path(path).open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError("fund mandate must be a YAML mapping")
    return FundSpec.model_validate(payload)


FundConfiguration = FundSpec | FundMandate


def load_fund_mandate(path: str | Path) -> FundMandate:
    """Load a fully hash-bound v3B mandate without changing legacy FundSpec defaults."""
    with Path(path).open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict) or "mandate_id" not in payload:
        raise ValueError("institutional fund mandate must contain mandate_id")
    return FundMandate.model_validate_json(json.dumps(payload, separators=(",", ":")))


def load_fund_configuration(path: str | Path) -> FundConfiguration:
    """Dispatch an explicit v3B mandate or the untouched legacy fund schema."""
    with Path(path).open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, dict):
        raise ValueError("fund mandate must be a YAML mapping")
    if "mandate_id" in payload:
        return FundMandate.model_validate_json(json.dumps(payload, separators=(",", ":")))
    return FundSpec.model_validate(payload)
