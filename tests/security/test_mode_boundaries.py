from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegis.brokers import SimBroker
from aegis.contracts import EvidenceBundle, ResearchCase
from aegis.data import FixtureDataClient, MarketSnapshot
from aegis.fund.models import ResearchDossier
from aegis.fund.run_cycle import run_cycle
from aegis.fund.spec import load_fund_spec
from aegis.harness.capability_broker import CapabilityBroker
from aegis.harness.skill_loader import SkillDefinition, SkillMetadata

ROOT = Path(__file__).resolve().parents[2]


class NetworkProvider:
    network_enabled = True

    def research(self, case: ResearchCase, snapshot: MarketSnapshot) -> ResearchDossier:
        raise AssertionError("network provider must be denied before invocation")


def test_replay_denies_network_provider_before_invocation() -> None:
    data = FixtureDataClient(ROOT / "data/fixtures")
    case = ResearchCase(
        case_id="network-denial",
        tickers=["AAPL"],
        as_of=datetime(2024, 2, 23, 21, 5, tzinfo=UTC),
        horizon_days=20,
        mode="replay",
        research_question="Verify mode denial.",
        created_at=datetime(2024, 2, 23, 21, 5, tzinfo=UTC),
    )
    with pytest.raises(RuntimeError, match="network-capable provider forbidden"):
        run_cycle(
            load_fund_spec(ROOT / "configs/funds/demo-fund.yaml"),
            case,
            SimBroker(100_000),
            data,
            NetworkProvider(),
        )


def test_historical_mode_denies_live_source_capability() -> None:
    metadata = SkillMetadata(
        name="malicious-live-source",
        version="1.0.0",
        owner="test",
        roles=("quant",),
        inputs=("Case",),
        outputs=("Artifact",),
        allowed_tools=("source.agent_reach.search",),
        historical_safe=True,
        memory_read=(),
        memory_write="none",
        model_alias="test",
        max_tool_calls=1,
        max_cost_usd=0.0,
    )
    skill = SkillDefinition(metadata=metadata, body="test", path="test", content_hash="a" * 64)
    broker = CapabilityBroker("historical")
    broker.register("quant", skill)
    decision = broker.decide("quant", skill, "source.agent_reach.search")
    assert not decision.allowed
    assert "disabled by mode" in decision.reason


def test_future_evidence_bundle_is_rejected() -> None:
    from aegis.contracts import EvidenceRecord

    future = datetime(2024, 2, 24, 21, 5, tzinfo=UTC)
    record = EvidenceRecord(
        evidence_id="future",
        source_id="fixture",
        content_hash="a" * 64,
        raw_uri="data/fixtures/prices.parquet",
        entity_ids=["AAPL"],
        document_type="price",
        available_at=future,
        retrieved_at=future,
        source_quality=1.0,
        extraction_confidence=1.0,
        historical_safe=True,
        parser_version="v1",
        extractor_version="v1",
    )
    with pytest.raises(ValueError, match="after bundle as_of"):
        EvidenceBundle(
            case_id="case",
            as_of=datetime(2024, 2, 23, 21, 5, tzinfo=UTC),
            records=[record],
        )
