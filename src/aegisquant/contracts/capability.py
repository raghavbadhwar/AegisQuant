"""Capability grants and tool-authorization requests."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import FixedDecimal, Identifier, StrictModel, require_utc


class CapabilityGrant(StrictModel):
    schema_version: Literal[1] = 1
    grant_id: UUID
    tenant_id: Identifier
    agent_id: Identifier
    case_id: UUID
    allowed_tools: tuple[Identifier, ...] = Field(min_length=1)
    allowed_data_scopes: tuple[Identifier, ...]
    allowed_domains: tuple[str, ...]
    may_write_case_artifacts: bool = False
    may_propose_memory: bool = False
    may_propose_skill_changes: bool = False
    may_read_portfolio: bool = False
    may_read_private_research: bool = False
    maximum_tool_calls: int = Field(ge=0, le=1000)
    maximum_cost_usd: FixedDecimal
    issued_at: datetime
    expires_at: datetime
    issued_by_policy: Identifier

    @field_validator("issued_at", "expires_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("maximum_cost_usd")
    @classmethod
    def cost_is_nonnegative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("maximum cost cannot be negative")
        return value

    @field_validator("allowed_tools")
    @classmethod
    def no_wildcard_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if "*" in value or any("shell" in item.lower() for item in value):
            raise ValueError("wildcard and shell capabilities are prohibited")
        if len(set(value)) != len(value):
            raise ValueError("allowed_tools must be unique")
        return value

    @field_validator("allowed_domains")
    @classmethod
    def domains_are_normalized(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.lower().rstrip(".") for item in value)
        if any(not item or "://" in item or "/" in item or item == "*" for item in normalized):
            raise ValueError("allowed_domains must be exact hostnames, not URLs or wildcards")
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed_domains must be unique")
        return normalized

    @model_validator(mode="after")
    def expiry_follows_issue(self) -> "CapabilityGrant":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self


class ToolRequirement(StrictModel):
    schema_version: Literal[1] = 1
    tool_id: Identifier
    requires_data_scope: bool
    requires_destination_domain: bool
    required_grant_flag: (
        Literal[
            "may_write_case_artifacts",
            "may_propose_memory",
            "may_propose_skill_changes",
            "may_read_portfolio",
            "may_read_private_research",
        ]
        | None
    ) = None


class ToolAuthorizationRequest(StrictModel):
    schema_version: Literal[1] = 1
    grant_id: UUID
    tenant_id: Identifier
    agent_id: Identifier
    case_id: UUID
    tool_id: Identifier
    data_scope: Identifier | None = None
    destination_domain: str | None = None
    estimated_cost_usd: FixedDecimal = Decimal(0)

    @field_validator("estimated_cost_usd")
    @classmethod
    def estimated_cost_is_nonnegative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("estimated tool cost cannot be negative")
        return value
