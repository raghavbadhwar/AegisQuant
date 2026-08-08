"""Paper/simulation-only order and signed hard-risk contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import (
    FixedDecimal,
    Identifier,
    Nonce,
    Sha256Digest,
    StrictModel,
    require_utc,
)


class TradingEnvironment(StrEnum):
    SIM = "SIM"
    PAPER = "PAPER"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    DAY = "DAY"


class OrderIntent(StrictModel):
    schema_version: Literal[1] = 1
    client_order_id: Identifier
    instrument_id: Identifier
    instrument_version: Identifier
    venue_id: Identifier
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce
    quantity: FixedDecimal
    limit_price: FixedDecimal | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("quantity")
    @classmethod
    def quantity_is_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("quantity must be positive")
        return value

    @model_validator(mode="after")
    def price_matches_order_type(self) -> "OrderIntent":
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders cannot include limit_price")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be positive")
        return self


class OrderBundle(StrictModel):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    environment: TradingEnvironment
    legal_entity_id: Identifier
    account_id: Identifier
    broker_id: Identifier
    strategy_id: Identifier
    case_id: UUID
    request_id: UUID
    portfolio_state_sequence: int = Field(ge=0)
    orders: tuple[OrderIntent, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def order_ids_are_unique(self) -> "OrderBundle":
        ids = [order.client_order_id for order in self.orders]
        if len(set(ids)) != len(ids):
            raise ValueError("client_order_id must be unique within a bundle")
        return self


class DecisionOutcome(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    HALT = "HALT"
    COUNTERPROPOSAL = "COUNTERPROPOSAL"


class RuleStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - rule outcome, not a credential
    FAIL = "FAIL"
    WARN = "WARN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RuleResult(StrictModel):
    schema_version: Literal[1] = 1
    rule_id: Identifier
    rule_version: Identifier
    status: RuleStatus
    reason_code: Identifier
    observed: FixedDecimal | None = None
    limit: FixedDecimal | None = None
    unit: Identifier | None = None
    input_ids: tuple[Identifier, ...] = ()


class RiskDecisionPayload(StrictModel):
    schema_version: Literal[1] = 1
    issuer: Literal["aegisquant-hard-risk"] = "aegisquant-hard-risk"
    tenant_id: Identifier
    audience: Literal["aegisquant-execution"] = "aegisquant-execution"
    decision_id: UUID
    request_id: UUID
    case_id: UUID
    issuance_sequence: int = Field(ge=1)
    nonce: Nonce
    environment: TradingEnvironment
    legal_entity_id: Identifier
    account_id: Identifier
    broker_id: Identifier
    strategy_id: Identifier
    outcome: DecisionOutcome
    policy_bundle_digest: Sha256Digest
    policy_epoch: int = Field(ge=1)
    kill_switch_epoch: int = Field(ge=0)
    input_manifest_digest: Sha256Digest
    portfolio_state_sequence: int = Field(ge=0)
    portfolio_snapshot_digest: Sha256Digest
    open_orders_snapshot_digest: Sha256Digest
    market_data_snapshot_digest: Sha256Digest
    reference_data_snapshot_digest: Sha256Digest
    fx_snapshot_digest: Sha256Digest
    model_validation_manifest_digest: Sha256Digest
    requested_order_bundle_digest: Sha256Digest
    approved_order_bundle_digest: Sha256Digest | None = None
    projected_portfolio_digest: Sha256Digest | None = None
    required_human_approval_digest: Sha256Digest | None = None
    rule_results: tuple[RuleResult, ...]
    created_at: datetime
    not_before: datetime
    expires_at: datetime

    @field_validator("created_at", "not_before", "expires_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def executable_outcome_has_exact_bundle(self) -> "RiskDecisionPayload":
        if not self.created_at <= self.not_before < self.expires_at:
            raise ValueError("decision time window is invalid")
        if self.outcome == DecisionOutcome.APPROVE:
            if self.approved_order_bundle_digest is None:
                raise ValueError("APPROVE requires an exact approved order-bundle digest")
            if any(result.status == RuleStatus.FAIL for result in self.rule_results):
                raise ValueError("APPROVE cannot contain a failed rule")
        elif self.approved_order_bundle_digest is not None:
            raise ValueError("non-APPROVE outcomes cannot authorize an order bundle")
        return self


class ProtectedHeader(StrictModel):
    typ: Literal["AQ-RISK-DECISION"] = "AQ-RISK-DECISION"
    schema_version: Literal[1] = 1
    alg: Literal["Ed25519"] = "Ed25519"
    key_id: Identifier


class SignedRiskDecision(StrictModel):
    protected: ProtectedHeader
    payload: RiskDecisionPayload
    signature_b64url: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")


class HumanApprovalPayload(StrictModel):
    schema_version: Literal[1] = 1
    issuer: Literal["aegisquant-approval"] = "aegisquant-approval"
    tenant_id: Identifier
    environment: TradingEnvironment
    approval_id: UUID
    approver_id: Identifier
    approver_role: Identifier
    account_id: Identifier
    approved_order_bundle_digest: Sha256Digest
    policy_epoch: int = Field(ge=1)
    nonce: Nonce
    created_at: datetime
    not_before: datetime
    expires_at: datetime

    @field_validator("created_at", "not_before", "expires_at")
    @classmethod
    def times_are_utc(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def time_window_is_valid(self) -> "HumanApprovalPayload":
        if not self.created_at <= self.not_before < self.expires_at:
            raise ValueError("approval time window is invalid")
        return self
