"""LED-12 / VAL-07: randomized transaction sequences must preserve the
ledger's accounting identities, and total economy-wide equity must equal
exactly the sum of all exogenous injections (receive_income, capitalize) --
every other operation here is a zero-sum transfer of existing claims between
agents, so nothing should ever be created or destroyed outside those two
entry points.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.core.money import Money
from prometheus.econosim.agents import CreditLimitExceededError, InsufficientFundsError
from prometheus.econosim.economy import Economy

ACTION_KINDS = (
    "income",
    "consume",
    "wages",
    "loan",
    "repay",
    "tax",
    "transfer",
    "gov_loan",
    "gov_repay",
)


@st.composite
def action_sequences(draw: st.DrawFn) -> list[tuple[str, int, int, int]]:
    n_actions = draw(st.integers(min_value=1, max_value=40))
    actions = []
    for _ in range(n_actions):
        kind = draw(st.sampled_from(ACTION_KINDS))
        amount_cents = draw(st.integers(min_value=1, max_value=100_000))
        actor_idx = draw(st.integers(min_value=0, max_value=2))
        counterpart_idx = draw(st.integers(min_value=0, max_value=2))
        actions.append((kind, amount_cents, actor_idx, counterpart_idx))
    return actions


@settings(max_examples=100)
@given(action_sequences())
def test_random_action_sequences_preserve_identities_and_total_equity(
    actions: list[tuple[str, int, int, int]],
) -> None:
    econ = Economy()
    households = [econ.add_household(f"hh-{i}") for i in range(3)]
    firms = [econ.add_firm(f"firm-{i}") for i in range(3)]
    bank = econ.add_bank("bank-1", max_leverage=5.0)
    government = econ.add_government("gov-1")

    injected = Money.zero("USD")
    seed_capital = Money(100_000_00, "USD")
    bank.capitalize(seed_capital)
    injected += seed_capital

    for kind, amount_cents, i, j in actions:
        amount = Money(amount_cents, "USD")
        hh = households[i % len(households)]
        firm = firms[j % len(firms)]
        try:
            if kind == "income":
                hh.receive_income(amount)
                injected += amount
            elif kind == "consume":
                hh.consume(firm, amount)
            elif kind == "wages":
                firm.pay_wages(hh, amount)
            elif kind == "loan":
                bank.originate_loan(hh, amount)
            elif kind == "repay":
                hh.repay_loan(bank, amount)
            elif kind == "tax":
                government.collect_tax(hh, amount)
            elif kind == "transfer":
                government.pay_transfer(hh, amount)
            elif kind == "gov_loan":
                government.issue_bonds(bank, amount)
            elif kind == "gov_repay":
                government.repay_bond(bank, amount)
        except (InsufficientFundsError, CreditLimitExceededError, ValueError):
            pass  # an infeasible action must be rejected, not silently clamped

        # every single posted transaction must leave every sector balanced
        econ.check_integrity()

    total_equity = (
        sum((h.net_worth for h in households), start=Money.zero("USD"))
        + sum((f.net_worth for f in firms), start=Money.zero("USD"))
        + bank.capital
        + government.net_worth
    )
    assert total_equity == injected
