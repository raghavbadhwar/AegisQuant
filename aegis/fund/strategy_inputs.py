"""Point-in-time adapter from research dossiers and prices to the pure strategy engine."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import cast

import numpy as np

from aegis.contracts import (
    AlphaForecast,
    EvidenceBundle,
    FundMandate,
    ModelForecastBatch,
    ResearchCase,
    canonical_sha256,
)
from aegis.data import DataClient, DataIntegrityError, PointInTimeViolation
from aegis.quant_research.hashing import build_hashed
from aegis.strategy import PodMarketContext


def _semantic_id(kind: str, payload: object) -> str:
    return f"{kind}-{canonical_sha256(payload)[:20]}-v1"


def _score(metadata: dict[str, object], name: str) -> float:
    value = metadata.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DataIntegrityError(f"multi-strategy forecast requires numeric {name}")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise DataIntegrityError(f"multi-strategy forecast {name} must be within [0,1]")
    return score


def _features(metadata: dict[str, object]) -> tuple[str, ...]:
    value = metadata.get("feature_ids", ())
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise DataIntegrityError("multi-strategy forecast feature_ids must be strings")
    features = tuple(sorted(cast(tuple[str, ...], tuple(value))))
    if len(features) != len(set(features)):
        raise DataIntegrityError("multi-strategy forecast feature_ids must be unique")
    return features


def build_model_batches(
    mandate: FundMandate,
    case: ResearchCase,
    forecasts: tuple[AlphaForecast, ...],
    evidence: EvidenceBundle,
) -> dict[str, tuple[ModelForecastBatch, ...]]:
    """Bind flat standard forecasts to exactly the models declared by the mandate."""
    if evidence.case_id != case.case_id or evidence.as_of != case.as_of:
        raise DataIntegrityError("strategy evidence does not match the research case")
    evidence_by_id = {item.evidence_id: item for item in evidence.records}
    declared = {model.model_id: pod.pod_id for pod in mandate.pods for model in pod.models}
    if len(declared) != sum(len(pod.models) for pod in mandate.pods):
        raise DataIntegrityError("alpha model IDs must be unique across strategy pods")
    unknown = sorted({item.model_name for item in forecasts}.difference(declared))
    if unknown:
        raise DataIntegrityError(f"forecast output contains undeclared alpha models: {unknown}")
    by_model: dict[str, list[AlphaForecast]] = {model_id: [] for model_id in declared}
    for forecast in forecasts:
        if forecast.as_of != case.as_of or forecast.horizon_days != case.horizon_days:
            raise DataIntegrityError("multi-strategy forecast cutoff/horizon mismatch")
        by_model[forecast.model_name].append(forecast)
    missing = sorted(model_id for model_id, values in by_model.items() if not values)
    if missing:
        raise DataIntegrityError(f"missing declared alpha-model forecasts: {missing}")

    result: dict[str, list[ModelForecastBatch]] = {pod.pod_id: [] for pod in mandate.pods}
    for model_id in sorted(by_model):
        values = tuple(sorted(by_model[model_id], key=lambda item: item.ticker))
        tickers = [item.ticker for item in values]
        if len(tickers) != len(set(tickers)):
            raise DataIntegrityError(f"duplicate ticker forecast for alpha model {model_id}")
        metadata_rows = [item.metadata for item in values]
        calibration = {_score(row, "calibration_score") for row in metadata_rows}
        regime = {_score(row, "regime_score") for row in metadata_rows}
        quality = {_score(row, "evidence_quality") for row in metadata_rows}
        feature_sets = {_features(row) for row in metadata_rows}
        if any(len(items) != 1 for items in (calibration, regime, quality, feature_sets)):
            raise DataIntegrityError("batch-level calibration/regime/evidence/features must agree")
        cited = {evidence_id for item in values for evidence_id in item.evidence_ids}
        if not cited.issubset(evidence_by_id):
            raise DataIntegrityError("multi-strategy forecast cites evidence outside the dossier")
        available_at = max(
            (evidence_by_id[item].available_at for item in cited),
            default=case.as_of,
        )
        if available_at > case.as_of:
            raise PointInTimeViolation("future evidence reached a strategy model batch")
        pod_id = declared[model_id]
        batch = build_hashed(
            ModelForecastBatch,
            batch_id=_semantic_id(
                "model-batch",
                {
                    "pod": pod_id,
                    "model": model_id,
                    "forecasts": [item.forecast_id for item in values],
                },
            ),
            pod_id=pod_id,
            model_id=model_id,
            as_of=case.as_of,
            available_at=available_at,
            forecasts=values,
            calibration_score=next(iter(calibration)),
            regime_score=next(iter(regime)),
            evidence_quality=next(iter(quality)),
            feature_ids=next(iter(feature_sets)),
        )
        result[pod_id].append(batch)
    return {
        pod_id: tuple(sorted(items, key=lambda item: item.model_id))
        for pod_id, items in sorted(result.items())
    }


def _covariance_context(
    pod_id: str,
    tickers: tuple[str, ...],
    case: ResearchCase,
    data_client: DataClient,
) -> PodMarketContext:
    if not tickers:
        return PodMarketContext(
            universe_snapshot_id=_semantic_id("universe", {"case": case.case_id}),
            as_of=case.as_of,
            available_at=case.as_of,
            covariance={},
            benchmark_weights={},
            covariance_training_start=case.as_of,
            covariance_training_end=case.as_of,
            covariance_observation_hash=canonical_sha256({"case": case.case_id, "empty": pod_id}),
            input_snapshot_hashes=(canonical_sha256({"case": case.case_id, "empty": pod_id}),),
        )
    start = case.as_of - timedelta(days=400)
    returns: dict[str, dict[str, float]] = {}
    histories: dict[str, list[dict[str, object]]] = {}
    available: list[datetime] = []
    for ticker in tickers:
        bars = data_client.price_history(ticker, start, case.as_of, as_of=case.as_of)
        if any(bar.available_at > case.as_of for bar in bars):
            raise PointInTimeViolation(f"future price history reached strategy context: {ticker}")
        if len(bars) < 4:
            raise DataIntegrityError(f"strategy covariance requires four prices: {ticker}")
        ordered = sorted(bars, key=lambda item: item.date)
        if len({bar.date for bar in ordered}) != len(ordered):
            raise DataIntegrityError(f"duplicate strategy price date: {ticker}")
        returns[ticker] = {
            ordered[index].date: ordered[index].close / ordered[index - 1].close - 1.0
            for index in range(1, len(ordered))
        }
        histories[ticker] = [bar.model_dump(mode="json") for bar in ordered]
        available.extend(bar.available_at for bar in ordered)
    common = sorted(set.intersection(*(set(values) for values in returns.values())))
    if len(common) < 3:
        raise DataIntegrityError("strategy covariance requires three common returns")
    matrix = np.asarray(
        [[returns[ticker][day] for ticker in tickers] for day in common], dtype=float
    )
    covariance_array = np.atleast_2d(np.cov(matrix, rowvar=False, ddof=1))
    if covariance_array.shape != (len(tickers), len(tickers)) or not np.all(
        np.isfinite(covariance_array)
    ):
        raise DataIntegrityError("strategy covariance is malformed")
    covariance = {
        left: {
            right: float(covariance_array[left_index, right_index])
            for right_index, right in enumerate(tickers)
        }
        for left_index, left in enumerate(tickers)
    }
    equal = 1.0 / len(tickers)
    observation_hash = canonical_sha256(histories)
    return PodMarketContext(
        universe_snapshot_id=_semantic_id("universe", {"case": case.case_id, "tickers": tickers}),
        as_of=case.as_of,
        available_at=max(available),
        covariance=covariance,
        benchmark_weights={ticker: equal for ticker in tickers},
        covariance_training_start=min(available),
        covariance_training_end=max(available),
        covariance_observation_hash=observation_hash,
        input_snapshot_hashes=(observation_hash,),
    )


def build_pod_contexts(
    mandate: FundMandate,
    case: ResearchCase,
    batches: dict[str, tuple[ModelForecastBatch, ...]],
    data_client: DataClient,
) -> dict[str, PodMarketContext]:
    """Calculate covariance contexts from sealed PIT price histories."""
    result = {}
    for pod in sorted(mandate.pods, key=lambda item: item.pod_id):
        pod_batches = batches.get(pod.pod_id)
        if pod_batches is None:
            raise DataIntegrityError(f"missing strategy batches for pod {pod.pod_id}")
        tickers = tuple(
            sorted(
                {
                    forecast.ticker
                    for batch in pod_batches
                    for forecast in batch.forecasts
                    if not forecast.abstained
                }
            )
        )
        result[pod.pod_id] = _covariance_context(pod.pod_id, tickers, case, data_client)
    return result
