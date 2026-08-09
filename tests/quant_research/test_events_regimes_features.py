from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aegis.contracts import EventStudySpec, MarketEvent
from aegis.quant_research.events import ReturnObservation, run_event_study
from aegis.quant_research.features import (
    BehavioralObservation,
    GraphEdgeObservation,
    calculate_behavioral_features,
    calculate_graph_features,
)
from aegis.quant_research.hashing import build_hashed
from aegis.quant_research.regimes import NumericObservation, RegimeInputs, classify_regime

NOW = datetime(2025, 6, 30, 16, tzinfo=UTC)


def _event_spec() -> EventStudySpec:
    return build_hashed(
        EventStudySpec,
        spec_id="earnings-event-study-v1",
        benchmark_ticker="SPY",
        event_types=("earnings",),
        estimation_window_start=-5,
        estimation_window_end=-2,
        car_windows=((-1, 1), (0, 1)),
        bootstrap_samples=100,
        confidence_level=0.95,
        pre_event_leakage_days=1,
        market_model_version="ordinary-market-model-v1",
    )


def _event_fixture() -> tuple[MarketEvent, list[ReturnObservation]]:
    occurred_at = NOW - timedelta(days=2)
    event = build_hashed(
        MarketEvent,
        event_id="aapl-earnings-event-v1",
        ticker="AAPL",
        event_type="earnings",
        occurred_at=occurred_at,
        source_type="filing",
        surprise=0.2,
        source_ids=("filing-aapl-2025q2",),
        as_of=NOW,
        available_at=occurred_at,
    )
    market = {-5: 0.01, -4: 0.02, -3: -0.01, -2: 0.03, -1: 0.0, 0: 0.01, 1: -0.02}
    abnormal = {-1: 0.0, 0: 0.01, 1: -0.003}
    observations: list[ReturnObservation] = []
    for offset, market_return in market.items():
        timestamp = occurred_at + timedelta(days=offset)
        observations.append(
            ReturnObservation("SPY", timestamp, timestamp, market_return, "prices-spy")
        )
        asset_return = 0.001 + 1.5 * market_return + abnormal.get(offset, 0.0)
        observations.append(
            ReturnObservation("AAPL", timestamp, timestamp, asset_return, "prices-aapl")
        )
    return event, observations


def test_event_study_has_golden_car_seeded_interval_and_stable_ids() -> None:
    event, observations = _event_fixture()
    result = run_event_study(_event_spec(), [event], observations, as_of=NOW, seed=7)

    assert result.cumulative_abnormal_returns["-1:1"] == pytest.approx(0.007)
    assert result.cumulative_abnormal_returns["0:1"] == pytest.approx(0.007)
    assert result.bootstrap_intervals["-1:1"].lower == pytest.approx(0.007)
    assert result.bootstrap_intervals["-1:1"].upper == pytest.approx(0.007)
    assert result.source_segment_cars["filing|-1:1"] == pytest.approx(0.007)
    assert result.surprise_slope is None
    assert result.pre_event_leakage_detected is False
    assert result == run_event_study(
        _event_spec(), [event], list(reversed(observations)), as_of=NOW, seed=7
    )


def test_event_study_ignores_future_mutation_and_rejects_bad_timestamps() -> None:
    event, observations = _event_fixture()
    baseline = run_event_study(_event_spec(), [event], observations, as_of=NOW, seed=11)
    future = ReturnObservation(
        "AAPL",
        NOW + timedelta(days=1),
        NOW + timedelta(days=2),
        999.0,
        "future-price",
    )
    assert baseline == run_event_study(
        _event_spec(), [event], [future, *observations], as_of=NOW, seed=11
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        ReturnObservation("AAPL", datetime(2025, 1, 1), datetime(2025, 1, 1), 0.1, "x")


def _number(value: float, index: int, *, future: bool = False) -> NumericObservation:
    observed = NOW + timedelta(days=1) if future else NOW - timedelta(days=10 - index)
    available = observed
    return NumericObservation(observed, available, value, f"series-{index}")


def test_regime_classifies_all_six_axes_and_is_cutoff_and_order_safe() -> None:
    inputs = RegimeInputs(
        as_of=NOW,
        volatility=[_number(value, i) for i, value in enumerate((10.0, 12.0, 14.0, 40.0))],
        market_returns=[_number(value, i) for i, value in enumerate((0.01, 0.02, 0.01))],
        rates_liquidity=[_number(1.0, 0)],
        risk_appetite=[_number(-1.0, 0)],
        factor_returns={
            "value": [_number(0.01, 0)],
            "momentum": [_number(0.03, 1)],
        },
        correlations=[_number(0.7, 0), _number(0.8, 1)],
    )
    result = classify_regime(inputs)
    assert result.volatility_regime == "crisis"
    assert result.market_trend == "up"
    assert result.rates_liquidity_context == "tightening"
    assert result.risk_state == "risk_off"
    assert result.factor_leadership == ("momentum", "value")
    assert result.correlation_regime == "high"
    assert result.interpretation_only is True and result.order_authority is False

    mutated = RegimeInputs(
        as_of=NOW,
        volatility=[_number(999.0, 99, future=True), *reversed(inputs.volatility)],
        market_returns=list(reversed(inputs.market_returns)),
        rates_liquidity=inputs.rates_liquidity,
        risk_appetite=inputs.risk_appetite,
        factor_returns=inputs.factor_returns,
        correlations=list(reversed(inputs.correlations)),
    )
    assert classify_regime(mutated) == result


def _behavioral_fixture() -> list[BehavioralObservation]:
    return [
        BehavioralObservation(
            "AAPL",
            NOW - timedelta(days=3 - i),
            NOW - timedelta(days=3 - i),
            source,
            mentions,
            sentiment,
            volume,
            price_return,
            narrative,
        )
        for i, (source, mentions, sentiment, volume, price_return, narrative) in enumerate(
            (
                ("news", 1.0, -1.0, 10.0, -0.01, "ai"),
                ("news", 2.0, 0.0, 12.0, 0.00, "ai"),
                ("social", 5.0, 1.0, 20.0, 0.02, "product"),
            )
        )
    ]


def test_behavioral_features_complete_order_safe_and_future_safe() -> None:
    observations = _behavioral_fixture()
    result = calculate_behavioral_features("aapl", observations, as_of=NOW)
    assert result.attention_shock == pytest.approx(7.0)
    assert result.mention_acceleration == pytest.approx(2.0)
    assert result.sentiment_dispersion == pytest.approx((2.0 / 3.0) ** 0.5)
    assert result.source_diversity == pytest.approx(2.0 / 3.0)
    assert result.narrative_saturation == pytest.approx(5.0 / 8.0)
    assert result.abnormal_volume == pytest.approx(9.0 / 11.0)
    assert result.order_authority is False
    assert calculate_behavioral_features("AAPL", list(reversed(observations)), as_of=NOW) == result

    future = BehavioralObservation(
        "AAPL",
        NOW + timedelta(days=1),
        NOW + timedelta(days=1),
        "future",
        999.0,
        999.0,
        999.0,
        999.0,
        "future",
    )
    assert calculate_behavioral_features("AAPL", [future, *observations], as_of=NOW) == result


def _edge(
    relation: str,
    target: str,
    weight: float,
    index: int,
    *,
    cluster: str | None = None,
    future: bool = False,
) -> GraphEdgeObservation:
    timestamp = NOW + timedelta(days=1) if future else NOW - timedelta(days=10 - index)
    return GraphEdgeObservation(
        "AAPL",
        target,
        relation,  # type: ignore[arg-type]
        weight,
        timestamp,
        timestamp,
        f"graph-source-{index}",
        cluster,
    )


def test_graph_features_cover_relationship_fields_and_are_cutoff_safe() -> None:
    edges = [
        _edge("supplier", "S1", 3.0, 0),
        _edge("supplier", "S2", 1.0, 1),
        _edge("customer", "C1", 2.0, 2),
        _edge("management", "M1", 0.5, 3),
        _edge("ownership", "O1", 0.4, 4),
        _edge("litigation_regulatory", "R1", 0.3, 5),
        _edge("narrative", "N1", 0.2, 6),
        _edge("common_exposure", "X1", 0.8, 7, cluster="chips"),
    ]
    result = calculate_graph_features(
        "AAPL", edges, as_of=NOW, graph_snapshot_id="relationship-graph-snapshot-v1"
    )
    assert result.supplier_concentration == pytest.approx(0.625)
    assert result.customer_concentration == pytest.approx(1.0)
    assert result.director_executive_overlap == pytest.approx(0.5)
    assert result.ownership_centrality == pytest.approx(0.4)
    assert result.litigation_regulatory_exposure == pytest.approx(0.3)
    assert result.narrative_propagation == pytest.approx(0.2)
    assert result.common_exposure_cluster == "chips"
    assert result.order_authority is False
    assert (
        calculate_graph_features(
            "AAPL",
            list(reversed(edges)),
            as_of=NOW,
            graph_snapshot_id="relationship-graph-snapshot-v1",
        )
        == result
    )

    future = _edge("supplier", "FUTURE", 999.0, 99, future=True)
    assert (
        calculate_graph_features(
            "AAPL",
            [future, *edges],
            as_of=NOW,
            graph_snapshot_id="relationship-graph-snapshot-v1",
        )
        == result
    )
