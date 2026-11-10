from __future__ import annotations

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.marl.feasibility import project_fraction_to_headroom
from prometheus.marl.policies import (
    RiskLimitedBankPolicy,
    TaylorRuleCentralBankPolicy,
    bank_observation,
)
from prometheus.marl.spaces import BankObservation, CentralBankObservation


def test_bank_observation_reports_real_headroom_from_the_real_ledger() -> None:
    economy = Economy()
    bank = economy.add_bank("bank-0", max_leverage=5.0)
    bank.capitalize(Money(10_000, "USD"))
    obs = bank_observation(bank)
    assert obs.capital_minor == 10_000
    assert obs.loans_outstanding_minor == 0
    assert obs.headroom_minor == 50_000  # 10,000 * 5.0 leverage, nothing lent yet
    assert obs.max_leverage == 5.0


def test_risk_limited_bank_policy_never_proposes_a_loan_the_real_bank_cannot_originate() -> None:
    """MAR-06: drive a real Bank through many steps, each time asking
    `RiskLimitedBankPolicy` for a lending fraction and feeding the
    projected amount through the REAL `Bank.originate_loan` -- the
    guardrail must never raise `CreditLimitExceededError`, demonstrated
    against the real ledger, not merely asserted of the projection in
    isolation (that half is `test_mar_action_feasibility.py`'s job)."""
    economy = Economy()
    bank = economy.add_bank("bank-0", max_leverage=4.0)
    bank.capitalize(Money(100_000, "USD"))
    policy = RiskLimitedBankPolicy(base_fraction=0.9)

    for step in range(30):
        borrower = economy.add_household(f"hh-{step}")
        obs = bank_observation(bank)
        action = policy(obs)
        headroom = Money(obs.headroom_minor, "USD")
        loan = project_fraction_to_headroom(action.lending_fraction, headroom)
        if loan.is_positive():
            bank.originate_loan(borrower, loan, step=step)  # must never raise

    max_exposure = bank.capital.minor_units * bank.max_leverage
    utilization = bank.loans_outstanding.minor_units / max_exposure
    assert 0.0 <= utilization < 1.0  # approaches, never reaches or exceeds, the cap


def test_risk_limited_bank_policy_lending_fraction_shrinks_as_utilization_rises() -> None:
    policy = RiskLimitedBankPolicy(base_fraction=0.8)
    low = policy(
        BankObservation(
            capital_minor=10_000, loans_outstanding_minor=0, headroom_minor=50_000, max_leverage=5.0
        )
    )
    high = policy(
        BankObservation(
            capital_minor=10_000,
            loans_outstanding_minor=45_000,
            headroom_minor=5_000,
            max_leverage=5.0,
        )
    )
    assert high.lending_fraction < low.lending_fraction


def test_taylor_rule_central_bank_raises_the_rate_when_loan_growth_exceeds_target() -> None:
    policy = TaylorRuleCentralBankPolicy(target_loan_growth=0.0, responsiveness=0.5)
    obs = CentralBankObservation(policy_rate=0.03, loan_growth=0.04, step=0)
    action = policy(obs)
    assert action.policy_rate > 0.03


def test_taylor_rule_central_bank_stays_within_its_band_for_a_huge_gap() -> None:
    policy = TaylorRuleCentralBankPolicy(
        target_loan_growth=0.0, responsiveness=100.0, rate_min=0.0, rate_max=0.20
    )
    obs = CentralBankObservation(policy_rate=0.03, loan_growth=50.0, step=0)
    action = policy(obs)
    assert 0.0 <= action.policy_rate <= 0.20
