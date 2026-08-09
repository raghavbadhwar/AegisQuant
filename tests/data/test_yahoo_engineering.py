from datetime import UTC, datetime

import pandas as pd
import pytest

from aegis.data.protocol import PriceBar
from aegis.data.yahoo_engineering import YahooEngineeringDataError, write_engineering_price_fixture


def test_writer_creates_explicit_nonrelease_immutable_fixture(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def bars(ticker: str, start: datetime, end: datetime) -> tuple[PriceBar, ...]:
        return (
            PriceBar(
                ticker=ticker,
                date="2020-01-02",
                available_at=datetime.now(UTC),
                open=1,
                high=2,
                low=1,
                close=2,
                volume=1,
                dataset="yahoo-engineering-nonrelease-v1",
            ),
        )

    monkeypatch.setattr("aegis.data.yahoo_engineering.download_daily_prices", bars)
    root = write_engineering_price_fixture(
        tmp_path / "fixture",
        ("AAPL",),
        datetime(2020, 1, 1, tzinfo=UTC),
        datetime(2020, 1, 3, tzinfo=UTC),
    )
    assert (
        pd.read_parquet(root / "prices.parquet").iloc[0]["dataset"]
        == "yahoo-engineering-nonrelease-v1"
    )
    with pytest.raises(YahooEngineeringDataError, match="immutable"):
        write_engineering_price_fixture(
            root, ("AAPL",), datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 1, 3, tzinfo=UTC)
        )
