"""Households: a fat-tailed wealth distribution, income, unemployment, saving and portfolio choice.

Households above the participation rank hold the allocation rule's portfolio; the rest hold cash
(deposits). Unemployment falls disproportionately on the lower half of the wealth distribution.
Wealth is nominal; real quantities divide by the world's price level.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.worldsim.allocation import weights_for
from prometheus.worldsim.config import HouseholdParams
from prometheus.worldsim.inequality import gini, shares
from prometheus.worldsim.world import WorldPath


@dataclass(frozen=True, slots=True)
class HouseholdResult:
    rule: str
    gini: np.ndarray
    top10_share: np.ndarray
    bottom50_share: np.ndarray
    mean_real_wealth: np.ndarray
    portfolio_value: np.ndarray  # one unit invested in the rule at month 0, no savings
    final_real_wealth_participants: float
    final_real_wealth_others: float


def simulate_households(
    path: WorldPath, rule: str, params: HouseholdParams, seed: int
) -> HouseholdResult:
    rng = np.random.default_rng(seed + 10_000_019)
    n_households, n_months = params.n_households, path.n_months
    z = rng.standard_normal(n_households)
    wealth = params.mean_monthly_income * 12.0 * np.exp(params.wealth_log_sigma * z)
    rho = params.income_wealth_correlation
    income_z = rho * z + np.sqrt(1.0 - rho**2) * rng.standard_normal(n_households)
    income = np.exp(params.income_log_sigma * income_z)
    income *= params.mean_monthly_income / income.mean()
    rank = (np.argsort(np.argsort(wealth)) + 0.5) / n_households
    participant = rank >= params.participation_rank
    exposure = np.where(rank < 0.5, 2.0, 0.5)
    uniforms = rng.random((n_months, n_households))
    consumption_rate: float | np.ndarray = params.consumption_rate
    premium = np.zeros(n_households)
    if params.heterogeneous:
        consumption_rate = np.clip(
            params.consumption_rate + params.saving_rank_slope * (0.5 - rank), 0.5, 1.0
        )
        premium = params.top_return_premium * np.clip((rank - 0.9) / 0.1, 0.0, 1.0)

    gini_path = np.zeros(n_months)
    top10 = np.zeros(n_months)
    bottom50 = np.zeros(n_months)
    mean_real = np.zeros(n_months)
    portfolio = np.ones(n_months)
    returns = path.asset_returns
    for t in range(n_months):
        if t > 0:
            weights = weights_for(rule, returns[:t])
            portfolio_return = float(weights @ returns[t])
            portfolio[t] = portfolio[t - 1] * (1.0 + portfolio_return)
            jobless = uniforms[t] < path.unemployment[t] / 100.0 * exposure
            earned = np.where(jobless, params.unemployment_benefit * income, income)
            spend = np.minimum(
                consumption_rate * earned + params.wealth_consumption * wealth,
                earned + 0.05 * wealth,
            )
            growth = np.where(participant, portfolio_return + premium, returns[t, 3])
            wealth = np.clip(wealth * (1.0 + growth) + earned - spend, 0.0, None)
            income = income * (1.0 + path.inflation[t] / 1200.0)
        gini_path[t] = gini(wealth)
        top10[t], bottom50[t] = shares(wealth)
        mean_real[t] = float(wealth.mean() / path.price_level[t])
    real = wealth / path.price_level[-1]
    return HouseholdResult(
        rule=rule,
        gini=gini_path,
        top10_share=top10,
        bottom50_share=bottom50,
        mean_real_wealth=mean_real,
        portfolio_value=portfolio,
        final_real_wealth_participants=float(real[participant].mean()),
        final_real_wealth_others=float(real[~participant].mean()),
    )
