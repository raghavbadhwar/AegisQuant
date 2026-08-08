"""Deterministic batch alpha models used by no-key historical backtests."""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np

from aegis.contracts import (
    AlphaForecast,
    EvidenceBundle,
    EvidenceRecord,
    ResearchCase,
    canonical_sha256,
)
from aegis.data import DataClient, MarketSnapshot


class DeterministicCompositeProvider:
    """Price/fundamental composite; deterministic, local, and point-in-time only."""

    network_enabled = False

    def __init__(self, data_client: DataClient) -> None:
        if data_client.network_enabled:
            raise ValueError("deterministic historical provider requires a network-denied client")
        self.data_client = data_client

    @staticmethod
    def _evidence_id(case: ResearchCase, ticker: str) -> str:
        return f"hist-{ticker.lower()}-{case.as_of:%Y%m%d}"

    def evidence_bundle(self, case: ResearchCase) -> EvidenceBundle:
        snapshot = self.data_client.latest_snapshot(case.tickers, case.as_of)
        records: list[EvidenceRecord] = []
        for bar in snapshot.bars:
            payload = bar.model_dump(mode="json")
            records.append(
                EvidenceRecord(
                    evidence_id=self._evidence_id(case, bar.ticker),
                    source_id=bar.dataset,
                    source_url=None,
                    content_hash=canonical_sha256(payload),
                    raw_uri="data/fixtures/prices.parquet",
                    entity_ids=[bar.ticker],
                    document_type="price_snapshot",
                    section="daily close history",
                    coordinates=f"ticker={bar.ticker};date<={bar.date};fields=close,volume",
                    event_time=bar.available_at,
                    published_at=bar.available_at,
                    available_at=bar.available_at,
                    retrieved_at=case.as_of,
                    source_quality=1.0,
                    extraction_confidence=1.0,
                    historical_safe=True,
                    injection_flags=[],
                    parser_version="parquet-v1",
                    extractor_version="deterministic-composite-v1",
                )
            )
        return EvidenceBundle(case_id=case.case_id, as_of=case.as_of, records=records)

    def forecast_batch(
        self, case: ResearchCase, snapshot: MarketSnapshot
    ) -> tuple[AlphaForecast, ...]:
        bundle = self.evidence_bundle(case)
        evidence_ids = {record.entity_ids[0]: record.evidence_id for record in bundle.records}
        start = case.as_of - timedelta(days=140)
        forecasts: list[AlphaForecast] = []
        for ticker in sorted(case.tickers):
            history = self.data_client.price_history(ticker, start, case.as_of, as_of=case.as_of)
            forecast_id = canonical_sha256(
                {
                    "model": "deterministic-composite-v1",
                    "ticker": ticker,
                    "as_of": case.as_of.isoformat(),
                    "snapshot": snapshot.content_hash,
                }
            )[:32]
            if len(history) < 21:
                forecasts.append(
                    AlphaForecast(
                        forecast_id=forecast_id,
                        model_name="deterministic-composite-v1",
                        ticker=ticker,
                        as_of=case.as_of,
                        horizon_days=case.horizon_days,
                        expected_excess_return=None,
                        expected_volatility=None,
                        probability_positive=0.5,
                        confidence=0.0,
                        uncertainty=1.0,
                        thesis="",
                        evidence_ids=[],
                        abstained=True,
                        abstain_reason="fewer than 21 point-in-time price observations",
                    )
                )
                continue
            closes = np.asarray([bar.close for bar in history], dtype=float)
            returns = np.diff(closes) / closes[:-1]
            momentum_20 = float(closes[-1] / closes[-21] - 1.0)
            volatility = float(np.std(returns[-60:], ddof=1) * math.sqrt(252))
            expected = max(-0.25, min(0.25, momentum_20 * 0.35))
            probability = 1.0 / (1.0 + math.exp(-momentum_20 * 8.0))
            confidence = min(0.85, 0.55 + len(history) / 1000.0)
            forecasts.append(
                AlphaForecast(
                    forecast_id=forecast_id,
                    model_name="deterministic-composite-v1",
                    ticker=ticker,
                    as_of=case.as_of,
                    horizon_days=case.horizon_days,
                    expected_excess_return=expected,
                    expected_volatility=max(volatility, 0.01),
                    probability_positive=probability,
                    confidence=confidence,
                    uncertainty=1.0 - confidence,
                    downside_case=min(expected - volatility / 4.0, expected),
                    base_case=expected,
                    upside_case=max(expected + volatility / 4.0, expected),
                    thesis="Deterministic momentum and volatility composite from local history.",
                    evidence_ids=[evidence_ids[ticker]],
                    invalidation_conditions=["point-in-time history becomes incomplete"],
                    catalyst_dates=[],
                    thesis_expiry=case.as_of + timedelta(days=case.horizon_days),
                    components={
                        "momentum_20": momentum_20,
                        "annualized_volatility": volatility,
                    },
                    metadata={"calculation": "deterministic-composite-v1"},
                )
            )
        return tuple(forecasts)
