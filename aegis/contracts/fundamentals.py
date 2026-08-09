"""Versioned institutional fundamental-research and valuation contracts."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ._base import ContractModel, normalize_ticker
from .artifacts import canonical_sha256
from .evidence import EvidenceBundle
from .forecasts import AlphaForecast

Version = Literal["3.0.0"]
ArchetypeKind = Literal[
    "general_operating_company",
    "saas_subscription",
    "bank_financial",
    "reit",
    "cyclical_commodity",
    "pre_profit",
]
ScenarioName = Literal["bear", "base", "bull"]


class CompanyResearchRequest(ContractModel):
    request_id: Annotated[str, Field(min_length=1)]
    ticker: str
    company_name: Annotated[str, Field(min_length=1)]
    as_of: AwareDatetime
    horizon_days: int = Field(gt=0, le=1825)
    mode: Literal["replay", "historical", "current_research"]
    question: Annotated[str, Field(min_length=1)]
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)


class CompanyArchetype(ContractModel):
    ticker: str
    kind: ArchetypeKind
    supported: bool
    reason: Annotated[str, Field(min_length=1)]
    router_version: Annotated[str, Field(min_length=1)]
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def only_general_path_is_release_supported(self) -> CompanyArchetype:
        if self.supported and self.kind != "general_operating_company":
            raise ValueError("v3 release supports only the general operating-company path")
        return self


class FilingFact(ContractModel):
    fact_id: Annotated[str, Field(min_length=1)]
    ticker: str
    concept: Annotated[str, Field(min_length=1)]
    value: Decimal = Field(allow_inf_nan=False)
    unit: Annotated[str, Field(min_length=1)]
    period_start: date | None = None
    period_end: date
    fiscal_year: int = Field(ge=1900, le=2200)
    fiscal_period: Literal["FY", "Q1", "Q2", "Q3", "Q4", "TTM"]
    form: Annotated[str, Field(min_length=1)]
    accession_number: Annotated[str, Field(min_length=1)]
    filed_at: AwareDatetime
    accepted_at: AwareDatetime
    available_at: AwareDatetime
    source_coordinate: Annotated[str, Field(min_length=1)]
    raw_content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    revision: int = Field(ge=0)
    supersedes_fact_id: str | None = None
    statement_scope: Literal["continuing_operations", "discontinued_operations"] = (
        "continuing_operations"
    )
    is_one_time: bool = False
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def timestamps_are_causal(self) -> FilingFact:
        if self.filed_at > self.accepted_at or self.accepted_at > self.available_at:
            raise ValueError("filing timestamps must be filed <= accepted <= available")
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("filing period start cannot follow period end")
        if (self.revision == 0) != (self.supersedes_fact_id is None):
            raise ValueError("only an initial filing fact may omit a superseded fact")
        return self


class RawFilingSnapshot(ContractModel):
    snapshot_id: Annotated[str, Field(min_length=1)]
    ticker: str
    as_of: AwareDatetime
    facts: list[FilingFact] = Field(min_length=1)
    raw_receipt_ids: list[str] = Field(min_length=1)
    source_manifest_versions: dict[str, str] = Field(min_length=1)
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def is_point_in_time_and_hashed(self) -> RawFilingSnapshot:
        if any(fact.ticker != self.ticker or fact.available_at > self.as_of for fact in self.facts):
            raise ValueError("raw filing snapshot contains wrong-entity or future facts")
        by_id = {fact.fact_id: fact for fact in self.facts}
        if len(by_id) != len(self.facts):
            raise ValueError("raw filing snapshot contains duplicate fact IDs")
        for fact in self.facts:
            if fact.revision == 0:
                continue
            prior = by_id.get(fact.supersedes_fact_id or "")
            if (
                prior is None
                or prior.ticker != fact.ticker
                or prior.concept != fact.concept
                or prior.period_end != fact.period_end
                or prior.revision >= fact.revision
                or prior.available_at >= fact.available_at
            ):
                raise ValueError("filing restatement chain is invalid")
        payload = self.model_dump(exclude={"content_hash"})
        if self.content_hash != canonical_sha256(payload):
            raise ValueError("raw filing snapshot hash mismatch")
        return self


class NormalizationAdjustment(ContractModel):
    adjustment_id: Annotated[str, Field(min_length=1)]
    period_end: date
    line_item: Annotated[str, Field(min_length=1)]
    amount: Decimal = Field(allow_inf_nan=False)
    reason: Annotated[str, Field(min_length=1)]
    adjustment_type: Literal[
        "manual", "one_time_item", "lease_treatment", "rd_capitalization", "continuing_operations"
    ] = "manual"
    evidence_fact_ids: list[str] = Field(min_length=1)
    reversible: Literal[True] = True
    analytical_only: bool = True
    contract_version: Version = "3.0.0"


class CalculationLineage(ContractModel):
    calculation_id: Annotated[str, Field(min_length=1)]
    calculator: Annotated[str, Field(min_length=1)]
    calculator_version: Annotated[str, Field(min_length=1)]
    formula: Annotated[str, Field(min_length=1)]
    input_fact_ids: list[str] = Field(default_factory=list)
    input_calculation_ids: list[str] = Field(default_factory=list)
    input_assumption_ids: list[str] = Field(default_factory=list)
    output_name: Annotated[str, Field(min_length=1)]
    output_value: Decimal | float = Field(allow_inf_nan=False)
    unit: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def lineage_is_hashed_and_sourced(self) -> CalculationLineage:
        if not (self.input_fact_ids or self.input_calculation_ids or self.input_assumption_ids):
            raise ValueError("calculation lineage requires facts, calculations, or assumptions")
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("calculation lineage hash mismatch")
        return self


class FinancialPeriod(ContractModel):
    period_end: date
    fiscal_year: int = Field(ge=1900, le=2200)
    revenue: Decimal = Field(ge=0, allow_inf_nan=False)
    cost_of_revenue: Decimal = Field(ge=0, allow_inf_nan=False)
    operating_expenses: Decimal = Field(ge=0, allow_inf_nan=False)
    operating_income: Decimal = Field(allow_inf_nan=False)
    interest_expense: Decimal = Field(ge=0, allow_inf_nan=False)
    tax_expense: Decimal = Field(allow_inf_nan=False)
    net_income: Decimal = Field(allow_inf_nan=False)
    diluted_shares: Decimal = Field(gt=0, allow_inf_nan=False)
    cash: Decimal = Field(ge=0, allow_inf_nan=False)
    current_assets: Decimal = Field(ge=0, allow_inf_nan=False)
    current_liabilities: Decimal = Field(ge=0, allow_inf_nan=False)
    total_assets: Decimal = Field(ge=0, allow_inf_nan=False)
    total_liabilities: Decimal = Field(ge=0, allow_inf_nan=False)
    total_debt: Decimal = Field(ge=0, allow_inf_nan=False)
    total_equity: Decimal = Field(allow_inf_nan=False)
    cash_from_operations: Decimal = Field(allow_inf_nan=False)
    cash_flow_working_capital_change: Decimal = Field(allow_inf_nan=False)
    other_operating_cash_adjustments: Decimal = Field(allow_inf_nan=False)
    capital_expenditure: Decimal = Field(ge=0, allow_inf_nan=False)
    depreciation_amortization: Decimal = Field(ge=0, allow_inf_nan=False)
    stock_based_compensation: Decimal = Field(ge=0, allow_inf_nan=False)
    acquisitions: Decimal = Field(ge=0, allow_inf_nan=False)
    dividends: Decimal = Field(ge=0, allow_inf_nan=False)
    share_repurchases: Decimal = Field(ge=0, allow_inf_nan=False)
    share_issuance: Decimal = Field(ge=0, allow_inf_nan=False)
    working_capital: Decimal = Field(allow_inf_nan=False)
    lineage_by_line_item: dict[str, list[str]] = Field(min_length=1)

    @model_validator(mode="after")
    def statements_reconcile(self) -> FinancialPeriod:
        tolerance = max(Decimal("1"), self.revenue) * Decimal("1e-8")
        expected_operating = self.revenue - self.cost_of_revenue - self.operating_expenses
        if abs(expected_operating - self.operating_income) > tolerance:
            raise ValueError("income statement does not reconcile")
        if self.current_assets > self.total_assets + tolerance:
            raise ValueError("current assets cannot exceed total assets")
        if abs(self.total_assets - self.total_liabilities - self.total_equity) > tolerance:
            raise ValueError("balance sheet does not reconcile")
        expected_cfo = (
            self.net_income
            + self.depreciation_amortization
            + self.stock_based_compensation
            + self.cash_flow_working_capital_change
            + self.other_operating_cash_adjustments
        )
        if abs(expected_cfo - self.cash_from_operations) > tolerance:
            raise ValueError("cash-flow statement does not reconcile")
        return self


class NormalizedFinancialStatements(ContractModel):
    statements_id: Annotated[str, Field(min_length=1)]
    ticker: str
    as_of: AwareDatetime
    reported_periods: list[FinancialPeriod] = Field(min_length=2)
    adjusted_periods: list[FinancialPeriod] = Field(min_length=2)
    adjustments: list[NormalizationAdjustment] = Field(default_factory=list)
    calculation_lineage: list[CalculationLineage] = Field(min_length=1)
    source_snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    normalizer_version: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def periods_and_hash_match(self) -> NormalizedFinancialStatements:
        reported = [period.period_end for period in self.reported_periods]
        adjusted = [period.period_end for period in self.adjusted_periods]
        if reported != sorted(reported) or adjusted != reported:
            raise ValueError("reported and adjusted periods must be aligned and chronological")
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("normalized statement hash mismatch")
        return self


class FundamentalMetrics(ContractModel):
    ticker: str
    as_of: AwareDatetime
    revenue_growth: float = Field(allow_inf_nan=False)
    revenue_cagr: float = Field(allow_inf_nan=False)
    organic_revenue_growth: float | None = Field(default=None, allow_inf_nan=False)
    acquired_revenue_growth: float | None = Field(default=None, allow_inf_nan=False)
    eps_growth: float | None = Field(default=None, allow_inf_nan=False)
    fcf_growth: float | None = Field(default=None, allow_inf_nan=False)
    growth_acceleration: float | None = Field(default=None, allow_inf_nan=False)
    gross_margin: float = Field(allow_inf_nan=False)
    operating_margin: float = Field(allow_inf_nan=False)
    ebitda_margin: float = Field(allow_inf_nan=False)
    margin_change: float = Field(allow_inf_nan=False)
    operating_leverage: float | None = Field(default=None, allow_inf_nan=False)
    roic: float | None = Field(default=None, allow_inf_nan=False)
    incremental_roic: float | None = Field(default=None, allow_inf_nan=False)
    roe: float | None = Field(default=None, allow_inf_nan=False)
    asset_turns: float | None = Field(default=None, allow_inf_nan=False)
    reinvestment_rate: float | None = Field(default=None, allow_inf_nan=False)
    cash_conversion: float | None = Field(default=None, allow_inf_nan=False)
    cfo_to_net_income: float | None = Field(default=None, allow_inf_nan=False)
    accrual_ratio: float | None = Field(default=None, allow_inf_nan=False)
    working_capital_to_revenue: float = Field(allow_inf_nan=False)
    working_capital_change: Decimal = Field(allow_inf_nan=False)
    cash_tax_rate: float | None = Field(default=None, allow_inf_nan=False)
    sbc_dilution: float = Field(allow_inf_nan=False)
    capex_intensity: float = Field(allow_inf_nan=False)
    net_debt: Decimal = Field(allow_inf_nan=False)
    debt_to_ebitda: float | None = Field(default=None, allow_inf_nan=False)
    interest_coverage: float | None = Field(default=None, allow_inf_nan=False)
    current_ratio: float | None = Field(default=None, allow_inf_nan=False)
    liquidity_runway_years: float | None = Field(default=None, allow_inf_nan=False)
    debt_change: Decimal = Field(allow_inf_nan=False)
    net_buyback_yield: float = Field(allow_inf_nan=False)
    dividend_yield: float = Field(allow_inf_nan=False)
    dividend_payout: float | None = Field(default=None, allow_inf_nan=False)
    acquisition_intensity: float = Field(allow_inf_nan=False)
    fcf_per_share: Decimal = Field(allow_inf_nan=False)
    calculation_ids: list[str] = Field(min_length=1)
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)


class BusinessModelAssessment(ContractModel):
    summary: Annotated[str, Field(min_length=1)]
    revenue_drivers: list[str] = Field(min_length=1)
    moat_evidence: list[str] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    contract_version: Version = "3.0.0"


class IndustryAssessment(ContractModel):
    industry: Annotated[str, Field(min_length=1)]
    structure: Annotated[str, Field(min_length=1)]
    cycle_position: Annotated[str, Field(min_length=1)]
    competitors: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    contract_version: Version = "3.0.0"


class AccountingQualityAssessment(ContractModel):
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    accrual_warning: bool
    sbc_warning: bool
    acquisition_warning: bool
    one_time_adjustments: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    calculation_ids: list[str] = Field(min_length=1)
    contract_version: Version = "3.0.0"


class GuidanceRecord(ContractModel):
    guidance_id: Annotated[str, Field(min_length=1)]
    metric: Annotated[str, Field(min_length=1)]
    lower_bound: float = Field(allow_inf_nan=False)
    upper_bound: float = Field(allow_inf_nan=False)
    issued_at: AwareDatetime
    period_end: date
    actual: float | None = Field(default=None, allow_inf_nan=False)
    actual_available_at: AwareDatetime | None = None
    evidence_ids: list[str] = Field(min_length=1)
    supersedes_guidance_id: str | None = None

    @model_validator(mode="after")
    def bounds_and_actual_time_match(self) -> GuidanceRecord:
        if self.lower_bound > self.upper_bound:
            raise ValueError("guidance lower bound exceeds upper bound")
        if (self.actual is None) != (self.actual_available_at is None):
            raise ValueError("actual and actual availability must be provided together")
        if self.actual_available_at is not None and self.actual_available_at <= self.issued_at:
            raise ValueError("guidance actual must become available after guidance issuance")
        return self


class ManagementActionRecord(ContractModel):
    action_id: Annotated[str, Field(min_length=1)]
    action_type: Literal["capital_allocation_promise", "acquisition", "buyback", "disclosure"]
    announced_at: AwareDatetime
    available_at: AwareDatetime
    promise: Annotated[str, Field(min_length=1)]
    completed: bool
    completed_at: AwareDatetime | None = None
    completion_available_at: AwareDatetime | None = None
    outcome_at: AwareDatetime | None = None
    outcome_available_at: AwareDatetime | None = None
    outcome_return: float | None = Field(default=None, allow_inf_nan=False)
    evidence_ids: list[str] = Field(min_length=1)
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def outcome_is_point_in_time(self) -> ManagementActionRecord:
        if self.available_at < self.announced_at:
            raise ValueError("management action availability precedes announcement")
        completion_fields = (self.completed_at, self.completion_available_at)
        if self.completed != all(value is not None for value in completion_fields):
            raise ValueError("completed management action requires completion timestamps")
        if self.completed_at is not None:
            assert self.completion_available_at is not None
            if (
                self.completed_at < self.announced_at
                or self.completion_available_at < self.completed_at
            ):
                raise ValueError("management completion timestamps are not causal")
        outcome_fields = (self.outcome_at, self.outcome_available_at, self.outcome_return)
        if any(value is not None for value in outcome_fields) != all(
            value is not None for value in outcome_fields
        ):
            raise ValueError("management outcome requires value and both timestamps")
        if self.outcome_at is not None:
            assert self.outcome_available_at is not None
            if (
                not self.completed
                or self.completed_at is None
                or self.completion_available_at is None
            ):
                raise ValueError("management outcome requires a completed action")
            if (
                self.outcome_at < self.completed_at
                or self.outcome_available_at < self.outcome_at
                or self.outcome_available_at < self.completion_available_at
            ):
                raise ValueError("management outcome timestamps are not causal")
        return self


class ManagementTrackRecord(ContractModel):
    ticker: str
    as_of: AwareDatetime
    guidance: list[GuidanceRecord] = Field(default_factory=list)
    matured_count: int = Field(ge=0)
    hit_rate: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    mean_bias: float | None = Field(default=None, allow_inf_nan=False)
    mean_absolute_error: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    dilution_rate: float = Field(allow_inf_nan=False)
    acquisition_return: float | None = Field(default=None, allow_inf_nan=False)
    buyback_timing_return: float | None = Field(default=None, allow_inf_nan=False)
    capital_allocation_follow_through: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    guidance_revision_count: int = Field(ge=0)
    disclosure_quality: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)


class ForecastDriver(ContractModel):
    driver_id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    scenario: ScenarioName
    year: int = Field(ge=1900, le=2200)
    value: float = Field(allow_inf_nan=False)
    unit: Annotated[str, Field(min_length=1)]
    evidence_ids: list[str] = Field(min_length=1)
    proposer_artifact_id: str | None = None


class ForecastPeriod(ContractModel):
    year: int = Field(ge=1900, le=2200)
    revenue: Decimal = Field(ge=0, allow_inf_nan=False)
    operating_margin: float = Field(ge=-1, le=1, allow_inf_nan=False)
    operating_income: Decimal = Field(allow_inf_nan=False)
    tax_rate: float = Field(ge=0, le=1, allow_inf_nan=False)
    nopat: Decimal = Field(allow_inf_nan=False)
    reinvestment: Decimal = Field(allow_inf_nan=False)
    fcff: Decimal = Field(allow_inf_nan=False)
    diluted_shares: Decimal = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def arithmetic_reconciles(self) -> ForecastPeriod:
        tolerance = max(Decimal("1"), self.revenue) * Decimal("1e-24")
        margin = Decimal(str(self.operating_margin))
        tax_rate = Decimal(str(self.tax_rate))
        if abs(self.operating_income - self.revenue * margin) > tolerance:
            raise ValueError("forecast operating income does not reconcile")
        if abs(self.nopat - self.operating_income * (Decimal("1") - tax_rate)) > tolerance:
            raise ValueError("forecast NOPAT does not reconcile")
        if abs(self.fcff - (self.nopat - self.reinvestment)) > tolerance:
            raise ValueError("forecast FCFF does not reconcile")
        return self


class OperatingForecast(ContractModel):
    forecast_id: Annotated[str, Field(min_length=1)]
    ticker: str
    as_of: AwareDatetime
    scenario: ScenarioName
    periods: list[ForecastPeriod] = Field(min_length=2)
    drivers: list[ForecastDriver] = Field(min_length=1)
    terminal_growth: float = Field(gt=-1, lt=1, allow_inf_nan=False)
    terminal_roic: float = Field(gt=0, allow_inf_nan=False)
    calculation_ids: list[str] = Field(min_length=1)
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def forecast_is_chronological_and_hashed(self) -> OperatingForecast:
        years = [period.year for period in self.periods]
        if years != sorted(years) or len(years) != len(set(years)):
            raise ValueError("forecast years must be unique and chronological")
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("operating forecast hash mismatch")
        return self


class ValuationAssumption(ContractModel):
    assumption_id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    value: Decimal = Field(allow_inf_nan=False)
    unit: Annotated[str, Field(min_length=1)]
    scenario: ScenarioName | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)


class SensitivityPoint(ContractModel):
    discount_rate: float = Field(gt=0, lt=1, allow_inf_nan=False)
    terminal_growth: float = Field(gt=-1, lt=1, allow_inf_nan=False)
    enterprise_value: Decimal = Field(allow_inf_nan=False)
    equity_value_per_share: Decimal = Field(allow_inf_nan=False)
    discount_rate_calculation_id: Annotated[str, Field(min_length=1)]
    terminal_growth_calculation_id: Annotated[str, Field(min_length=1)]
    enterprise_value_calculation_id: Annotated[str, Field(min_length=1)]
    equity_value_per_share_calculation_id: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def coordinate_and_calculations_are_valid(self) -> SensitivityPoint:
        if self.terminal_growth >= self.discount_rate:
            raise ValueError("sensitivity terminal growth must be below discount rate")
        calculation_ids = (
            self.discount_rate_calculation_id,
            self.terminal_growth_calculation_id,
            self.enterprise_value_calculation_id,
            self.equity_value_per_share_calculation_id,
        )
        if len(set(calculation_ids)) != len(calculation_ids):
            raise ValueError("sensitivity fields require distinct calculation IDs")
        return self


class DCFResult(ContractModel):
    valuation_id: Annotated[str, Field(min_length=1)]
    ticker: str
    scenario: ScenarioName
    as_of: AwareDatetime
    forecast_id: Annotated[str, Field(min_length=1)]
    discount_rate: float = Field(gt=0, lt=1, allow_inf_nan=False)
    terminal_growth: float = Field(gt=-1, lt=1, allow_inf_nan=False)
    explicit_present_value: Decimal = Field(allow_inf_nan=False)
    terminal_value: Decimal = Field(allow_inf_nan=False)
    terminal_present_value: Decimal = Field(allow_inf_nan=False)
    enterprise_value: Decimal = Field(allow_inf_nan=False)
    net_debt: Decimal = Field(allow_inf_nan=False)
    diluted_shares: Decimal = Field(gt=0, allow_inf_nan=False)
    equity_value: Decimal = Field(allow_inf_nan=False)
    value_per_share: Decimal = Field(allow_inf_nan=False)
    sensitivity: list[SensitivityPoint] = Field(min_length=1)
    assumptions: list[ValuationAssumption] = Field(min_length=1)
    calculation_ids: list[str] = Field(min_length=1)
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def valuation_reconciles_and_hashes(self) -> DCFResult:
        tolerance = max(Decimal("1"), abs(self.enterprise_value)) * Decimal("1e-8")
        if self.terminal_growth >= self.discount_rate:
            raise ValueError("terminal growth must be below discount rate")
        if (
            abs(self.enterprise_value - (self.explicit_present_value + self.terminal_present_value))
            > tolerance
        ):
            raise ValueError("DCF enterprise value does not reconcile")
        if abs(self.equity_value - (self.enterprise_value - self.net_debt)) > tolerance:
            raise ValueError("DCF equity value does not reconcile")
        if abs(self.value_per_share - self.equity_value / self.diluted_shares) > tolerance:
            raise ValueError("DCF per-share value does not reconcile")
        sensitivity_ids = [
            calculation_id
            for point in self.sensitivity
            for calculation_id in (
                point.discount_rate_calculation_id,
                point.terminal_growth_calculation_id,
                point.enterprise_value_calculation_id,
                point.equity_value_per_share_calculation_id,
            )
        ]
        if len(sensitivity_ids) != len(set(sensitivity_ids)):
            raise ValueError("DCF sensitivity calculation IDs must be unique")
        if not set(sensitivity_ids).issubset(self.calculation_ids):
            raise ValueError("DCF sensitivity calculations must be indexed by the result")
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("DCF result hash mismatch")
        return self


class ImpliedExpectations(ContractModel):
    expectations_id: Annotated[str, Field(min_length=1)]
    ticker: str
    market_price: Decimal = Field(gt=0, allow_inf_nan=False)
    solved_variable: Literal["revenue_growth", "growth_duration", "operating_margin"]
    implied_value: float | None = Field(default=None, allow_inf_nan=False)
    feasible: bool
    lower_bound: float = Field(allow_inf_nan=False)
    upper_bound: float = Field(allow_inf_nan=False)
    residual: Decimal | None = Field(default=None, allow_inf_nan=False)
    limitations: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(min_length=1)
    calculation_ids: list[str] = Field(min_length=1)
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def feasibility_fields_match(self) -> ImpliedExpectations:
        if self.lower_bound > self.upper_bound:
            raise ValueError("implied-expectation bounds are reversed")
        if self.feasible != (self.implied_value is not None):
            raise ValueError("feasible expectation requires an implied value")
        return self


class PeerMultiple(ContractModel):
    ticker: str
    ev_revenue: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    ev_ebitda: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    ev_ebit: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    price_earnings: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    price_fcf: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    revenue_growth: float = Field(allow_inf_nan=False)
    operating_margin: float = Field(allow_inf_nan=False)
    roic: float | None = Field(default=None, allow_inf_nan=False)
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_is_normalized(cls, value: object) -> str:
        return normalize_ticker(value)


class ComparableValuation(ContractModel):
    valuation_id: Annotated[str, Field(min_length=1)]
    ticker: str
    peers: list[PeerMultiple] = Field(min_length=2)
    selection_rationale: Annotated[str, Field(min_length=1)]
    multiple_distributions: dict[str, list[float]] = Field(min_length=1)
    implied_value_low: Decimal = Field(allow_inf_nan=False)
    implied_value_mid: Decimal = Field(allow_inf_nan=False)
    implied_value_high: Decimal = Field(allow_inf_nan=False)
    calculation_ids: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def value_range_is_ordered(self) -> ComparableValuation:
        if not self.implied_value_low <= self.implied_value_mid <= self.implied_value_high:
            raise ValueError("comparable valuation range is not ordered")
        return self


class SOTPSegment(ContractModel):
    name: Annotated[str, Field(min_length=1)]
    metric: Annotated[str, Field(min_length=1)]
    metric_value: Decimal = Field(allow_inf_nan=False)
    multiple: Decimal = Field(gt=0, allow_inf_nan=False)
    enterprise_value: Decimal = Field(allow_inf_nan=False)
    evidence_ids: list[str] = Field(min_length=1)


class SOTPResult(ContractModel):
    valuation_id: Annotated[str, Field(min_length=1)]
    ticker: str
    supported: bool
    segments: list[SOTPSegment] = Field(default_factory=list)
    corporate_adjustments: Decimal = Field(default=Decimal("0"), allow_inf_nan=False)
    total_enterprise_value: Decimal | None = Field(default=None, allow_inf_nan=False)
    abstain_reason: str | None = None
    calculation_ids: list[str] = Field(default_factory=list)
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def support_state_matches(self) -> SOTPResult:
        if self.supported and (not self.segments or self.total_enterprise_value is None):
            raise ValueError("supported SOTP requires segments and total value")
        if not self.supported and not self.abstain_reason:
            raise ValueError("unsupported SOTP requires abstain reason")
        return self


class ScenarioValuation(ContractModel):
    ticker: str
    dcf_by_scenario: dict[ScenarioName, DCFResult]
    probabilities: dict[ScenarioName, float]
    probability_weighted_value: Decimal = Field(allow_inf_nan=False)
    market_price: Decimal = Field(gt=0, allow_inf_nan=False)
    implied_return: float = Field(allow_inf_nan=False)
    calculation_ids: list[str] = Field(min_length=1)
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def probabilities_and_value_reconcile(self) -> ScenarioValuation:
        required: tuple[ScenarioName, ...] = ("bear", "base", "bull")
        if set(self.dcf_by_scenario) != set(required) or set(self.probabilities) != set(required):
            raise ValueError("scenario valuation requires bear/base/bull")
        if any(not math.isfinite(value) or value < 0 for value in self.probabilities.values()):
            raise ValueError("scenario probabilities must be finite and nonnegative")
        if abs(sum(self.probabilities.values()) - 1.0) > 1e-9:
            raise ValueError("scenario probabilities must sum to one")
        expected = sum(
            (
                Decimal(str(self.probabilities[name])) * self.dcf_by_scenario[name].value_per_share
                for name in required
            ),
            Decimal("0"),
        )
        if abs(expected - self.probability_weighted_value) > max(
            Decimal("1"), abs(expected)
        ) * Decimal("1e-8"):
            raise ValueError("probability-weighted value does not reconcile")
        if abs(self.implied_return - float(expected / self.market_price - Decimal("1"))) > 1e-8:
            raise ValueError("scenario implied return does not reconcile")
        values = [self.dcf_by_scenario[name].value_per_share for name in required]
        if values != sorted(values):
            raise ValueError("bear/base/bull DCF values must be ordered")
        return self


class ForecastCalibrationRecord(ContractModel):
    calibration_id: Annotated[str, Field(min_length=1)]
    model_name: Annotated[str, Field(min_length=1)]
    available_at: AwareDatetime
    horizon_days_min: int = Field(gt=0)
    horizon_days_max: int = Field(gt=0)
    sample_size: int = Field(gt=30)
    return_slope: float = Field(gt=0, allow_inf_nan=False)
    return_intercept: float = Field(allow_inf_nan=False)
    probability_slope: float = Field(gt=0, allow_inf_nan=False)
    probability_intercept: float = Field(allow_inf_nan=False)
    root_mean_squared_error: float = Field(ge=0, allow_inf_nan=False)
    brier_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    outcome_ids: list[str] = Field(min_length=1)
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def calibration_is_ordered_and_hashed(self) -> ForecastCalibrationRecord:
        if self.horizon_days_min > self.horizon_days_max:
            raise ValueError("calibration horizon bounds are reversed")
        expected = canonical_sha256(self.model_dump(exclude={"content_hash"}))
        if self.content_hash != expected:
            raise ValueError("forecast calibration hash mismatch")
        return self


class FundamentalScorecard(ContractModel):
    ticker: str
    quality: float = Field(ge=-1, le=1, allow_inf_nan=False)
    growth: float = Field(ge=-1, le=1, allow_inf_nan=False)
    profitability: float = Field(ge=-1, le=1, allow_inf_nan=False)
    accounting: float = Field(ge=-1, le=1, allow_inf_nan=False)
    balance_sheet: float = Field(ge=-1, le=1, allow_inf_nan=False)
    cash_conversion: float = Field(ge=-1, le=1, allow_inf_nan=False)
    capital_allocation: float = Field(ge=-1, le=1, allow_inf_nan=False)
    management: float = Field(ge=-1, le=1, allow_inf_nan=False)
    valuation: float = Field(ge=-1, le=1, allow_inf_nan=False)
    expectations_gap: float = Field(ge=-1, le=1, allow_inf_nan=False)
    catalyst: float = Field(ge=-1, le=1, allow_inf_nan=False)
    uncertainty: float = Field(ge=0, le=1, allow_inf_nan=False)
    composite: float = Field(ge=-1, le=1, allow_inf_nan=False)
    calculation_ids: list[str] = Field(min_length=1)
    contract_version: Version = "3.0.0"


class ThesisClaim(ContractModel):
    claim_id: Annotated[str, Field(min_length=1)]
    statement: Annotated[str, Field(min_length=1)]
    status: Literal["active", "strengthened", "weakened", "invalidated", "resolved"]
    evidence_ids: list[str] = Field(min_length=1)
    calculation_ids: list[str] = Field(default_factory=list)


class ThesisCheckpoint(ContractModel):
    checkpoint_id: Annotated[str, Field(min_length=1)]
    due_at: AwareDatetime
    condition: Annotated[str, Field(min_length=1)]
    status: Literal["pending", "met", "missed", "superseded"]
    evidence_ids: list[str] = Field(default_factory=list)


class InvestmentThesis(ContractModel):
    thesis_id: Annotated[str, Field(min_length=1)]
    ticker: str
    version: int = Field(gt=0)
    as_of: AwareDatetime
    horizon_days: int = Field(gt=0)
    core_claims: list[ThesisClaim] = Field(min_length=1)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(min_length=1)
    invalidation_conditions: list[str] = Field(min_length=1)
    valuation_case_ids: list[str] = Field(min_length=1)
    checkpoints: list[ThesisCheckpoint] = Field(default_factory=list)
    supersedes_thesis_id: str | None = None
    status: Literal[
        "draft",
        "active",
        "strengthened",
        "weakened",
        "invalidated",
        "resolved",
        "archived",
    ]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def thesis_versions_and_hash_match(self) -> InvestmentThesis:
        if (self.version == 1) != (self.supersedes_thesis_id is None):
            raise ValueError("only first thesis version may omit supersedes ID")
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("investment thesis hash mismatch")
        return self


SpecialistRole = Literal[
    "business_industry",
    "financial_quality",
    "growth_drivers",
    "accounting_quality",
    "balance_sheet",
    "capital_allocation",
    "management_guidance",
    "valuation",
    "catalysts_risks",
]
REQUIRED_SPECIALIST_ROLES: tuple[SpecialistRole, ...] = (
    "business_industry",
    "financial_quality",
    "growth_drivers",
    "accounting_quality",
    "balance_sheet",
    "capital_allocation",
    "management_guidance",
    "valuation",
    "catalysts_risks",
)


class SpecialistCalculationPredicate(ContractModel):
    calculation_id: Annotated[str, Field(min_length=1)]
    operator: Literal["gt", "ge", "lt", "le", "eq"]
    reference_value: Decimal = Field(allow_inf_nan=False)
    tolerance: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)


class FundamentalSpecialistInput(ContractModel):
    specialist_input_id: Annotated[str, Field(min_length=1)]
    request_id: Annotated[str, Field(min_length=1)]
    role: SpecialistRole
    as_of: AwareDatetime
    evidence_ids: list[str] = Field(min_length=1)
    calculation_lineage: list[CalculationLineage] = Field(min_length=1)
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def specialist_input_is_hashed(self) -> FundamentalSpecialistInput:
        if len({item.calculation_id for item in self.calculation_lineage}) != len(
            self.calculation_lineage
        ):
            raise ValueError("specialist input calculation IDs must be unique")
        expected = canonical_sha256(self.model_dump(exclude={"content_hash"}))
        if self.content_hash != expected:
            raise ValueError("fundamental specialist input hash mismatch")
        return self


class FundamentalSpecialistClaim(ContractModel):
    claim_id: Annotated[str, Field(min_length=1)]
    statement: Annotated[str, Field(min_length=1)]
    conclusion: Literal["supportive", "neutral", "cautionary"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_ids: list[str] = Field(min_length=1)
    calculation_ids: list[str] = Field(min_length=1)
    predicates: list[SpecialistCalculationPredicate] = Field(min_length=1)

    @model_validator(mode="after")
    def predicates_match_calculations(self) -> FundamentalSpecialistClaim:
        if set(self.calculation_ids) != {predicate.calculation_id for predicate in self.predicates}:
            raise ValueError("specialist claim predicates do not match calculation IDs")
        return self


class FundamentalSpecialistArtifact(ContractModel):
    artifact_id: Annotated[str, Field(min_length=1)]
    request_id: Annotated[str, Field(min_length=1)]
    role: SpecialistRole
    as_of: AwareDatetime
    producer: Annotated[str, Field(min_length=1)]
    claims: list[FundamentalSpecialistClaim] = Field(default_factory=list)
    abstained: bool = False
    abstain_reason: str | None = None
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def abstention_and_hash_match(self) -> FundamentalSpecialistArtifact:
        if self.abstained != (self.abstain_reason is not None):
            raise ValueError("specialist abstention requires exactly one reason")
        if self.abstained and self.claims:
            raise ValueError("abstaining specialist cannot emit claims")
        if not self.abstained and not self.claims:
            raise ValueError("non-abstaining specialist requires a claim")
        expected = canonical_sha256(self.model_dump(exclude={"content_hash"}))
        if self.content_hash != expected:
            raise ValueError("fundamental specialist artifact hash mismatch")
        return self


class FundamentalCommitteeDecision(ContractModel):
    committee_id: Annotated[str, Field(min_length=1)]
    request_id: Annotated[str, Field(min_length=1)]
    specialist_artifact_ids: list[str] = Field(min_length=1)
    accepted_claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    decision: Literal["approved", "abstained"]
    rationale: Annotated[str, Field(min_length=1)]
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def committee_is_hash_bound(self) -> FundamentalCommitteeDecision:
        if self.decision == "approved" and (
            not self.accepted_claim_ids or not self.evidence_ids or not self.calculation_ids
        ):
            raise ValueError("approved committee decision requires accepted audited claims")
        expected = canonical_sha256(self.model_dump(exclude={"content_hash"}))
        if self.content_hash != expected:
            raise ValueError("fundamental committee decision hash mismatch")
        return self


class FundamentalAlphaForecast(AlphaForecast):
    """A fundamental forecast bound to its dossier and verification authority."""

    verification_status: Literal["pending", "committee_verified", "terminal_abstention"]
    committee_id: str | None = None
    committee_content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    source_dossier_id: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def verification_authority_is_consistent(self) -> FundamentalAlphaForecast:
        if self.verification_status == "committee_verified":
            if self.committee_id is None or self.committee_content_hash is None:
                raise ValueError("committee-verified forecasts require committee identity")
        elif (
            self.committee_id is not None
            or self.committee_content_hash is not None
            or not self.abstained
        ):
            raise ValueError("unverified fundamental forecasts must abstain without committee")
        if not self.abstained and self.verification_status != "committee_verified":
            raise ValueError("active fundamental forecasts require committee verification")
        return self


class FundamentalResearchDossier(ContractModel):
    dossier_id: Annotated[str, Field(min_length=1)]
    request: CompanyResearchRequest
    archetype: CompanyArchetype
    source_snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    input_snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    input_evidence: EvidenceBundle | None
    statements: NormalizedFinancialStatements | None
    metrics: FundamentalMetrics | None
    business: BusinessModelAssessment | None
    industry: IndustryAssessment | None
    accounting: AccountingQualityAssessment | None
    management: ManagementTrackRecord | None
    forecasts: dict[ScenarioName, OperatingForecast]
    dcf: dict[ScenarioName, DCFResult]
    reverse_dcf: dict[
        Literal["revenue_growth", "growth_duration", "operating_margin"],
        ImpliedExpectations,
    ]
    comparables: ComparableValuation | None
    sotp: SOTPResult | None
    scenario_valuation: ScenarioValuation | None
    scorecard: FundamentalScorecard | None
    thesis: InvestmentThesis | None
    alpha_forecast: FundamentalAlphaForecast
    specialist_artifacts: list[FundamentalSpecialistArtifact] = Field(default_factory=list)
    specialist_findings: dict[str, list[str]] = Field(default_factory=dict)
    release_status: Literal["preliminary", "committee_verified", "terminal_abstention"]
    committee_decision: FundamentalCommitteeDecision | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_ids: list[str] = Field(default_factory=list)
    calculation_lineage: list[CalculationLineage] = Field(default_factory=list)
    known_gaps: list[str] = Field(default_factory=list)
    abstained: bool
    abstain_reason: str | None = None
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    contract_version: Version = "3.0.0"

    @model_validator(mode="after")
    def dossier_state_and_hash_match(self) -> FundamentalResearchDossier:
        if self.alpha_forecast.source_dossier_id != self.dossier_id:
            raise ValueError("fundamental forecast is not bound to its dossier")
        if self.release_status == "preliminary" and (
            self.committee_decision is not None
            or not self.alpha_forecast.abstained
            or self.alpha_forecast.verification_status != "pending"
        ):
            raise ValueError(
                "preliminary dossier requires a committee-less pending forecast abstention"
            )
        if self.release_status == "terminal_abstention" and (
            not self.abstained
            or not self.alpha_forecast.abstained
            or self.committee_decision is not None
            or self.alpha_forecast.verification_status != "terminal_abstention"
        ):
            raise ValueError("terminal abstention requires an abstained forecast and no committee")
        if self.release_status == "committee_verified":
            committee = self.committee_decision
            roles = [artifact.role for artifact in self.specialist_artifacts]
            artifact_ids = [artifact.artifact_id for artifact in self.specialist_artifacts]
            required_roles = set(REQUIRED_SPECIALIST_ROLES)
            if (
                committee is None
                or set(roles) != required_roles
                or len(roles) != len(required_roles)
                or len(artifact_ids) != len(set(artifact_ids))
            ):
                raise ValueError("released dossier requires committee and nine unique specialists")
            claim_ids = [
                claim.claim_id
                for artifact in self.specialist_artifacts
                for claim in artifact.claims
            ]
            if (
                committee.request_id != self.request.request_id
                or any(
                    artifact.request_id != self.request.request_id
                    for artifact in self.specialist_artifacts
                )
                or set(committee.specialist_artifact_ids) != set(artifact_ids)
                or len(committee.specialist_artifact_ids)
                != len(set(committee.specialist_artifact_ids))
                or committee.evidence_ids != self.evidence_ids
                or committee.calculation_ids != self.calculation_ids
                or self.alpha_forecast.verification_status != "committee_verified"
                or self.alpha_forecast.committee_id != committee.committee_id
                or self.alpha_forecast.committee_content_hash != committee.content_hash
            ):
                raise ValueError("committee decision is not exactly bound to the dossier")
            expected_decision = "abstained" if self.abstained else "approved"
            if committee.decision != expected_decision:
                raise ValueError("committee decision does not match dossier state")
            if len(claim_ids) != len(set(claim_ids)):
                raise ValueError("released dossier specialist claim IDs must be unique")
            if committee.decision == "approved":
                if len(committee.accepted_claim_ids) != len(
                    set(committee.accepted_claim_ids)
                ) or sorted(committee.accepted_claim_ids) != sorted(claim_ids):
                    raise ValueError("committee approval does not bind every specialist claim")
                if self.alpha_forecast.abstained:
                    raise ValueError("approved dossier requires a verified active forecast")
            elif committee.accepted_claim_ids or not self.alpha_forecast.abstained:
                raise ValueError("abstaining committee requires an abstained forecast")
        if self.abstained:
            if not self.abstain_reason or not self.alpha_forecast.abstained:
                raise ValueError("abstained dossier requires reason and abstained forecast")
        else:
            required = (
                self.statements,
                self.metrics,
                self.business,
                self.industry,
                self.accounting,
                self.management,
                self.scenario_valuation,
                self.scorecard,
                self.thesis,
            )
            if any(value is None for value in required):
                raise ValueError("complete dossier is missing a required section")
            if set(self.forecasts) != {"bear", "base", "bull"} or set(self.dcf) != {
                "bear",
                "base",
                "bull",
            }:
                raise ValueError("complete dossier requires three operating and DCF cases")
            if set(self.reverse_dcf) != {
                "revenue_growth",
                "growth_duration",
                "operating_margin",
            }:
                raise ValueError("complete dossier requires three reverse-DCF inversions")
            if not self.evidence_ids or not self.calculation_ids:
                raise ValueError("complete dossier requires provenance")
            lineage_ids = [item.calculation_id for item in self.calculation_lineage]
            if len(lineage_ids) != len(set(lineage_ids)):
                raise ValueError("dossier calculation lineage IDs must be unique")
            if set(lineage_ids) != set(self.calculation_ids):
                raise ValueError("dossier calculation index and lineage must match")
            known_ids = set(lineage_ids)
            if any(
                not set(item.input_calculation_ids).issubset(known_ids)
                for item in self.calculation_lineage
            ):
                raise ValueError("dossier calculation lineage is not closed")
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError("fundamental dossier hash mismatch")
        return self
