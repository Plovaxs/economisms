"""MAR-06: "Implement bank underwriting and risk-limit agent -- Credit
risk and capital guardrails enforced in simulator."
MAR-07: "Provide central-bank controller sandbox with policy constraints
-- Agent cannot issue actions outside allowed policy set."

Both agents here are RULE-BASED, not gradient-learned, by deliberate
choice, not a shortfall: MAR-06/MAR-07's own requirement text says
"implement...agent"/"provide...sandbox", not "policy LEARNING" --
contrast MAR-04/MAR-05's explicit "policy learning" wording, which
`training.py`'s PPO trainer answers instead. A hard-constrained rule is
also the more defensible choice for exactly these two agents: a bank's
risk limit and a central bank's rate band are regulatory/structural
constraints a real institution enforces by policy, not something it
would want a black-box network discovering by trial and error.

Both guardrails are enforced BY CONSTRUCTION, the same pattern
`spaces.py`/`feasibility.py` already establish for the household/firm
actions: `RiskLimitedBankPolicy` outputs a `BankAction.lending_fraction`
that `feasibility.project_fraction_to_headroom` then turns into a
`Money` amount provably `<=` the bank's own real remaining headroom
(`core.ledger`-derived, via `econosim.agents.Bank`), and
`CentralBankAction.__post_init__` (`spaces.py`) hard-clips any proposed
rate into `[rate_min, rate_max]` unconditionally. `tests/property/
test_mar_action_feasibility.py` sweeps adversarial inputs through both.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.econosim.agents import Bank
from prometheus.marl.spaces import (
    BankAction,
    BankObservation,
    CentralBankAction,
    CentralBankObservation,
)


def bank_observation(bank: Bank) -> BankObservation:
    max_exposure_minor = int(bank.capital.minor_units * bank.max_leverage)
    headroom_minor = max(max_exposure_minor - bank.loans_outstanding.minor_units, 0)
    return BankObservation(
        capital_minor=bank.capital.minor_units,
        loans_outstanding_minor=bank.loans_outstanding.minor_units,
        headroom_minor=headroom_minor,
        max_leverage=bank.max_leverage,
    )


@dataclass(frozen=True, slots=True)
class RiskLimitedBankPolicy:
    """`lending_fraction = base_fraction * (1 - utilization)`, where
    utilization = loans_outstanding / (capital*max_leverage). A simple,
    disclosed linear risk-limit rule: at zero utilization the bank lends
    `base_fraction` of its headroom; as utilization approaches 1 (the
    leverage cap itself), the fraction it is willing to lend shrinks
    toward 0 -- the bank never deliberately pushes flush against its own
    cap, a real (if simple) risk-limiting behavior, not just a passive
    backstop that only stops the bank once it is already at the edge."""

    base_fraction: float = 0.5

    def __call__(self, observation: BankObservation) -> BankAction:
        max_exposure_minor = observation.capital_minor * observation.max_leverage
        utilization = (
            0.0
            if max_exposure_minor <= 0
            else min(observation.loans_outstanding_minor / max_exposure_minor, 1.0)
        )
        return BankAction(lending_fraction=self.base_fraction * (1.0 - utilization))


@dataclass(frozen=True, slots=True)
class TaylorRuleCentralBankPolicy:
    """A simplified Taylor-rule-style controller: moves the policy rate
    toward closing the gap between observed loan growth and a target,
    scaled by `responsiveness` -- a standard, disclosed simplification
    (a real Taylor rule also responds to an inflation gap and uses an
    equilibrium real rate term; this sandbox's only real-activity
    signal is loan growth, so that is what the rule responds to).
    `CentralBankAction`'s own construction (`spaces.py`) is what
    actually enforces MAR-07's policy-set constraint -- this rule can
    propose anything; what the agent can ISSUE is bounded regardless."""

    target_loan_growth: float = 0.0
    responsiveness: float = 0.5
    rate_min: float = 0.0
    rate_max: float = 0.20

    def __call__(self, observation: CentralBankObservation) -> CentralBankAction:
        gap = observation.loan_growth - self.target_loan_growth
        proposed_rate = observation.policy_rate + self.responsiveness * gap
        return CentralBankAction(
            policy_rate=proposed_rate, rate_min=self.rate_min, rate_max=self.rate_max
        )
