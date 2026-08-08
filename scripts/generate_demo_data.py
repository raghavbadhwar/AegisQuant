from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fixtures"
TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "SPY"]
BASE = {"AAPL": 125.0, "MSFT": 220.0, "NVDA": 15.0, "AMZN": 85.0, "GOOGL": 90.0, "SPY": 370.0}
SECTOR = {
    "AAPL": "Information Technology",
    "MSFT": "Information Technology",
    "NVDA": "Information Technology",
    "AMZN": "Consumer Discretionary",
    "GOOGL": "Communication Services",
}

DRIFT = {
    "AAPL": 0.00045,
    "MSFT": 0.00055,
    "NVDA": 0.00115,
    "AMZN": 0.00050,
    "GOOGL": 0.00048,
    "SPY": 0.00032,
}


def business_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    days = business_days(date(2023, 1, 2), date(2025, 12, 31))
    prices: list[dict[str, object]] = []
    for ticker_index, ticker in enumerate(TICKERS):
        base = BASE[ticker]
        drift = DRIFT[ticker]
        for index, day in enumerate(days):
            cycle = 0.035 * math.sin(index / (13.0 + ticker_index))
            shock = 0.012 * math.cos(index / (29.0 + ticker_index * 2))
            close = base * math.exp(drift * index + cycle + shock)
            open_ = close * (1 - 0.002 * math.sin(index / 3.0 + ticker_index))
            high = max(open_, close) * 1.004
            low = min(open_, close) * 0.996
            prices.append(
                {
                    "ticker": ticker,
                    "date": day.isoformat(),
                    "available_at": f"{day.isoformat()}T21:05:00+00:00",
                    "open": round(open_, 6),
                    "high": round(high, 6),
                    "low": round(low, 6),
                    "close": round(close, 6),
                    "volume": int(20_000_000 + ticker_index * 2_000_000 + (index % 31) * 100_000),
                    "dataset": "synthetic-demo-v1",
                }
            )
    pd.DataFrame(prices).to_parquet(OUT / "prices.parquet", index=False)

    fundamentals: list[dict[str, object]] = []
    quarters = [
        date(2023, 3, 31),
        date(2023, 6, 30),
        date(2023, 9, 30),
        date(2023, 12, 31),
        date(2024, 3, 31),
        date(2024, 6, 30),
        date(2024, 9, 30),
        date(2024, 12, 31),
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
    ]
    for ticker_index, ticker in enumerate(TICKERS[:-1]):
        for q_index, report_period in enumerate(quarters):
            available = report_period + timedelta(days=32 + ticker_index)
            fundamentals.append(
                {
                    "ticker": ticker,
                    "report_period": report_period.isoformat(),
                    "available_at": f"{available.isoformat()}T12:00:00+00:00",
                    "revenue_growth": round(0.07 + ticker_index * 0.025 + q_index * 0.001, 6),
                    "return_on_equity": round(0.16 + ticker_index * 0.018, 6),
                    "debt_to_equity": round(0.62 - ticker_index * 0.06, 6),
                    "free_cash_flow_yield": round(0.035 + ticker_index * 0.003, 6),
                    "sector": SECTOR[ticker],
                    "source": "synthetic-demo-v1",
                }
            )
    pd.DataFrame(fundamentals).to_parquet(OUT / "fundamentals.parquet", index=False)

    earnings: list[dict[str, object]] = []
    for row in fundamentals:
        ticker_index = TICKERS.index(str(row["ticker"]))
        earnings.append(
            {
                "ticker": row["ticker"],
                "report_period": row["report_period"],
                "available_at": row["available_at"],
                "eps_surprise_pct": round(0.01 + ticker_index * 0.012, 6),
                "revenue_surprise_pct": round(0.005 + ticker_index * 0.004, 6),
                "source": "synthetic-demo-v1",
            }
        )
    pd.DataFrame(earnings).to_parquet(OUT / "earnings.parquet", index=False)

    evidence_dir = OUT / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    as_of = "2024-02-23T21:05:00+00:00"
    records = []
    for ticker in TICKERS[:-1]:
        evidence_id = f"demo-{ticker.lower()}-20240223-price"
        payload = {
            "ticker": ticker,
            "as_of": as_of,
            "field": "close",
            "dataset": "synthetic-demo-v1",
        }
        records.append(
            {
                "evidence_id": evidence_id,
                "source_id": "synthetic-demo-v1",
                "source_url": None,
                "entity_ids": [ticker],
                "document_type": "price_snapshot",
                "published_at": as_of,
                "available_at": as_of,
                "retrieved_at": as_of,
                "raw_uri": "data/fixtures/prices.parquet",
                "section": "daily close",
                "page": None,
                "coordinates": f"ticker={ticker};date=2024-02-23;field=close",
                "event_time": as_of,
                "content_hash": __import__("hashlib")
                .sha256(json.dumps(payload, sort_keys=True).encode())
                .hexdigest(),
                "historical_safe": True,
                "source_quality": 1.0,
                "extraction_confidence": 1.0,
                "injection_flags": [],
                "parser_version": "parquet-v1",
                "extractor_version": "fixture-generator-v2",
            }
        )
    (evidence_dir / "replay_evidence.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
    )

    forecasts = []
    scores = {
        "AAPL": (0.085, 0.22, 0.64, 0.78),
        "MSFT": (0.095, 0.20, 0.68, 0.84),
        "NVDA": (0.14, 0.38, 0.70, 0.80),
        "AMZN": (0.075, 0.30, 0.61, 0.70),
        "GOOGL": (0.07, 0.24, 0.60, 0.72),
    }
    for ticker, (ret, vol, prob, conf) in scores.items():
        forecasts.append(
            {
                "forecast_id": f"replay-cio-v2-{ticker.lower()}-20240223",
                "model_name": "replay-cio-v2",
                "ticker": ticker,
                "as_of": as_of,
                "horizon_days": 20,
                "expected_excess_return": ret,
                "expected_volatility": vol,
                "probability_positive": prob,
                "confidence": conf,
                "uncertainty": round(1 - conf, 6),
                "downside_case": round(-ret * 0.75, 6),
                "base_case": ret,
                "upside_case": round(ret * 1.5, 6),
                "thesis": (
                    f"Deterministic replay forecast for {ticker} from approved local fixtures."
                ),
                "evidence_ids": [f"demo-{ticker.lower()}-20240223-price"],
                "invalidation_conditions": ["fixture schema or point-in-time validation fails"],
                "catalyst_dates": [],
                "thesis_expiry": "2024-03-31T21:05:00+00:00",
                "abstained": False,
                "abstain_reason": None,
                "components": {"quality": round(conf - 0.5, 6), "momentum": round(prob - 0.5, 6)},
                "metadata": {"provider": "fixture", "version": "v2"},
            }
        )
    (OUT / "replay_forecasts.json").write_text(
        json.dumps(forecasts, indent=2, sort_keys=True) + "\n"
    )
    case = {
        "case_id": "nvda-earnings-demo",
        "mode": "replay",
        "as_of": as_of,
        "created_at": as_of,
        "horizon_days": 20,
        "research_question": "Assess the approved demo universe after the NVDA earnings event.",
        "fund_path": "configs/funds/demo-fund.yaml",
        "tickers": TICKERS[:-1],
        "forecast_fixture": "data/fixtures/replay_forecasts.json",
        "evidence_fixture": "data/fixtures/evidence/replay_evidence.jsonl",
    }
    (OUT / "cases" / "nvda_earnings_case.json").write_text(
        json.dumps(case, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
