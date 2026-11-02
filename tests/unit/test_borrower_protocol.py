"""Confirms Bank.originate_loan / receive_repayment are genuinely
polymorphic over the Borrower protocol -- Household and Government go
through the identical code path, not a parallel copy that could drift."""

import pytest

from prometheus.core.money import Money
from prometheus.econosim.agents import Government, Household
from prometheus.econosim.economy import Economy


def _capitalized_bank(econ: Economy, capital: int = 1_000_000_00):
    bank = econ.add_bank("bank-1", max_leverage=10.0)
    bank.capitalize(Money(capital, "USD"))
    return bank


def _top_up_cash_without_changing_debt(econ: Economy, agent, amount: Money) -> None:
    """Give `agent` extra cash from a source independent of any loan, so a
    test can exercise the debt-insufficiency branch specifically rather
    than always tripping the cash-insufficiency branch first (both start
    out equal right after origination, since the loan is the only cash
    source otherwise)."""
    if isinstance(agent, Household):
        agent.receive_income(amount)
    elif isinstance(agent, Government):
        donor = econ.add_household("donor")
        donor.receive_income(amount)
        agent.collect_tax(donor, amount)
    else:  # pragma: no cover - defensive; only the two types above are parametrized
        raise TypeError(f"no top-up strategy for agent type {type(agent)!r}")


@pytest.fixture(params=["household", "government"])
def borrower(request):
    econ = Economy()
    bank = _capitalized_bank(econ)
    if request.param == "household":
        agent = econ.add_household("hh-1")
    else:
        agent = econ.add_government("gov-1")
    return econ, bank, agent


def test_origination_increases_borrower_cash_and_debt_identically(borrower) -> None:
    econ, bank, agent = borrower
    bank.originate_loan(agent, Money(500_00, "USD"))
    assert agent.cash_balance == Money(500_00, "USD")
    assert agent.debt_balance == Money(500_00, "USD")
    econ.check_integrity()


def test_repayment_reduces_borrower_debt_identically(borrower) -> None:
    econ, bank, agent = borrower
    bank.originate_loan(agent, Money(500_00, "USD"))
    bank.receive_repayment(agent, Money(200_00, "USD"))
    assert agent.debt_balance == Money(300_00, "USD")
    assert agent.cash_balance == Money(300_00, "USD")
    econ.check_integrity()


def test_overrepayment_rejected_identically(borrower) -> None:
    econ, bank, agent = borrower
    bank.originate_loan(agent, Money(100_00, "USD"))
    _top_up_cash_without_changing_debt(econ, agent, Money(50_00, "USD"))
    assert agent.cash_balance > agent.debt_balance

    with pytest.raises(ValueError):
        bank.receive_repayment(agent, agent.debt_balance + Money(1, "USD"))
