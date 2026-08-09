"""Frozen v3B multi-strategy hierarchy and attribution contracts."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, FiniteFloat, field_validator, model_validator

from ._base import normalize_ticker, normalize_ticker_map
from .artifacts import canonical_sha256
from .forecasts import AlphaForecast
from .portfolio import PortfolioProposal
from .quant import (
    PREDECLARED_STRATEGY_IDS,
    BaselinePerformance,
    BehavioralFeatures,
    EventStudyResult,
    FactorEvaluation,
    GraphFeatures,
    HashedContractModel,
    NonNegativeFloat,
    PortfolioMethod,
    PositiveFloat,
    Probability,
    RegimeSnapshot,
    SemanticId,
    Sha256,
    UniverseSnapshot,
)
from .risk import RiskPolicy

Fraction = Annotated[FiniteFloat, Field(ge=0.0, le=1.0)]


class AlphaModelRef(HashedContractModel):
    model_id: SemanticId
    feature_ids: tuple[SemanticId, ...] = ()
    horizon_days: int = Field(gt=0)
    weight: PositiveFloat = 1.0
    provider: Annotated[str, Field(min_length=1)] = "deterministic"

    @model_validator(mode="after")
    def features_are_unique(self) -> Self:
        if len(set(self.feature_ids)) != len(self.feature_ids):
            raise ValueError("alpha model feature IDs must be unique")
        return self


class ForecastBlendPolicy(HashedContractModel):
    policy_id: SemanticId
    maximum_horizon_gap_days: int = Field(ge=0)
    overlap_penalty: Fraction
    minimum_evidence_quality: Probability
    minimum_calibration: Probability


class PodPortfolioPolicy(HashedContractModel):
    policy_id: SemanticId
    method: PortfolioMethod
    gross_target: Fraction
    market_neutral: bool = False


class PodRiskBudget(HashedContractModel):
    budget_id: SemanticId
    maximum_gross: Fraction
    maximum_position: Fraction
    maximum_drawdown: Fraction

    @model_validator(mode="after")
    def position_fits_gross(self) -> Self:
        if self.maximum_position > self.maximum_gross:
            raise ValueError("pod maximum position cannot exceed maximum gross")
        return self


class StrategyPod(HashedContractModel):
    pod_id: SemanticId
    display_name: Annotated[str, Field(min_length=1)]
    capital_weight: Fraction
    models: tuple[AlphaModelRef, ...] = Field(min_length=1)
    blend_policy: ForecastBlendPolicy
    portfolio_policy: PodPortfolioPolicy
    risk_budget: PodRiskBudget

    @model_validator(mode="after")
    def pod_ids_are_unique(self) -> Self:
        ids = [model.model_id for model in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError("pod alpha model IDs must be unique")
        return self


class FundAllocatorPolicy(HashedContractModel):
    policy_id: SemanticId
    method: Literal["static", "inverse_volatility"] = "static"
    maximum_pod_weight: Fraction = 1.0
    # v3B deliberately does not permit redistribution of an abstaining pod's budget.
    preserve_unallocated_cash: Literal[True] = True


class FundMandate(HashedContractModel):
    mandate_id: SemanticId
    display_name: Annotated[str, Field(min_length=1)]
    capital: Annotated[Decimal, Field(gt=Decimal("0"))]
    pods: tuple[StrategyPod, ...] = Field(min_length=1)
    allocator_policy: FundAllocatorPolicy
    master_risk: RiskPolicy
    rebalance: Literal["daily", "weekly", "monthly"] = "weekly"
    benchmark: str = "SPY"

    @field_validator("benchmark", mode="before")
    @classmethod
    def normalize_benchmark(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def mandate_is_coherent(self) -> Self:
        ids = [pod.pod_id for pod in self.pods]
        if len(set(ids)) != len(ids):
            raise ValueError("fund mandate pod IDs must be unique")
        total = sum(pod.capital_weight for pod in self.pods)
        if total > 1.0 + 1e-12:
            raise ValueError("fund mandate pod weights cannot exceed one")
        if any(pod.capital_weight > self.allocator_policy.maximum_pod_weight for pod in self.pods):
            raise ValueError("fund mandate pod weight exceeds allocator cap")
        return self


class ModelForecastBatch(HashedContractModel):
    batch_id: SemanticId
    pod_id: SemanticId
    model_id: SemanticId
    quant_bundle_id: SemanticId
    quant_bundle_hash: Sha256
    universe_snapshot_id: SemanticId
    as_of: AwareDatetime
    available_at: AwareDatetime
    forecasts: tuple[AlphaForecast, ...] = Field(min_length=1)
    calibration_score: Probability
    regime_score: Probability
    evidence_quality: Probability
    feature_ids: tuple[SemanticId, ...] = ()

    @model_validator(mode="after")
    def batch_is_point_in_time_and_unique(self) -> Self:
        if self.available_at > self.as_of:
            raise ValueError("forecast batch is not point in time")
        ids = [forecast.forecast_id for forecast in self.forecasts]
        tickers = [forecast.ticker for forecast in self.forecasts]
        if len(set(ids)) != len(ids) or len(set(tickers)) != len(tickers):
            raise ValueError("forecast batch IDs and tickers must be unique")
        if any(forecast.as_of != self.as_of for forecast in self.forecasts):
            raise ValueError("forecast batch contains a mismatched cutoff")
        if len(set(self.feature_ids)) != len(self.feature_ids):
            raise ValueError("forecast batch feature IDs must be unique")
        return self


class ForecastContribution(HashedContractModel):
    contribution_id: SemanticId
    pod_id: SemanticId
    model_id: SemanticId
    forecast_id: Annotated[str, Field(min_length=1)]
    ticker: str
    blend_weight: Fraction
    expected_return_contribution: FiniteFloat
    uncertainty: Probability
    calibration_score: Probability
    regime_score: Probability
    evidence_quality: Probability
    overlap_penalty_applied: Fraction

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)


class BlendedForecast(HashedContractModel):
    blended_id: SemanticId
    pod_id: SemanticId
    ticker: str
    as_of: AwareDatetime
    horizon_days: int = Field(gt=0)
    expected_excess_return: FiniteFloat
    expected_volatility: PositiveFloat
    probability_positive: Probability
    uncertainty: Probability
    contributions: tuple[ForecastContribution, ...] = Field(min_length=1)

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def contributions_reconcile(self) -> Self:
        if any(
            item.pod_id != self.pod_id or item.ticker != self.ticker for item in self.contributions
        ):
            raise ValueError("blended forecast contribution identity mismatch")
        if len({item.forecast_id for item in self.contributions}) != len(self.contributions):
            raise ValueError("blended forecast contains duplicate source forecasts")
        if not math.isclose(
            sum(item.blend_weight for item in self.contributions), 1.0, abs_tol=1e-12
        ):
            raise ValueError("blended forecast weights must sum to one")
        if not math.isclose(
            sum(item.expected_return_contribution for item in self.contributions),
            self.expected_excess_return,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("blended expected return does not reconcile")
        return self


class PodContribution(HashedContractModel):
    contribution_id: SemanticId
    pod_id: SemanticId
    ticker: str
    pod_weight: FiniteFloat
    allocator_weight: Fraction
    allocated_weight: FiniteFloat

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_symbol(cls, value: object) -> str:
        return normalize_ticker(value)

    @model_validator(mode="after")
    def allocation_reconciles(self) -> Self:
        if not math.isclose(
            self.allocated_weight,
            self.pod_weight * self.allocator_weight,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("pod contribution does not reconcile")
        return self


class PodTarget(HashedContractModel):
    target_id: SemanticId
    pod_id: SemanticId
    as_of: AwareDatetime
    target_weights: dict[str, float] = Field(default_factory=dict)
    cash_weight: Fraction
    gross_exposure: NonNegativeFloat
    blended_forecast_ids: tuple[SemanticId, ...] = ()

    @field_validator("target_weights", mode="before")
    @classmethod
    def normalize_weights(cls, value: object) -> object:
        return normalize_ticker_map(value) if isinstance(value, dict) else value

    @model_validator(mode="after")
    def target_exposures_reconcile(self) -> Self:
        gross = sum(abs(value) for value in self.target_weights.values())
        cash = max(0.0, 1.0 - sum(self.target_weights.values()))
        if not math.isclose(gross, self.gross_exposure, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("pod gross exposure does not reconcile")
        if not math.isclose(cash, self.cash_weight, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("pod cash does not reconcile")
        if len(set(self.blended_forecast_ids)) != len(self.blended_forecast_ids):
            raise ValueError("pod blended forecast IDs must be unique")
        return self


class MasterPortfolio(HashedContractModel):
    master_id: SemanticId
    mandate_id: SemanticId
    as_of: AwareDatetime
    target_weights: dict[str, float] = Field(default_factory=dict)
    cash_weight: Fraction
    gross_exposure: NonNegativeFloat
    net_exposure: FiniteFloat
    allocator_weights: dict[SemanticId, Fraction]
    pod_targets: tuple[PodTarget, ...] = Field(min_length=1)
    contributions: tuple[PodContribution, ...] = ()
    input_hash: Sha256

    @field_validator("target_weights", mode="before")
    @classmethod
    def normalize_weights(cls, value: object) -> object:
        return normalize_ticker_map(value) if isinstance(value, dict) else value

    @model_validator(mode="after")
    def master_reconciles(self) -> Self:
        pod_ids = [pod.pod_id for pod in self.pod_targets]
        if len(set(pod_ids)) != len(pod_ids) or set(pod_ids) != set(self.allocator_weights):
            raise ValueError("master allocator weights must bind each pod exactly once")
        if any(pod.as_of != self.as_of for pod in self.pod_targets):
            raise ValueError("master portfolio contains a mismatched pod cutoff")
        if any(item.pod_id not in self.allocator_weights for item in self.contributions):
            raise ValueError("master portfolio contains an unknown pod contribution")
        by_ticker: defaultdict[str, float] = defaultdict(float)
        for item in self.contributions:
            by_ticker[item.ticker] += item.allocated_weight
        expected = {
            ticker: value for ticker, value in sorted(by_ticker.items()) if abs(value) > 1e-15
        }
        if set(expected) != set(self.target_weights) or any(
            not math.isclose(
                expected[ticker], self.target_weights[ticker], rel_tol=1e-12, abs_tol=1e-12
            )
            for ticker in expected
        ):
            raise ValueError("master target does not reconcile to pod contributions")
        gross = sum(abs(value) for value in self.target_weights.values())
        net = sum(self.target_weights.values())
        cash = max(0.0, 1.0 - net)
        if not math.isclose(gross, self.gross_exposure, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("master gross exposure does not reconcile")
        if not math.isclose(net, self.net_exposure, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("master net exposure does not reconcile")
        if not math.isclose(cash, self.cash_weight, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("master cash does not reconcile")
        return self

    def to_portfolio_proposal(self, current_weights: Mapping[str, float]) -> PortfolioProposal:
        current = dict(sorted(normalize_ticker_map(dict(current_weights)).items()))
        names = set(current) | set(self.target_weights)
        turnover = 0.5 * sum(
            abs(self.target_weights.get(ticker, 0.0) - current.get(ticker, 0.0)) for ticker in names
        )
        payload = {
            "master_portfolio": self.model_dump(mode="json"),
            "current_weights": current,
        }
        return PortfolioProposal(
            as_of=self.as_of.date(),
            target_weights=self.target_weights,
            cash_weight=self.cash_weight,
            gross_exposure=self.gross_exposure,
            turnover=turnover,
            input_hash=canonical_sha256(payload),
        )


class QuantResearchBundle(HashedContractModel):
    """Hash-bound, point-in-time research inputs for a single strategy cutoff."""

    bundle_id: SemanticId
    as_of: AwareDatetime
    universe_snapshot: UniverseSnapshot
    factor_evaluations: tuple[FactorEvaluation, ...] = Field(min_length=1)
    event_study_results: tuple[EventStudyResult, ...] = Field(min_length=1)
    regime_snapshot: RegimeSnapshot
    behavioral_features: tuple[BehavioralFeatures, ...] = Field(min_length=1)
    graph_features: tuple[GraphFeatures, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def research_is_complete_and_point_in_time(self) -> Self:
        if self.universe_snapshot.as_of != self.as_of:
            raise ValueError("research bundle universe snapshot cutoff mismatch")

        evaluation_ids = [evaluation.evaluation_id for evaluation in self.factor_evaluations]
        if len(set(evaluation_ids)) != len(evaluation_ids):
            raise ValueError("research bundle factor evaluation IDs must be unique")
        expected_snapshot_ids = (self.universe_snapshot.snapshot_id,)
        for evaluation in self.factor_evaluations:
            if evaluation.as_of != self.as_of:
                raise ValueError(
                    "research bundle contains a future or mismatched factor evaluation"
                )
            if evaluation.universe_snapshot_ids != expected_snapshot_ids:
                raise ValueError("factor evaluation must bind exactly the bundle universe snapshot")

        result_ids = [result.result_id for result in self.event_study_results]
        if len(set(result_ids)) != len(result_ids):
            raise ValueError("research bundle event study result IDs must be unique")
        for result in self.event_study_results:
            if result.as_of != self.as_of:
                raise ValueError(
                    "research bundle contains a future or mismatched event study result"
                )
            if result.pre_event_leakage_detected:
                raise ValueError("research bundle cannot contain an event study with leakage")

        if self.regime_snapshot.as_of != self.as_of:
            raise ValueError("research bundle regime snapshot cutoff mismatch")

        eligible_tickers = {
            decision.ticker for decision in self.universe_snapshot.decisions if decision.eligible
        }
        self._validate_feature_coverage(self.behavioral_features, eligible_tickers, "behavioral")
        self._validate_feature_coverage(self.graph_features, eligible_tickers, "graph")
        return self

    def _validate_feature_coverage(
        self,
        features: tuple[BehavioralFeatures, ...] | tuple[GraphFeatures, ...],
        eligible_tickers: set[str],
        feature_kind: str,
    ) -> None:
        feature_ids = [feature.feature_id for feature in features]
        tickers = [feature.ticker for feature in features]
        if len(set(feature_ids)) != len(feature_ids) or len(set(tickers)) != len(tickers):
            raise ValueError(
                f"research bundle {feature_kind} feature IDs and tickers must be unique"
            )
        if any(feature.as_of != self.as_of for feature in features):
            raise ValueError(
                f"research bundle contains a future or mismatched {feature_kind} feature"
            )
        if set(tickers) != eligible_tickers:
            raise ValueError(
                f"research bundle {feature_kind} features must cover exactly eligible "
                "universe tickers"
            )


class StrategyComparison(HashedContractModel):
    comparison_id: SemanticId
    common_sample_hash: Sha256
    cost_grid_bps: tuple[NonNegativeFloat, ...] = Field(min_length=3)
    declared_at: AwareDatetime
    evaluated_at: AwareDatetime
    baselines: tuple[BaselinePerformance, ...]
    combined_status: Literal["eligible", "rejected", "abstained"]
    eligibility_checks: dict[str, bool]
    experiment_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def comparison_is_predeclared_and_complete(self) -> Self:
        if self.declared_at > self.evaluated_at:
            raise ValueError("strategy comparison must be declared before evaluation")
        ids = [baseline.strategy_id for baseline in self.baselines]
        if tuple(sorted(ids)) != tuple(sorted(PREDECLARED_STRATEGY_IDS)) or len(ids) != len(
            set(ids)
        ):
            raise ValueError(
                "strategy comparison must contain all six predeclared strategies exactly once"
            )
        if tuple(sorted(self.cost_grid_bps)) != self.cost_grid_bps or len(
            set(self.cost_grid_bps)
        ) != len(self.cost_grid_bps):
            raise ValueError("strategy comparison cost grid must be sorted and unique")
        passed = bool(self.eligibility_checks) and all(self.eligibility_checks.values())
        if self.combined_status == "eligible" and not passed:
            raise ValueError("eligible combined strategy must pass every predeclared check")
        if self.combined_status == "rejected" and passed:
            raise ValueError("rejected combined strategy must fail a predeclared check")
        if len(set(self.experiment_ids)) != len(self.experiment_ids):
            raise ValueError("strategy comparison experiment IDs must be unique")
        return self
