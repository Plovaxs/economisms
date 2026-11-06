from fractions import Fraction as F

from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.market_settlement import settle_market
from prometheus.econosim.price_discovery import (
    BudgetDemand,
    LinearSupply,
    PriceSearchConfig,
    clear_at_price,
    discover_price,
)


@settings(max_examples=100)
@given(
    price=st.integers(1, 1000),
    budgets=st.lists(st.integers(0, 10_000), min_size=1, max_size=5),
    numerator=st.integers(0, 100),
    denominator=st.integers(1, 10),
)
def test_exact_goods_settlement_preserves_cash_equity_budgets_and_quantity(
    price, budgets, numerator, denominator
):
    economy = Economy()
    firm = economy.add_firm("firm")
    households = {f"h{index}": economy.add_household(f"h{index}") for index in range(len(budgets))}
    for household, budget in zip(households.values(), budgets, strict=True):
        if budget:
            household.receive_income(Money(budget))
    capacity = F(numerator, denominator)
    allocation = clear_at_price(
        Money(price),
        {
            name: BudgetDemand(Money(budget), F(100))
            for name, budget in zip(households, budgets, strict=True)
        },
        {"firm": LinearSupply(Money(price), capacity, F(0), capacity)},
    )
    settlement = settle_market(allocation, "goods", firm, households)
    assert settlement.total_paid.minor_units == int(allocation.realized_quantity * price)
    assert 0 <= settlement.rounding_remainder < 1
    assert sum(order.realized for order in allocation.buyers) == allocation.realized_quantity
    assert sum(order.realized for order in allocation.sellers) == allocation.realized_quantity
    assert all(household.cash_balance.minor_units >= 0 for household in households.values())
    assert firm.cash_balance.minor_units + sum(
        hh.cash_balance.minor_units for hh in households.values()
    ) == sum(budgets)
    assert firm.net_worth.minor_units + sum(
        hh.net_worth.minor_units for hh in households.values()
    ) == sum(budgets)
    economy.check_integrity()


@settings(max_examples=100)
@given(
    price=st.integers(1, 1000),
    budget=st.integers(0, 10_000),
    supplies=st.lists(st.integers(0, 100), min_size=1, max_size=5),
)
def test_exact_payroll_never_exceeds_firm_budget(price, budget, supplies):
    economy = Economy()
    firm = economy.add_firm("firm")
    if budget:
        firm.capitalize(Money(budget))
    households = {f"h{index}": economy.add_household(f"h{index}") for index in range(len(supplies))}
    allocation = clear_at_price(
        Money(price),
        {"firm": BudgetDemand(Money(budget), F(1000))},
        {
            name: LinearSupply(Money(price), F(supply, 3), F(0), F(supply, 3))
            for name, supply in zip(households, supplies, strict=True)
        },
    )
    result = settle_market(allocation, "labor", firm, households)
    assert result.total_paid.minor_units <= budget
    assert (
        sum(hh.cash_balance.minor_units for hh in households.values())
        == result.total_paid.minor_units
    )
    assert firm.cash_balance.minor_units == budget - result.total_paid.minor_units
    assert 0 <= result.rounding_remainder < 1
    economy.check_integrity()


@settings(max_examples=75)
@given(budget=st.integers(0, 1000), capacity=st.integers(0, 50), slope=st.integers(0, 5))
def test_integer_bisection_matches_an_exhaustive_price_grid(budget, capacity, slope):
    buyers = {"b": BudgetDemand(Money(budget), F(20))}
    sellers = {"s": LinearSupply(Money(5), F(0), F(slope, 3), F(capacity))}
    result = discover_price(buyers, sellers, PriceSearchConfig(Money(1), Money(30), F(0)))
    exhaustive = [clear_at_price(Money(price), buyers, sellers) for price in range(1, 31)]
    assert abs(result.allocation.excess_demand) == min(
        abs(item.excess_demand) for item in exhaustive
    )
    assert result.status != "iteration_limit"
