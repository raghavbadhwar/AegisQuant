from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from aegis.brokers import SimBroker
from aegis.data import DataIntegrityError, FixtureDataClient
from aegis.fund.ledger import LedgerIntegrityError, SQLiteRunLedger
from aegis.fund.models import FixtureForecastProvider, load_replay_manifest
from aegis.fund.run_cycle import run_cycle
from aegis.fund.spec import load_fund_spec

ROOT = Path(__file__).resolve().parents[2]


def setup_components(tmp_path: Path):  # type: ignore[no-untyped-def]
    manifest = load_replay_manifest(ROOT / "data/fixtures/cases/nvda_earnings_case.json")
    case = manifest.research_case()
    fund = load_fund_spec(ROOT / manifest.fund_path)
    data = FixtureDataClient(ROOT / "demo_data")
    provider = FixtureForecastProvider(
        ROOT / manifest.forecast_fixture, ROOT / manifest.evidence_fixture
    )
    ledger = SQLiteRunLedger(tmp_path / "runs.sqlite")
    return manifest, case, fund, data, provider, ledger


def test_replay_cycle_is_byte_identical_and_reconciled(tmp_path: Path) -> None:
    _, case, fund, data, provider, ledger = setup_components(tmp_path)
    first = run_cycle(fund, case, SimBroker(fund.capital), data, provider, ledger)
    second = run_cycle(fund, case, SimBroker(fund.capital), data, provider, ledger)
    assert first.canonical().encode() == second.canonical().encode()
    assert first.digest() == second.digest()
    assert ledger.list_run_ids() == [first.run_id]
    assert ledger.get(first.run_id).canonical() == first.canonical()
    signed_quantity = {
        fill.order_id: fill.quantity if fill.side == "buy" else -fill.quantity
        for fill in first.fills
    }
    assert all(signed_quantity[fill.order_id] != 0 for fill in first.fills)
    assert first.nav_after == pytest.approx(
        first.cash_after + sum(position.market_value for position in first.positions), abs=0.01
    )
    assert all(forecast.evidence_ids for forecast in first.forecasts)
    evidence_ids = {record.evidence_id for record in first.evidence.records}
    assert all(set(forecast.evidence_ids) <= evidence_ids for forecast in first.forecasts)


def test_ledger_tamper_is_detected(tmp_path: Path) -> None:
    _, case, fund, data, provider, ledger = setup_components(tmp_path)
    record = run_cycle(fund, case, SimBroker(fund.capital), data, provider, ledger)
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            "UPDATE cycles SET record_json = replace(record_json, 'AAPL', 'EVIL') WHERE run_id = ?",
            (record.run_id,),
        )
    with pytest.raises(LedgerIntegrityError):
        ledger.get(record.run_id)


def test_all_model_abstentions_hold_existing_book(tmp_path: Path) -> None:
    _, case, fund, data, provider, ledger = setup_components(tmp_path)
    broker = SimBroker(fund.capital)
    first = run_cycle(fund, case, broker, data, provider, ledger)
    held = broker.quantities()
    later = case.model_copy(
        update={
            "case_id": "abstain-follow-up",
            "as_of": datetime(2024, 2, 26, 21, 5, tzinfo=UTC),
            "created_at": datetime(2024, 2, 26, 21, 5, tzinfo=UTC),
        }
    )
    forecasts_path = tmp_path / "abstaining-forecasts.json"
    abstaining = []
    for forecast in first.forecasts:
        payload = forecast.model_dump(mode="json")
        payload.update(
            {
                "forecast_id": f"abstain-{forecast.ticker}",
                "model_name": "failed-model",
                "as_of": later.as_of.isoformat(),
                "expected_excess_return": None,
                "expected_volatility": None,
                "thesis": "",
                "evidence_ids": [],
                "abstained": True,
                "abstain_reason": "provider unavailable",
            }
        )
        abstaining.append(payload)
    forecasts_path.write_text(__import__("json").dumps(abstaining))
    abstaining_provider = FixtureForecastProvider(
        forecasts_path, ROOT / "data/fixtures/evidence/replay_evidence.jsonl"
    )
    second = run_cycle(
        fund,
        later,
        broker,
        data,
        abstaining_provider,
        SQLiteRunLedger(tmp_path / "follow-up.sqlite"),
    )
    assert second.orders == ()
    assert broker.quantities() == held


def test_missing_mark_for_held_position_halts_before_research(tmp_path: Path) -> None:
    _, case, fund, data, provider, ledger = setup_components(tmp_path)
    broker = SimBroker(fund.capital)
    run_cycle(fund, case, broker, data, provider, ledger)
    missing = sorted(broker.quantities())[0]
    fixture_root = tmp_path / "missing-fixtures"
    fixture_root.mkdir()
    for name in ("fundamentals.parquet", "earnings.parquet"):
        shutil.copy2(ROOT / "data/fixtures" / name, fixture_root / name)
    prices = pd.read_parquet(ROOT / "data/fixtures/prices.parquet")
    prices = prices[prices["ticker"] != missing]
    prices.to_parquet(fixture_root / "prices.parquet", index=False)
    with pytest.raises(DataIntegrityError, match="missing point-in-time marks"):
        run_cycle(
            fund,
            case,
            broker,
            FixtureDataClient(fixture_root),
            provider,
            SQLiteRunLedger(tmp_path / "missing.sqlite"),
        )


def test_replay_price_cutoff_is_as_of_not_later_case_creation(tmp_path: Path) -> None:
    _, case, fund, data, provider, _ = setup_components(tmp_path)
    delayed_case = case.model_copy(update={"created_at": case.as_of + timedelta(days=3)})
    record = run_cycle(
        fund,
        delayed_case,
        SimBroker(fund.capital),
        data,
        provider,
        SQLiteRunLedger(tmp_path / "delayed.sqlite"),
    )
    assert record.snapshot.as_of == case.as_of
    assert max(bar.available_at for bar in record.snapshot.bars) <= case.as_of
