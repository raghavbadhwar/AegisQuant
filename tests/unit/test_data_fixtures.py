from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from aegis.data import DataIntegrityError, FixtureDataClient

ROOT = Path(__file__).resolve().parents[2]
AS_OF = datetime(2024, 2, 23, 21, 5, tzinfo=UTC)


def test_fixture_snapshot_is_point_in_time_and_deterministic() -> None:
    client = FixtureDataClient(ROOT / "demo_data")
    first = client.latest_snapshot(["nvda", "AAPL", "NVDA"], AS_OF)
    second = client.latest_snapshot(["AAPL", "NVDA"], AS_OF)
    assert [bar.ticker for bar in first.bars] == ["AAPL", "NVDA"]
    assert first == second
    assert all(bar.available_at <= AS_OF for bar in first.bars)
    assert client.network_enabled is False


def test_future_prices_are_not_visible() -> None:
    client = FixtureDataClient(ROOT / "demo_data")
    snapshot = client.latest_snapshot(["AAPL"], AS_OF)
    assert len(snapshot.bars) == 1
    assert snapshot.bars[0].date <= "2024-02-23"


def test_history_respects_as_of() -> None:
    client = FixtureDataClient(ROOT / "demo_data")
    history = client.price_history(
        "AAPL",
        datetime(2024, 2, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
        as_of=AS_OF,
    )
    assert history
    assert max(bar.available_at for bar in history) <= AS_OF
    assert max(bar.date for bar in history) <= "2024-02-23"


def test_duplicate_price_rows_halt(tmp_path: Path) -> None:
    source = pd.read_parquet(ROOT / "demo_data" / "prices.parquet").head(2)
    pd.concat([source, source.iloc[[0]]], ignore_index=True).to_parquet(
        tmp_path / "prices.parquet", index=False
    )
    with pytest.raises(DataIntegrityError, match="duplicate"):
        FixtureDataClient(tmp_path)


def test_missing_fixture_halts(tmp_path: Path) -> None:
    with pytest.raises(DataIntegrityError, match="missing fixture"):
        FixtureDataClient(tmp_path)
