"""Deterministic, atomic, simulated execution only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from aegis.contracts import Fill, Order, Position, RiskPolicy, canonical_sha256

_CENT = Decimal("0.01")
_BPS = Decimal("10000")


class BrokerError(RuntimeError):
    """A simulated order batch could not be executed safely."""


@dataclass(frozen=True)
class BrokerState:
    cash: Decimal
    shares: tuple[tuple[str, int], ...]
    average_costs: tuple[tuple[str, Decimal], ...]


class SimBroker:
    """In-memory long-only simulator with deterministic costs and atomic batches."""

    is_live_broker = False

    def __init__(self, cash: float) -> None:
        if cash <= 0:
            raise ValueError("starting cash must be positive")
        self._cash = Decimal(str(cash)).quantize(_CENT)
        self._shares: dict[str, int] = {}
        self._average_costs: dict[str, Decimal] = {}

    @property
    def cash(self) -> Decimal:
        return self._cash

    def state(self) -> BrokerState:
        return BrokerState(
            cash=self._cash,
            shares=tuple(sorted(self._shares.items())),
            average_costs=tuple(sorted(self._average_costs.items())),
        )

    def restore(self, state: BrokerState) -> None:
        self._cash = state.cash
        self._shares = dict(state.shares)
        self._average_costs = dict(state.average_costs)

    def quantities(self) -> dict[str, int]:
        return dict(sorted(self._shares.items()))

    def equity(self, marks: Mapping[str, float]) -> Decimal:
        total = self._cash
        for ticker, quantity in self._shares.items():
            if ticker not in marks:
                raise BrokerError(f"missing mark for held position {ticker}")
            total += Decimal(quantity) * Decimal(str(marks[ticker]))
        return total.quantize(_CENT)

    def weights(self, marks: Mapping[str, float]) -> dict[str, float]:
        equity = self.equity(marks)
        if equity <= 0:
            raise BrokerError("cannot calculate weights for non-positive equity")
        return {
            ticker: float((Decimal(quantity) * Decimal(str(marks[ticker]))) / equity)
            for ticker, quantity in sorted(self._shares.items())
        }

    def execute_batch(
        self,
        orders: tuple[Order, ...],
        policy: RiskPolicy,
        filled_at: datetime,
    ) -> tuple[Fill, ...]:
        """Validate and simulate all fills on copies, then commit once."""
        cash = self._cash
        shares = dict(self._shares)
        average_costs = dict(self._average_costs)
        fills: list[Fill] = []
        seen: set[str] = set()
        fee_rate = Decimal(str(policy.commission_bps)) / _BPS
        slippage_rate = Decimal(str(policy.slippage_bps)) / _BPS

        for order in orders:
            if order.order_id in seen:
                raise BrokerError(f"duplicate order ID: {order.order_id}")
            seen.add(order.order_id)
            quantity_decimal = Decimal(str(order.quantity))
            if quantity_decimal != quantity_decimal.to_integral_value() or quantity_decimal <= 0:
                raise BrokerError("simulator accepts positive whole-share quantities only")
            quantity = int(quantity_decimal)
            reference = Decimal(str(order.reference_price))
            direction = Decimal("1") if order.side == "buy" else Decimal("-1")
            fill_price = (reference * (Decimal("1") + direction * slippage_rate)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            notional = fill_price * quantity
            fee = (notional * fee_rate).quantize(_CENT, rounding=ROUND_HALF_UP)
            slippage = (abs(fill_price - reference) * quantity).quantize(
                _CENT, rounding=ROUND_HALF_UP
            )

            current = shares.get(order.ticker, 0)
            if order.side == "buy":
                new_quantity = current + quantity
                old_cost = average_costs.get(order.ticker, Decimal("0")) * current
                average_costs[order.ticker] = (old_cost + notional) / new_quantity
                shares[order.ticker] = new_quantity
                cash -= notional + fee
            else:
                if not policy.allow_shorting and quantity > current:
                    raise BrokerError(f"short sale denied for {order.ticker}")
                shares[order.ticker] = current - quantity
                cash += notional - fee
                if shares[order.ticker] == 0:
                    shares.pop(order.ticker)
                    average_costs.pop(order.ticker, None)

            fills.append(
                Fill(
                    fill_id=canonical_sha256(
                        {
                            "order_id": order.order_id,
                            "price": str(fill_price),
                            "fee": str(fee),
                            "slippage": str(slippage),
                            "filled_at": filled_at.isoformat(),
                        }
                    )[:32],
                    order_id=order.order_id,
                    ticker=order.ticker,
                    side=order.side,
                    quantity=float(quantity),
                    price=float(fill_price),
                    fee=float(fee),
                    slippage=float(slippage),
                    filled_at=filled_at,
                    execution_mode=order.execution_mode,
                )
            )

        if cash < 0:
            raise BrokerError("order batch would create negative cash")
        self._cash = cash.quantize(_CENT, rounding=ROUND_HALF_UP)
        self._shares = shares
        self._average_costs = average_costs
        return tuple(fills)

    def positions(self, marks: Mapping[str, float], as_of: datetime) -> tuple[Position, ...]:
        positions: list[Position] = []
        for ticker, quantity in sorted(self._shares.items()):
            if ticker not in marks:
                raise BrokerError(f"missing mark for held position {ticker}")
            average = self._average_costs[ticker]
            mark = Decimal(str(marks[ticker]))
            market_value = mark * quantity
            unrealized = (mark - average) * quantity
            positions.append(
                Position(
                    ticker=ticker,
                    quantity=float(quantity),
                    average_cost=float(average),
                    market_price=float(mark),
                    market_value=float(market_value),
                    unrealized_pnl=float(unrealized),
                    as_of=as_of,
                )
            )
        return tuple(positions)
