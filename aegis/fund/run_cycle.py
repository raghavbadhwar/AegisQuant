"""One replay/backtest/paper-simulation cycle; agents end at typed forecasts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from aegis.brokers import BrokerError, SimBroker
from aegis.contracts import (
    Fill,
    FundMandate,
    Order,
    ResearchCase,
    SimulationMode,
    canonical_sha256,
)
from aegis.data import DataClient, DataIntegrityError, PointInTimeViolation
from aegis.fund.execution import build_orders
from aegis.fund.ledger import CycleRecord, SQLiteRunLedger
from aegis.fund.models import ForecastProvider
from aegis.fund.spec import FundConfiguration
from aegis.observability import ReproducibilityManifest, local_build_fingerprint
from aegis.quant import construct_portfolio
from aegis.risk import evaluate_risk


def _age_minutes(as_of: datetime, available_at: datetime) -> float:
    return (as_of - available_at).total_seconds() / 60.0


def _execution_mode(case: ResearchCase) -> SimulationMode:
    if case.mode == "live_research":
        return "paper"
    if case.mode == "historical":
        return "historical"
    if case.mode == "replay":
        return "replay"
    raise RuntimeError("research_lab cases cannot execute a portfolio cycle")


def run_cycle(
    fund: FundConfiguration,
    case: ResearchCase,
    broker: SimBroker,
    data_client: DataClient,
    forecast_provider: ForecastProvider,
    ledger: SQLiteRunLedger | None = None,
) -> CycleRecord:
    """Run the sole deterministic portfolio/risk/simulated-execution path."""
    risk_policy = fund.master_risk if isinstance(fund, FundMandate) else fund.risk
    if broker.is_live_broker:
        raise RuntimeError("live brokers are forbidden")
    if case.mode in {"replay", "historical"} and (
        data_client.network_enabled or forecast_provider.network_enabled
    ):
        raise RuntimeError(f"network-capable provider forbidden in {case.mode} mode")
    if case.mode in {"replay", "historical"}:
        from aegis.data import FixtureDataClient
        from aegis.fund.models import (
            FixtureForecastProvider,
            HistoricalMultiStrategyFixtureProvider,
            MultiStrategyFixtureProvider,
        )
        from aegis.harness.graph import LangGraphForecastProvider
        from aegis.quant.models import DeterministicCompositeProvider

        if type(data_client) is not FixtureDataClient:
            raise RuntimeError(f"unsealed data provider forbidden in {case.mode} mode")
        sealed_provider_types = {
            FixtureForecastProvider,
            MultiStrategyFixtureProvider,
            HistoricalMultiStrategyFixtureProvider,
            LangGraphForecastProvider,
            DeterministicCompositeProvider,
        }
        if type(forecast_provider) not in sealed_provider_types:
            raise RuntimeError(f"unsealed forecast provider forbidden in {case.mode} mode")

    held = broker.quantities()
    requested = sorted(set(case.tickers) | set(held))
    snapshot = data_client.latest_snapshot(requested, case.as_of)
    bars = {bar.ticker: bar for bar in snapshot.bars}
    for bar in snapshot.bars:
        if bar.available_at > case.as_of:
            raise PointInTimeViolation(f"future price bar reached cycle: {bar.ticker}")
    missing = sorted(set(requested).difference(bars))
    if missing:
        raise DataIntegrityError(f"missing point-in-time marks: {missing}")
    stale_held = sorted(
        ticker
        for ticker in held
        if _age_minutes(case.as_of, bars[ticker].available_at) > risk_policy.stale_price_minutes
    )
    if stale_held:
        raise DataIntegrityError(f"stale held-position marks: {stale_held}")

    marks = {ticker: bars[ticker].close for ticker in sorted(bars)}
    equity_before_decimal = broker.equity(marks)
    cash_before_decimal = broker.cash
    current_weights = broker.weights(marks) if held else {}
    dossier = forecast_provider.research(case, snapshot)
    if isinstance(fund, FundMandate) and dossier.quant_research_bundle is None:
        raise DataIntegrityError("institutional cycle requires a sealed quant research bundle")
    evidence = dossier.evidence
    forecasts = dossier.forecasts
    master_portfolio = None
    if isinstance(fund, FundMandate):
        from aegis.fund.strategy_inputs import build_model_batches, build_pod_contexts
        from aegis.strategy import build_master_portfolio

        quant_bundle = dossier.quant_research_bundle
        if quant_bundle is None:  # Narrowing guard for strict type checkers.
            raise DataIntegrityError("institutional cycle requires a sealed quant research bundle")
        model_batches = build_model_batches(fund, case, forecasts, evidence, quant_bundle)
        pod_contexts = build_pod_contexts(fund, case, model_batches, data_client, quant_bundle)
        master_portfolio = build_master_portfolio(
            fund, model_batches, pod_contexts, current_weights
        )
        proposal = master_portfolio.to_portfolio_proposal(current_weights)
        strategy_allocations = master_portfolio.allocator_weights
    else:
        proposal = construct_portfolio(
            forecasts, fund.portfolio, risk_policy.minimum_confidence, current_weights
        )
        total_strategy_weight = sum(strategy.weight for strategy in fund.strategies)
        strategy_allocations = {
            strategy.name: strategy.weight / total_strategy_weight for strategy in fund.strategies
        }
    sector_by_ticker = data_client.sector_map(case.tickers, case.as_of)
    risk = evaluate_risk(
        proposal,
        risk_policy,
        current_weights,
        sector_by_ticker=sector_by_ticker,
        strategy_allocations=strategy_allocations,
    )

    orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    before_execution = broker.state()
    hold_existing_book = bool(held) and proposal.target_weights == current_weights
    if risk.decision.approved and not hold_existing_book:
        orders = build_orders(
            case_id=case.case_id,
            final_weights=risk.decision.final_weights,
            current_quantities=held,
            marks=marks,
            equity=equity_before_decimal,
            created_at=case.created_at,
            execution_mode=_execution_mode(case),
        )
        fills = broker.execute_batch(orders, risk_policy, case.created_at)

    positions = broker.positions(marks, case.created_at)
    nav_after_decimal = broker.equity(marks)
    if broker.cash < 0:
        broker.restore(before_execution)
        raise BrokerError("cycle reconciliation found negative cash")
    if not risk_policy.allow_shorting and any(position.quantity < 0 for position in positions):
        broker.restore(before_execution)
        raise BrokerError("cycle reconciliation found a forbidden short position")
    calculated_nav = broker.cash + sum(
        Decimal(str(position.market_value)) for position in positions
    )
    if abs(calculated_nav - nav_after_decimal) > Decimal("0.01"):
        broker.restore(before_execution)
        raise BrokerError("cycle NAV does not reconcile")

    project_root = Path(__file__).resolve().parents[2]
    revision, tree_hash, lock_hash = local_build_fingerprint(project_root)
    reproducibility = ReproducibilityManifest(
        code_revision=revision,
        code_tree_hash=tree_hash,
        environment_lock_hash=lock_hash,
        data_snapshot_hash=snapshot.content_hash,
        dataset_hash=data_client.dataset_hash,
        source_manifest_versions={
            record.source_id: record.source_manifest_version for record in evidence.records
        },
        raw_evidence_hashes={
            record.evidence_id: record.content_hash for record in evidence.records
        },
        memory_snapshot_hash=dossier.memory_snapshot_hash,
        relation_snapshot_hash=dossier.relation_snapshot_hash,
        skill_versions=sorted(
            {version for artifact in dossier.artifacts for version in artifact.skill_versions}
        ),
        prompt_versions=sorted(
            {version for artifact in dossier.artifacts for version in artifact.prompt_versions}
        ),
        model_deployments=sorted(
            {artifact.actual_model for artifact in dossier.artifacts}
            | {forecast.model_name for forecast in forecasts}
        ),
        embedding_versions=[],
        reranker_versions=[],
        cost_assumptions={
            "commission_bps": risk_policy.commission_bps,
            "slippage_bps": risk_policy.slippage_bps,
        },
        random_seeds={"deterministic": 0},
    )

    run_id = canonical_sha256(
        {
            "case": case.model_dump(mode="json"),
            "fund": fund.model_dump(mode="json"),
            "snapshot_hash": snapshot.content_hash,
            "reproducibility": reproducibility.model_dump(mode="json"),
            "dossier_hash": dossier.content_hash,
            "evidence": evidence.model_dump(mode="json"),
            "forecasts": [item.model_dump(mode="json") for item in forecasts],
            "master_portfolio": master_portfolio.model_dump(mode="json")
            if master_portfolio is not None
            else None,
            "broker_before": {
                "cash": str(before_execution.cash),
                "shares": before_execution.shares,
                "average_costs": [
                    (ticker, str(cost)) for ticker, cost in before_execution.average_costs
                ],
            },
        }
    )[:32]
    record = CycleRecord(
        schema_version="aegis-cycle-v2" if master_portfolio is not None else "aegis-cycle-v1",
        run_id=run_id,
        case=case,
        fund=fund,
        reproducibility=reproducibility,
        snapshot=snapshot,
        dossier=dossier,
        evidence=evidence,
        forecasts=forecasts,
        portfolio=proposal,
        risk=risk,
        marks=marks,
        equity_before=float(equity_before_decimal),
        cash_before=float(cash_before_decimal),
        orders=orders,
        fills=fills,
        positions=positions,
        cash_after=float(broker.cash),
        nav_after=float(nav_after_decimal),
        master_portfolio=master_portfolio,
        quant_research_bundle=dossier.quant_research_bundle,
    )
    if ledger is not None:
        try:
            ledger.append(record)
        except Exception:
            broker.restore(before_execution)
            raise
    return record
