"""Historical backtest that loops through the exact same run_cycle path."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time

import numpy as np
from pydantic import BaseModel, ConfigDict

from aegis.brokers import SimBroker
from aegis.contracts import ResearchCase, canonical_json, canonical_sha256
from aegis.data import DataClient, DataIntegrityError, PriceBar
from aegis.fund.ledger import CycleRecord, SQLiteRunLedger
from aegis.fund.run_cycle import run_cycle
from aegis.fund.spec import FundSpec
from aegis.quant import DeterministicCompositeProvider


class BacktestMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    benchmark_return: float
    total_turnover: float
    total_cost: float
    cycles: int


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "aegis-backtest-v1"
    fund_name: str
    universe: tuple[str, ...]
    start: date
    end: date
    rebalance: str
    records: tuple[CycleRecord, ...]
    nav: tuple[float, ...]
    benchmark_nav: tuple[float, ...]
    metrics: BacktestMetrics

    def canonical(self) -> str:
        return canonical_json(self)

    def digest(self) -> str:
        return canonical_sha256(self)


def _rebalance_bars(bars: tuple[PriceBar, ...], cadence: str) -> list[PriceBar]:
    if cadence == "daily":
        return list(bars)
    grouped: dict[tuple[int, int] | tuple[int], PriceBar] = {}
    for bar in bars:
        day = date.fromisoformat(bar.date)
        key: tuple[int, int] | tuple[int]
        if cadence == "weekly":
            iso = day.isocalendar()
            key = (iso.year, iso.week)
        elif cadence == "monthly":
            key = (day.year * 100 + day.month,)
        else:
            raise ValueError(f"unsupported rebalance cadence: {cadence}")
        grouped[key] = bar
    return list(grouped.values())


def _metrics(
    nav: list[float], benchmark_nav: list[float], records: list[CycleRecord]
) -> BacktestMetrics:
    if not nav:
        raise ValueError("backtest produced no cycles")
    total_return = nav[-1] / nav[0] - 1.0 if len(nav) > 1 else 0.0
    benchmark_return = benchmark_nav[-1] / benchmark_nav[0] - 1.0 if len(benchmark_nav) > 1 else 0.0
    elapsed_days = max((records[-1].case.as_of - records[0].case.as_of).days, 1)
    years = elapsed_days / 365.25
    cagr = (nav[-1] / nav[0]) ** (1.0 / years) - 1.0 if len(nav) > 1 else 0.0
    returns = np.diff(np.asarray(nav, dtype=float)) / np.asarray(nav[:-1], dtype=float)
    if len(returns) > 1 and float(np.std(returns, ddof=1)) > 0:
        periods = 252 if records[0].fund.rebalance == "daily" else 52
        if records[0].fund.rebalance == "monthly":
            periods = 12
        sharpe = float(np.mean(returns) / np.std(returns, ddof=1) * math.sqrt(periods))
        downside = returns[returns < 0]
        sortino = (
            float(np.mean(returns) / np.std(downside, ddof=1) * math.sqrt(periods))
            if len(downside) > 1 and float(np.std(downside, ddof=1)) > 0
            else 0.0
        )
    else:
        sharpe = 0.0
        sortino = 0.0
    running_peak = nav[0]
    max_drawdown = 0.0
    for value in nav:
        running_peak = max(running_peak, value)
        max_drawdown = max(max_drawdown, (running_peak - value) / running_peak)
    total_cost = sum(fill.fee + fill.slippage for record in records for fill in record.fills)
    return BacktestMetrics(
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown,
        benchmark_return=benchmark_return,
        total_turnover=sum(record.portfolio.turnover for record in records),
        total_cost=total_cost,
        cycles=len(records),
    )


def backtest_fund(
    fund: FundSpec,
    universe: list[str],
    start: date,
    end: date,
    data_client: DataClient,
    ledger: SQLiteRunLedger,
) -> BacktestResult:
    """Run historical research cycles with one persistent simulated broker."""
    if start > end:
        raise ValueError("backtest start must not be after end")
    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end, time.max, tzinfo=UTC)
    benchmark_bars = data_client.price_history(fund.benchmark, start_dt, end_dt, as_of=end_dt)
    grid = _rebalance_bars(benchmark_bars, fund.rebalance)
    if not grid:
        raise DataIntegrityError("benchmark produced no historical trading grid")

    broker = SimBroker(fund.capital)
    provider = DeterministicCompositeProvider(data_client)
    records: list[CycleRecord] = []
    for bar in grid:
        as_of = bar.available_at
        case = ResearchCase(
            case_id=f"backtest-{fund.name}-{as_of:%Y%m%d}",
            tickers=universe,
            as_of=as_of,
            horizon_days=20,
            mode="historical",
            research_question="Run the deterministic historical composite.",
            created_at=as_of,
        )
        records.append(run_cycle(fund, case, broker, data_client, provider, ledger))

    nav = [record.nav_after for record in records]
    benchmark_by_date = {bar.date: bar.close for bar in benchmark_bars}
    initial_benchmark = benchmark_by_date[grid[0].date]
    benchmark_nav = [fund.capital * benchmark_by_date[bar.date] / initial_benchmark for bar in grid]
    return BacktestResult(
        fund_name=fund.name,
        universe=tuple(sorted(set(universe))),
        start=start,
        end=end,
        rebalance=fund.rebalance,
        records=tuple(records),
        nav=tuple(nav),
        benchmark_nav=tuple(benchmark_nav),
        metrics=_metrics(nav, benchmark_nav, records),
    )
