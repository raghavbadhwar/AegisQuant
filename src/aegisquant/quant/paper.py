"""Deterministic local paper venue. It has no broker or network integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import (
    FixedDecimal,
    Identifier,
    Sha256Digest,
    StrictModel,
    require_utc,
)
from aegisquant.contracts.research import MarketBar, PaperFill, PositionLedgerEntry, SecurityVersion
from aegisquant.contracts.risk import (
    OrderBundle,
    OrderSide,
    OrderType,
    RuleResult,
    SignedHumanApproval,
    SignedRiskDecision,
)
from aegisquant.quant.pit import next_market_bar
from aegisquant.quant.risk import RiskPolicy, evaluate_policy, policy_allows
from aegisquant.quant.timeline import ExecutionTimeline
from aegisquant.security.digests import digest_canonical
from aegisquant.security.risk_signing import ExecutionAuthorizationGate, RiskVerificationContext


class PaperAccountState(StrictModel):
    tenant_id: Identifier
    case_id: UUID
    account_id: Identifier
    cash: FixedDecimal
    positions: tuple[PositionLedgerEntry, ...]
    state_sequence: int = Field(ge=0)

    @field_validator("cash")
    @classmethod
    def nonnegative_cash(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("paper account cash cannot be negative")
        return value

    @model_validator(mode="after")
    def positions_unique(self) -> PaperAccountState:
        ids = [item.instrument_id for item in self.positions]
        if len(set(ids)) != len(ids):
            raise ValueError("paper account contains duplicate positions")
        return self


class PaperExecutionResult(StrictModel):
    fills: tuple[PaperFill, ...]
    unfilled_order_ids: tuple[str, ...]
    account: PaperAccountState
    pre_trade_rules: tuple[RuleResult, ...]
    post_trade_rules: tuple[RuleResult, ...]
    execution_digest: Sha256Digest


class PaperExecutionError(ValueError):
    pass


class DeterministicPaperVenue:
    """Next-bar, open-price fills with deterministic costs and post-trade checks."""

    def __init__(
        self,
        *,
        authorization_gate: ExecutionAuthorizationGate,
        transaction_cost_rate: Decimal = Decimal("0.0005"),
    ) -> None:
        if transaction_cost_rate < 0:
            raise ValueError("transaction_cost_rate must be nonnegative")
        self._authorization_gate = authorization_gate
        self._transaction_cost_rate = transaction_cost_rate

    def execute(
        self,
        bundle: OrderBundle,
        *,
        signed_decision: SignedRiskDecision,
        verification_context: RiskVerificationContext,
        human_approval: SignedHumanApproval | None = None,
        account: PaperAccountState,
        bars: tuple[MarketBar, ...],
        securities: Mapping[str, SecurityVersion],
        policy: RiskPolicy,
        timeline: ExecutionTimeline,
        as_of: datetime,
    ) -> PaperExecutionResult:
        now = require_utc(as_of)
        payload = signed_decision.payload
        if now != timeline.order_submitted_at or timeline.decision_at != payload.created_at:
            raise PaperExecutionError("execution timeline is not bound to the signed decision")
        if (
            account.tenant_id != bundle.tenant_id
            or account.case_id != bundle.case_id
            or account.account_id != bundle.account_id
            or account.tenant_id != verification_context.tenant_id
            or account.account_id != verification_context.account_id
        ):
            raise PaperExecutionError("paper account identity is not bound to the signed decision")
        if account.state_sequence != bundle.portfolio_state_sequence:
            raise PaperExecutionError("paper account sequence does not match order bundle")
        required_instruments = {order.instrument_id for order in bundle.orders} | {
            position.instrument_id for position in account.positions
        }
        latest_bars = {
            instrument_id: max(
                (
                    bar
                    for bar in bars
                    if bar.instrument_id == instrument_id and bar.available_at <= now
                ),
                key=lambda item: (item.available_at, item.observed_at),
            )
            for instrument_id in required_instruments
        }
        actual_bindings = (
            (digest_canonical(account), verification_context.portfolio_snapshot_digest),
            (digest_canonical(()), verification_context.open_orders_snapshot_digest),
            (
                digest_canonical(
                    tuple(latest_bars[instrument_id] for instrument_id in sorted(latest_bars))
                ),
                verification_context.market_data_snapshot_digest,
            ),
            (
                digest_canonical(
                    tuple(securities[instrument_id] for instrument_id in sorted(securities))
                ),
                verification_context.reference_data_snapshot_digest,
            ),
            (digest_canonical({"USD": Decimal(1)}), verification_context.fx_snapshot_digest),
            (digest_canonical(policy), payload.policy_bundle_digest),
        )
        if any(actual != expected for actual, expected in actual_bindings):
            raise PaperExecutionError("execution inputs are not bound to the signed decision")
        if (
            digest_canonical(
                {
                    "bars": bars,
                    "timeline": timeline,
                    "transaction_cost_rate": self._transaction_cost_rate,
                }
            )
            != payload.execution_plan_digest
        ):
            raise PaperExecutionError("future inputs are not bound to the signed execution plan")
        pre_rules = evaluate_policy(
            bundle,
            positions=account.positions,
            bars=latest_bars,
            securities=securities,
            cash=account.cash,
            policy=policy,
            as_of=now,
        )
        if not policy_allows(pre_rules):
            raise PaperExecutionError("pre-trade policy rejected exact order bundle")
        cash = account.cash
        quantities = {entry.instrument_id: entry.quantity for entry in account.positions}
        versions = {entry.instrument_id: entry.instrument_version for entry in account.positions}
        mark_prices = {
            instrument_id: market_bar.close_price
            for instrument_id, market_bar in latest_bars.items()
        }
        mark_sources = dict(latest_bars)
        fills: list[PaperFill] = []
        unfilled: list[str] = []
        for order in bundle.orders:
            bar = next_market_bar(
                bars, instrument_id=order.instrument_id, after=timeline.order_submitted_at
            )
            if bar.tradable_at != timeline.fill_at:
                raise PaperExecutionError("selected fill bar does not match the execution timeline")
            if bar.instrument_version != order.instrument_version:
                raise PaperExecutionError("fill bar version does not match the authorized order")
            security = securities[order.instrument_id]
            if security.valid_from > timeline.fill_at or (
                security.valid_until is not None and security.valid_until <= timeline.fill_at
            ):
                raise PaperExecutionError("fill requires an active security version")
            price = bar.open_price
            limit_ok = (
                order.order_type == OrderType.MARKET
                or (
                    order.side == OrderSide.BUY
                    and order.limit_price is not None
                    and price <= order.limit_price
                )
                or (
                    order.side == OrderSide.SELL
                    and order.limit_price is not None
                    and price >= order.limit_price
                )
            )
            if not limit_ok:
                unfilled.append(order.client_order_id)
                continue
            notional = order.quantity * price
            cost = notional * self._transaction_cost_rate
            quantity = quantities.get(order.instrument_id, Decimal(0))
            if order.side == OrderSide.BUY:
                if cash < notional + cost:
                    raise PaperExecutionError("paper account has insufficient cash")
                cash -= notional + cost
                quantities[order.instrument_id] = quantity + order.quantity
            else:
                if quantity < order.quantity:
                    raise PaperExecutionError("paper venue cannot create a short position")
                cash += notional - cost
                quantities[order.instrument_id] = quantity - order.quantity
            versions[order.instrument_id] = order.instrument_version
            mark_prices[order.instrument_id] = price
            mark_sources[order.instrument_id] = bar
            fills.append(
                PaperFill(
                    client_order_id=order.client_order_id,
                    instrument_id=order.instrument_id,
                    instrument_version=order.instrument_version,
                    side=order.side,
                    quantity=order.quantity,
                    price=price,
                    transaction_cost=cost,
                    filled_at=bar.tradable_at,
                    market_data_digest=digest_canonical(bar),
                )
            )
        for instrument_id, quantity in quantities.items():
            if quantity <= 0:
                continue
            current_mark = max(
                (
                    item
                    for item in bars
                    if item.instrument_id == instrument_id
                    and item.instrument_version == versions[instrument_id]
                    and item.available_at <= timeline.fill_at
                    and item.tradable_at <= timeline.fill_at
                ),
                key=lambda item: (item.available_at, item.observed_at, item.tradable_at),
                default=None,
            )
            if current_mark is None:
                raise PaperExecutionError("post-trade position requires a current bound market bar")
            mark_prices[instrument_id] = current_mark.close_price
            mark_sources[instrument_id] = current_mark
        positions = tuple(
            PositionLedgerEntry(
                instrument_id=instrument_id,
                instrument_version=versions[instrument_id],
                quantity=quantity,
                mark_price=mark_prices[instrument_id],
                marked_at=timeline.fill_at,
                source_digest=digest_canonical(mark_sources[instrument_id]),
            )
            for instrument_id, quantity in sorted(quantities.items())
            if quantity > 0
        )
        post_bundle = bundle.model_copy(
            update={"portfolio_state_sequence": account.state_sequence + 1}
        )
        post_rules = evaluate_policy(
            post_bundle,
            positions=positions,
            bars=mark_sources,
            securities=securities,
            cash=cash,
            policy=policy,
            as_of=timeline.fill_at,
            include_orders=False,
        )
        if not policy_allows(post_rules):
            raise PaperExecutionError("post-trade policy rejected projected account")
        updated = PaperAccountState(
            tenant_id=account.tenant_id,
            case_id=account.case_id,
            account_id=account.account_id,
            cash=cash,
            positions=positions,
            state_sequence=account.state_sequence + 1,
        )
        result = PaperExecutionResult(
            fills=tuple(fills),
            unfilled_order_ids=tuple(unfilled),
            account=updated,
            pre_trade_rules=pre_rules,
            post_trade_rules=post_rules,
            execution_digest=digest_canonical(
                {
                    "bundle": bundle,
                    "fills": tuple(fills),
                    "account": updated,
                    "unfilled": tuple(unfilled),
                }
            ),
        )
        self._authorization_gate.authorize_once(
            signed_decision,
            bundle,
            verification_context,
            now=timeline.order_submitted_at,
            human_approval=human_approval,
        )
        return result


def reconcile_execution(initial: PaperAccountState, result: PaperExecutionResult) -> bool:
    """Independently recompute cash and positions from immutable paper fills."""

    cash = initial.cash
    quantities = {entry.instrument_id: entry.quantity for entry in initial.positions}
    for fill in result.fills:
        notional = fill.quantity * fill.price
        quantity = quantities.get(fill.instrument_id, Decimal(0))
        if fill.side == OrderSide.BUY:
            cash -= notional + fill.transaction_cost
            quantities[fill.instrument_id] = quantity + fill.quantity
        else:
            cash += notional - fill.transaction_cost
            quantities[fill.instrument_id] = quantity - fill.quantity
    actual = {entry.instrument_id: entry.quantity for entry in result.account.positions}
    expected = {
        instrument_id: quantity for instrument_id, quantity in quantities.items() if quantity > 0
    }
    return (
        cash == result.account.cash
        and actual == expected
        and result.account.tenant_id == initial.tenant_id
        and result.account.case_id == initial.case_id
        and result.account.account_id == initial.account_id
        and result.account.state_sequence == initial.state_sequence + 1
        and all(quantity >= 0 for quantity in quantities.values())
    )
