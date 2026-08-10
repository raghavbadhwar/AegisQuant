"""Candidate-only adapter from twin drivers to the existing deterministic FCFF seam."""

from __future__ import annotations

from math import isfinite
from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, field_validator, model_validator

from aegis.contracts import (
    CalculationLineage,
    ForecastDriver,
    NormalizedFinancialStatements,
    OperatingForecast,
    canonical_sha256,
)
from aegis.contracts._base import CandidateContractModel, normalize_ticker
from aegis.fundamentals.forecasting import forecast_operating_case

from .twin import TwinTransition


class TwinOperatingDriver(CandidateContractModel):
    """One candidate operating-driver period that fits the v3 FCFF input schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    year: int = Field(ge=1900, le=2200)
    revenue_growth: float
    operating_margin: float
    tax_rate: float
    reinvestment_rate: float
    share_dilution: float
    assumption_ids: tuple[str, ...] = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def has_feasible_fcff_driver_bounds(self) -> TwinOperatingDriver:
        values = (
            self.revenue_growth,
            self.operating_margin,
            self.tax_rate,
            self.reinvestment_rate,
            self.share_dilution,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("twin operating driver values must be finite")
        if (
            self.revenue_growth <= -1
            or not -1 <= self.operating_margin <= 1
            or not 0 <= self.tax_rate <= 1
            or not -2 <= self.reinvestment_rate <= 2
            or not -1 < self.share_dilution <= 1
        ):
            raise ValueError("twin operating driver values exceed FCFF hard bounds")
        if any(not assumption_id for assumption_id in self.assumption_ids):
            raise ValueError("twin operating driver assumption IDs must be nonempty")
        if len(self.assumption_ids) != len(set(self.assumption_ids)):
            raise ValueError("twin operating driver assumption IDs must be unique")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("twin operating driver content hash mismatch")
        return self

    def sealed(self) -> TwinOperatingDriver:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = TwinOperatingDriver.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


class TwinOperatingOutput(CandidateContractModel):
    """Sealed candidate operating output; it is not a valuation or release artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output_id: str = Field(min_length=1)
    ticker: str
    as_of: AwareDatetime
    scenario: Literal["bear", "base", "bull"]
    source_transition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    world_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_transition: TwinTransition
    drivers: tuple[TwinOperatingDriver, ...] = Field(min_length=2)
    terminal_growth: float
    terminal_roic: float = Field(gt=0.0)
    authority: Literal["candidate_only"] = "candidate_only"
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def is_sealed_feasible_and_chronological(self) -> TwinOperatingOutput:
        drivers = tuple(
            TwinOperatingDriver.model_validate(driver.model_dump(mode="json"))
            for driver in self.drivers
        )
        transition = TwinTransition.model_validate(self.source_transition.model_dump(mode="json"))
        if any(driver.content_hash is None for driver in drivers):
            raise ValueError("twin operating output requires sealed drivers")
        if transition.content_hash is None:
            raise ValueError("twin operating output requires a sealed source transition")
        if self.source_transition_hash != transition.content_hash:
            raise ValueError("twin operating output source transition hash does not match")
        if self.world_snapshot_hash != transition.from_state.world_snapshot_hash:
            raise ValueError("twin operating output world snapshot hash does not match")
        if self.as_of != transition.to_state.as_of:
            raise ValueError("twin operating output cutoff does not match its source transition")
        years = [driver.year for driver in drivers]
        if years != sorted(years) or len(years) != len(set(years)):
            raise ValueError("twin operating output driver years must be chronological and unique")
        if not isfinite(self.terminal_growth) or not isfinite(self.terminal_roic):
            raise ValueError("twin operating output terminal values must be finite")
        if not -1 < self.terminal_growth < 1 or self.terminal_growth >= self.terminal_roic:
            raise ValueError("twin operating output terminal assumptions are infeasible")
        expected = canonical_sha256(self.model_dump(mode="json", exclude={"content_hash"}))
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("twin operating output content hash mismatch")
        return self

    def sealed(self) -> TwinOperatingOutput:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        validated = TwinOperatingOutput.model_validate(payload)
        return validated.model_copy(update={"content_hash": canonical_sha256(payload)})


def adapt_twin_output_to_fcff_forecast(
    output: TwinOperatingOutput,
    statements: NormalizedFinancialStatements,
    *,
    evidence_ids: tuple[str, ...],
) -> tuple[OperatingForecast, tuple[CalculationLineage, ...]]:
    """Create an existing FCFF forecast from a sealed candidate driver set without valuation."""
    validated = TwinOperatingOutput.model_validate(output.model_dump(mode="json"))
    if validated.content_hash is None:
        raise ValueError("FCFF adapter requires a sealed twin operating output")
    if validated.ticker != statements.ticker or validated.as_of != statements.as_of:
        raise ValueError("twin operating output does not match the supplied financial statements")
    if not evidence_ids or any(not evidence_id for evidence_id in evidence_ids):
        raise ValueError("FCFF adapter requires retained source evidence IDs")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("FCFF adapter evidence IDs must be unique")
    drivers = [
        ForecastDriver(
            driver_id=f"v4-twin:{validated.output_id}:{driver.year}:{name}",
            name=name,
            scenario=validated.scenario,
            year=driver.year,
            value=value,
            unit="ratio",
            evidence_ids=list(evidence_ids),
            proposer_artifact_id=validated.output_id,
        )
        for driver in validated.drivers
        for name, value in (
            ("revenue_growth", driver.revenue_growth),
            ("operating_margin", driver.operating_margin),
            ("tax_rate", driver.tax_rate),
            ("reinvestment_rate", driver.reinvestment_rate),
            ("share_dilution", driver.share_dilution),
        )
    ]
    return forecast_operating_case(
        statements,
        validated.scenario,
        drivers,
        terminal_growth=validated.terminal_growth,
        terminal_roic=validated.terminal_roic,
    )
