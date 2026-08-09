"""Explicitly non-release Yahoo public-price download for engineering tests only."""

from __future__ import annotations

from datetime import UTC, datetime

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
