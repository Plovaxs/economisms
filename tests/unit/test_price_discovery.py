from fractions import Fraction as F

import pytest

from prometheus.core.money import CurrencyMismatchError, Money
from prometheus.econosim.price_discovery import (
    BudgetDemand,
    FilledOrder,
    LinearSupply,
    MarketAllocation,
    PriceSearchConfig,
    clear_at_price,
    discover_price,
    quantity,
)


def fixed_supply(amount):
    return LinearSupply(Money(100), F(amount), F(0), F(amount))


def test_budget_linear_market_finds_an_independent_exact_root() -> None:
    # 1000/p = (p - 50)/5 has a positive root p=100, quantity=10.
    result = discover_price(
        {"buyer": BudgetDemand(Money(1000), F(100))},
        {"seller": LinearSupply(Money(50), F(0), F(1, 5), F(100))},
        PriceSearchConfig(Money(50), Money(150)),
        initial_price=Money(75),
    )
    assert result.status == "cleared"
    assert result.allocation.price == Money(100)
    assert result.allocation.realized_quantity == 10
    assert result.allocation.excess_demand == 0
    assert len(result.evaluations) <= 32


def test_adjacent_integer_ticks_report_residual_instead_of_false_equilibrium() -> None:
    # The real root is 100.5; 101 has a smaller absolute residual than 100.
    result = discover_price(
        {"buyer": BudgetDemand(Money(1005), F(100))},
        {"seller": fixed_supply(10)},
        PriceSearchConfig(Money(50), Money(150)),
    )
    assert result.status == "tick_limited"
    assert result.bracket == (Money(100), Money(101))
    assert result.allocation.price == Money(101)
    assert result.allocation.excess_demand == F(-5, 101)
    assert result.allocation.realized_quantity == F(1005, 101)


@pytest.mark.parametrize(
    "budget,expected,status",
    [
        (500, 100, "floor_limited"),
        (3000, 200, "ceiling_limited"),
    ],
)
def test_binding_price_bounds_keep_explicit_rationing(budget, expected, status) -> None:
    result = discover_price(
        {"buyer": BudgetDemand(Money(budget), F(100))},
        {"seller": fixed_supply(10)},
        PriceSearchConfig(Money(100), Money(200)),
    )
    assert result.status == status
    assert result.allocation.price == Money(expected)
    assert result.allocation.excess_demand != 0
    assert result.allocation.realized_quantity == min(F(budget, expected), F(10))


def test_empty_market_keeps_initial_quote_and_posts_no_equilibrium_claim() -> None:
    result = discover_price(
        {"buyer": BudgetDemand(Money(0), F(100))},
        {"seller": fixed_supply(0)},
        PriceSearchConfig(Money(1), Money(100)),
        initial_price=Money(77),
    )
    assert result.status == "no_trade"
    assert result.allocation.price == Money(77)
    assert result.allocation.realized_quantity == 0
    assert len(result.evaluations) == 1


def test_evaluation_budget_is_bounded_and_unresolved_bracket_is_reported() -> None:
    result = discover_price(
        {"buyer": BudgetDemand(Money(1005), F(100))},
        {"seller": fixed_supply(10)},
        PriceSearchConfig(Money(10), Money(1000), max_evaluations=3),
        initial_price=Money(75),
    )
    assert result.status == "iteration_limit"
    assert len(result.evaluations) == 3
    assert result.bracket[1].minor_units - result.bracket[0].minor_units > 1


def test_exact_rationing_is_immutable_and_order_independent() -> None:
    buyers = {"b2": BudgetDemand(Money(200), F(20)), "b1": BudgetDemand(Money(100), F(20))}
    sellers = {"s2": fixed_supply(1), "s1": fixed_supply(1)}
    first = clear_at_price(Money(100), buyers, sellers)
    second = clear_at_price(
        Money(100), dict(reversed(list(buyers.items()))), dict(reversed(list(sellers.items())))
    )
    assert first == second
    assert [order.realized for order in first.buyers] == [F(2, 3), F(4, 3)]
    assert (
        sum(order.realized for order in first.buyers)
        == sum(order.realized for order in first.sellers)
        == 2
    )


def test_forged_or_self_crossing_allocation_is_rejected() -> None:
    with pytest.raises(ValueError, match="pro-rata"):
        MarketAllocation(
            Money(100), (FilledOrder("b", F(2), F(1)),), (FilledOrder("s", F(2), F(1)),)
        )
    with pytest.raises(ValueError, match="both market sides"):
        clear_at_price(
            Money(100), {"same": BudgetDemand(Money(100), F(1))}, {"same": fixed_supply(1)}
        )


@pytest.mark.parametrize("value", [True, -1, float("inf"), float("nan"), "1.5"])
def test_invalid_quantities_fail_before_search(value) -> None:
    with pytest.raises(ValueError):
        quantity(value)


def test_decimal_float_quantities_are_converted_to_declared_exact_decimal() -> None:
    assert quantity(0.1) == F(1, 10)


def test_currency_mismatch_and_invalid_initial_price_are_rejected() -> None:
    buyers = {"b": BudgetDemand(Money(100), F(1))}
    with pytest.raises(CurrencyMismatchError):
        clear_at_price(Money(10, "EUR"), buyers, {"s": fixed_supply(1)})
    with pytest.raises(ValueError, match="within"):
        discover_price(
            buyers,
            {"s": fixed_supply(1)},
            PriceSearchConfig(Money(1), Money(100)),
            initial_price=Money(101),
        )


@pytest.mark.parametrize("low,high,limit", [(0, 100, 32), (100, 1, 32), (1, 100, 2)])
def test_invalid_search_bounds_and_limits_are_rejected(low, high, limit) -> None:
    with pytest.raises(ValueError):
        PriceSearchConfig(Money(low), Money(high), max_evaluations=limit)
