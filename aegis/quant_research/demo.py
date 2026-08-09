"""Frozen no-network v3B demonstration inputs used by the CLI acceptance surface."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from aegis.contracts import (
    EventStudyResult,
    EventStudySpec,
    FactorDiagnostics,
    MarketEvent,
    RegimeSnapshot,
    UniverseSnapshot,
)
from aegis.quant_research.diagnostics import DiagnosticObservation, compute_factor_diagnostics
from aegis.quant_research.events import ReturnObservation, run_event_study
from aegis.quant_research.hashing import build_hashed
from aegis.quant_research.regimes import NumericObservation, RegimeInputs, classify_regime
from aegis.quant_research.universe import RawUniverseRecord, UniverseRules, build_universe_snapshot

AS_OF = datetime(2025, 6, 30, 16, tzinfo=UTC)


def demo_universe() -> UniverseSnapshot:
    trading_status = "listed"
    eligible = RawUniverseRecord(
        member_id="member-aaa-v1",
        ticker="AAA",
        available_at=AS_OF - timedelta(days=2),
        listing_date=date(2020, 1, 1),
        delisting_date=None,
        listing_status=trading_status,
        average_daily_dollar_volume=10_000_000.0,
        market_cap=1_000_000_000.0,
        sector="Technology",
        industry="Software",
        source_ids=("source-aaa",),
    )
    excluded = RawUniverseRecord(
        member_id="member-bad-v1",
        ticker="BAD",
        available_at=AS_OF - timedelta(days=2),
        listing_date=date(2020, 1, 1),
        delisting_date=None,
        listing_status="halted",
        average_daily_dollar_volume=1.0,
        market_cap=2.0,
        sector=None,
        industry=None,
        corporate_action_status="pending_merger",
        data_completeness=0.2,
        borrow_eligible=False,
        outside_mandate=True,
        source_ids=("source-bad",),
    )
    return build_universe_snapshot(
        (eligible, excluded),
        snapshot_id="snapshot-demo-v1",
        universe_id="universe-demo-v1",
        as_of=AS_OF,
        rules=UniverseRules("universe-rules-v1", 1_000_000.0, 100_000_000.0, 0.9),
        fixed_fixture=True,
        limitation="Fixed CLI fixture; not a survivorship-free production security master.",
    )


def demo_factor_diagnostics() -> FactorDiagnostics:
    rows = []
    for period, (values, returns) in enumerate(
        (((1.0, 2.0, 3.0, 4.0), (0.0, 1.0, 2.0, 3.0)), ((4.0, 3.0, 2.0, 1.0), (4.0, 3.0, 2.0, 1.0)))
    ):
        as_of = AS_OF + timedelta(days=period * 10)
        for index, ticker in enumerate(("AAA", "BBB", "CCC", "DDD")):
            rows.append(
                DiagnosticObservation(
                    observation_id=f"diagnostic-{period}-{ticker.lower()}-v1",
                    universe_snapshot_id=f"snapshot-{period + 1}-v1",
                    calculation_id="calculation-diagnostic-v1",
                    ticker=ticker,
                    as_of=as_of,
                    feature_available_at=as_of - timedelta(days=1),
                    return_start_at=as_of,
                    return_end_at=as_of + timedelta(days=5),
                    factor_value=values[index],
                    forward_return=returns[index],
                    sector="Technology" if index % 2 == 0 else "Financials",
                    market_cap=100.0 * (index + 1),
                    average_daily_dollar_volume=1_000_000.0 * (index + 1),
                    subperiod=f"half-{period + 1}",
                    regime="calm" if period == 0 else "stress",
                    decay_returns=((5, values[index]),),
                    comparison_factors=(("momentum-core-v1", values[index]),),
                )
            )
    return compute_factor_diagnostics(
        tuple(rows), quantiles=2, commission_bps=4.0, slippage_bps=6.0
    )


def demo_event_study() -> EventStudyResult:
    occurred = AS_OF - timedelta(days=2)
    event = build_hashed(
        MarketEvent,
        event_id="aapl-earnings-event-v1",
        ticker="AAPL",
        event_type="earnings",
        occurred_at=occurred,
        source_type="filing",
        surprise=0.2,
        source_ids=("filing-aapl-2025q2",),
        as_of=AS_OF,
        available_at=occurred,
    )
    spec = build_hashed(
        EventStudySpec,
        spec_id="earnings-event-study-v1",
        benchmark_ticker="SPY",
        event_types=("earnings",),
        estimation_window_start=-5,
        estimation_window_end=-2,
        car_windows=((-1, 1), (0, 1)),
        bootstrap_samples=100,
        confidence_level=0.95,
        pre_event_leakage_days=1,
        market_model_version="ordinary-market-model-v1",
    )
    market = {-5: 0.01, -4: 0.02, -3: -0.01, -2: 0.03, -1: 0.0, 0: 0.01, 1: -0.02}
    abnormal = {-1: 0.0, 0: 0.01, 1: -0.003}
    returns = []
    for offset, market_return in market.items():
        timestamp = occurred + timedelta(days=offset)
        returns.append(ReturnObservation("SPY", timestamp, timestamp, market_return, "prices-spy"))
        returns.append(
            ReturnObservation(
                "AAPL",
                timestamp,
                timestamp,
                0.001 + 1.5 * market_return + abnormal.get(offset, 0.0),
                "prices-aapl",
            )
        )
    return run_event_study(spec, [event], returns, as_of=AS_OF, seed=7)


def _number(value: float, index: int) -> NumericObservation:
    at = AS_OF - timedelta(days=10 - index)
    return NumericObservation(at, at, value, f"series-{index}")


def demo_regime() -> RegimeSnapshot:
    return classify_regime(
        RegimeInputs(
            as_of=AS_OF,
            volatility=[
                _number(value, index) for index, value in enumerate((10.0, 12.0, 14.0, 40.0))
            ],
            market_returns=[
                _number(value, index) for index, value in enumerate((0.01, 0.02, 0.01))
            ],
            rates_liquidity=[_number(1.0, 0)],
            risk_appetite=[_number(-1.0, 0)],
            factor_returns={"value": [_number(0.01, 0)], "momentum": [_number(0.03, 1)]},
            correlations=[_number(0.7, 0), _number(0.8, 1)],
        )
    )
