from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import pytest

from aegisquant.contracts.capability import CapabilityGrant
from aegisquant.contracts.research import DataSnapshot
from aegisquant.intelligence.last30days_adapter import (
    Last30DaysAdapterError,
    record_last30days_capture,
)
from aegisquant.intelligence.source_gateway import (
    LAST30DAYS_TOOL_ID,
    SCRAPLING_TOOL_ID,
    SourceGateway,
    SourceGatewayError,
    SourceRequest,
    TransportResponse,
    source_tool_requirements,
)
from aegisquant.security.capability_broker import AuthorizationDenied, CapabilityBroker


class FakeTransport:
    def __init__(self, response: TransportResponse) -> None:
        self.response = response
        self.calls: list[str] = []

    def get(self, url: str, *, maximum_response_bytes: int) -> TransportResponse:
        assert maximum_response_bytes == 32
        self.calls.append(url)
        return self.response


def gateway(
    *, domain: str = "public.example"
) -> tuple[SourceGateway, FakeTransport, CapabilityGrant]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = CapabilityGrant(
        grant_id=uuid4(),
        tenant_id="tenant-a",
        agent_id="research-agent",
        case_id=uuid4(),
        allowed_tools=(LAST30DAYS_TOOL_ID, SCRAPLING_TOOL_ID),
        allowed_data_scopes=("public-research",),
        allowed_domains=(domain,),
        maximum_tool_calls=2,
        maximum_cost_usd=Decimal("0"),
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=1),
        issued_by_policy="source-policy-v1",
    )
    transport = FakeTransport(TransportResponse("https://public.example/report", 200, b"safe"))
    broker = CapabilityBroker(
        (grant,),
        source_tool_requirements(),
    )
    return SourceGateway(broker, transport), transport, grant


def request(
    tool_id: Literal["last30days-public-research", "scrapling-public-fetch"] = LAST30DAYS_TOOL_ID,
    url: str = "https://public.example/report",
) -> SourceRequest:
    return SourceRequest(
        tenant_id="tenant-a",
        case_id=CASE_ID,
        tool_id=tool_id,
        url=url,
        data_scope="public-research",
        maximum_response_bytes=32,
    )


CASE_ID = uuid4()


def snapshot(*, tenant_id: str, case_id: UUID) -> DataSnapshot:
    return DataSnapshot(
        tenant_id=tenant_id,
        case_id=case_id,
        snapshot_id="snapshot-v1",
        manifest_digest="sha256:" + "a" * 64,
        content_digest="sha256:" + "b" * 64,
        as_of=datetime(2026, 1, 1, tzinfo=UTC),
        frozen_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_gateway_authorizes_last30days_and_scrapling_before_fetching() -> None:
    source_gateway, transport, grant = gateway()
    source_request = request(SCRAPLING_TOOL_ID)
    source_request = source_request.model_copy(update={"case_id": grant.case_id})
    receipt, body = source_gateway.fetch(
        source_request,
        grant_id=grant.grant_id,
        agent_id="research-agent",
        authenticated_tenant_id="tenant-a",
        authenticated_agent_id="research-agent",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert body == b"safe"
    assert (
        receipt.content_digest
        == "sha256:" + "8b3369944dd2a3fab39e32d1aeb1f763946a458ae3e6368a46432adc8f3a0860"
    )
    assert transport.calls == ["https://public.example/report"]


@pytest.mark.parametrize(
    "url",
    (
        "http://public.example/report",
        "https://127.0.0.1/report",
        "https://user@public.example/report",
    ),
)
def test_gateway_rejects_unsafe_urls_before_transport(url: str) -> None:
    source_gateway, transport, grant = gateway()
    source_request = request(url=url).model_copy(update={"case_id": grant.case_id})
    with pytest.raises(SourceGatewayError):
        source_gateway.fetch(
            source_request,
            grant_id=grant.grant_id,
            agent_id="research-agent",
            authenticated_tenant_id="tenant-a",
            authenticated_agent_id="research-agent",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert transport.calls == []


def test_gateway_rejects_unapproved_domain_before_transport() -> None:
    source_gateway, transport, grant = gateway()
    source_request = request("last30days-public-research", "https://other.example/report")
    source_request = source_request.model_copy(update={"case_id": grant.case_id})
    with pytest.raises(AuthorizationDenied):
        source_gateway.fetch(
            source_request,
            grant_id=grant.grant_id,
            agent_id="research-agent",
            authenticated_tenant_id="tenant-a",
            authenticated_agent_id="research-agent",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert transport.calls == []


def test_gateway_rejects_cross_host_redirect_after_fetch() -> None:
    source_gateway, transport, grant = gateway()
    transport.response = TransportResponse("https://other.example/report", 200, b"safe")
    source_request = request().model_copy(update={"case_id": grant.case_id})
    with pytest.raises(SourceGatewayError, match="redirect"):
        source_gateway.fetch(
            source_request,
            grant_id=grant.grant_id,
            agent_id="research-agent",
            authenticated_tenant_id="tenant-a",
            authenticated_agent_id="research-agent",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_last30days_record_binds_gateway_capture_to_snapshot() -> None:
    source_gateway, _, grant = gateway()
    source_request = request().model_copy(update={"case_id": grant.case_id})
    receipt, body = source_gateway.fetch(
        source_request,
        grant_id=grant.grant_id,
        agent_id="research-agent",
        authenticated_tenant_id="tenant-a",
        authenticated_agent_id="research-agent",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    record = record_last30days_capture(
        receipt,
        body,
        snapshot=snapshot(tenant_id=receipt.tenant_id, case_id=receipt.case_id),
    )
    assert record.tenant_id == receipt.tenant_id
    assert record.case_id == receipt.case_id
    assert record.source_content_digest == receipt.content_digest
    assert record.available_at == receipt.captured_at


def test_last30days_record_rejects_wrong_tool_and_tampered_body() -> None:
    source_gateway, _, grant = gateway()
    scrapling_request = request(SCRAPLING_TOOL_ID).model_copy(update={"case_id": grant.case_id})
    receipt, _ = source_gateway.fetch(
        scrapling_request,
        grant_id=grant.grant_id,
        agent_id="research-agent",
        authenticated_tenant_id="tenant-a",
        authenticated_agent_id="research-agent",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(Last30DaysAdapterError, match="Last30Days source receipt"):
        record_last30days_capture(
            receipt,
            b"safe",
            snapshot=snapshot(tenant_id=receipt.tenant_id, case_id=receipt.case_id),
        )
    last30days_receipt = receipt.model_copy(update={"tool_id": LAST30DAYS_TOOL_ID})
    with pytest.raises(Last30DaysAdapterError, match="does not match"):
        record_last30days_capture(
            last30days_receipt,
            b"tampered",
            snapshot=snapshot(tenant_id=receipt.tenant_id, case_id=receipt.case_id),
        )
    with pytest.raises(Last30DaysAdapterError, match="share tenant and case"):
        record_last30days_capture(
            last30days_receipt,
            b"safe",
            snapshot=snapshot(tenant_id="tenant-b", case_id=receipt.case_id),
        )
