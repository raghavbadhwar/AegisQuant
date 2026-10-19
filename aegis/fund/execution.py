"""Pure target-weight to simulated-order construction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from aegis.contracts import Order, OrderSide, SimulationMode, canonical_sha256


def build_orders(
    case_id: str,
    final_weights: Mapping[str, float],
    current_quantities: Mapping[str, int],
    marks: Mapping[str, float],
    equity: Decimal,
    created_at: datetime,
    execution_mode: SimulationMode,
) -> tuple[Order, ...]:
    """Build whole-share delta orders, sells first and then buys."""
    sells: list[Order] = []
    buys: list[Order] = []
    for ticker in sorted(set(final_weights) | set(current_quantities)):
        if ticker not in marks:
            raise ValueError(f"missing mark for order construction: {ticker}")
        mark = Decimal(str(marks[ticker]))
        target_value = Decimal(str(final_weights.get(ticker, 0.0))) * equity
        target_quantity = int((target_value / mark).to_integral_value(rounding=ROUND_DOWN))
        delta = target_quantity - current_quantities.get(ticker, 0)
        if delta == 0:
            continue
        side: OrderSide = "buy" if delta > 0 else "sell"
        payload = {
            "case_id": case_id,
            "ticker": ticker,
            "side": side,
            "quantity": abs(delta),
            "reference_price": str(mark),
            "created_at": created_at.isoformat(),
            "execution_mode": execution_mode,
        }
        order = Order(
            order_id=canonical_sha256(payload)[:32],
            case_id=case_id,
            ticker=ticker,
            side=side,
            quantity=float(abs(delta)),
            reference_price=float(mark),
            created_at=created_at,
            execution_mode=execution_mode,
        )
        (buys if side == "buy" else sells).append(order)
    return tuple(sells + buys)
