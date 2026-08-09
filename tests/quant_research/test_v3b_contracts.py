from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from aegis.contracts import (
    BaselinePerformance,
    EligibilityDecision,
    MasterPortfolio,
    PodContribution,
    PodTarget,
    StrategyComparison,
    UniverseMember,
    UniverseSnapshot,
    canonical_sha256,
)

NOW = datetime(2025, 6, 30, tzinfo=UTC)
H = canonical_sha256({"fixture": "v3b"})


def hashed[T: BaseModel](cls: type[T], /, **payload: Any) -> T:
    draft = cls.model_construct(**payload)
    return cls(
        **payload,
        content_hash=canonical_sha256(draft.model_dump(exclude={"content_hash"})),
    )


def member(*, available_at: datetime = NOW) -> UniverseMember:
    return hashed(
        UniverseMember,
        member_id="member-aapl-v1",
        ticker="AAPL",
        as_of=NOW,
        available_at=available_at,
        listing_status="listed",
        average_daily_dollar_volume=100_000_000.0,
        market_cap=3_000_000_000_000.0,
        sector="Technology",
        industry="Hardware",
        corporate_action_status="none",
        data_completeness=1.0,
        borrow_eligible=True,
        source_ids=("source-aapl",),
    )


def decision() -> EligibilityDecision:
    return hashed(
        EligibilityDecision,
        decision_id="decision-aapl-v1",
        member_id="member-aapl-v1",
        ticker="AAPL",
        as_of=NOW,
        available_at=NOW,
        eligible=True,
        reasons=("eligible",),
        rules_version="rules-demo-v1",
    )


def test_universe_snapshot_is_hash_bound_point_in_time_and_explicitly_fixed() -> None:
    snapshot = hashed(
        UniverseSnapshot,
        snapshot_id="snapshot-demo-v1",
        universe_id="universe-demo-v1",
        as_of=NOW,
        members=(member(),),
        decisions=(decision(),),
        fixed_fixture=True,
        limitation="Frozen supplied universe; it is not a survivorship-free production feed.",
    )
    assert snapshot.members[0].ticker == "AAPL"
    with pytest.raises(ValidationError, match="available_at"):
        member(available_at=NOW + timedelta(seconds=1))
    payload = snapshot.model_dump(exclude={"content_hash"})
    with pytest.raises(ValidationError, match="hash mismatch"):
        UniverseSnapshot(**payload, content_hash="0" * 64)


def test_master_contributions_reconcile_and_convert_to_existing_proposal() -> None:
    pod_a = hashed(
        PodTarget,
        target_id="target-alpha-v1",
        pod_id="pod-alpha-v1",
        as_of=NOW,
        target_weights={"AAPL": 0.6},
        cash_weight=0.4,
        gross_exposure=0.6,
        blended_forecast_ids=("blend-aapl-v1",),
    )
    pod_b = hashed(
        PodTarget,
        target_id="target-beta-v1",
        pod_id="pod-beta-v1",
        as_of=NOW,
        target_weights={"AAPL": -0.2, "MSFT": 0.4},
        cash_weight=0.8,
        gross_exposure=0.6,
        blended_forecast_ids=("blend-msft-v1",),
    )
    contributions = (
        hashed(
            PodContribution,
            contribution_id="allocation-aapl-alpha-v1",
            pod_id="pod-alpha-v1",
            ticker="AAPL",
            pod_weight=0.6,
            allocator_weight=0.5,
            allocated_weight=0.3,
        ),
        hashed(
            PodContribution,
            contribution_id="allocation-aapl-beta-v1",
            pod_id="pod-beta-v1",
            ticker="AAPL",
            pod_weight=-0.2,
            allocator_weight=0.5,
            allocated_weight=-0.1,
        ),
        hashed(
            PodContribution,
            contribution_id="allocation-msft-beta-v1",
            pod_id="pod-beta-v1",
            ticker="MSFT",
            pod_weight=0.4,
            allocator_weight=0.5,
            allocated_weight=0.2,
        ),
    )
    payload = dict(
        master_id="master-demo-v1",
        mandate_id="mandate-demo-v1",
        as_of=NOW,
        target_weights={"AAPL": 0.2, "MSFT": 0.2},
        cash_weight=0.6,
        gross_exposure=0.4,
        net_exposure=0.4,
        allocator_weights={"pod-alpha-v1": 0.5, "pod-beta-v1": 0.5},
        pod_targets=(pod_a, pod_b),
        contributions=contributions,
        input_hash=H,
    )
    master = hashed(MasterPortfolio, **payload)
    proposal = master.to_portfolio_proposal({"AAPL": 0.1})
    assert proposal.target_weights == {"AAPL": 0.2, "MSFT": 0.2}
    assert proposal.turnover == pytest.approx(0.15)
    bad = {**payload, "target_weights": {"AAPL": 0.3, "MSFT": 0.2}}
    with pytest.raises(ValidationError, match="pod contributions"):
        hashed(MasterPortfolio, **bad)


def baseline(strategy_id: str) -> BaselinePerformance:
    return hashed(
        BaselinePerformance,
        strategy_id=strategy_id,
        common_sample_hash=H,
        benchmark_id="benchmark-spy-v1",
        return_horizon_days=20,
        capital=100_000.0,
        constraints_hash=H,
        cost_grid=(1.0, 2.0, 5.0),
        net_annualized_sharpe=0.5,
        dsr=0.6,
        pbo=0.4,
        max_drawdown=0.1,
        turnover=0.2,
        two_x_cost_sharpe=0.1,
        evaluated_at=NOW,
    )


def test_strategy_comparison_requires_all_predeclared_visible_baselines() -> None:
    ids = (
        "equal-weight-v1",
        "inverse-vol-v1",
        "simple-factor-v1",
        "fundamental-only-v1",
        "quant-only-v1",
        "combined-multistrategy-v1",
    )
    payload = dict(
        comparison_id="comparison-demo-v1",
        common_sample_hash=H,
        cost_grid_bps=(1.0, 2.0, 5.0),
        declared_at=NOW - timedelta(days=1),
        evaluated_at=NOW,
        baselines=tuple(baseline(item) for item in ids),
        combined_status="eligible",
        eligibility_checks={"risk": True, "performance": True},
        experiment_ids=("experiment-demo",),
    )
    comparison = hashed(StrategyComparison, **payload)
    assert len(comparison.baselines) == 6
    with pytest.raises(ValidationError, match="all six"):
        hashed(StrategyComparison, **{**payload, "baselines": comparison.baselines[:-1]})
