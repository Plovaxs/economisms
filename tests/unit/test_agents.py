import pytest

from prometheus.core.money import Money
from prometheus.econosim.agents import CreditLimitExceededError, InsufficientFundsError
from prometheus.econosim.economy import Economy


def _economy_with_capitalized_bank(capital: int = 100_000, max_leverage: float = 10.0) -> Economy:
    econ = Economy()
    bank = econ.add_bank("bank-1", max_leverage=max_leverage)
    bank.capitalize(Money(capital, "USD"))
    return econ


def test_household_receive_income_and_consume() -> None:
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")

    hh.receive_income(Money(1000, "USD"))
    assert hh.cash_balance == Money(1000, "USD")
    assert hh.net_worth == Money(1000, "USD")

    hh.consume(firm, Money(400, "USD"))
    assert hh.cash_balance == Money(600, "USD")
    assert hh.net_worth == Money(600, "USD")
    assert firm.cash_balance == Money(400, "USD")
    assert firm.net_worth == Money(400, "USD")

    econ.check_integrity()  # whole economy still balances sector by sector


def test_consume_more_than_cash_balance_raises_and_does_not_mutate() -> None:
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    hh.receive_income(Money(100, "USD"))

    with pytest.raises(InsufficientFundsError):
        hh.consume(firm, Money(101, "USD"))

    assert hh.cash_balance == Money(100, "USD")
    assert firm.cash_balance == Money(0, "USD")


def test_consume_rejects_non_positive_amount() -> None:
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    with pytest.raises(ValueError):
        hh.consume(firm, Money(0, "USD"))


def test_firm_pays_wages() -> None:
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    firm.deposit_account  # noqa: B018 - accessed for clarity only
    # seed the firm with cash via a household purchase first
    hh.receive_income(Money(1000, "USD"))
    hh.consume(firm, Money(1000, "USD"))

    firm.pay_wages(hh, Money(300, "USD"))
    assert firm.cash_balance == Money(700, "USD")
    assert hh.cash_balance == Money(300, "USD")
    econ.check_integrity()


def test_bank_capitalize_then_originate_loan() -> None:
    econ = _economy_with_capitalized_bank(capital=1_000_00)  # $1,000.00
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")

    bank.originate_loan(hh, Money(500_00, "USD"))

    assert hh.cash_balance == Money(500_00, "USD")
    assert hh.debt_balance == Money(500_00, "USD")
    assert bank.loans_outstanding == Money(500_00, "USD")
    econ.check_integrity()


def test_loan_origination_blocked_beyond_leverage_cap() -> None:
    econ = _economy_with_capitalized_bank(capital=100_00, max_leverage=2.0)  # cap = $200
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")

    with pytest.raises(CreditLimitExceededError):
        bank.originate_loan(hh, Money(201_00, "USD"))

    assert hh.cash_balance == Money(0, "USD")
    assert bank.loans_outstanding == Money(0, "USD")


def test_loan_repayment_reduces_debt_and_bank_assets() -> None:
    econ = _economy_with_capitalized_bank(capital=1_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    bank.originate_loan(hh, Money(500_00, "USD"))

    hh.repay_loan(bank, Money(200_00, "USD"))

    assert hh.debt_balance == Money(300_00, "USD")
    assert hh.cash_balance == Money(300_00, "USD")
    assert bank.loans_outstanding == Money(300_00, "USD")
    econ.check_integrity()


def test_repay_more_than_outstanding_debt_rejected() -> None:
    """Exercise the debt-insufficiency branch specifically (as opposed to
    the cash-insufficiency branch): the household has plenty of cash, just
    not that much outstanding debt to repay."""
    econ = _economy_with_capitalized_bank(capital=1_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    bank.originate_loan(hh, Money(100_00, "USD"))
    hh.receive_income(Money(50_00, "USD"))
    assert hh.cash_balance > hh.debt_balance

    with pytest.raises(ValueError):
        hh.repay_loan(bank, hh.debt_balance + Money(1, "USD"))
