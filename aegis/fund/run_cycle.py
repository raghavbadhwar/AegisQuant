"""One replay/backtest/paper-simulation cycle; agents end at typed forecasts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from aegis.brokers import BrokerError, SimBroker
from aegis.contracts import Fill, Order, ResearchCase, SimulationMode, canonical_sha256
from aegis.data import DataClient, DataIntegrityError, PointInTimeViolation
from aegis.fund.execution import build_orders
from aegis.fund.ledger import CycleRecord, SQLiteRunLedger
from aegis.fund.models import ForecastProvider
from aegis.fund.spec import FundSpec
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
    fund: FundSpec,
    case: ResearchCase,
    broker: SimBroker,
    data_client: DataClient,
    forecast_provider: ForecastProvider,
    ledger: SQLiteRunLedger | None = None,
) -> CycleRecord:
    """Run the sole deterministic portfolio/risk/simulated-execution path."""
    if broker.is_live_broker:
        raise RuntimeError("live brokers are forbidden")
    if case.mode in {"replay", "historical"} and (
        data_client.network_enabled or forecast_provider.network_enabled
    ):
        raise RuntimeError(f"network-capable provider forbidden in {case.mode} mode")

    held = broker.quantities()
    requested = sorted(set(case.tickers) | set(held))
    snapshot = data_client.latest_snapshot(requested, case.created_at)
    bars = {bar.ticker: bar for bar in snapshot.bars}
    for bar in snapshot.bars:
        if bar.available_at > case.created_at:
            raise PointInTimeViolation(f"future price bar reached cycle: {bar.ticker}")
    missing = sorted(set(requested).difference(bars))
    if missing:
        raise DataIntegrityError(f"missing point-in-time marks: {missing}")
    stale_held = sorted(
        ticker
        for ticker in held
        if _age_minutes(case.as_of, bars[ticker].available_at) > fund.risk.stale_price_minutes
    )
    if stale_held:
        raise DataIntegrityError(f"stale held-position marks: {stale_held}")

    marks = {ticker: bars[ticker].close for ticker in sorted(bars)}
    equity_before_decimal = broker.equity(marks)
    cash_before_decimal = broker.cash
    current_weights = broker.weights(marks) if held else {}
    evidence = forecast_provider.evidence_bundle(case)
    forecasts = forecast_provider.forecast_batch(case, snapshot)
    proposal = construct_portfolio(
        forecasts, fund.portfolio, fund.risk.minimum_confidence, current_weights
    )
    sector_by_ticker = data_client.sector_map(case.tickers, case.as_of)
    total_strategy_weight = sum(strategy.weight for strategy in fund.strategies)
    strategy_allocations = {
        strategy.name: strategy.weight / total_strategy_weight for strategy in fund.strategies
    }
    risk = evaluate_risk(
        proposal,
        fund.risk,
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
        fills = broker.execute_batch(orders, fund.risk, case.created_at)

    positions = broker.positions(marks, case.created_at)
    nav_after_decimal = broker.equity(marks)
    if broker.cash < 0:
        broker.restore(before_execution)
        raise BrokerError("cycle reconciliation found negative cash")
    if not fund.risk.allow_shorting and any(position.quantity < 0 for position in positions):
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
            record.source_id: f"{record.parser_version}/{record.extractor_version}"
            for record in evidence.records
        },
        raw_evidence_hashes={
            record.evidence_id: record.content_hash for record in evidence.records
        },
        memory_snapshot_hash=canonical_sha256([]),
        relation_snapshot_hash=canonical_sha256([]),
        skill_versions=[],
        prompt_versions=[],
        model_deployments=sorted({forecast.model_name for forecast in forecasts}),
        embedding_versions=[],
        reranker_versions=[],
        cost_assumptions={
            "commission_bps": fund.risk.commission_bps,
            "slippage_bps": fund.risk.slippage_bps,
        },
        random_seeds={"deterministic": 0},
    )

    run_id = canonical_sha256(
        {
            "case": case.model_dump(mode="json"),
            "fund": fund.model_dump(mode="json"),
            "snapshot_hash": snapshot.content_hash,
            "reproducibility": reproducibility.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
            "forecasts": [item.model_dump(mode="json") for item in forecasts],
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
        run_id=run_id,
        case=case,
        fund=fund,
        reproducibility=reproducibility,
        snapshot=snapshot,
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
    )
    if ledger is not None:
        try:
            ledger.append(record)
        except Exception:
            broker.restore(before_execution)
            raise
    return record
