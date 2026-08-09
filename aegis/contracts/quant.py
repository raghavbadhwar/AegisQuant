"""Frozen point-in-time contracts for v3B quantitative research."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, FiniteFloat, field_validator, model_validator

from ._base import ContractModel, normalize_ticker
from .artifacts import canonical_sha256

ContractVersion = Literal["3.1.0"]
SemanticId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-v[1-9][0-9]*$"),
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Probability = Annotated[FiniteFloat, Field(ge=0.0, le=1.0)]
NonNegativeFloat = Annotated[FiniteFloat, Field(ge=0.0)]
PositiveFloat = Annotated[FiniteFloat, Field(gt=0.0)]

EligibilityReason = Literal[
    "eligible",
    "not_listed",
    "insufficient_liquidity",
    "insufficient_market_cap",
    "missing_sector_industry",
    "corporate_action_restricted",
    "incomplete_data",
    "borrow_unavailable",
    "outside_mandate",
]
FactorFamily = Literal[
    "value",
    "quality",
    "profitability",
    "investment",
    "momentum",
    "reversal",
    "volatility",
    "liquidity",
    "earnings_revisions",
    "pead",
    "behavioral_attention",
    "expectations_gap",
    "graph_relationship_risk",
]
PortfolioMethod = Literal[
    "equal_weight",
    "inverse_volatility",
    "forecast_weighted",
    "shrinkage_mean_risk",
    "risk_budgeting",
    "hierarchical_risk_parity",
    "maximum_diversification",
    "benchmark_tracking",
]
StrategyComparisonId = Literal[
    "equal-weight-v1",
    "inverse-vol-v1",
    "simple-factor-v1",
    "fundamental-only-v1",
    "quant-only-v1",
    "combined-multistrategy-v1",
]
PREDECLARED_STRATEGY_IDS: tuple[StrategyComparisonId, ...] = (
    "equal-weight-v1",
    "inverse-vol-v1",
    "simple-factor-v1",
    "fundamental-only-v1",
    "quant-only-v1",
    "combined-multistrategy-v1",
)


class FrozenContractModel(ContractModel):
    """Strict and assignment-frozen v3B boundary model."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class HashedContractModel(FrozenContractModel):
    """A contract whose complete payload is bound to a canonical SHA-256."""

    content_hash: Sha256

    @model_validator(mode="after")
    def canonical_hash_matches(self) -> Self:
        if self.content_hash != canonical_sha256(self.model_dump(exclude={"content_hash"})):
            raise ValueError(f"{type(self).__name__} content hash mismatch")
        return self


class PointInTimeContract(HashedContractModel):
    """A hash-bound contract whose inputs were knowable at its decision cutoff."""

    as_of: AwareDatetime
    available_at: AwareDatetime

    @model_validator(mode="after")
    def availability_is_point_in_time(self) -> Self:
        if self.available_at > self.as_of:
            raise ValueError("available_at must not be after as_of")
        return self


class UniverseMember(PointInTimeContract):
    member_id: SemanticId
    ticker: str
    listing_status: Literal["listed", "halted", "delisted"]
    average_daily_dollar_volume: NonNegativeFloat
    market_cap: NonNegativeFloat
    sector: Annotated[str, Field(min_length=1)] | None
    industry: Annotated[str, Field(min_length=1)] | None
    corporate_action_status: Literal[
        "none", "pending_merger", "pending_spinoff", "bankruptcy", "other_restricted"
    ] = "none"
    data_completeness: Probability
    borrow_eligible: bool
    source_ids: tuple[str, ...] = ()
    contract_version: ContractVersion = "3.1.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)


class EligibilityDecision(PointInTimeContract):
    decision_id: SemanticId
    member_id: SemanticId
    ticker: str
    eligible: bool
    reasons: tuple[EligibilityReason, ...] = Field(min_length=1)
    rules_version: SemanticId
    contract_version: ContractVersion = "3.1.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def reasons_match_decision(self) -> Self:
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("eligibility reasons must be unique")
        if self.eligible != (self.reasons == ("eligible",)):
            raise ValueError("eligible decisions require only the stable 'eligible' reason")
        if not self.eligible and "eligible" in self.reasons:
            raise ValueError("ineligible decisions cannot contain the 'eligible' reason")
        return self


class UniverseSnapshot(HashedContractModel):
    snapshot_id: SemanticId
    universe_id: SemanticId
    as_of: AwareDatetime
    members: tuple[UniverseMember, ...] = Field(min_length=1)
    decisions: tuple[EligibilityDecision, ...] = Field(min_length=1)
    fixed_fixture: bool
    limitation: str | None = None
    contract_version: ContractVersion = "3.1.0"

    @model_validator(mode="after")
    def snapshot_is_complete_and_point_in_time(self) -> Self:
        member_ids = [member.member_id for member in self.members]
        decision_ids = [decision.decision_id for decision in self.decisions]
        tickers = [member.ticker for member in self.members]
        if len(set(member_ids)) != len(member_ids) or len(set(tickers)) != len(tickers):
            raise ValueError("universe member semantic IDs and tickers must be unique")
        if len(set(decision_ids)) != len(decision_ids):
            raise ValueError("eligibility decision semantic IDs must be unique")
        by_member = {member.member_id: member for member in self.members}
        if {decision.member_id for decision in self.decisions} != set(by_member):
            raise ValueError("universe snapshot requires exactly one decision for every member")
        if len(self.decisions) != len(self.members):
            raise ValueError("universe snapshot contains duplicate member decisions")
        if any(
            member.as_of != self.as_of or member.available_at > self.as_of
            for member in self.members
        ):
            raise ValueError("universe snapshot contains a future or mismatched member")
        for decision in self.decisions:
            member = by_member[decision.member_id]
            if (
                decision.ticker != member.ticker
                or decision.as_of != self.as_of
                or decision.available_at > self.as_of
            ):
                raise ValueError("universe snapshot contains a future or mismatched decision")
        if self.fixed_fixture and (self.limitation is None or not self.limitation.strip()):
            raise ValueError("fixed universe fixtures require an explicit limitation")
        if not self.fixed_fixture and self.limitation is not None:
            raise ValueError("non-fixture universes cannot claim a fixed-fixture limitation")
        return self


class FactorDefinition(HashedContractModel):
    factor_id: SemanticId
    name: Annotated[str, Field(min_length=1)]
    family: FactorFamily
    economic_rationale: Annotated[str, Field(min_length=1)]
    deterministic_formula: Annotated[str, Field(min_length=1)]
    lookback_days: int = Field(gt=0)
    lag_days: int = Field(ge=0)
    universe_id: SemanticId
    neutralization: tuple[Literal["sector", "industry", "size", "market_beta"], ...] = ()
    horizon_days: int = Field(gt=0)
    commission_bps: NonNegativeFloat
    slippage_bps: NonNegativeFloat
    evaluation_ids: tuple[SemanticId, ...] = ()
    contract_version: ContractVersion = "3.1.0"

    @model_validator(mode="after")
    def definition_ids_are_unique(self) -> Self:
        if len(set(self.neutralization)) != len(self.neutralization):
            raise ValueError("neutralization dimensions must be unique")
        if len(set(self.evaluation_ids)) != len(self.evaluation_ids):
            raise ValueError("factor evaluation semantic IDs must be unique")
        return self


class FactorObservation(PointInTimeContract):
    observation_id: SemanticId
    factor_id: SemanticId
    universe_snapshot_id: SemanticId
    ticker: str
    value: FiniteFloat
    input_available_at: AwareDatetime
    source_ids: tuple[str, ...] = ()
    calculation_id: SemanticId
    contract_version: ContractVersion = "3.1.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def input_is_lagged(self) -> Self:
        if self.input_available_at > self.available_at:
            raise ValueError("factor input cannot become available after the observation")
        return self


class FactorDiagnostics(FrozenContractModel):
    information_coefficient: FiniteFloat
    rank_information_coefficient: FiniteFloat
    icir: FiniteFloat
    quantile_returns: tuple[FiniteFloat, ...] = Field(min_length=2)
    long_short_return: FiniteFloat
    monotonicity: FiniteFloat
    turnover: NonNegativeFloat
    autocorrelation: FiniteFloat
    sector_neutrality: NonNegativeFloat
    size_neutrality: NonNegativeFloat
    subperiod_returns: dict[str, FiniteFloat] = Field(default_factory=dict)
    regime_returns: dict[str, FiniteFloat] = Field(default_factory=dict)
    gross_return: FiniteFloat
    cost_adjusted_return: FiniteFloat
    capacity: NonNegativeFloat
    decay: dict[int, FiniteFloat] = Field(default_factory=dict)
    factor_correlations: dict[SemanticId, FiniteFloat] = Field(default_factory=dict)
    crowding_score: NonNegativeFloat
    contract_version: ContractVersion = "3.1.0"

    @model_validator(mode="after")
    def diagnostic_keys_are_valid(self) -> Self:
        if any(lag <= 0 for lag in self.decay):
            raise ValueError("factor decay lags must be positive")
        return self


class FactorEvaluation(PointInTimeContract):
    evaluation_id: SemanticId
    factor_id: SemanticId
    universe_snapshot_ids: tuple[SemanticId, ...] = Field(min_length=1)
    observation_ids: tuple[SemanticId, ...] = Field(min_length=1)
    period_start: date
    period_end: date
    diagnostics: FactorDiagnostics
    calculation_ids: tuple[SemanticId, ...] = Field(min_length=1)
    contract_version: ContractVersion = "3.1.0"

    @model_validator(mode="after")
    def evaluation_is_well_formed(self) -> Self:
        if self.period_start > self.period_end:
            raise ValueError("factor evaluation period start cannot follow period end")
        for values, label in (
            (self.universe_snapshot_ids, "universe snapshot"),
            (self.observation_ids, "observation"),
            (self.calculation_ids, "calculation"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"factor evaluation {label} semantic IDs must be unique")
        return self


class MarketEvent(PointInTimeContract):
    event_id: SemanticId
    ticker: str
    event_type: Annotated[str, Field(min_length=1)]
    occurred_at: AwareDatetime
    source_type: Annotated[str, Field(min_length=1)]
    surprise: FiniteFloat | None = None
    source_ids: tuple[str, ...] = Field(min_length=1)
    contract_version: ContractVersion = "3.1.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def event_timestamps_are_causal(self) -> Self:
        if self.occurred_at > self.available_at:
            raise ValueError("event must occur before it becomes available")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("market event source IDs must be unique")
        return self


class EventStudySpec(HashedContractModel):
    spec_id: SemanticId
    benchmark_ticker: str
    event_types: tuple[str, ...] = Field(min_length=1)
    estimation_window_start: int = Field(lt=0)
    estimation_window_end: int = Field(lt=0)
    car_windows: tuple[tuple[int, int], ...] = Field(min_length=1)
    bootstrap_samples: int = Field(gt=0)
    confidence_level: Probability
    segment_by_source_type: bool = True
    include_surprise: bool = True
    pre_event_leakage_days: int = Field(gt=0)
    market_model_version: SemanticId
    contract_version: ContractVersion = "3.1.0"

    @field_validator("benchmark_ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def windows_are_ordered_and_unique(self) -> Self:
        if self.estimation_window_start >= self.estimation_window_end:
            raise ValueError("estimation window start must precede its end")
        if len(set(self.event_types)) != len(self.event_types):
            raise ValueError("event study event types must be unique")
        if len(set(self.car_windows)) != len(self.car_windows):
            raise ValueError("event study CAR windows must be unique")
        if any(start > end for start, end in self.car_windows):
            raise ValueError("CAR window start cannot follow its end")
        earliest_test_offset = min(
            *(start for start, _ in self.car_windows), -self.pre_event_leakage_days
        )
        if self.estimation_window_end >= earliest_test_offset:
            raise ValueError("estimation window must end before CAR and leakage windows")
        return self


class BootstrapInterval(FrozenContractModel):
    lower: FiniteFloat
    upper: FiniteFloat

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> Self:
        if self.lower > self.upper:
            raise ValueError("bootstrap interval lower bound cannot exceed upper bound")
        return self


class EventStudyResult(PointInTimeContract):
    result_id: SemanticId
    spec_id: SemanticId
    event_ids: tuple[SemanticId, ...] = Field(min_length=1)
    cumulative_abnormal_returns: dict[str, FiniteFloat] = Field(min_length=1)
    bootstrap_intervals: dict[str, BootstrapInterval] = Field(min_length=1)
    source_segment_cars: dict[str, FiniteFloat] = Field(default_factory=dict)
    surprise_slope: FiniteFloat | None = None
    pre_event_leakage_detected: bool
    calculation_ids: tuple[SemanticId, ...] = Field(min_length=1)
    contract_version: ContractVersion = "3.1.0"

    @model_validator(mode="after")
    def result_is_complete(self) -> Self:
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("event study event semantic IDs must be unique")
        if set(self.cumulative_abnormal_returns) != set(self.bootstrap_intervals):
            raise ValueError("every CAR window requires a bootstrap interval")
        if len(set(self.calculation_ids)) != len(self.calculation_ids):
            raise ValueError("event study calculation semantic IDs must be unique")
        return self


class RegimeSnapshot(PointInTimeContract):
    snapshot_id: SemanticId
    volatility_regime: Literal["low", "normal", "high", "crisis"]
    market_trend: Literal["down", "sideways", "up"]
    rates_liquidity_context: Literal["tightening", "neutral", "easing"]
    risk_state: Literal["risk_off", "neutral", "risk_on"]
    factor_leadership: tuple[FactorFamily, ...] = Field(min_length=1)
    correlation_regime: Literal["low", "normal", "high"]
    model_id: SemanticId
    calculation_ids: tuple[SemanticId, ...] = Field(min_length=1)
    interpretation_only: Literal[True] = True
    order_authority: Literal[False] = False
    contract_version: ContractVersion = "3.1.0"

    @model_validator(mode="after")
    def regime_ids_are_unique(self) -> Self:
        if len(set(self.factor_leadership)) != len(self.factor_leadership):
            raise ValueError("factor leadership entries must be unique")
        if len(set(self.calculation_ids)) != len(self.calculation_ids):
            raise ValueError("regime calculation semantic IDs must be unique")
        return self


class BehavioralFeatures(PointInTimeContract):
    feature_id: SemanticId
    ticker: str
    attention_shock: FiniteFloat
    mention_acceleration: FiniteFloat
    sentiment_dispersion: NonNegativeFloat
    source_diversity: NonNegativeFloat
    narrative_saturation: NonNegativeFloat
    abnormal_volume: FiniteFloat
    price_attention_reflexivity: FiniteFloat
    source_ids: tuple[str, ...] = Field(min_length=1)
    calculator_id: SemanticId
    order_authority: Literal[False] = False
    contract_version: ContractVersion = "3.1.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)


class GraphFeatures(PointInTimeContract):
    feature_id: SemanticId
    ticker: str
    supplier_concentration: NonNegativeFloat
    customer_concentration: NonNegativeFloat
    director_executive_overlap: NonNegativeFloat
    ownership_centrality: NonNegativeFloat
    litigation_regulatory_exposure: NonNegativeFloat
    narrative_propagation: NonNegativeFloat
    common_exposure_cluster: Annotated[str, Field(min_length=1)] | None = None
    graph_snapshot_id: SemanticId
    calculator_id: SemanticId
    order_authority: Literal[False] = False
    contract_version: ContractVersion = "3.1.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)


class PortfolioModelRequest(PointInTimeContract):
    request_id: SemanticId
    model_id: SemanticId
    method: PortfolioMethod
    universe_snapshot_id: SemanticId
    tickers: tuple[str, ...] = Field(min_length=1)
    expected_returns: dict[str, FiniteFloat] = Field(default_factory=dict)
    volatilities: dict[str, PositiveFloat] = Field(default_factory=dict)
    covariance: dict[str, dict[str, FiniteFloat]] = Field(default_factory=dict)
    benchmark_weights: dict[str, FiniteFloat] = Field(default_factory=dict)
    lower_bound: FiniteFloat = 0.0
    upper_bound: FiniteFloat = 1.0
    gross_target: PositiveFloat = 1.0
    constraints_hash: Sha256
    input_snapshot_hashes: tuple[Sha256, ...] = Field(min_length=1)
    contract_version: ContractVersion = "3.1.0"

    @field_validator("tickers", mode="before")
    @classmethod
    def normalize_symbols(cls, value: object) -> object:
        if not isinstance(value, (tuple, list)):
            return value
        return tuple(normalize_ticker(ticker) for ticker in value)

    @field_validator("expected_returns", "volatilities", "benchmark_weights", mode="before")
    @classmethod
    def normalize_numeric_maps(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {normalize_ticker(ticker): item for ticker, item in value.items()}

    @field_validator("covariance", mode="before")
    @classmethod
    def normalize_covariance(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {
            normalize_ticker(row): {
                normalize_ticker(column): item for column, item in columns.items()
            }
            for row, columns in value.items()
        }

    @model_validator(mode="after")
    def numerical_inputs_are_explicit(self) -> Self:
        names = set(self.tickers)
        if len(names) != len(self.tickers):
            raise ValueError("portfolio request tickers must be unique")
        if self.lower_bound > self.upper_bound:
            raise ValueError("portfolio lower bound cannot exceed upper bound")
        for values, label in (
            (self.expected_returns, "expected returns"),
            (self.volatilities, "volatilities"),
            (self.benchmark_weights, "benchmark weights"),
        ):
            if not set(values).issubset(names):
                raise ValueError(f"portfolio {label} contain an unknown ticker")
        if self.covariance:
            if set(self.covariance) != names or any(
                set(row) != names for row in self.covariance.values()
            ):
                raise ValueError("portfolio covariance must be a complete square ticker matrix")
            for left in names:
                for right in names:
                    if abs(self.covariance[left][right] - self.covariance[right][left]) > 1e-12:
                        raise ValueError("portfolio covariance must be symmetric")
        if len(set(self.input_snapshot_hashes)) != len(self.input_snapshot_hashes):
            raise ValueError("portfolio input snapshot hashes must be unique")
        return self


class PortfolioModelResult(PointInTimeContract):
    result_id: SemanticId
    request_id: SemanticId
    model_id: SemanticId
    method: PortfolioMethod
    weights: dict[str, FiniteFloat] = Field(min_length=1)
    expected_return: FiniteFloat
    expected_volatility: NonNegativeFloat
    gross_exposure: NonNegativeFloat
    net_exposure: FiniteFloat
    adapter: Literal["dependency_free", "skfolio"]
    fallback_model_id: SemanticId | None = None
    calculation_ids: tuple[SemanticId, ...] = Field(min_length=1)
    input_hash: Sha256
    contract_version: ContractVersion = "3.1.0"

    @field_validator("weights", mode="before")
    @classmethod
    def normalize_weights(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {normalize_ticker(ticker): weight for ticker, weight in value.items()}

    @model_validator(mode="after")
    def result_arithmetic_is_self_consistent(self) -> Self:
        gross = sum(abs(weight) for weight in self.weights.values())
        net = sum(self.weights.values())
        if abs(gross - self.gross_exposure) > 1e-12 or abs(net - self.net_exposure) > 1e-12:
            raise ValueError("portfolio result gross/net exposure mismatch")
        if self.adapter == "dependency_free" and self.fallback_model_id is not None:
            raise ValueError("dependency-free results cannot name a fallback")
        if self.adapter == "skfolio" and self.fallback_model_id == self.model_id:
            raise ValueError("portfolio fallback must be a distinct model")
        if len(set(self.calculation_ids)) != len(self.calculation_ids):
            raise ValueError("portfolio calculation semantic IDs must be unique")
        return self


class QuantTrialRecord(HashedContractModel):
    trial_id: SemanticId
    experiment_id: Annotated[str, Field(min_length=1)]
    experiment_hash: Sha256
    trial_number: int = Field(gt=0)
    strategy_id: StrategyComparisonId
    common_sample_hash: Sha256
    parameters_hash: Sha256
    status: Literal["declared", "running", "completed", "failed", "rejected", "abstained"]
    declared_at: AwareDatetime
    evaluated_at: AwareDatetime | None = None
    metrics: dict[str, FiniteFloat] = Field(default_factory=dict)
    contract_version: ContractVersion = "3.1.0"

    @model_validator(mode="after")
    def trial_timestamps_match_status(self) -> Self:
        terminal = self.status in {"completed", "failed", "rejected", "abstained"}
        if terminal != (self.evaluated_at is not None):
            raise ValueError("terminal trials require evaluated_at; open trials must omit it")
        if self.evaluated_at is not None and self.evaluated_at < self.declared_at:
            raise ValueError("trial cannot be evaluated before declaration")
        return self


class BaselinePerformance(HashedContractModel):
    strategy_id: StrategyComparisonId
    common_sample_hash: Sha256
    benchmark_id: SemanticId
    return_horizon_days: int = Field(gt=0)
    capital: PositiveFloat
    constraints_hash: Sha256
    cost_grid: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    net_annualized_sharpe: FiniteFloat
    psr: Probability = 0.5
    dsr: Probability
    pbo: Probability
    max_drawdown: Annotated[FiniteFloat, Field(ge=0.0, le=1.0)]
    turnover: NonNegativeFloat
    two_x_cost_sharpe: FiniteFloat
    five_x_cost_sharpe: FiniteFloat = 0.0
    evaluated_at: AwareDatetime
    contract_version: ContractVersion = "3.1.0"

    @model_validator(mode="after")
    def cost_grid_is_predeclared(self) -> Self:
        base, double, quintuple = self.cost_grid
        if base <= 0.0 or double != 2.0 * base or quintuple != 5.0 * base:
            raise ValueError("baseline cost grid must be the declared base/2x/5x grid")
        return self
