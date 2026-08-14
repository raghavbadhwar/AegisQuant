"""Capability-gated public-web ingress for approved research adapters.

The transport is injected.  Deployments must provide an egress proxy that also
resolves DNS and blocks non-public addresses; this reference boundary never
lets the Last30Days or Scrapling processes make direct workflow calls.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from aegisquant.contracts.capability import ToolAuthorizationRequest, ToolRequirement
from aegisquant.contracts.common import Identifier, StrictModel, require_utc
from aegisquant.contracts.research import SourceReceipt
from aegisquant.security.capability_broker import CapabilityBroker
from aegisquant.security.digests import sha256_bytes

LAST30DAYS_TOOL_ID: Literal["last30days-public-research"] = "last30days-public-research"
SCRAPLING_TOOL_ID: Literal["scrapling-public-fetch"] = "scrapling-public-fetch"


def source_tool_requirements() -> tuple[ToolRequirement, ...]:
    """The only runtime capability names exposed by the public-source boundary."""

    return tuple(
        ToolRequirement(
            tool_id=tool_id,
            requires_data_scope=True,
            requires_destination_domain=True,
        )
        for tool_id in (LAST30DAYS_TOOL_ID, SCRAPLING_TOOL_ID)
    )


class SourceGatewayError(ValueError):
    pass


class SourceRequest(StrictModel):
    tenant_id: Identifier
    case_id: UUID
    tool_id: Literal["last30days-public-research", "scrapling-public-fetch"]
    url: str
    data_scope: Identifier
    maximum_response_bytes: int = 1_000_000


@dataclass(frozen=True)
class TransportResponse:
    final_url: str
    status_code: int
    body: bytes


class PublicHttpTransport(Protocol):
    def get(self, url: str, *, maximum_response_bytes: int) -> TransportResponse: ...


def _public_https_host(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or parsed.port not in (None, 443)
    ):
        raise SourceGatewayError(
            "source URL must be public HTTPS without credentials or custom port"
        )
    host = parsed.hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if not address.is_global:
        raise SourceGatewayError("source URL must not target a non-public address")
    return host


class SourceGateway:
    """Authorize and validate public retrieval before invoking an egress transport."""

    def __init__(self, broker: CapabilityBroker, transport: PublicHttpTransport) -> None:
        self._broker = broker
        self._transport = transport

    def fetch(
        self,
        request: SourceRequest,
        *,
        grant_id: UUID,
        agent_id: str,
        authenticated_tenant_id: str,
        authenticated_agent_id: str,
        now: datetime,
    ) -> tuple[SourceReceipt, bytes]:
        host = _public_https_host(request.url)
        self._broker.authorize(
            ToolAuthorizationRequest(
                grant_id=grant_id,
                tenant_id=request.tenant_id,
                agent_id=agent_id,
                case_id=request.case_id,
                tool_id=request.tool_id,
                data_scope=request.data_scope,
                destination_domain=host,
            ),
            authenticated_tenant_id=authenticated_tenant_id,
            authenticated_agent_id=authenticated_agent_id,
            now=now,
        )
        response = self._transport.get(
            request.url, maximum_response_bytes=request.maximum_response_bytes
        )
        if _public_https_host(response.final_url) != host:
            raise SourceGatewayError("cross-host redirects are prohibited")
        if response.status_code != 200:
            raise SourceGatewayError("source response was not successful")
        if len(response.body) > request.maximum_response_bytes:
            raise SourceGatewayError("source response exceeded the approved limit")
        captured_at = require_utc(now)
        return (
            SourceReceipt(
                tenant_id=request.tenant_id,
                case_id=request.case_id,
                tool_id=request.tool_id,
                url=response.final_url,
                content_digest=sha256_bytes(response.body),
                captured_at=captured_at,
            ),
            response.body,
        )
