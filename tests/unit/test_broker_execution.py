from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aegis.brokers import BrokerError, SimBroker
from aegis.contracts import Order, RiskPolicy
from aegis.fund.execution import build_orders

NOW = datetime(2024, 2, 23, 21, 5, tzinfo=UTC)
POLICY = RiskPolicy(version="test-v1")


def test_costed_fill_and_conservation() -> None:
    broker = SimBroker(10_000)
    order = Order(
        order_id="order-1",
        case_id="case-1",
        ticker="aapl",
        side="buy",
        quantity=10.0,
        reference_price=100.0,
        created_at=NOW,
        execution_mode="replay",
    )
    (fill,) = broker.execute_batch((order,), POLICY, NOW)
    assert fill.price == pytest.approx(100.05)
    assert fill.fee == pytest.approx(0.50)
    assert fill.slippage == pytest.approx(0.50)
    assert broker.cash == Decimal("8999.00")
    assert broker.quantities() == {"AAPL": 10}


def test_batch_failure_is_atomic() -> None:
    broker = SimBroker(1_000)
    before = broker.state()
    huge = Order(
        order_id="order-2",
        case_id="case-1",
        ticker="AAPL",
        side="buy",
        quantity=100.0,
        reference_price=100.0,
        created_at=NOW,
        execution_mode="replay",
    )
    with pytest.raises(BrokerError, match="negative cash"):
        broker.execute_batch((huge,), POLICY, NOW)
    assert broker.state() == before


def test_short_sale_is_denied_atomically() -> None:
    broker = SimBroker(1_000)
    sell = Order(
        order_id="order-3",
        case_id="case-1",
        ticker="AAPL",
        side="sell",
        quantity=1.0,
        reference_price=100.0,
        created_at=NOW,
        execution_mode="replay",
    )
    with pytest.raises(BrokerError, match="short sale denied"):
        broker.execute_batch((sell,), POLICY, NOW)
    assert broker.quantities() == {}
    assert broker.cash == Decimal("1000.00")


def test_order_builder_is_deterministic_and_sells_first() -> None:
    kwargs = dict(
        case_id="case-1",
        final_weights={"AAPL": 0.2, "MSFT": 0.2},
        current_quantities={"AAPL": 30},
        marks={"AAPL": 100.0, "MSFT": 200.0},
        equity=Decimal("10000"),
        created_at=NOW,
        execution_mode="replay",
    )
    first = build_orders(**kwargs)
    second = build_orders(**kwargs)
    assert first == second
    assert [(order.ticker, order.side, order.quantity) for order in first] == [
        ("AAPL", "sell", 10.0),
        ("MSFT", "buy", 10.0),
    ]
