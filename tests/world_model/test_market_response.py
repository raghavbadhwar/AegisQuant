from datetime import UTC, datetime

import pytest

from aegis.world_model.market_response import (
    DeterministicInvestorResponseAdapter,
    InvestorArchetype,
    InvestorArchetypeState,
    MarketResponseRequest,
    MarketResponseStatus,
)

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _state(archetype: InvestorArchetype) -> InvestorArchetypeState:
    return InvestorArchetypeState(
        archetype_id=f"{archetype.value}-v1",
        archetype=archetype,
        capital_share=0.2,
        information_set=("engineering-scenario",),
        horizon_days=20,
        risk_budget=0.1,
        leverage=1.0,
        liquidity_need=0.2,
        current_positioning=0.0,
        demand_sensitivity=0.5,
        continuation_probability=0.6,
        reversal_probability=0.2,
        volatility_sensitivity=0.1,
        liquidity_sensitivity=-0.1,
    ).sealed()


def _request(archetype: InvestorArchetype) -> MarketResponseRequest:
    return MarketResponseRequest(
        request_id=f"response-{archetype.value}",
        scenario_run_id="candidate-scenario-run-v1",
        scenario_run_hash="a" * 64,
        as_of=NOW,
        regime_id="normal",
        candidate_event_signal=-0.4,
        archetype_state=_state(archetype),
        assumption_ids=("candidate-archetype-parameter",),
    ).sealed()


def test_deterministic_investor_response_is_candidate_only_and_repeatable() -> None:
    request = _request(InvestorArchetype.FUNDAMENTAL_LONG_ONLY)
    adapter = DeterministicInvestorResponseAdapter()

    first = adapter.respond(request)
    repeated = adapter.respond(request)

    assert first.model_dump_json() == repeated.model_dump_json()
    assert first.status == MarketResponseStatus.CANDIDATE_RESPONSE
    assert first.calibration_status == "not_calibrated"
    assert first.expected_demand_imbalance == -0.4 * 0.2 * 0.5
    assert first.authority == "candidate_only"
    assert first.content_hash


def test_deterministic_investor_response_abstains_for_an_unsupported_archetype() -> None:
    outcome = DeterministicInvestorResponseAdapter().respond(
        _request(InvestorArchetype.RETAIL_ATTENTION)
    )

    assert outcome.status == MarketResponseStatus.ABSTAINED
    assert outcome.reason == "unsupported_archetype"
    assert outcome.expected_demand_imbalance is None
    assert outcome.flow_timing_days is None


def test_deterministic_investor_response_abstains_for_an_unsupported_regime() -> None:
    request = (
        _request(InvestorArchetype.FUNDAMENTAL_LONG_ONLY)
        .model_copy(update={"regime_id": "unsupported-regime", "content_hash": None})
        .sealed()
    )

    outcome = DeterministicInvestorResponseAdapter().respond(request)

    assert outcome.status == MarketResponseStatus.ABSTAINED
    assert outcome.reason == "unsupported_regime"


def test_investor_state_rejects_non_candidate_authority() -> None:
    payload = _state(InvestorArchetype.FUNDAMENTAL_LONG_ONLY).model_dump(
        mode="json", exclude={"content_hash"}
    )
    payload["authority"] = "llm_population"

    with pytest.raises(ValueError, match="candidate_only"):
        InvestorArchetypeState.model_validate(payload)
