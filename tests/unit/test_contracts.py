from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from aegis.contracts import (
    AlphaForecast,
    EvidenceRecord,
    Fill,
    LearningCandidate,
    Order,
    PortfolioProposal,
    ResearchArtifact,
    ResearchCase,
    RiskDecision,
    RiskPolicy,
    canonical_json,
    canonical_sha256,
)

UTC_NOW = datetime(2025, 1, 3, 15, 30, tzinfo=UTC)
HASH = "a" * 64


def forecast(**overrides: object) -> AlphaForecast:
    values: dict[str, object] = {
        "forecast_id": "forecast-1",
        "model_name": "demo",
        "ticker": "nvda",
        "as_of": UTC_NOW,
        "horizon_days": 20,
        "expected_excess_return": 0.04,
        "expected_volatility": 0.22,
        "probability_positive": 0.63,
        "confidence": 0.71,
        "uncertainty": 0.29,
        "thesis": "Earnings revisions remain positive.",
        "evidence_ids": ["ev-1"],
    }
    values.update(overrides)
    return AlphaForecast(**values)


def evidence(**overrides: object) -> EvidenceRecord:
    values: dict[str, object] = {
        "evidence_id": "ev-1",
        "source_id": "sec-edgar",
        "document_type": "10-Q",
        "available_at": UTC_NOW,
        "retrieved_at": UTC_NOW,
        "raw_uri": "file:///snapshot/ev-1.json",
        "content_hash": HASH,
        "historical_safe": True,
        "source_quality": 0.95,
        "extraction_confidence": 0.9,
        "parser_version": "pdf-v1",
        "extractor_version": "table-v1",
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def test_models_are_strict_and_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ResearchCase(
            case_id="case-1",
            tickers=["AAPL"],
            as_of=UTC_NOW,
            horizon_days=20,
            mode="replay",
            research_question="What is the expected return?",
            created_at=UTC_NOW,
            extra_field=True,  # type: ignore[call-arg]
        )


def test_tickers_are_normalized_and_mutable_defaults_are_isolated() -> None:
    first = forecast()
    second = forecast(ticker="brk.b", evidence_ids=["ev-2"])
    assert first.ticker == "NVDA"
    assert second.ticker == "BRK.B"
    first.components["quality"] = 0.5
    assert second.components == {}


def test_non_abstained_forecast_requires_evidence_and_numeric_outputs() -> None:
    with pytest.raises(ValidationError, match="evidence IDs"):
        forecast(evidence_ids=[])
    with pytest.raises(ValidationError, match="expected return and volatility"):
        forecast(expected_excess_return=None)


@pytest.mark.parametrize("field,value", [("confidence", 1.01), ("uncertainty", -0.01)])
def test_forecast_probabilities_are_bounded(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        forecast(**{field: value})


def test_abstained_forecast_requires_reason_but_not_evidence() -> None:
    result = forecast(
        abstained=True,
        abstain_reason="Required snapshot was unavailable.",
        evidence_ids=[],
        expected_excess_return=None,
        expected_volatility=None,
    )
    assert result.abstained


def test_evidence_requires_aware_causal_timestamps_and_sha256() -> None:
    with pytest.raises(ValidationError):
        evidence(available_at=datetime(2025, 1, 3, 15, 30))
    with pytest.raises(ValidationError, match="available_at must not be after retrieved_at"):
        evidence(available_at=datetime(2025, 1, 4, tzinfo=UTC))
    with pytest.raises(ValidationError, match="SHA-256"):
        evidence(content_hash="not-a-hash")


def test_canonical_json_and_hash_are_stable_across_mapping_order() -> None:
    left = {"ticker": "NVDA", "values": {"b": 2, "a": 1}}
    right = {"values": {"a": 1, "b": 2}, "ticker": "NVDA"}
    assert canonical_json(left) == '{"ticker":"NVDA","values":{"a":1,"b":2}}'
    assert canonical_sha256(left) == canonical_sha256(right)
    assert len(canonical_sha256(left)) == 64


def test_artifact_validates_hash_shape_and_uses_isolated_defaults() -> None:
    first = ResearchArtifact(
        artifact_id="artifact-1",
        case_id="case-1",
        artifact_type="quant_memo",
        producer_agent="quant",
        model_alias="analysis",
        actual_model="replay",
        content_hash=canonical_sha256({}),
    )
    second = first.model_copy(update={"artifact_id": "artifact-2", "warnings": []})
    first.warnings.append("low coverage")
    assert second.warnings == []


def test_risk_policy_defaults_are_frozen_and_coherent() -> None:
    policy = RiskPolicy(version="demo-v1")
    assert policy.max_position_pct == 0.15
    assert policy.max_gross_exposure == 0.9
    assert not policy.allow_leverage
    assert policy.commission_bps > 0 and policy.slippage_bps > 0
    with pytest.raises(ValidationError):
        policy.max_position_pct = 0.2
    with pytest.raises(ValidationError, match="leverage is disabled"):
        RiskPolicy(version="bad", max_gross_exposure=1.1)


def test_portfolio_and_risk_decision_normalize_weight_tickers() -> None:
    proposal = PortfolioProposal(
        as_of=date(2025, 1, 3),
        target_weights={"nvda": 0.15, "msft": 0.2},
        cash_weight=0.65,
        gross_exposure=0.35,
        turnover=0.1,
        input_hash=HASH,
    )
    decision = RiskDecision(
        approved=True,
        final_weights=proposal.target_weights,
        policy_version="demo-v1",
        input_hash=HASH,
    )
    assert decision.final_weights == {"NVDA": 0.15, "MSFT": 0.2}
    with pytest.raises(ValidationError, match="approved decisions"):
        RiskDecision(
            approved=True,
            final_weights={},
            violations=["turnover"],
            policy_version="demo-v1",
            input_hash=HASH,
        )


def test_execution_contracts_are_simulation_only_and_timezone_aware() -> None:
    order = Order(
        order_id="order-1",
        case_id="case-1",
        ticker="nvda",
        side="buy",
        quantity=10.0,
        reference_price=100.0,
        created_at=UTC_NOW,
        execution_mode="paper",
    )
    fill = Fill(
        fill_id="fill-1",
        order_id=order.order_id,
        ticker=order.ticker,
        side=order.side,
        quantity=10.0,
        price=100.1,
        fee=0.5,
        slippage=1.0,
        filled_at=UTC_NOW,
        execution_mode="paper",
    )
    assert fill.ticker == "NVDA"
    with pytest.raises(ValidationError):
        Order(**{**order.model_dump(), "execution_mode": "live"})


def test_learning_candidate_cannot_mark_itself_promoted() -> None:
    values = {
        "candidate_id": "candidate-1",
        "candidate_type": "skill",
        "proposed_patch": "tighten evidence checks",
        "trigger_case_ids": ["case-1"],
        "evidence_ids": ["ev-1"],
        "diagnosis": "citation coverage was incomplete",
        "expected_improvement": "higher citation coverage",
        "falsifiable_metric": "coverage >= 0.95",
        "minimum_required_delta": 0.05,
        "risk_class": "medium",
        "evaluation_suite_id": "suite-1",
        "proposer_model": "replay",
        "proposer_id": "postmortem-agent",
    }
    candidate = LearningCandidate(**values)
    assert candidate.status == "candidate_only"
    with pytest.raises(ValidationError):
        LearningCandidate(**values, status="promoted")  # type: ignore[arg-type]
