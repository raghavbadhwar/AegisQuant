"""Explicitly non-release Yahoo public-price download for engineering tests only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from aegis.data.protocol import DataIntegrityError, PriceBar


class YahooEngineeringDataError(DataIntegrityError):
    pass


def download_daily_prices(ticker: str, start: datetime, end: datetime) -> tuple[PriceBar, ...]:
    """Download public Yahoo EOD bars; never use for release/performance qualification.

    Returned bars are marked `yahoo-engineering-nonrelease-v1` and their
    availability is retrieval time, not a historical publication assertion.
    A caller must raw-capture and seal them before any offline engineering replay.
    """
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise YahooEngineeringDataError("Yahoo engineering query requires ordered aware timestamps")
    try:
        import httpx

        response = httpx.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}",
            params={
                "period1": int(start.timestamp()),
                "period2": int(end.timestamp()),
                "interval": "1d",
                "events": "history",
            },
            headers={"User-Agent": "AegisQuant engineering-only test"},
            timeout=30.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]
    except (ImportError, KeyError, TypeError, ValueError, httpx.HTTPError) as exc:
        raise YahooEngineeringDataError("Yahoo engineering response is invalid") from exc
    retrieved_at = datetime.now(UTC)
    bars: list[PriceBar] = []
    for index, timestamp in enumerate(timestamps):
        values = {name: quotes[name][index] for name in ("open", "high", "low", "close", "volume")}
        if any(value is None for value in values.values()):
            continue
        bars.append(
            PriceBar(
                ticker=ticker,
                date=datetime.fromtimestamp(timestamp, UTC).date().isoformat(),
                available_at=retrieved_at,
                open=float(values["open"]),
                high=float(values["high"]),
                low=float(values["low"]),
                close=float(values["close"]),
                volume=int(values["volume"]),
                dataset="yahoo-engineering-nonrelease-v1",
            )
        )
    if not bars:
        raise YahooEngineeringDataError("Yahoo engineering response has no complete bars")
    return tuple(bars)


def write_engineering_price_fixture(
    root: str | Path, tickers: tuple[str, ...], start: datetime, end: datetime
) -> Path:
    """Write a local-only, explicitly non-release price fixture for offline tests."""
    destination = Path(root).resolve()
    if destination.exists():
        raise YahooEngineeringDataError("engineering price fixture destination is immutable")
    rows = [
        item.model_dump(mode="json")
        for ticker in sorted(set(tickers))
        for item in download_daily_prices(ticker, start, end)
    ]
    if not rows:
        raise YahooEngineeringDataError("engineering fixture has no prices")
    destination.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(destination / "prices.parquet", index=False)
    (destination / "README.md").write_text(
        "# Non-release engineering price fixture\n\n"
        "Source: Yahoo public chart endpoint. Not valid for release, performance, "
        "eligibility, or investment claims.\n"
    )
    return destination
