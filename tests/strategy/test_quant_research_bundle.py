"""Tests for the hash-bound point-in-time quant research bundle."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from aegis.contracts import (
    BehavioralFeatures,
    BootstrapInterval,
    EligibilityDecision,
    EventStudyResult,
    FactorDiagnostics,
    FactorEvaluation,
    GraphFeatures,
    QuantResearchBundle,
    RegimeSnapshot,
    UniverseMember,
    UniverseSnapshot,
    canonical_sha256,
)
from aegis.quant_research.hashing import build_hashed

AS_OF = datetime(2025, 1, 15, 16, tzinfo=UTC)
TICKERS = ("AAPL", "MSFT")


def _member(ticker: str) -> UniverseMember:
    name = ticker.lower()
    return build_hashed(
        UniverseMember,
        member_id=f"member-{name}-v1",
        ticker=ticker,
        as_of=AS_OF,
        available_at=AS_OF,
        listing_status="listed",
        average_daily_dollar_volume=1_000_000.0,
        market_cap=1_000_000_000.0,
        sector="Technology",
        industry="Software",
        data_completeness=1.0,
        borrow_eligible=True,
        source_ids=(f"source-{name}",),
    )


def _decision(member: UniverseMember) -> EligibilityDecision:
    return build_hashed(
        EligibilityDecision,
        decision_id=f"decision-{member.ticker.lower()}-v1",
        member_id=member.member_id,
        ticker=member.ticker,
        as_of=AS_OF,
        available_at=AS_OF,
        eligible=True,
        reasons=("eligible",),
        rules_version="eligibility-rules-v1",
    )


def _universe() -> UniverseSnapshot:
    members = tuple(_member(ticker) for ticker in TICKERS)
    return build_hashed(
        UniverseSnapshot,
        snapshot_id="universe-demo-v1",
        universe_id="universe-demo-v1",
        as_of=AS_OF,
        members=members,
        decisions=tuple(_decision(member) for member in members),
        fixed_fixture=False,
    )


def _diagnostics() -> FactorDiagnostics:
    return FactorDiagnostics(
        information_coefficient=0.1,
        rank_information_coefficient=0.1,
        icir=0.5,
        quantile_returns=(0.01, 0.02),
        long_short_return=0.01,
        monotonicity=1.0,
        turnover=0.2,
        autocorrelation=0.1,
        sector_neutrality=0.0,
        size_neutrality=0.0,
        gross_return=0.02,
        cost_adjusted_return=0.01,
        capacity=1_000_000.0,
        crowding_score=0.1,
    )


def _factor_evaluation(
    *, as_of: datetime = AS_OF, universe_snapshot_id: str = "universe-demo-v1"
) -> FactorEvaluation:
    return build_hashed(
        FactorEvaluation,
        evaluation_id="factor-evaluation-v1",
        factor_id="quality-factor-v1",
        universe_snapshot_ids=(universe_snapshot_id,),
        observation_ids=("factor-observation-v1",),
        as_of=as_of,
        available_at=as_of,
        period_start=date(2024, 1, 1),
        period_end=date(2025, 1, 15),
        diagnostics=_diagnostics(),
        calculation_ids=("factor-calculation-v1",),
    )


def _event_study_result(*, leakage_detected: bool = False) -> EventStudyResult:
    return build_hashed(
        EventStudyResult,
        result_id="event-study-result-v1",
        spec_id="event-study-spec-v1",
        event_ids=("market-event-v1",),
        as_of=AS_OF,
        available_at=AS_OF,
        cumulative_abnormal_returns={"-1:1": 0.01},
        bootstrap_intervals={"-1:1": BootstrapInterval(lower=-0.01, upper=0.03)},
        pre_event_leakage_detected=leakage_detected,
        calculation_ids=("event-study-calculation-v1",),
    )


def _regime() -> RegimeSnapshot:
    return build_hashed(
        RegimeSnapshot,
        snapshot_id="regime-demo-v1",
        as_of=AS_OF,
        available_at=AS_OF,
        volatility_regime="normal",
        market_trend="up",
        rates_liquidity_context="neutral",
        risk_state="risk_on",
        factor_leadership=("quality",),
        correlation_regime="normal",
        model_id="regime-model-v1",
        calculation_ids=("regime-calculation-v1",),
    )


def _behavioral(ticker: str) -> BehavioralFeatures:
    name = ticker.lower()
    return build_hashed(
        BehavioralFeatures,
        feature_id=f"behavioral-{name}-v1",
        ticker=ticker,
        as_of=AS_OF,
        available_at=AS_OF,
        attention_shock=0.1,
        mention_acceleration=0.1,
        sentiment_dispersion=0.1,
        source_diversity=2.0,
        narrative_saturation=0.1,
        abnormal_volume=0.1,
        price_attention_reflexivity=0.1,
        source_ids=(f"source-{name}",),
        calculator_id="behavioral-calculator-v1",
    )


def _graph(ticker: str) -> GraphFeatures:
    name = ticker.lower()
    return build_hashed(
        GraphFeatures,
        feature_id=f"graph-{name}-v1",
        ticker=ticker,
        as_of=AS_OF,
        available_at=AS_OF,
        supplier_concentration=0.1,
        customer_concentration=0.1,
        director_executive_overlap=0.1,
        ownership_centrality=0.1,
        litigation_regulatory_exposure=0.1,
        narrative_propagation=0.1,
        graph_snapshot_id="relationship-graph-v1",
        calculator_id="graph-calculator-v1",
    )


def _bundle(**updates: object) -> QuantResearchBundle:
    payload: dict[str, object] = {
        "bundle_id": "quant-research-bundle-v1",
        "as_of": AS_OF,
        "universe_snapshot": _universe(),
        "factor_evaluations": (_factor_evaluation(),),
        "event_study_results": (_event_study_result(),),
        "regime_snapshot": _regime(),
        "behavioral_features": tuple(_behavioral(ticker) for ticker in TICKERS),
        "graph_features": tuple(_graph(ticker) for ticker in TICKERS),
    }
    payload.update(updates)
    return build_hashed(QuantResearchBundle, **payload)


def test_quant_research_bundle_binds_complete_hashed_pit_inputs() -> None:
    bundle = _bundle()

    assert bundle.content_hash == canonical_sha256(bundle.model_dump(exclude={"content_hash"}))
    assert bundle.universe_snapshot.snapshot_id == "universe-demo-v1"
    assert {feature.ticker for feature in bundle.behavioral_features} == set(TICKERS)
    assert {feature.ticker for feature in bundle.graph_features} == set(TICKERS)


def test_quant_research_bundle_rejects_future_factor_evaluation() -> None:
    with pytest.raises(ValueError, match="future or mismatched factor evaluation"):
        _bundle(factor_evaluations=(_factor_evaluation(as_of=AS_OF + timedelta(days=1)),))


def test_quant_research_bundle_rejects_factor_universe_mismatch() -> None:
    with pytest.raises(ValueError, match="bind exactly the bundle universe snapshot"):
        _bundle(factor_evaluations=(_factor_evaluation(universe_snapshot_id="other-universe-v1"),))


def test_quant_research_bundle_rejects_event_study_leakage() -> None:
    with pytest.raises(ValueError, match="event study with leakage"):
        _bundle(event_study_results=(_event_study_result(leakage_detected=True),))


def test_quant_research_bundle_rejects_incomplete_behavioral_ticker_coverage() -> None:
    with pytest.raises(ValueError, match="behavioral features must cover exactly eligible"):
        _bundle(behavioral_features=(_behavioral("AAPL"),))


def test_quant_bundle_rejects_missing_behavioral_or_graph_feature_collections() -> None:
    with pytest.raises(ValueError, match="behavioral_features"):
        _bundle(behavioral_features=())
    with pytest.raises(ValueError, match="graph_features"):
        _bundle(graph_features=())
