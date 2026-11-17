from __future__ import annotations

import pytest

from prometheus.core.money import Money
from prometheus.trading_readiness.mock_broker import InMemoryMockBroker
from prometheus.trading_readiness.orders import Order
from prometheus.trading_readiness.risk_gate import PreTradeRiskGate, RiskLimits, RiskLimitViolation
from prometheus.trading_readiness.shadow_trading import ShadowTradingSession

_LIMITS = RiskLimits(
    max_order_quantity=1_000, max_order_notional=Money(10_000_000), max_position_quantity=5_000
)


def test_a_sequence_of_valid_orders_all_fill() -> None:
    session = ShadowTradingSession(
        PreTradeRiskGate(_LIMITS), InMemoryMockBroker(cash=Money(10_000_000))
    )
    orders = [
        Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)),
        Order("AAPL", "buy", 5, "limit", limit_price=Money(11_000)),
        Order("MSFT", "sell", 3, "limit", limit_price=Money(20_000)),
    ]
    fills = session.run(orders)
    assert len(fills) == 3
    assert session.broker.account_statement().position_for("AAPL").quantity == 15


def test_a_risk_violating_order_in_the_sequence_stops_the_session() -> None:
    session = ShadowTradingSession(
        PreTradeRiskGate(_LIMITS), InMemoryMockBroker(cash=Money(10_000_000))
    )
    orders = [
        Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)),
        Order(
            "AAPL", "buy", 1_001, "limit", limit_price=Money(10_000)
        ),  # exceeds max_order_quantity
    ]
    with pytest.raises(RiskLimitViolation):
        session.run(orders)
    # The first, valid order still filled before the second was rejected.
    assert session.broker.account_statement().position_for("AAPL").quantity == 10


def test_market_orders_use_the_supplied_reference_prices() -> None:
    session = ShadowTradingSession(
        PreTradeRiskGate(_LIMITS), InMemoryMockBroker(cash=Money(10_000_000))
    )
    fills = session.run(
        [Order("AAPL", "buy", 10, "market")], reference_prices={"AAPL": Money(9_500)}
    )
    assert fills[0].fill_price == Money(9_500)
