from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from aegisquant.contracts.capability import CapabilityGrant
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
        maximum_cost_usd="0",
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
    tool_id: str = LAST30DAYS_TOOL_ID, url: str = "https://public.example/report"
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
