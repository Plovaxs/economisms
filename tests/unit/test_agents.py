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


def test_accrue_interest_capitalizes_into_the_loan_balance_and_bank_equity() -> None:
    """LED-05: unpaid interest compounds directly into both the
    borrower's liability and the bank's receivable; no cash moves, so the
    gain shows up entirely as a non-cash equity change on both sides."""
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    bank.originate_loan(hh, Money(1_000_00, "USD"))

    bank.accrue_interest(hh, annual_rate=0.12, dt=1 / 12)  # 1% of 1000.00 = 10.00

    assert hh.debt_balance == Money(1_010_00, "USD")
    assert bank.loans_outstanding == Money(1_010_00, "USD")
    assert bank.capital == Money(10_010_00, "USD")  # interest income
    assert hh.net_worth == Money(-10_00, "USD")  # interest expense
    econ.check_integrity()


def test_accrue_interest_compounds_across_multiple_periods() -> None:
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    bank.originate_loan(hh, Money(1_000_00, "USD"))

    for _ in range(3):
        bank.accrue_interest(hh, annual_rate=0.12, dt=1 / 12)

    # 1000.00 * 1.01^3 = 1030.301 -> rounds to 1030.30
    assert hh.debt_balance == Money(1_030_30, "USD")
    econ.check_integrity()


def test_accrue_interest_rejects_negative_rate() -> None:
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    bank.originate_loan(hh, Money(1_000_00, "USD"))
    with pytest.raises(ValueError):
        bank.accrue_interest(hh, annual_rate=-0.01, dt=1 / 12)


def test_accrue_interest_rejects_non_positive_dt() -> None:
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    bank.originate_loan(hh, Money(1_000_00, "USD"))
    with pytest.raises(ValueError):
        bank.accrue_interest(hh, annual_rate=0.1, dt=0)


def test_accrue_interest_rejects_an_amount_that_rounds_to_zero() -> None:
    """A zero (or negative-rate-cancelled) balance/rate/dt combination
    must raise a clear, specific error rather than silently posting an
    empty transaction or failing deep inside Posting's own validation."""
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    with pytest.raises(ValueError):
        bank.accrue_interest(hh, annual_rate=0.12, dt=1 / 12)  # zero balance


def test_write_off_loan_extinguishes_debt_and_reallocates_equity() -> None:
    """LED-06: the bank recognizes a realized loss (equity falls); the
    borrower's debt is forgiven (equity rises by the same amount) -- the
    accounting-correct counterpart, not merely a cash write-down."""
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    bank.originate_loan(hh, Money(1_000_00, "USD"))

    bank.write_off_loan(hh, Money(1_000_00, "USD"))

    assert hh.debt_balance == Money.zero("USD")
    assert bank.loans_outstanding == Money.zero("USD")
    assert bank.capital == Money(9_000_00, "USD")  # realized loss
    assert hh.net_worth == Money(1_000_00, "USD")  # debt forgiveness gain
    econ.check_integrity()


def test_write_off_loan_rejects_non_positive_amount() -> None:
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh = econ.add_household("hh-1")
    bank.originate_loan(hh, Money(1_000_00, "USD"))
    with pytest.raises(ValueError):
        bank.write_off_loan(hh, Money(-1, "USD"))


def test_write_off_loan_rejects_amount_exceeding_borrowers_own_balance() -> None:
    """Validated against the SPECIFIC borrower's own outstanding balance,
    not the bank's pooled aggregate across every borrower -- a second
    borrower's larger debt must not make this one's write-off succeed."""
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh1 = econ.add_household("hh-1")
    hh2 = econ.add_household("hh-2")
    bank.originate_loan(hh1, Money(300_00, "USD"))
    bank.originate_loan(hh2, Money(900_00, "USD"))  # larger, but a DIFFERENT borrower

    with pytest.raises(ValueError):
        bank.write_off_loan(hh1, Money(400_00, "USD"))

    assert hh1.debt_balance == Money(300_00, "USD")  # unchanged
    assert hh2.debt_balance == Money(900_00, "USD")  # unaffected either way


def test_write_off_loan_does_not_affect_a_different_borrowers_debt() -> None:
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    hh1 = econ.add_household("hh-1")
    hh2 = econ.add_household("hh-2")
    bank.originate_loan(hh1, Money(300_00, "USD"))
    bank.originate_loan(hh2, Money(900_00, "USD"))

    bank.write_off_loan(hh1, Money(300_00, "USD"))

    assert hh1.debt_balance == Money.zero("USD")
    assert hh2.debt_balance == Money(900_00, "USD")
    assert bank.loans_outstanding == Money(900_00, "USD")
    econ.check_integrity()


def test_government_borrower_supports_interest_accrual_and_write_off_too() -> None:
    """accrue_interest/write_off_loan are written against the Borrower
    protocol, exactly like originate_loan/receive_repayment -- Government
    goes through the identical code path as Household, not a separate
    mechanism."""
    econ = _economy_with_capitalized_bank(capital=10_000_00)
    bank = econ.banks["bank-1"]
    gov = econ.add_government("gov-1")
    bank.originate_loan(gov, Money(1_000_00, "USD"))

    bank.accrue_interest(gov, annual_rate=0.12, dt=1 / 12)
    assert gov.debt_balance == Money(1_010_00, "USD")

    bank.write_off_loan(gov, gov.debt_balance)
    assert gov.debt_balance == Money.zero("USD")
    econ.check_integrity()
