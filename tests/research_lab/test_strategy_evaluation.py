from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel

from aegis.contracts import PREDECLARED_STRATEGY_IDS, ExperimentRecord, canonical_sha256
from aegis.research_lab.experiments import ExperimentLedger
from aegis.research_lab.strategy_evaluation import (
    StrategyEvaluationError,
    StrategyReturnSeries,
    common_sample_hash,
    evaluate_predeclared_strategies,
    strategy_series_hash,
)

DECLARED = datetime(2025, 1, 1, tzinfo=UTC)
EVALUATED = datetime(2025, 2, 1, tzinfo=UTC)
SNAPSHOT = canonical_sha256({"data": "common"})
TREE = canonical_sha256({"tree": "v3b"})
CONSTRAINTS = canonical_sha256({"constraints": "common"})
DATES = tuple(date(2025, 1, 2) + timedelta(days=index) for index in range(8))


def hashed[T: BaseModel](contract: type[T], /, **values: Any) -> T:
    draft = contract.model_construct(**values)
    return contract(
        **values, content_hash=canonical_sha256(draft.model_dump(exclude={"content_hash"}))
    )


def experiment(strategy_id: str, number: int, series_hash: str) -> ExperimentRecord:
    return hashed(
        ExperimentRecord,
        experiment_id=f"experiment-{strategy_id}",
        candidate_id=f"candidate-{strategy_id}",
        hypothesis_id=f"hypothesis-{strategy_id}",
        code_revision="0a45af0",
        tree_hash=TREE,
        data_snapshot_hash=SNAPSHOT,
        parameters={"strategy_id": strategy_id, "series_input_hash": series_hash},
        dependency_versions={"aegis": "v3b"},
        trial_number=number,
        status="passed",
        created_at=DECLARED + timedelta(hours=number),
    )


def series(*, combined_return: float = 0.02) -> tuple[StrategyReturnSeries, ...]:
    returns = {
        "equal-weight-v1": (0.004, -0.002, 0.005, -0.001, 0.004, 0.001, 0.003, -0.001),
        "inverse-vol-v1": (0.003, -0.001, 0.004, 0.0, 0.003, 0.001, 0.002, 0.0),
        "simple-factor-v1": (0.005, -0.003, 0.006, -0.002, 0.005, 0.001, 0.004, -0.001),
        "fundamental-only-v1": (0.004, -0.004, 0.007, -0.001, 0.003, 0.002, 0.005, -0.002),
        "quant-only-v1": (0.006, -0.003, 0.005, -0.001, 0.006, 0.0, 0.004, -0.001),
        "combined-multistrategy-v1": tuple(
            combined_return * multiplier
            for multiplier in (1.0, 0.9, 1.1, 0.95, 1.05, 0.85, 1.15, 1.0)
        ),
    }
    output = []
    eligible_ids = tuple(f"eligible-observation-{index}-v1" for index in range(len(DATES)))
    common_hash = common_sample_hash(
        dates=DATES,
        data_snapshot_hash=SNAPSHOT,
        eligible_observation_ids=eligible_ids,
        label_end_dates=tuple(value + timedelta(days=20) for value in DATES),
        quant_bundle_hashes=("a" * 64,) * len(DATES),
        return_horizon_days=20,
        capital=100_000.0,
        constraints_hash=CONSTRAINTS,
        benchmark_id="benchmark-spy-v1",
        base_cost_bps=10.0,
    )
    for number, strategy_id in enumerate(PREDECLARED_STRATEGY_IDS, start=1):
        turnover = 0.05 if strategy_id == "combined-multistrategy-v1" else 0.1
        turnovers = (turnover,) * 8
        series_hash = strategy_series_hash(
            common_hash=common_hash, gross_returns=returns[strategy_id], turnover=turnovers
        )
        output.append(
            StrategyReturnSeries(
                strategy_id=strategy_id,
                common_sample_hash=common_hash,
                dates=DATES,
                data_snapshot_hash=SNAPSHOT,
                eligible_observation_ids=eligible_ids,
                label_end_dates=tuple(value + timedelta(days=20) for value in DATES),
                quant_bundle_hashes=("a" * 64,) * len(DATES),
                series_input_hash=series_hash,
                return_horizon_days=20,
                capital=100_000.0,
                constraints_hash=CONSTRAINTS,
                benchmark_id="benchmark-spy-v1",
                gross_returns=returns[strategy_id],
                turnover=turnovers,
                base_cost_bps=10.0,
                experiment=experiment(strategy_id, number, series_hash),
            )
        )
    return tuple(output)


def test_six_way_comparison_is_visible_cost_stressed_and_never_promotes(tmp_path: Any) -> None:
    ledger = ExperimentLedger(tmp_path / "experiments.sqlite")
    comparison = evaluate_predeclared_strategies(series(), DECLARED, EVALUATED, ledger)
    assert tuple(item.strategy_id for item in comparison.baselines) == PREDECLARED_STRATEGY_IDS
    assert comparison.combined_status == "eligible"
    assert all(comparison.eligibility_checks.values())
    assert set(comparison.experiment_ids) == {item.experiment.experiment_id for item in series()}
    for item in comparison.baselines:
        assert (
            ledger.get(f"experiment-{item.strategy_id}").parameters["strategy_id"]
            == item.strategy_id
        )
        assert item.two_x_cost_sharpe <= item.net_annualized_sharpe + 1e-12


def test_losing_combined_remains_visible_and_is_rejected(tmp_path: Any) -> None:
    comparison = evaluate_predeclared_strategies(
        series(combined_return=-0.002),
        DECLARED,
        EVALUATED,
        ExperimentLedger(tmp_path / "experiments.sqlite"),
    )
    assert comparison.combined_status == "rejected"
    combined = next(
        item for item in comparison.baselines if item.strategy_id == "combined-multistrategy-v1"
    )
    assert combined.net_annualized_sharpe < 0
    assert not all(comparison.eligibility_checks.values())


def test_invalid_common_sample_still_records_every_attempt_before_rejection(tmp_path: Any) -> None:
    ledger = ExperimentLedger(tmp_path / "experiments.sqlite")
    attempted = list(series())
    attempted[-1] = attempted[-1].model_copy(
        update={"common_sample_hash": canonical_sha256({"other": 1})}
    )
    with pytest.raises(StrategyEvaluationError, match="common sample"):
        evaluate_predeclared_strategies(attempted, DECLARED, EVALUATED, ledger)
    for item in attempted:
        assert (
            ledger.get(item.experiment.experiment_id).experiment_id == item.experiment.experiment_id
        )

    second_ledger = ExperimentLedger(tmp_path / "missing.sqlite")
    with pytest.raises(StrategyEvaluationError, match="exactly the six"):
        evaluate_predeclared_strategies(series()[:-1], DECLARED, EVALUATED, second_ledger)
    for item in series()[:-1]:
        assert second_ledger.get(item.experiment.experiment_id)


def test_label_interval_is_hash_bound_and_must_match_all_six(tmp_path: Any) -> None:
    attempted = list(series())
    attempted[-1] = attempted[-1].model_copy(update={"label_end_dates": tuple(DATES)})
    with pytest.raises(StrategyEvaluationError, match="common sample"):
        evaluate_predeclared_strategies(
            attempted, DECLARED, EVALUATED, ExperimentLedger(tmp_path / "labels.sqlite")
        )


def test_quant_bundle_hashes_are_part_of_the_six_way_common_sample(tmp_path: Any) -> None:
    attempted = list(series())
    attempted[-1] = attempted[-1].model_copy(
        update={"quant_bundle_hashes": ("b" * 64,) * len(DATES)}
    )
    with pytest.raises(StrategyEvaluationError, match="common sample"):
        evaluate_predeclared_strategies(
            attempted, DECLARED, EVALUATED, ExperimentLedger(tmp_path / "bundles.sqlite")
        )
