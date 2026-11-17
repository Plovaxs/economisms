from __future__ import annotations

import pytest

from prometheus.core.money import Money
from prometheus.trading_readiness.orders import Order, Position
from prometheus.trading_readiness.risk_gate import PreTradeRiskGate, RiskLimits, RiskLimitViolation

_LIMITS = RiskLimits(
    max_order_quantity=1_000,
    max_order_notional=Money(10_000_000),
    max_position_quantity=5_000,
)


def test_an_order_within_every_limit_passes() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    order = Order("AAPL", "buy", 10, "limit", limit_price=Money(10_000))
    gate.check(order, book=None)  # does not raise


def test_an_oversized_order_quantity_is_rejected_and_named() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    order = Order("AAPL", "buy", 1_001, "limit", limit_price=Money(1_000))
    with pytest.raises(RiskLimitViolation, match="max_order_quantity"):
        gate.check(order, book=None)


def test_an_oversized_notional_is_rejected_and_named() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    order = Order("AAPL", "buy", 1_000, "limit", limit_price=Money(50_000))  # 50,000,000 notional
    with pytest.raises(RiskLimitViolation, match="max_order_notional"):
        gate.check(order, book=None)


def test_a_resulting_position_over_the_limit_is_rejected_and_named() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    book = Position("AAPL", 4_900, Money(10_000))
    order = Order("AAPL", "buy", 200, "limit", limit_price=Money(10_000))
    with pytest.raises(RiskLimitViolation, match="max_position_quantity"):
        gate.check(order, book=book)


def test_a_resulting_short_position_over_the_limit_is_also_rejected() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    book = Position("AAPL", -4_900, Money(10_000))
    order = Order("AAPL", "sell", 200, "limit", limit_price=Money(10_000))
    with pytest.raises(RiskLimitViolation, match="max_position_quantity"):
        gate.check(order, book=book)


def test_a_sell_reduces_the_position_so_it_can_exceed_the_cap_on_the_buy_side() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    book = Position("AAPL", 4_900, Money(10_000))
    order = Order("AAPL", "sell", 200, "limit", limit_price=Money(10_000))
    gate.check(order, book=book)  # resulting quantity 4,700 -- within the limit


def test_multiple_simultaneous_breaches_are_all_named_at_once() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    order = Order("AAPL", "buy", 1_001, "limit", limit_price=Money(50_000))
    with pytest.raises(RiskLimitViolation) as excinfo:
        gate.check(order, book=None)
    assert "max_order_quantity" in str(excinfo.value)
    assert "max_order_notional" in str(excinfo.value)


def test_a_market_order_uses_the_supplied_reference_price_for_the_notional_check() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    order = Order("AAPL", "buy", 1_000, "market")
    with pytest.raises(RiskLimitViolation, match="max_order_notional"):
        gate.check(order, book=None, reference_price=Money(50_000))


def test_a_market_order_without_a_reference_price_raises() -> None:
    gate = PreTradeRiskGate(_LIMITS)
    order = Order("AAPL", "buy", 10, "market")
    with pytest.raises(ValueError, match="reference_price"):
        gate.check(order, book=None)


def test_risk_limits_reject_non_positive_values() -> None:
    with pytest.raises(ValueError, match="max_order_quantity"):
        RiskLimits(max_order_quantity=0, max_order_notional=Money(1), max_position_quantity=1)
