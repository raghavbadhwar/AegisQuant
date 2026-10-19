"""Local, network-denied Parquet client used by replay and CI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from aegis.data.protocol import DataIntegrityError, MarketSnapshot, PriceBar


def _canonical_hash(rows: list[dict[str, Any]]) -> str:
    import hashlib
    import json

    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class FixtureDataClient:
    """Read immutable local fixtures. This class has no network code by construction."""

    network_enabled = False

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        import hashlib

        digest = hashlib.sha256()
        for name in ("earnings.parquet", "fundamentals.parquet", "prices.parquet"):
            path = self.root / name
            if not path.is_file():
                raise DataIntegrityError(f"missing fixture: {path}")
            digest.update(name.encode())
            digest.update(path.read_bytes())
        self.dataset_hash = digest.hexdigest()
        self._prices = self._read("prices.parquet")
        self._validate_prices()

    def _read(self, name: str) -> pd.DataFrame:
        path = self.root / name
        if not path.is_file():
            raise DataIntegrityError(f"missing fixture: {path}")
        try:
            return pd.read_parquet(path)
        except Exception as exc:
            raise DataIntegrityError(f"cannot read fixture {path}: {exc}") from exc

    def _validate_prices(self) -> None:
        required = {
            "ticker",
            "date",
            "available_at",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "dataset",
        }
        missing = required.difference(self._prices.columns)
        if missing:
            raise DataIntegrityError(f"prices fixture missing columns: {sorted(missing)}")
        frame = self._prices.copy()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        try:
            frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
        except Exception as exc:
            raise DataIntegrityError("invalid available_at in prices fixture") from exc
        if frame.duplicated(["ticker", "date"]).any():
            raise DataIntegrityError("duplicate ticker/date rows in prices fixture")
        numeric = frame[["open", "high", "low", "close"]]
        if numeric.isna().any().any() or (numeric <= 0).any().any():
            raise DataIntegrityError("prices must be finite and positive")
        if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
            raise DataIntegrityError("high is below another OHLC field")
        if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
            raise DataIntegrityError("low is above another OHLC field")
        self._prices = frame.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)

    @staticmethod
    def _bar(row: pd.Series) -> PriceBar:
        return PriceBar(
            ticker=str(row["ticker"]),
            date=str(row["date"]),
            available_at=row["available_at"].to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row["volume"]),
            dataset=str(row["dataset"]),
        )

    def latest_snapshot(self, tickers: list[str], as_of: datetime) -> MarketSnapshot:
        universe = sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})
        available = self._prices[
            self._prices["ticker"].isin(universe)
            & (self._prices["available_at"] <= pd.Timestamp(as_of))
            & (self._prices["date"] <= as_of.date().isoformat())
        ]
        latest = available.groupby("ticker", sort=True, as_index=False).tail(1)
        bars = tuple(self._bar(row) for _, row in latest.sort_values("ticker").iterrows())
        rows = [bar.model_dump(mode="json") for bar in bars]
        return MarketSnapshot(as_of=as_of, bars=bars, content_hash=_canonical_hash(rows))

    def price_history(
        self, ticker: str, start: datetime, end: datetime, *, as_of: datetime
    ) -> tuple[PriceBar, ...]:
        symbol = ticker.strip().upper()
        frame = self._prices[
            (self._prices["ticker"] == symbol)
            & (self._prices["date"] >= start.date().isoformat())
            & (self._prices["date"] <= end.date().isoformat())
            & (self._prices["available_at"] <= pd.Timestamp(as_of))
        ]
        return tuple(self._bar(row) for _, row in frame.iterrows())

    def sector_map(self, tickers: list[str], as_of: datetime) -> dict[str, str]:
        rows = self.table_as_of("fundamentals", tickers, as_of)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest[str(row["ticker"]).upper()] = row
        sectors: dict[str, str] = {}
        for ticker, row in sorted(latest.items()):
            sector = row.get("sector")
            if isinstance(sector, str) and sector.strip():
                sectors[ticker] = sector.strip()
        return sectors

    def table_as_of(self, name: str, tickers: list[str], as_of: datetime) -> list[dict[str, Any]]:
        if name not in {"fundamentals", "earnings"}:
            raise ValueError(f"unsupported fixture table: {name}")
        frame = self._read(f"{name}.parquet")
        required = {"ticker", "available_at"}
        if not required.issubset(frame.columns):
            raise DataIntegrityError(f"{name} fixture missing point-in-time columns")
        try:
            available = pd.to_datetime(frame["available_at"], utc=True)
        except Exception as exc:
            raise DataIntegrityError(f"invalid available_at in {name} fixture") from exc
        universe = {ticker.strip().upper() for ticker in tickers}
        filtered = frame[
            frame["ticker"].str.upper().isin(universe) & (available <= pd.Timestamp(as_of))
        ]
        rows = filtered.sort_values(["ticker", "available_at"], kind="stable").to_dict("records")
        return cast(list[dict[str, Any]], rows)
