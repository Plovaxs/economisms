from __future__ import annotations

import pytest

from prometheus.core.money import Money
from prometheus.trading_readiness.mock_broker import BrokerFault, InMemoryMockBroker
from prometheus.trading_readiness.orders import Order


def test_a_limit_order_fills_at_its_own_price() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    order = Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000))
    fill = broker.submit_order(order)
    assert fill.fill_price == Money(10_000)
    assert fill.fill_quantity == 10


def test_a_market_order_requires_an_explicit_reference_price() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    order = Order("AAPL", "buy", 10, "market")
    with pytest.raises(ValueError, match="reference_price"):
        broker.submit_order(order)


def test_a_market_order_fills_at_the_supplied_reference_price() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    order = Order("AAPL", "buy", 10, "market")
    fill = broker.submit_order(order, reference_price=Money(9_500))
    assert fill.fill_price == Money(9_500)


def test_buying_opens_a_long_position_and_debits_cash() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    position = broker.positions()[0]
    assert position.instrument == "AAPL"
    assert position.quantity == 10
    assert position.average_price == Money(10_000)
    assert broker.account_statement().cash == Money(900_000)


def test_selling_opens_a_short_position_and_credits_cash() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.submit_order(Order("AAPL", "sell", 10, "limit", limit_price=Money(10_000)))
    position = broker.positions()[0]
    assert position.quantity == -10
    assert broker.account_statement().cash == Money(1_100_000)


def test_adding_to_a_long_position_computes_the_weighted_average_price() -> None:
    broker = InMemoryMockBroker(cash=Money(10_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(12_000)))
    position = broker.positions()[0]
    assert position.quantity == 20
    assert position.average_price == Money(11_000)  # (10*10000 + 10*12000) / 20


def test_partially_closing_a_long_position_leaves_the_average_price_unchanged() -> None:
    broker = InMemoryMockBroker(cash=Money(10_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    broker.submit_order(Order("AAPL", "sell", 4, "limit", limit_price=Money(15_000)))
    position = broker.positions()[0]
    assert position.quantity == 6
    assert position.average_price == Money(10_000)


def test_fully_closing_a_position_resets_its_average_price_to_zero() -> None:
    broker = InMemoryMockBroker(cash=Money(10_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    broker.submit_order(Order("AAPL", "sell", 10, "limit", limit_price=Money(15_000)))
    position = broker.positions()[0]
    assert position.quantity == 0
    assert position.average_price == Money(0)


def test_account_statement_reflects_positions_and_cash_together() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    statement = broker.account_statement()
    assert statement.cash == Money(900_000)
    assert statement.position_for("AAPL").quantity == 10


def test_a_configured_fault_is_raised_by_submit_order_and_nothing_else() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    fault = BrokerFault("simulated timeout")
    broker.configure_fault(fault)
    with pytest.raises(BrokerFault, match="simulated timeout"):
        broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    # positions()/account_statement() are unaffected by a configured fault.
    assert broker.positions() == ()
    assert broker.account_statement().cash == Money(1_000_000)


def test_clearing_the_fault_lets_orders_through_again() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.configure_fault(BrokerFault("simulated timeout"))
    broker.configure_fault(None)
    fill = broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    assert fill.fill_quantity == 10
