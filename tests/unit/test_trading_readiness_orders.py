from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prometheus.core.money import Money
from prometheus.trading_readiness.orders import AccountStatement, Fill, Order, Position


def test_a_limit_order_requires_a_limit_price() -> None:
    with pytest.raises(ValueError, match="requires a limit_price"):
        Order("AAPL", "buy", 10, "limit")


def test_a_market_order_must_not_carry_a_limit_price() -> None:
    with pytest.raises(ValueError, match="must not carry"):
        Order("AAPL", "buy", 10, "market", limit_price=Money(10_000))


def test_zero_or_negative_quantity_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive int"):
        Order("AAPL", "buy", 0, "market")
    with pytest.raises(ValueError, match="positive int"):
        Order("AAPL", "buy", -5, "market")


def test_an_invalid_side_or_order_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="side"):
        Order("AAPL", "short", 10, "market")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="order_type"):
        Order("AAPL", "buy", 10, "stop")  # type: ignore[arg-type]


def test_order_notional_uses_the_limit_price() -> None:
    order = Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000))
    assert order.notional == Money(100_000)


def test_market_order_notional_raises_without_a_price() -> None:
    order = Order("AAPL", "buy", 10, "market")
    with pytest.raises(ValueError, match="market order"):
        _ = order.notional


def test_fill_quantity_cannot_exceed_the_orders_quantity() -> None:
    order = Order("AAPL", "buy", 10, "market")
    with pytest.raises(ValueError, match="cannot exceed"):
        Fill(order, Money(10_000), 11, datetime.now(UTC))


def test_fill_notional_is_price_times_quantity() -> None:
    order = Order("AAPL", "buy", 10, "market")
    fill = Fill(order, Money(10_050), 10, datetime.now(UTC))
    assert fill.notional == Money(100_500)


def test_position_quantity_may_be_negative_for_a_short() -> None:
    position = Position("AAPL", -10, Money(10_000))
    assert position.quantity == -10


def test_position_average_price_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="average_price"):
        Position("AAPL", 10, Money(-1))


def test_account_statement_rejects_a_duplicate_instrument() -> None:
    with pytest.raises(ValueError, match="repeat"):
        AccountStatement(
            positions=(Position("AAPL", 10, Money(10_000)), Position("AAPL", 5, Money(9_000))),
            cash=Money(0),
            as_of=datetime.now(UTC),
        )


def test_position_for_finds_the_matching_instrument_or_none() -> None:
    statement = AccountStatement(
        positions=(Position("AAPL", 10, Money(10_000)),), cash=Money(0), as_of=datetime.now(UTC)
    )
    assert statement.position_for("AAPL").quantity == 10
    assert statement.position_for("MSFT") is None
