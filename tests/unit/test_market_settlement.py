from fractions import Fraction as F

import pytest

from prometheus.core.money import Money
from prometheus.econosim.agents import InsufficientFundsError
from prometheus.econosim.economy import Economy
from prometheus.econosim.market_settlement import settle_market
from prometheus.econosim.price_discovery import BudgetDemand, LinearSupply, clear_at_price


def setup_economy(firm_cash=10_000, household_cash=1000):
    economy = Economy()
    firm = economy.add_firm("firm")
    households = {name: economy.add_household(name) for name in ("h1", "h2")}
    if firm_cash:
        firm.capitalize(Money(firm_cash))
    if household_cash:
        for household in households.values():
            household.receive_income(Money(household_cash))
    return economy, firm, households


def supply(amount):
    return LinearSupply(Money(1), F(amount), F(0), F(amount))


def test_entire_labor_market_is_one_balanced_batch() -> None:
    economy, firm, households = setup_economy()
    allocation = clear_at_price(
        Money(100),
        {"firm": BudgetDemand(Money(1000), F(20))},
        {name: supply(5) for name in households},
    )
    previous = len(economy.ledger.journal)
    result = settle_market(allocation, "labor", firm, households, step=1)
    assert len(economy.ledger.journal) == previous + 1
    assert result.total_paid == Money(1000)
    assert result.transaction.is_balanced()
    assert result.transaction.step == 1
    assert firm.cash_balance == Money(9000)
    assert all(household.cash_balance == Money(1500) for household in households.values())
    economy.check_integrity()


def test_largest_remainder_rounding_is_deterministic_and_does_not_exceed_total() -> None:
    economy, firm, households = setup_economy(firm_cash=1, household_cash=0)
    allocation = clear_at_price(
        Money(1), {"firm": BudgetDemand(Money(1), F(1))}, {"h2": supply(1), "h1": supply(1)}
    )
    result = settle_market(allocation, "labor", firm, dict(reversed(list(households.items()))))
    assert [payment.quantity for payment in result.payments] == [F(1, 2), F(1, 2)]
    assert [payment.paid for payment in result.payments] == [Money(1), Money(0)]
    assert result.rounding_remainder == 0
    assert result.total_paid == Money(1)
    assert firm.cash_balance == Money(0)
    economy.check_integrity()


def test_aggregate_rounding_remainder_is_exact_and_reported() -> None:
    _, firm, households = setup_economy(firm_cash=2, household_cash=0)
    allocation = clear_at_price(
        Money(3),
        {"firm": BudgetDemand(Money(2), F(1, 2))},
        {name: supply(F(1, 4)) for name in households},
    )
    result = settle_market(allocation, "labor", firm, households)
    assert result.total_paid == Money(1)
    assert result.rounding_remainder == F(1, 2)
    assert sum(payment.nominal_minor_units for payment in result.payments) == F(3, 2)
    assert sum(payment.rounding_adjustment for payment in result.payments) == F(-1, 2)


def test_goods_rounding_preserves_individual_buyer_budgets() -> None:
    economy, firm, households = setup_economy(firm_cash=0, household_cash=1)
    allocation = clear_at_price(
        Money(3),
        {name: BudgetDemand(Money(1), F(1)) for name in households},
        {"firm": supply(F(1, 2))},
    )
    result = settle_market(allocation, "goods", firm, households)
    assert result.total_paid == Money(1)
    assert result.rounding_remainder == F(1, 2)
    assert all(household.cash_balance.minor_units >= 0 for household in households.values())
    assert firm.cash_balance == Money(1)
    economy.check_integrity()


def test_later_insolvent_buyer_cannot_leave_a_partial_market() -> None:
    economy, firm, households = setup_economy(household_cash=0)
    households["h1"].receive_income(Money(1000))
    allocation = clear_at_price(
        Money(100),
        {name: BudgetDemand(Money(1000), F(10)) for name in households},
        {"firm": supply(20)},
    )
    before = economy.ledger.snapshot(0).state_hash(), economy.ledger.journal
    with pytest.raises(InsufficientFundsError):
        settle_market(allocation, "goods", firm, households)
    assert (economy.ledger.snapshot(0).state_hash(), economy.ledger.journal) == before


def test_unfunded_payroll_is_rejected_without_any_posting() -> None:
    economy, firm, households = setup_economy(firm_cash=1000)
    allocation = clear_at_price(
        Money(100),
        {"firm": BudgetDemand(Money(2000), F(20))},
        {name: supply(10) for name in households},
    )
    before = economy.ledger.snapshot(0).state_hash()
    with pytest.raises(InsufficientFundsError):
        settle_market(allocation, "labor", firm, households)
    assert economy.ledger.snapshot(0).state_hash() == before


def test_foreign_ledger_participant_is_rejected_before_posting() -> None:
    economy, firm, households = setup_economy()
    foreign = Economy().add_household("h2")
    allocation = clear_at_price(
        Money(100),
        {"firm": BudgetDemand(Money(1000), F(20))},
        {name: supply(5) for name in households},
    )
    before = economy.ledger.snapshot(0).state_hash()
    with pytest.raises(ValueError, match="share one ledger"):
        settle_market(allocation, "labor", firm, households | {"h2": foreign})
    assert economy.ledger.snapshot(0).state_hash() == before


def test_zero_market_volume_creates_no_empty_journal_transaction() -> None:
    economy, firm, households = setup_economy()
    allocation = clear_at_price(
        Money(100),
        {"firm": BudgetDemand(Money(0), F(20))},
        {name: supply(5) for name in households},
    )
    previous = economy.ledger.journal
    result = settle_market(allocation, "labor", firm, households)
    assert result.transaction is None
    assert result.total_paid == Money(0)
    assert economy.ledger.journal == previous
