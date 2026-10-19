from __future__ import annotations

from datetime import date
from pathlib import Path

from aegis.data import FixtureDataClient
from aegis.fund import backtest as backtest_module
from aegis.fund.ledger import SQLiteRunLedger
from aegis.fund.spec import load_fund_spec

ROOT = Path(__file__).resolve().parents[2]


def test_every_backtest_tick_invokes_the_same_run_cycle(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    original = backtest_module.run_cycle

    def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        record = original(*args, **kwargs)
        calls.append(record.run_id)
        return record

    monkeypatch.setattr(backtest_module, "run_cycle", spy)
    result = backtest_module.backtest_fund(
        load_fund_spec(ROOT / "configs/funds/demo-fund.yaml"),
        ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"],
        date(2024, 1, 1),
        date(2024, 3, 31),
        FixtureDataClient(ROOT / "demo_data"),
        SQLiteRunLedger(tmp_path / "runs.sqlite"),
    )
    assert calls == [record.run_id for record in result.records]
    assert len(calls) == result.metrics.cycles
