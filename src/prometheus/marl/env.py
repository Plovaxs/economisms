"""The household/firm circular-flow environment MAR-01/04/05/08/09/10/11/
12/13 all run against: one step is (1) the firm pays wages out of its own
cash, (2) the household consumes out of its own (now-larger) cash with
that same firm. Both actions are fraction-projected through
`feasibility.project_fraction_to_amount` before being posted through the
REAL `econosim.agents`/`core.ledger` methods, so every step is a real,
balanced, feasibility-checked ledger transaction -- not a parallel
toy-economy simulation that merely resembles one.

Rewards are read directly from the resulting real balance changes
(`StepReward`, `spaces.py`), never computed from a parallel running
total that could drift from what the ledger actually recorded.

`household_utility` is log(1 + consumption_in_major_units) each step,
PLUS, on the final step only, `bequest_weight * log(1 + ending net
worth)` -- a standard "warm glow" bequest-motive term (the household
values wealth left over at the end of the horizon, not only what it
consumed along the way). This term is not cosmetic: a direct numeric
sweep over fixed consumption fractions, run before this module was
finalized (see `test_mar_env.py`'s
`test_the_reward_design_has_a_genuine_interior_optimum_not_a_degenerate_one`),
found that WITHOUT it, total utility is strictly increasing in the
consumption fraction and is maximized at fraction=1.0 (spend
everything, every step) -- a degenerate, uninteresting "optimum" that
would have made MAR-04's "improvement checked against rule-based
counterfactuals" meaningless (an RL policy "learning" to spend more is
not evidence of anything). WITH `bequest_weight=1.0` (a modest, fixed,
disclosed weight -- not tuned to flatter any particular policy), the
same sweep finds a genuine interior optimum near fraction ~0.75-0.8:
spending too little forgoes current utility, spending too much leaves
nothing for the bequest term. `firm_profit` is the firm's own
net_worth delta this step (revenue from the household's consumption,
minus the wage expense just paid) -- the ledger already tracks this as
the firm's equity change; nothing here recomputes it independently.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from prometheus.core.money import Money
from prometheus.econosim.agents import Firm, Household
from prometheus.econosim.economy import Economy
from prometheus.marl.feasibility import project_fraction_to_amount
from prometheus.marl.spaces import (
    FirmAction,
    FirmObservation,
    HouseholdAction,
    HouseholdObservation,
    StepReward,
)

HouseholdPolicy = Callable[[HouseholdObservation], HouseholdAction]
FirmPolicy = Callable[[FirmObservation], FirmAction]


def household_observation(household: Household, step: int) -> HouseholdObservation:
    return HouseholdObservation(
        cash_balance_minor=household.cash_balance.minor_units,
        net_worth_minor=household.net_worth.minor_units,
        step=step,
    )


def firm_observation(firm: Firm, step: int) -> FirmObservation:
    return FirmObservation(
        cash_balance_minor=firm.cash_balance.minor_units,
        net_worth_minor=firm.net_worth.minor_units,
        step=step,
    )


@dataclass(frozen=True, slots=True)
class RolloutResult:
    rewards: tuple[StepReward, ...]
    final_household_net_worth_minor: int
    final_firm_net_worth_minor: int

    def total_household_utility(self) -> float:
        return sum(r.household_utility for r in self.rewards)

    def total_firm_profit(self) -> float:
        return sum(r.firm_profit for r in self.rewards)


DEFAULT_BEQUEST_WEIGHT = 1.0


def run_rollout(
    *,
    household_policy: HouseholdPolicy,
    firm_policy: FirmPolicy,
    n_steps: int,
    firm_opening_capital: Money,
    currency: str = "USD",
    bequest_weight: float = DEFAULT_BEQUEST_WEIGHT,
) -> RolloutResult:
    """One self-contained circular-flow episode: a fresh `Economy`, one
    household (zero opening cash -- it earns everything via wages) and
    one firm (capitalized with `firm_opening_capital`), stepped
    `n_steps` times. Deterministic given deterministic policies (both
    policy callables are pure functions of the observation; any
    randomness a caller wants belongs inside the policy closure, seeded
    by the caller -- this function itself draws no randomness of its
    own)."""
    if n_steps < 1:
        raise ValueError("n_steps must be >= 1")
    economy = Economy(currency=currency)
    household = economy.add_household("hh-0")
    firm = economy.add_firm("firm-0")
    firm.capitalize(firm_opening_capital, step=0)

    rewards: list[StepReward] = []
    for step in range(n_steps):
        firm_net_worth_before = firm.net_worth

        firm_action = firm_policy(firm_observation(firm, step))
        wage = project_fraction_to_amount(firm_action.wage_fraction, firm.cash_balance)
        if wage.is_positive():
            firm.pay_wages(household, wage, step=step)

        household_action = household_policy(household_observation(household, step))
        spend = project_fraction_to_amount(
            household_action.consumption_fraction, household.cash_balance
        )
        if spend.is_positive():
            household.consume(firm, spend, step=step)

        firm_net_worth_after = firm.net_worth
        consumption_major = spend.minor_units / 100.0
        household_utility = 0.0 if spend.is_zero() else math.log1p(consumption_major)
        if step == n_steps - 1:
            ending_net_worth_major = max(household.net_worth.minor_units, 0) / 100.0
            household_utility += bequest_weight * math.log1p(ending_net_worth_major)
        firm_profit = (
            firm_net_worth_after.minor_units - firm_net_worth_before.minor_units
        ) / 100.0
        rewards.append(StepReward(household_utility=household_utility, firm_profit=firm_profit))

    return RolloutResult(
        rewards=tuple(rewards),
        final_household_net_worth_minor=household.net_worth.minor_units,
        final_firm_net_worth_minor=firm.net_worth.minor_units,
    )
