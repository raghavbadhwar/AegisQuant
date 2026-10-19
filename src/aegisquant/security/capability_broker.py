"""Deny-by-default capability reference monitor core."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from threading import Lock
from uuid import UUID

from aegisquant.contracts.capability import (
    CapabilityGrant,
    ToolAuthorizationRequest,
    ToolRequirement,
)
from aegisquant.contracts.common import require_utc


class DenialReason(StrEnum):
    UNKNOWN_GRANT = "UNKNOWN_GRANT"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    EXPIRED = "EXPIRED"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    SCOPE_NOT_ALLOWED = "SCOPE_NOT_ALLOWED"
    DOMAIN_NOT_ALLOWED = "DOMAIN_NOT_ALLOWED"
    CALL_BUDGET_EXCEEDED = "CALL_BUDGET_EXCEEDED"
    COST_BUDGET_EXCEEDED = "COST_BUDGET_EXCEEDED"
    REVOKED = "REVOKED"
    MISSING_REQUIRED_CONTEXT = "MISSING_REQUIRED_CONTEXT"
    PRIVILEGE_NOT_ALLOWED = "PRIVILEGE_NOT_ALLOWED"


class AuthorizationDenied(PermissionError):
    def __init__(self, reason: DenialReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


@dataclass(frozen=True)
class AuthorizationReceipt:
    grant_id: UUID
    call_number: int
    cumulative_cost_usd: Decimal


@dataclass
class _Usage:
    calls: int = 0
    cost_usd: Decimal = Decimal(0)


class CapabilityBroker:
    """In-memory reference monitor used for contract tests and local M0.

    Production storage must make check-and-consume atomic and must derive the
    tenant/subject/case from authenticated context, not model-supplied input.
    """

    def __init__(
        self,
        grants: tuple[CapabilityGrant, ...] = (),
        tool_requirements: tuple[ToolRequirement, ...] = (),
    ) -> None:
        self._grants = {grant.grant_id: grant for grant in grants}
        self._tool_requirements = {
            requirement.tool_id: requirement for requirement in tool_requirements
        }
        self._usage: dict[UUID, _Usage] = {}
        self._revoked: set[UUID] = set()
        self._lock = Lock()

    def add_grant(self, grant: CapabilityGrant) -> None:
        with self._lock:
            if grant.grant_id in self._grants:
                raise ValueError("grant already exists; grants are immutable")
            self._grants[grant.grant_id] = grant

    def revoke(self, grant_id: UUID) -> None:
        with self._lock:
            if grant_id not in self._grants:
                raise ValueError("cannot revoke an unknown grant")
            self._revoked.add(grant_id)

    def authorize(
        self,
        request: ToolAuthorizationRequest,
        *,
        authenticated_tenant_id: str,
        authenticated_agent_id: str,
        now: datetime,
    ) -> AuthorizationReceipt:
        now = require_utc(now)
        if request.estimated_cost_usd < 0:
            raise AuthorizationDenied(DenialReason.COST_BUDGET_EXCEEDED)
        with self._lock:
            grant = self._grants.get(request.grant_id)
            if grant is None:
                raise AuthorizationDenied(DenialReason.UNKNOWN_GRANT)
            if grant.grant_id in self._revoked:
                raise AuthorizationDenied(DenialReason.REVOKED)
            if (
                request.tenant_id != authenticated_tenant_id
                or request.agent_id != authenticated_agent_id
                or request.tenant_id != grant.tenant_id
                or request.agent_id != grant.agent_id
                or request.case_id != grant.case_id
            ):
                raise AuthorizationDenied(DenialReason.IDENTITY_MISMATCH)
            if now < grant.issued_at or now >= grant.expires_at:
                raise AuthorizationDenied(DenialReason.EXPIRED)
            requirement = self._tool_requirements.get(request.tool_id)
            if request.tool_id not in grant.allowed_tools or requirement is None:
                raise AuthorizationDenied(DenialReason.TOOL_NOT_ALLOWED)
            if requirement.requires_data_scope and request.data_scope is None:
                raise AuthorizationDenied(DenialReason.MISSING_REQUIRED_CONTEXT)
            if requirement.requires_destination_domain and request.destination_domain is None:
                raise AuthorizationDenied(DenialReason.MISSING_REQUIRED_CONTEXT)
            if (
                request.data_scope is not None
                and request.data_scope not in grant.allowed_data_scopes
            ):
                raise AuthorizationDenied(DenialReason.SCOPE_NOT_ALLOWED)
            if request.destination_domain is not None:
                domain = request.destination_domain.lower().rstrip(".")
                if domain not in grant.allowed_domains:
                    raise AuthorizationDenied(DenialReason.DOMAIN_NOT_ALLOWED)
            if requirement.required_grant_flag is not None and not getattr(
                grant, requirement.required_grant_flag
            ):
                raise AuthorizationDenied(DenialReason.PRIVILEGE_NOT_ALLOWED)
            usage = self._usage.setdefault(grant.grant_id, _Usage())
            if usage.calls + 1 > grant.maximum_tool_calls:
                raise AuthorizationDenied(DenialReason.CALL_BUDGET_EXCEEDED)
            new_cost = usage.cost_usd + request.estimated_cost_usd
            if new_cost > grant.maximum_cost_usd:
                raise AuthorizationDenied(DenialReason.COST_BUDGET_EXCEEDED)
            usage.calls += 1
            usage.cost_usd = new_cost
            return AuthorizationReceipt(grant.grant_id, usage.calls, new_cost)
