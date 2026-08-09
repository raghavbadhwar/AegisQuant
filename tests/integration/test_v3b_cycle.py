from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from aegis.brokers import SimBroker
from aegis.contracts import (
    AlphaModelRef,
    ForecastBlendPolicy,
    FundAllocatorPolicy,
    FundMandate,
    PodPortfolioPolicy,
    PodRiskBudget,
    RiskPolicy,
    StrategyPod,
)
from aegis.data import FixtureDataClient
from aegis.fund import (
    FundSpec,
    MultiStrategyFixtureProvider,
    load_fund_configuration,
    load_fund_mandate,
)
from aegis.fund.ledger import SQLiteRunLedger
from aegis.fund.models import load_replay_manifest
from aegis.fund.run_cycle import run_cycle
from aegis.quant_research.hashing import build_hashed

ROOT = Path(__file__).resolve().parents[2]


def pod(pod_id: str, model_id: str, weight: float) -> StrategyPod:
    base = pod_id.removesuffix("-v1")
    return build_hashed(
        StrategyPod,
        pod_id=pod_id,
        display_name=pod_id,
        capital_weight=weight,
        models=(
            build_hashed(
                AlphaModelRef,
                model_id=model_id,
                horizon_days=20,
                weight=1.0,
                provider="sealed-fixture",
            ),
        ),
        blend_policy=build_hashed(
            ForecastBlendPolicy,
            policy_id=f"{base}-blend-v1",
            maximum_horizon_gap_days=0,
            overlap_penalty=0.4,
            minimum_evidence_quality=0.5,
            minimum_calibration=0.5,
        ),
        portfolio_policy=build_hashed(
            PodPortfolioPolicy,
            policy_id=f"{base}-portfolio-v1",
            method="forecast_weighted",
            gross_target=0.8,
            market_neutral=False,
        ),
        risk_budget=build_hashed(
            PodRiskBudget,
            budget_id=f"{base}-budget-v1",
            maximum_gross=0.8,
            maximum_position=0.15,
            maximum_drawdown=0.2,
        ),
    )


def mandate() -> FundMandate:
    return build_hashed(
        FundMandate,
        mandate_id="mandate-institutional-demo-v1",
        display_name="Institutional demo",
        capital=Decimal("100000"),
        pods=(
            pod("pod-fundamental-v1", "model-fundamental-v1", 0.5),
            pod("pod-systematic-v1", "model-systematic-v1", 0.4),
        ),
        allocator_policy=build_hashed(
            FundAllocatorPolicy,
            policy_id="allocator-static-v1",
            method="static",
            maximum_pod_weight=0.6,
            preserve_unallocated_cash=True,
        ),
        master_risk=RiskPolicy(
            max_position_pct=0.15, maximum_single_strategy_pct=0.6, version="risk-v3b-v1"
        ),
        benchmark="SPY",
    )


def strategy_forecasts(path: Path) -> None:
    base = json.loads((ROOT / "data/fixtures/replay_forecasts.json").read_text())
    rows = []
    for model_id, return_scale in (("model-fundamental-v1", 1.0), ("model-systematic-v1", 0.7)):
        for item in base:
            copied = dict(item)
            copied["forecast_id"] = f"{item['forecast_id']}-{model_id}"
            copied["model_name"] = model_id
            copied["expected_excess_return"] *= return_scale
            copied["base_case"] *= return_scale
            copied["downside_case"] *= return_scale
            copied["upside_case"] *= return_scale
            copied["metadata"] = {
                "calibration_score": 0.8,
                "regime_score": 0.75,
                "evidence_quality": 0.9,
                "feature_ids": [f"feature-{model_id.removeprefix('model-')}"],
            }
            rows.append(copied)
    path.write_text(json.dumps(rows, sort_keys=True))


def test_v3b_master_portfolio_runs_twice_through_the_existing_cycle(tmp_path: Path) -> None:
    manifest = load_replay_manifest(ROOT / "data/fixtures/cases/nvda_earnings_case.json")
    case = manifest.research_case()
    forecasts = tmp_path / "strategy_forecasts.json"
    strategy_forecasts(forecasts)
    provider = MultiStrategyFixtureProvider(
        forecasts,
        ROOT / manifest.evidence_fixture,
        ROOT / "data/fixtures/v3b/quant_research_bundle.json",
    )
    fund = mandate()
    client = FixtureDataClient(ROOT / "data/fixtures")

    first = run_cycle(
        fund,
        case,
        SimBroker(fund.capital),
        client,
        provider,
        SQLiteRunLedger(tmp_path / "a.sqlite"),
    )
    second = run_cycle(
        fund,
        case,
        SimBroker(fund.capital),
        client,
        provider,
        SQLiteRunLedger(tmp_path / "b.sqlite"),
    )

    assert first.canonical() == second.canonical()
    assert first.schema_version == "aegis-cycle-v2"
    assert first.master_portfolio is not None
    assert first.quant_research_bundle is not None
    assert first.dossier.quant_research_bundle == first.quant_research_bundle
    assert first.portfolio.target_weights == first.master_portfolio.target_weights
    assert first.risk.decision.approved
    assert 0.0 < first.nav_after < 100_000.0
    assert first.fills
    assert sum(
        item.allocated_weight for item in first.master_portfolio.contributions
    ) == pytest.approx(sum(first.master_portfolio.target_weights.values()))
    restored = SQLiteRunLedger(tmp_path / "a.sqlite").get(first.run_id)
    assert restored == first
    assert restored.digest() == first.digest()


def test_configuration_loader_is_explicit_and_hash_tampering_fails(tmp_path: Path) -> None:
    institutional = load_fund_configuration(ROOT / "configs/funds/aegis-institutional-demo-v3.yaml")
    legacy = load_fund_configuration(ROOT / "configs/funds/demo-fund.yaml")
    assert isinstance(institutional, FundMandate)
    assert isinstance(legacy, FundSpec)

    tampered = (ROOT / "configs/funds/aegis-institutional-demo-v3.yaml").read_text()
    tampered_path = tmp_path / "tampered.yaml"
    tampered_path.write_text(tampered.replace("capital: '100000'", "capital: '200000'"))
    with pytest.raises(ValueError, match="content_hash"):
        load_fund_mandate(tampered_path)


def test_replay_rejects_multi_strategy_provider_subclasses(tmp_path: Path) -> None:
    class UnsealedProvider(MultiStrategyFixtureProvider):
        pass

    manifest = load_replay_manifest(ROOT / "data/fixtures/cases/nvda_earnings_case.json")
    provider = UnsealedProvider(
        ROOT / "data/fixtures/v3b/multi_strategy_forecasts.json",
        ROOT / manifest.evidence_fixture,
        ROOT / "data/fixtures/v3b/quant_research_bundle.json",
    )
    fund = load_fund_mandate(ROOT / "configs/funds/aegis-institutional-demo-v3.yaml")
    with pytest.raises(RuntimeError, match="unsealed forecast provider"):
        run_cycle(
            fund,
            manifest.research_case(),
            SimBroker(float(fund.capital)),
            FixtureDataClient(ROOT / "data/fixtures"),
            provider,
            SQLiteRunLedger(tmp_path / "denied.sqlite"),
        )
