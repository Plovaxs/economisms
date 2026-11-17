from __future__ import annotations

from datetime import UTC, datetime

from prometheus.core.money import Money
from prometheus.trading_readiness.mock_broker import InMemoryMockBroker
from prometheus.trading_readiness.orders import AccountStatement, Order, Position
from prometheus.trading_readiness.reconciliation import reconcile


def _statement(positions: tuple[Position, ...], cash: Money) -> AccountStatement:
    return AccountStatement(positions=positions, cash=cash, as_of=datetime.now(UTC))


def test_matching_books_produce_zero_breaks() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    system = _statement((Position("AAPL", 10, Money(10_000)),), Money(900_000))
    report = reconcile(system, broker.account_statement())
    assert report.is_clean


def test_a_position_quantity_discrepancy_is_a_named_break() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    system = _statement((Position("AAPL", 7, Money(10_000)),), Money(900_000))
    report = reconcile(system, broker.account_statement())
    assert not report.is_clean
    assert len(report.position_breaks) == 1
    break_ = report.position_breaks[0]
    assert break_.instrument == "AAPL"
    assert break_.system_quantity == 7
    assert break_.broker_quantity == 10
    assert break_.delta == -3


def test_a_cash_discrepancy_is_a_named_break() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    system = _statement((Position("AAPL", 10, Money(10_000)),), Money(950_000))
    report = reconcile(system, broker.account_statement())
    assert report.cash_break is not None
    assert report.cash_break.delta == Money(50_000)


def test_multiple_simultaneous_breaks_are_all_reported() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    broker.submit_order(Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000)))
    broker.submit_order(Order("MSFT", "buy", 5, "limit", limit_price=Money(20_000)))
    system = _statement(
        (Position("AAPL", 7, Money(10_000)), Position("MSFT", 2, Money(20_000))),
        Money(950_000),
    )
    report = reconcile(system, broker.account_statement())
    assert len(report.position_breaks) == 2
    assert report.cash_break is not None


def test_an_instrument_the_system_has_but_the_broker_does_not_is_a_break() -> None:
    broker = InMemoryMockBroker(cash=Money(1_000_000))
    system = _statement((Position("AAPL", 10, Money(10_000)),), Money(1_000_000))
    report = reconcile(system, broker.account_statement())
    assert len(report.position_breaks) == 1
    assert report.position_breaks[0].broker_quantity == 0
