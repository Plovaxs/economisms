import pytest

from prometheus.core.money import Money
from prometheus.econosim.agents import InsufficientFundsError
from prometheus.econosim.economy import Economy


def _economy_with_capitalized_bank(capital: int = 1_000_000_00) -> Economy:
    econ = Economy()
    bank = econ.add_bank("bank-1", max_leverage=10.0)
    bank.capitalize(Money(capital, "USD"))
    return econ


def test_collect_tax_moves_cash_and_equity_from_household_to_government() -> None:
    econ = Economy()
    gov = econ.add_government("gov-1")
    hh = econ.add_household("hh-1")
    hh.receive_income(Money(1000, "USD"))

    gov.collect_tax(hh, Money(300, "USD"))

    assert hh.cash_balance == Money(700, "USD")
    assert hh.net_worth == Money(700, "USD")
    assert gov.cash_balance == Money(300, "USD")
    assert gov.net_worth == Money(300, "USD")
    econ.check_integrity()


def test_collect_tax_more_than_household_cash_rejected() -> None:
    econ = Economy()
    gov = econ.add_government("gov-1")
    hh = econ.add_household("hh-1")
    hh.receive_income(Money(100, "USD"))
    with pytest.raises(InsufficientFundsError):
        gov.collect_tax(hh, Money(101, "USD"))


def test_pay_transfer_moves_cash_and_equity_from_government_to_household() -> None:
    econ = Economy()
    gov = econ.add_government("gov-1")
    hh = econ.add_household("hh-1")
    hh.receive_income(Money(1000, "USD"))
    gov.collect_tax(hh, Money(1000, "USD"))  # fund the government first

    gov.pay_transfer(hh, Money(400, "USD"))

    assert hh.cash_balance == Money(400, "USD")
    assert gov.cash_balance == Money(600, "USD")
    econ.check_integrity()


def test_pay_transfer_more_than_government_cash_rejected() -> None:
    econ = Economy()
    gov = econ.add_government("gov-1")
    hh = econ.add_household("hh-1")
    with pytest.raises(InsufficientFundsError):
        gov.pay_transfer(hh, Money(1, "USD"))


def test_government_issues_and_repays_bonds_through_the_bank() -> None:
    econ = _economy_with_capitalized_bank()
    bank = econ.banks["bank-1"]
    gov = econ.add_government("gov-1")

    gov.issue_bonds(bank, Money(500_00, "USD"))
    assert gov.cash_balance == Money(500_00, "USD")
    assert gov.debt_balance == Money(500_00, "USD")
    assert bank.loans_outstanding == Money(500_00, "USD")
    econ.check_integrity()

    gov.repay_bond(bank, Money(200_00, "USD"))
    assert gov.debt_balance == Money(300_00, "USD")
    assert bank.loans_outstanding == Money(300_00, "USD")
    econ.check_integrity()


def test_government_and_household_borrowing_share_the_same_leverage_cap() -> None:
    """ECO-09 must apply uniformly: a bank's capital constrains total
    lending across ALL borrower types combined, not per borrower type."""
    from prometheus.econosim.agents import CreditLimitExceededError

    econ = _economy_with_capitalized_bank(capital=100_00)  # max exposure = $1,000 at 10x
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    gov = econ.add_government("gov-1")

    bank.originate_loan(hh, Money(700_00, "USD"))
    gov.issue_bonds(bank, Money(250_00, "USD"))  # 700+250 = 950, still under 1000
    assert bank.loans_outstanding == Money(950_00, "USD")

    with pytest.raises(CreditLimitExceededError):
        gov.issue_bonds(bank, Money(100_00, "USD"))  # would push to 1050 > 1000
