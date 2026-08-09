"""Honest, deterministic evaluation of the six predeclared v3B strategies.

This module evaluates supplied return series only.  It cannot configure, activate,
or promote a strategy.  Every supplied experiment is ledgered before any
cross-strategy performance calculation is run.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime
from typing import Annotated, Any, Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aegis.contracts import (
    PREDECLARED_STRATEGY_IDS,
    BaselinePerformance,
    ExperimentRecord,
    StrategyComparison,
    canonical_sha256,
)
from aegis.contracts.quant import StrategyComparisonId
from aegis.research_lab.experiments import ExperimentLedger
from aegis.research_lab.validation import (
    probability_of_backtest_overfitting,
    validation_statistics,
)

_SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_COST_GRID_BPS = (1.0, 2.0, 5.0)
_SIMPLE_STRATEGY_IDS: tuple[StrategyComparisonId, ...] = (
    "equal-weight-v1",
    "inverse-vol-v1",
    "simple-factor-v1",
)
_COMBINED_STRATEGY_ID: StrategyComparisonId = "combined-multistrategy-v1"


def common_sample_hash(
    *,
    dates: tuple[date, ...],
    data_snapshot_hash: str,
    eligible_observation_ids: tuple[str, ...],
    return_horizon_days: int,
    capital: float,
    constraints_hash: str,
    benchmark_id: str,
    base_cost_bps: float,
) -> str:
    """Content hash for the PIT sample shared by all six strategy rows."""
    return canonical_sha256(
        {
            "dates": dates,
            "data_snapshot_hash": data_snapshot_hash,
            "eligible_observation_ids": eligible_observation_ids,
            "return_horizon_days": return_horizon_days,
            "capital": capital,
            "constraints_hash": constraints_hash,
            "benchmark_id": benchmark_id,
            "base_cost_bps": base_cost_bps,
        }
    )


def strategy_series_hash(
    *, common_hash: str, gross_returns: tuple[float, ...], turnover: tuple[float, ...]
) -> str:
    """Content hash for a particular model's immutable realized return row."""
    return canonical_sha256(
        {"common_sample_hash": common_hash, "gross_returns": gross_returns, "turnover": turnover}
    )


class StrategyEvaluationError(ValueError):
    """The supplied trials do not form the predeclared common-sample test."""


class StrategyReturnSeries(BaseModel):
    """Frozen inputs and experiment lineage for one predeclared strategy.

    Returns are decimal period returns (``0.01`` means one percent).  Turnover
    is a non-negative fraction of capital for the matching period.  Costs are
    therefore deducted as ``turnover * bps / 10_000``.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    strategy_id: StrategyComparisonId
    common_sample_hash: _SHA256
    dates: tuple[date, ...] = Field(min_length=4)
    data_snapshot_hash: _SHA256
    eligible_observation_ids: tuple[str, ...] = Field(min_length=4)
    series_input_hash: _SHA256
    return_horizon_days: int = Field(gt=0)
    capital: Annotated[float, Field(gt=0.0)]
    constraints_hash: _SHA256
    benchmark_id: Annotated[str, Field(min_length=1)]
    gross_returns: tuple[float, ...] = Field(min_length=4)
    turnover: tuple[Annotated[float, Field(ge=0.0)], ...] = Field(min_length=4)
    experiment: ExperimentRecord
    base_cost_bps: Annotated[float, Field(gt=0.0)] = 10.0

    @model_validator(mode="after")
    def inputs_are_aligned_and_bound(self) -> Self:
        if self.strategy_id not in PREDECLARED_STRATEGY_IDS:
            raise ValueError("strategy is not one of the six predeclared strategy IDs")
        if len(set(self.eligible_observation_ids)) != len(self.eligible_observation_ids):
            raise ValueError("eligible observation IDs must be unique")
        if len(self.eligible_observation_ids) != len(self.dates):
            raise ValueError("eligible observation IDs must align to the common sample")
        if len(self.gross_returns) != len(self.dates) or len(self.turnover) != len(self.dates):
            raise ValueError("dates, gross returns, and turnover must have equal lengths")
        if any(
            current <= previous
            for previous, current in zip(self.dates, self.dates[1:], strict=False)
        ):
            raise ValueError("strategy dates must be strictly increasing")
        numeric = (*self.gross_returns, *self.turnover, self.capital, self.base_cost_bps)
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("strategy evaluation inputs must be finite")
        if any(value <= -1.0 for value in self.gross_returns):
            raise ValueError("gross period returns must be greater than -100 percent")
        if self.experiment.data_snapshot_hash != self.data_snapshot_hash:
            raise ValueError("experiment record is not bound to the data snapshot")
        recorded_strategy = self.experiment.parameters.get("strategy_id")
        if recorded_strategy != self.strategy_id:
            raise ValueError("experiment record is not bound to the strategy ID")
        expected_common_hash = common_sample_hash(
            dates=self.dates,
            data_snapshot_hash=self.data_snapshot_hash,
            eligible_observation_ids=self.eligible_observation_ids,
            return_horizon_days=self.return_horizon_days,
            capital=self.capital,
            constraints_hash=self.constraints_hash,
            benchmark_id=self.benchmark_id,
            base_cost_bps=self.base_cost_bps,
        )
        if self.common_sample_hash != expected_common_hash:
            raise ValueError("common sample hash does not bind the supplied PIT sample")
        expected_series_hash = strategy_series_hash(
            common_hash=self.common_sample_hash,
            gross_returns=self.gross_returns,
            turnover=self.turnover,
        )
        if self.series_input_hash != expected_series_hash:
            raise ValueError("series input hash does not bind returns and turnover")
        if self.experiment.parameters.get("series_input_hash") != self.series_input_hash:
            raise ValueError("experiment record is not bound to the return series")
        return self

    @property
    def experiment_record(self) -> ExperimentRecord:
        """Explicit alias for callers that use the full lineage name."""
        return self.experiment

    @property
    def per_period_turnover(self) -> tuple[float, ...]:
        """Explicit alias documenting that turnover is period-aligned."""
        return self.turnover


def _net_returns(series: StrategyReturnSeries, cost_bps: float) -> list[float]:
    values = [
        gross - period_turnover * cost_bps / 10_000.0
        for gross, period_turnover in zip(series.gross_returns, series.turnover, strict=True)
    ]
    if any(value <= -1.0 for value in values):
        raise StrategyEvaluationError("cost-stressed period return is at or below -100 percent")
    return values


def _max_drawdown(returns: Sequence[float]) -> float:
    wealth = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        worst = max(worst, (peak - wealth) / peak)
    return worst


def _common_split_performance(
    ordered: Sequence[StrategyReturnSeries],
) -> list[list[float]]:
    """Build a deterministic four-column matrix from common contiguous dates."""
    split_indices = np.array_split(np.arange(len(ordered[0].dates)), 4)
    matrix: list[list[float]] = []
    for series in ordered:
        base_returns = _net_returns(series, series.base_cost_bps)
        # Mean net return is deliberately used as the split score: unlike a
        # one-observation Sharpe it remains defined for every valid split.
        matrix.append(
            [
                float(np.mean([base_returns[int(index)] for index in split]))
                for split in split_indices
            ]
        )
    return matrix


def _hashed_contract[T: BaseModel](contract: type[T], values: dict[str, Any]) -> T:
    draft = contract.model_construct(**values, content_hash="0" * 64)
    payload = draft.model_dump(exclude={"content_hash"})
    return contract(**values, content_hash=canonical_sha256(payload))


def _validate_common_comparison(ordered: Sequence[StrategyReturnSeries]) -> None:
    reference = ordered[0]
    fields = (
        "common_sample_hash",
        "dates",
        "data_snapshot_hash",
        "return_horizon_days",
        "capital",
        "constraints_hash",
        "benchmark_id",
        "base_cost_bps",
    )
    for series in ordered[1:]:
        mismatched = [name for name in fields if getattr(series, name) != getattr(reference, name)]
        if mismatched:
            raise StrategyEvaluationError(
                "all six strategies must use the same common sample; mismatched "
                + ", ".join(mismatched)
            )


def _validate_experiment_times(
    ordered: Sequence[StrategyReturnSeries], declared_at: datetime, evaluated_at: datetime
) -> None:
    if declared_at.tzinfo is None or declared_at.utcoffset() is None:
        raise StrategyEvaluationError("declared_at must be timezone-aware")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise StrategyEvaluationError("evaluated_at must be timezone-aware")
    if declared_at > evaluated_at:
        raise StrategyEvaluationError("the comparison must be declared before evaluation")
    if any(series.experiment.created_at < declared_at for series in ordered):
        raise StrategyEvaluationError("every experiment must follow the comparison declaration")
    if any(series.experiment.created_at > evaluated_at for series in ordered):
        raise StrategyEvaluationError("an experiment cannot be created after evaluation")


def evaluate_predeclared_strategies(
    series: Sequence[StrategyReturnSeries],
    declared_at: datetime,
    evaluated_at: datetime,
    ledger: ExperimentLedger,
) -> StrategyComparison:
    """Evaluate all six frozen strategies and return eligibility, never promotion.

    All supplied experiment records are appended before common-sample validation
    or metric calculation.  Consequently a losing or subsequently rejected
    trial cannot disappear from the audit ledger.
    """
    supplied = tuple(series)
    _validate_experiment_times(supplied, declared_at, evaluated_at)

    experiment_ids = [item.experiment.experiment_id for item in supplied]
    if len(set(experiment_ids)) != len(experiment_ids):
        raise StrategyEvaluationError("every supplied strategy requires a unique experiment record")

    # This deliberately precedes the exact-set and common-sample gates.  Those
    # gates judge an attempted comparison; they must not become ways to erase
    # already-run failed or losing experiments.
    for item in supplied:
        ledger.append(item.experiment)

    strategy_ids = [item.strategy_id for item in supplied]
    if len(supplied) != len(PREDECLARED_STRATEGY_IDS) or set(strategy_ids) != set(
        PREDECLARED_STRATEGY_IDS
    ):
        raise StrategyEvaluationError("exactly the six predeclared strategies are required")

    by_id = {item.strategy_id: item for item in supplied}
    ordered = [by_id[strategy_id] for strategy_id in PREDECLARED_STRATEGY_IDS]
    _validate_common_comparison(ordered)

    base_returns = {item.strategy_id: _net_returns(item, item.base_cost_bps) for item in ordered}
    trial_sharpes = [
        validation_statistics(values, trial_sharpes=[])["annualized_sharpe"]
        for values in base_returns.values()
    ]
    pbo = probability_of_backtest_overfitting(_common_split_performance(ordered))

    baselines: list[BaselinePerformance] = []
    statistics_by_id: dict[StrategyComparisonId, dict[str, float]] = {}
    for item in ordered:
        statistics = validation_statistics(
            base_returns[item.strategy_id], trial_sharpes=trial_sharpes
        )
        statistics_by_id[item.strategy_id] = statistics
        two_x_statistics = validation_statistics(
            _net_returns(item, item.base_cost_bps * 2.0), trial_sharpes=trial_sharpes
        )
        # Evaluate the full declared stress grid even though the current
        # BaselinePerformance contract exposes only base and 2x Sharpe.
        five_x_statistics = validation_statistics(
            _net_returns(item, item.base_cost_bps * 5.0), trial_sharpes=trial_sharpes
        )
        values = {
            "strategy_id": item.strategy_id,
            "common_sample_hash": item.common_sample_hash,
            "benchmark_id": item.benchmark_id,
            "return_horizon_days": item.return_horizon_days,
            "capital": item.capital,
            "constraints_hash": item.constraints_hash,
            "cost_grid": (item.base_cost_bps, item.base_cost_bps * 2.0, item.base_cost_bps * 5.0),
            "net_annualized_sharpe": statistics["annualized_sharpe"],
            "psr": statistics["probabilistic_sharpe_ratio"],
            "dsr": statistics["deflated_sharpe_ratio"],
            "pbo": pbo,
            "max_drawdown": _max_drawdown(base_returns[item.strategy_id]),
            "turnover": float(np.mean(item.turnover)),
            "two_x_cost_sharpe": two_x_statistics["annualized_sharpe"],
            "five_x_cost_sharpe": five_x_statistics["annualized_sharpe"],
            "evaluated_at": evaluated_at,
        }
        baselines.append(_hashed_contract(BaselinePerformance, values))

    baseline_by_id = {item.strategy_id: item for item in baselines}
    combined = baseline_by_id[_COMBINED_STRATEGY_ID]
    best_simple_sharpe = max(
        baseline_by_id[strategy_id].net_annualized_sharpe for strategy_id in _SIMPLE_STRATEGY_IDS
    )
    checks = {
        "sharpe_delta_vs_best_simple": combined.net_annualized_sharpe >= best_simple_sharpe + 0.10,
        "deflated_sharpe_ratio": combined.dsr >= 0.50,
        "probability_of_backtest_overfitting": combined.pbo <= 0.50,
        "max_drawdown_vs_equal_weight": combined.max_drawdown
        <= baseline_by_id["equal-weight-v1"].max_drawdown,
        "turnover_vs_inverse_vol": combined.turnover
        <= 1.5 * baseline_by_id["inverse-vol-v1"].turnover,
        "two_x_cost_sharpe": combined.two_x_cost_sharpe >= 0.0,
    }
    status = "eligible" if all(checks.values()) else "rejected"
    comparison_fingerprint = canonical_sha256(
        {
            "common_sample_hash": ordered[0].common_sample_hash,
            "experiment_ids": [item.experiment.experiment_id for item in ordered],
            "series_input_hashes": [item.series_input_hash for item in ordered],
            "declared_at": declared_at,
            "evaluated_at": evaluated_at,
        }
    )
    comparison_values = {
        "comparison_id": f"strategy-comparison-{comparison_fingerprint[:16]}-v1",
        "common_sample_hash": ordered[0].common_sample_hash,
        "cost_grid_bps": (
            ordered[0].base_cost_bps,
            ordered[0].base_cost_bps * 2.0,
            ordered[0].base_cost_bps * 5.0,
        ),
        "declared_at": declared_at,
        "evaluated_at": evaluated_at,
        "baselines": tuple(baselines),
        "combined_status": status,
        "eligibility_checks": checks,
        "experiment_ids": tuple(item.experiment.experiment_id for item in ordered),
    }
    return _hashed_contract(StrategyComparison, comparison_values)
