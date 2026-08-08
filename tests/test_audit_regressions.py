from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from aegisquant.case_ledger.store import IdempotencyConflict, InMemoryCaseEventStore
from aegisquant.contracts.artifact import (
    ArtifactEnvelope,
    BlobRef,
    DataClassification,
    ProducerStamp,
)
from aegisquant.contracts.capability import ToolAuthorizationRequest
from aegisquant.contracts.case import InvestmentCaseRequest
from aegisquant.security.digests import (
    case_event_chain_digest,
    case_event_content_canonical,
    sha256_bytes,
)
from aegisquant.workflows.contracts import (
    FixtureArtifactRef,
    RegisteredEvidenceRef,
    ResearchCaseWorkflowInput,
    ResearchCaseWorkflowResult,
    SnapshotRef,
)

D = "sha256:" + "a" * 64


def test_runtime_rejects_numeric_string_that_schema_declares_integer() -> None:
    raw = b"""{
      "strategy_id": "control",
      "instrument_ids": ["SPY"],
      "analysis_time": "2026-01-01T00:00:00Z",
      "forecast_horizon_days": "20",
      "requested_mode": "standard",
      "maximum_cost_usd": "1.00",
      "purpose": "research"
    }"""
    with pytest.raises(ValidationError, match="forecast_horizon_days"):
        InvestmentCaseRequest.model_validate_json(raw)


def test_idempotency_distinguishes_decimal_from_string_payload() -> None:
    store = InMemoryCaseEventStore()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = dict(
        tenant_id="tenant-a",
        case_id=uuid4(),
        event_type="TEST",
        occurred_at=now,
        recorded_at=now,
        actor_id="test",
        correlation_id=uuid4(),
        idempotency_key="typed-value",
    )
    store.append(**base, payload={"value": Decimal("1")})
    with pytest.raises(IdempotencyConflict):
        store.append(**base, payload={"value": "1"})


def test_workflow_rejects_cross_tenant_blob_reference() -> None:
    blob = BlobRef(
        tenant_id="tenant-b",
        uri="file:///fixture",
        content_digest=D,
        size_bytes=1,
        media_type="text/plain",
        retention_class="test",
    )
    with pytest.raises(ValidationError, match="workflow tenant"):
        ResearchCaseWorkflowInput(
            tenant_id="tenant-a",
            case_id=uuid4(),
            data_snapshot_id="snapshot-1",
            fixture_evidence=blob,
        )


def test_artifact_rejects_cross_tenant_payload_reference() -> None:
    blob = BlobRef(
        tenant_id="tenant-b",
        uri="file:///fixture",
        content_digest=D,
        size_bytes=1,
        media_type="text/plain",
        retention_class="test",
    )
    with pytest.raises(ValidationError, match="artifact tenant"):
        ArtifactEnvelope(
            tenant_id="tenant-a",
            artifact_id=uuid4(),
            case_id=uuid4(),
            schema_id="fixture",
            artifact_schema_version="1",
            payload=blob,
            payload_digest=D,
            producer=ProducerStamp(
                agent_id="fixture-agent",
                agent_version="1",
                prompt_bundle_digest=D,
                skill_bundle_digest=D,
            ),
            data_snapshot_id="snapshot-1",
            classification=DataClassification.PUBLIC,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            idempotency_key="artifact-1",
        )


def test_negative_tool_cost_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot be negative"):
        ToolAuthorizationRequest(
            grant_id=uuid4(),
            tenant_id="tenant-a",
            agent_id="agent-a",
            case_id=uuid4(),
            tool_id="filings.retrieve",
            estimated_cost_usd="-1",
        )


def test_workflow_result_rejects_cross_tenant_activity_references() -> None:
    with pytest.raises(ValidationError, match="result tenant"):
        ResearchCaseWorkflowResult(
            tenant_id="tenant-a",
            case_id=uuid4(),
            snapshot=SnapshotRef(tenant_id="tenant-b", snapshot_id="snapshot", manifest_digest=D),
            evidence=RegisteredEvidenceRef(
                tenant_id="tenant-b", evidence_id=uuid4(), evidence_digest=D
            ),
            artifact=FixtureArtifactRef(
                tenant_id="tenant-b", artifact_id=uuid4(), artifact_digest=D
            ),
        )


def test_case_event_chain_golden_digest_matches_postgres_fixture() -> None:
    content = case_event_content_canonical(
        schema_version=1,
        tenant_id="tenant-a",
        case_id=UUID("00000000-0000-0000-0000-000000000001"),
        event_id=UUID("00000000-0000-0000-0000-000000000010"),
        sequence=1,
        event_type="CASE_CREATED",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        actor_id="test",
        correlation_id=UUID("00000000-0000-0000-0000-000000000011"),
        causation_id=None,
        idempotency_key="event-1",
        payload_canonical='["object",[]]',
    )
    assert content == (
        "AEGISQUANT_CASE_EVENT_CONTENT_V11:18:tenant-a36:00000000-0000-0000-0000-"
        "00000000000136:00000000-0000-0000-0000-0000000000101:112:CASE_CREATED27:"
        "2026-01-01T00:00:00.000000Z27:2026-01-01T00:00:00.000000Z4:test36:"
        '00000000-0000-0000-0000-0000000000116:<NULL>7:event-113:["object",[]]'
    )
    content_digest = sha256_bytes(content.encode())
    assert content_digest == (
        "sha256:782684f277d1f4ebb76c152d18fa42fcc657a8a53d3d435eb49489723de4a158"
    )
    assert case_event_chain_digest(None, content_digest) == (
        "sha256:46b856958022ff7f82ee1478ad6825a04f4f49971077aa856229a0365a82b374"
    )
