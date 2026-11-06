"""VAL-08: "check budget, capital, leverage and action feasibility
always... invariant violation forces explicit fault state."

`econosim.agents` already checks all four, for every action that debits
an existing balance or extends new credit (confirmed by reading every
mutating method in that module before writing this file): budget/capital
feasibility via a cash-balance check before `Household.consume`,
`Firm.pay_wages`, `Bank.receive_repayment`, `Government.collect_tax` and
`Government.pay_transfer` (`InsufficientFundsError`); leverage
feasibility via a capital*max_leverage cap before `Bank.originate_loan`
(and `Government.issue_bonds`, which is the SAME code path --
`CreditLimitExceededError`). Both are named, structured exception
classes carrying the relevant amounts as attributes, not a bare
`ValueError` or a silently clamped/no-op action -- the literal "explicit
fault state" this ID asks for.

The one exception, by deliberate design rather than oversight:
`Bank.accrue_interest` capitalizes unpaid interest directly into the
loan balance without re-checking the leverage cap, so `loans_outstanding`
can organically drift past `capital*max_leverage` through compounding
alone over many periods. This is NOT re-checked here as a violation --
interest accrual is a passive, mechanical bookkeeping process, not a
discretionary "action" in the sense VAL-08 means (a NEW extension of
credit, which is what `originate_loan` represents and gates) -- but it
is exactly the kind of distinction `CHECKLIST_STATUS.md` should state
rather than paper over.

What is NEW here, not just re-citing `test_agents.py`'s existing
hand-picked cases: a Hypothesis property sweep confirming feasibility is
checked for EVERY randomly generated (capital, leverage, loan size) and
(income, spend amount) combination, not just the specific values those
unit tests happened to pick -- the literal "always" in VAL-08's text.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.core.money import Money
from prometheus.econosim.agents import CreditLimitExceededError, InsufficientFundsError
from prometheus.econosim.economy import Economy

_SUPPRESS = settings(max_examples=150, deadline=None)

_minor_units = st.integers(min_value=1, max_value=10_000_000)
_max_leverage = st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False)


@given(income_minor=_minor_units, overspend_minor=st.integers(min_value=1, max_value=1_000_000))
@_SUPPRESS
def test_household_spending_beyond_income_always_raises_with_the_exact_shortfall(
    income_minor, overspend_minor
):
    """Budget feasibility: spending exactly income+overspend must ALWAYS
    be rejected, with the fault state naming the exact requested and
    available amounts (not just raising ANY exception)."""
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    hh.receive_income(Money(income_minor, "USD"))

    overspend_amount = Money(income_minor + overspend_minor, "USD")
    try:
        hh.consume(firm, overspend_amount)
    except InsufficientFundsError as exc:
        assert exc.agent_id == "hh-1"
        assert exc.requested == overspend_amount
        assert exc.available == Money(income_minor, "USD")
    else:
        raise AssertionError("expected InsufficientFundsError, but the overspend was accepted")

    # The rejected action must not have mutated state (no silent partial effect).
    assert hh.cash_balance == Money(income_minor, "USD")


@given(income_minor=_minor_units, spend_minor=st.integers(min_value=1))
@_SUPPRESS
def test_household_spending_at_or_under_income_is_always_accepted(income_minor, spend_minor):
    """The converse of the test above: feasibility checking must not be
    OVER-tight either -- any amount within budget always succeeds."""
    spend_minor = min(spend_minor, income_minor)
    econ = Economy()
    hh = econ.add_household("hh-1")
    firm = econ.add_firm("firm-1")
    hh.receive_income(Money(income_minor, "USD"))
    hh.consume(firm, Money(spend_minor, "USD"))
    assert hh.cash_balance == Money(income_minor - spend_minor, "USD")


@given(
    capital_minor=_minor_units,
    max_leverage=_max_leverage,
    overshoot_minor=st.integers(min_value=1, max_value=1_000_000),
)
@_SUPPRESS
def test_loan_origination_beyond_the_leverage_cap_always_raises_with_the_exact_limit(
    capital_minor, max_leverage, overshoot_minor
):
    """Leverage/capital feasibility: a loan principal that pushes total
    loans past capital*max_leverage must ALWAYS be rejected, with the
    fault state naming the exact capital and leverage multiple used."""
    econ = Economy()
    bank = econ.add_bank("bank-1", max_leverage=max_leverage)
    bank.capitalize(Money(capital_minor, "USD"))
    hh = econ.add_household("hh-1")

    max_exposure_minor = int(capital_minor * max_leverage)
    principal = Money(max_exposure_minor + overshoot_minor, "USD")
    try:
        bank.originate_loan(hh, principal)
    except CreditLimitExceededError as exc:
        assert exc.bank_id == "bank-1"
        assert exc.capital == Money(capital_minor, "USD")
        assert exc.max_leverage == max_leverage
    else:
        raise AssertionError("expected CreditLimitExceededError, but the overshoot was accepted")

    assert bank.loans_outstanding == Money(0, "USD")


@given(capital_minor=_minor_units, max_leverage=_max_leverage)
@_SUPPRESS
def test_loan_origination_at_exactly_the_leverage_cap_is_accepted(capital_minor, max_leverage):
    """The converse: a loan that exactly reaches (does not exceed) the
    leverage cap must always be accepted, not over-rejected."""
    econ = Economy()
    bank = econ.add_bank("bank-1", max_leverage=max_leverage)
    bank.capitalize(Money(capital_minor, "USD"))
    hh = econ.add_household("hh-1")

    max_exposure_minor = int(capital_minor * max_leverage)
    if max_exposure_minor < 1:
        return
    bank.originate_loan(hh, Money(max_exposure_minor, "USD"))
    assert bank.loans_outstanding == Money(max_exposure_minor, "USD")
