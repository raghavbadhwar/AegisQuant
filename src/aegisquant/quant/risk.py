"""Deterministic policy-as-data checks for long-only paper orders."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from aegisquant.contracts.common import FixedDecimal, Identifier, StrictModel, require_utc
from aegisquant.contracts.research import MarketBar, PositionLedgerEntry, SecurityVersion
from aegisquant.contracts.risk import OrderBundle, OrderSide, RuleResult, RuleStatus


class RiskPolicy(StrictModel):
    schema_version: int = Field(default=1, ge=1)
    policy_id: Identifier
    policy_version: Identifier
    maximum_position_weight: FixedDecimal = Decimal("0.20")
    maximum_sector_weight: FixedDecimal = Decimal("0.40")
    maximum_gross_exposure: FixedDecimal = Decimal(1)
    maximum_turnover: FixedDecimal = Decimal("0.25")
    maximum_order_notional: FixedDecimal = Decimal("100000")
    maximum_staleness_seconds: int = Field(default=86400, ge=0)

    @field_validator(
        "maximum_position_weight",
        "maximum_sector_weight",
        "maximum_gross_exposure",
        "maximum_turnover",
        "maximum_order_notional",
    )
    @classmethod
    def positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("risk policy limits must be positive")
        return value

    @model_validator(mode="after")
    def coherent(self) -> RiskPolicy:
        if self.maximum_position_weight > self.maximum_gross_exposure:
            raise ValueError("position limit cannot exceed gross exposure limit")
        return self


def compile_risk_policy(policy_data: dict[str, object]) -> RiskPolicy:
    """Strict compilation rejects unknown or malformed policy-as-data fields."""

    return RiskPolicy.model_validate(policy_data)


def _result(
    rule_id: str,
    status: RuleStatus,
    reason_code: str,
    observed: Decimal,
    limit: Decimal,
    unit: str,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_version="1",
        status=status,
        reason_code=reason_code,
        observed=observed,
        limit=limit,
        unit=unit,
    )


def evaluate_policy(
    bundle: OrderBundle,
    *,
    positions: tuple[PositionLedgerEntry, ...],
    bars: Mapping[str, MarketBar],
    securities: Mapping[str, SecurityVersion],
    cash: Decimal,
    policy: RiskPolicy,
    as_of: datetime,
    include_orders: bool = True,
) -> tuple[RuleResult, ...]:
    """Evaluate the exact bundle against both current and projected long-only state."""

    now = require_utc(as_of)
    if cash < 0:
        raise ValueError("long-only paper account cash cannot be negative")
    position_quantity = {entry.instrument_id: entry.quantity for entry in positions}
    marks: dict[str, Decimal] = {}
    for position in positions:
        security = securities.get(position.instrument_id)
        market_bar = bars.get(position.instrument_id)
        bar_age = (
            Decimal((now - market_bar.available_at).total_seconds())
            if market_bar is not None
            else Decimal(-1)
        )
        if (
            security is None
            or market_bar is None
            or security.instrument_id != position.instrument_id
            or security.instrument_version != position.instrument_version
            or market_bar.instrument_id != position.instrument_id
            or market_bar.instrument_version != position.instrument_version
            or bar_age < 0
            or bar_age > policy.maximum_staleness_seconds
            or position.marked_at > now
            or security.valid_from > now
            or (security.valid_until is not None and security.valid_until <= now)
        ):
            raise ValueError(
                "each position requires a current market bar and active matching security identity"
            )
        marks[position.instrument_id] = market_bar.close_price
    nav = cash + sum(
        (entry.quantity * marks[entry.instrument_id] for entry in positions), Decimal(0)
    )
    if nav <= 0:
        raise ValueError("risk evaluation requires positive NAV")
    results: list[RuleResult] = []
    notionals: list[Decimal] = []
    projected = dict(position_quantity)
    for order in bundle.orders if include_orders else ():
        bar = bars.get(order.instrument_id)
        security = securities.get(order.instrument_id)
        if bar is None or security is None:
            raise ValueError("each order requires a market bar and security version")
        if (
            bar.instrument_id != order.instrument_id
            or security.instrument_id != order.instrument_id
            or bar.instrument_version != order.instrument_version
            or security.instrument_version != order.instrument_version
            or security.valid_from > now
            or (security.valid_until is not None and security.valid_until <= now)
        ):
            raise ValueError(
                "order does not bind an active matching security version or instrument identity"
            )
        age = Decimal((now - bar.available_at).total_seconds())
        fresh = Decimal(0) <= age <= policy.maximum_staleness_seconds
        results.append(
            _result(
                "market-data-staleness",
                RuleStatus.PASS if fresh else RuleStatus.FAIL,
                "FRESH" if fresh else ("FUTURE" if age < 0 else "STALE"),
                age,
                Decimal(policy.maximum_staleness_seconds),
                "SECONDS",
            )
        )
        price = order.limit_price if order.limit_price is not None else bar.close_price
        notional = order.quantity * price
        notionals.append(notional)
        results.append(
            _result(
                "maximum-order-notional",
                RuleStatus.PASS if notional <= policy.maximum_order_notional else RuleStatus.FAIL,
                "WITHIN_LIMIT" if notional <= policy.maximum_order_notional else "EXCEEDED",
                notional,
                policy.maximum_order_notional,
                "USD",
            )
        )
        delta = order.quantity if order.side == OrderSide.BUY else -order.quantity
        projected_quantity = projected.get(order.instrument_id, Decimal(0)) + delta
        projected[order.instrument_id] = projected_quantity
        results.append(
            _result(
                "long-only",
                RuleStatus.PASS if projected_quantity >= 0 else RuleStatus.FAIL,
                "NONNEGATIVE" if projected_quantity >= 0 else "SHORT_PROHIBITED",
                projected_quantity,
                Decimal(0),
                "SHARES",
            )
        )
        marks[order.instrument_id] = price
    turnover = sum(notionals, Decimal(0)) / nav
    results.append(
        _result(
            "maximum-turnover",
            RuleStatus.PASS if turnover <= policy.maximum_turnover else RuleStatus.FAIL,
            "WITHIN_LIMIT" if turnover <= policy.maximum_turnover else "EXCEEDED",
            turnover,
            policy.maximum_turnover,
            "RATIO",
        )
    )
    projected_gross = sum(
        (quantity * marks[instrument_id] for instrument_id, quantity in projected.items()),
        Decimal(0),
    )
    results.append(
        _result(
            "maximum-gross-exposure",
            RuleStatus.PASS
            if projected_gross / nav <= policy.maximum_gross_exposure
            else RuleStatus.FAIL,
            "WITHIN_LIMIT"
            if projected_gross / nav <= policy.maximum_gross_exposure
            else "EXCEEDED",
            projected_gross / nav,
            policy.maximum_gross_exposure,
            "RATIO",
        )
    )
    sector_notionals: dict[str, Decimal] = {}
    for instrument_id, quantity in projected.items():
        weight = quantity * marks[instrument_id] / nav
        sector_id = securities[instrument_id].sector_id
        sector_notionals[sector_id] = sector_notionals.get(sector_id, Decimal(0)) + weight
        results.append(
            _result(
                "maximum-position-weight",
                RuleStatus.PASS if weight <= policy.maximum_position_weight else RuleStatus.FAIL,
                "WITHIN_LIMIT" if weight <= policy.maximum_position_weight else "EXCEEDED",
                weight,
                policy.maximum_position_weight,
                "RATIO",
            )
        )
    for sector_weight in sector_notionals.values():
        results.append(
            _result(
                "maximum-sector-weight",
                RuleStatus.PASS
                if sector_weight <= policy.maximum_sector_weight
                else RuleStatus.FAIL,
                "WITHIN_LIMIT" if sector_weight <= policy.maximum_sector_weight else "EXCEEDED",
                sector_weight,
                policy.maximum_sector_weight,
                "RATIO",
            )
        )
    return tuple(results)


def policy_allows(results: tuple[RuleResult, ...]) -> bool:
    return all(result.status != RuleStatus.FAIL for result in results)
