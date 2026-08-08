from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from aegisquant.contracts.capability import (
    CapabilityGrant,
    ToolAuthorizationRequest,
    ToolRequirement,
)
from aegisquant.security.capability_broker import (
    AuthorizationDenied,
    CapabilityBroker,
    DenialReason,
)


def make_grant(now: datetime) -> CapabilityGrant:
    return CapabilityGrant(
        grant_id=uuid4(),
        tenant_id="tenant-a",
        agent_id="fundamental-agent",
        case_id=uuid4(),
        allowed_tools=("filings.retrieve",),
        allowed_data_scopes=("public_filings",),
        allowed_domains=("sec.gov",),
        maximum_tool_calls=1,
        maximum_cost_usd="0.10",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
        issued_by_policy="capability-policy-1",
    )


def make_broker(grant: CapabilityGrant) -> CapabilityBroker:
    return CapabilityBroker(
        (grant,),
        (
            ToolRequirement(
                tool_id="filings.retrieve",
                requires_data_scope=True,
                requires_destination_domain=True,
            ),
        ),
    )


def test_capability_is_completely_scoped_and_budgeted() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = make_grant(now)
    broker = make_broker(grant)
    request = ToolAuthorizationRequest(
        grant_id=grant.grant_id,
        tenant_id=grant.tenant_id,
        agent_id=grant.agent_id,
        case_id=grant.case_id,
        tool_id="filings.retrieve",
        data_scope="public_filings",
        destination_domain="sec.gov",
        estimated_cost_usd="0.01",
    )
    receipt = broker.authorize(
        request,
        authenticated_tenant_id="tenant-a",
        authenticated_agent_id="fundamental-agent",
        now=now,
    )
    assert receipt.call_number == 1
    with pytest.raises(AuthorizationDenied) as exc:
        broker.authorize(
            request,
            authenticated_tenant_id="tenant-a",
            authenticated_agent_id="fundamental-agent",
            now=now,
        )
    assert exc.value.reason == DenialReason.CALL_BUDGET_EXCEEDED


def test_cross_tenant_request_is_denied() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = make_grant(now)
    broker = make_broker(grant)
    request = ToolAuthorizationRequest(
        grant_id=grant.grant_id,
        tenant_id="tenant-b",
        agent_id=grant.agent_id,
        case_id=grant.case_id,
        tool_id="filings.retrieve",
        data_scope="public_filings",
        destination_domain="sec.gov",
    )
    with pytest.raises(AuthorizationDenied) as exc:
        broker.authorize(
            request,
            authenticated_tenant_id="tenant-b",
            authenticated_agent_id="fundamental-agent",
            now=now,
        )
    assert exc.value.reason == DenialReason.IDENTITY_MISMATCH


def test_revoked_grant_fails_before_tool_call() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = make_grant(now)
    broker = make_broker(grant)
    broker.revoke(grant.grant_id)
    request = ToolAuthorizationRequest(
        grant_id=grant.grant_id,
        tenant_id=grant.tenant_id,
        agent_id=grant.agent_id,
        case_id=grant.case_id,
        tool_id="filings.retrieve",
        data_scope="public_filings",
        destination_domain="sec.gov",
    )
    with pytest.raises(AuthorizationDenied) as exc:
        broker.authorize(
            request,
            authenticated_tenant_id="tenant-a",
            authenticated_agent_id="fundamental-agent",
            now=now,
        )
    assert exc.value.reason == DenialReason.REVOKED


def test_required_scope_and_domain_cannot_be_omitted() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = make_grant(now)
    broker = make_broker(grant)
    request = ToolAuthorizationRequest(
        grant_id=grant.grant_id,
        tenant_id=grant.tenant_id,
        agent_id=grant.agent_id,
        case_id=grant.case_id,
        tool_id="filings.retrieve",
    )
    with pytest.raises(AuthorizationDenied) as exc:
        broker.authorize(
            request,
            authenticated_tenant_id="tenant-a",
            authenticated_agent_id="fundamental-agent",
            now=now,
        )
    assert exc.value.reason == DenialReason.MISSING_REQUIRED_CONTEXT


def test_declared_privilege_bit_is_enforced() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = make_grant(now).model_copy(
        update={"allowed_tools": ("memory.propose",), "may_propose_memory": False}
    )
    broker = CapabilityBroker(
        (grant,),
        (
            ToolRequirement(
                tool_id="memory.propose",
                requires_data_scope=False,
                requires_destination_domain=False,
                required_grant_flag="may_propose_memory",
            ),
        ),
    )
    request = ToolAuthorizationRequest(
        grant_id=grant.grant_id,
        tenant_id=grant.tenant_id,
        agent_id=grant.agent_id,
        case_id=grant.case_id,
        tool_id="memory.propose",
    )
    with pytest.raises(AuthorizationDenied) as exc:
        broker.authorize(
            request,
            authenticated_tenant_id="tenant-a",
            authenticated_agent_id="fundamental-agent",
            now=now,
        )
    assert exc.value.reason == DenialReason.PRIVILEGE_NOT_ALLOWED


def test_broker_rejects_negative_cost_even_if_contract_validation_is_bypassed() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    grant = make_grant(now)
    broker = make_broker(grant)
    request = ToolAuthorizationRequest.model_construct(
        grant_id=grant.grant_id,
        tenant_id=grant.tenant_id,
        agent_id=grant.agent_id,
        case_id=grant.case_id,
        tool_id="filings.retrieve",
        data_scope="public_filings",
        destination_domain="sec.gov",
        estimated_cost_usd=Decimal("-1"),
    )
    with pytest.raises(AuthorizationDenied) as exc:
        broker.authorize(
            request,
            authenticated_tenant_id="tenant-a",
            authenticated_agent_id="fundamental-agent",
            now=now,
        )
    assert exc.value.reason == DenialReason.COST_BUDGET_EXCEEDED
