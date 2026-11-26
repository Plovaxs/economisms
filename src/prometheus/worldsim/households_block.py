"""The household sector inside the world: the part that feeds back into output, the budget and the
banks.

Unlike `households.simulate_households` (which replays a finished world under one allocation rule),
this block runs month by month inside `simulate_world` when `LinkParams.enabled`. Households hold a
fixed passive portfolio. Each month it reports aggregate consumption (which moves next month's
output gap), the taxes and transfers the government collects and pays (which move its budget), and
the distribution of wealth. Bank failures reach it through uninsured deposits held by the
wealthiest households.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.worldsim.config import HouseholdParams, LinkParams
from prometheus.worldsim.inequality import gini, shares


@dataclass(frozen=True, slots=True)
class HouseholdFlow:
    consumption: float
    tax_share: float
    transfer_share: float
    gini: float
    top10_share: float
    bottom50_share: float
    mean_wealth: float
    income: float = 0.0


class AggregateHouseholds:
    def __init__(
        self,
        params: HouseholdParams,
        links: LinkParams,
        tax_rate: float,
        seed: int,
        n_months: int,
    ) -> None:
        rng = np.random.default_rng(seed + 10_000_019)
        n = params.n_households
        z = rng.standard_normal(n)
        self.wealth = params.mean_monthly_income * 12.0 * np.exp(params.wealth_log_sigma * z)
        rho = params.income_wealth_correlation
        income_z = rho * z + np.sqrt(1.0 - rho**2) * rng.standard_normal(n)
        income = np.exp(params.income_log_sigma * income_z)
        self.income = income * (params.mean_monthly_income / income.mean())
        self.rank = (np.argsort(np.argsort(self.wealth)) + 0.5) / n
        self.participant = self.rank >= params.participation_rank
        self.exposure = np.where(self.rank < 0.5, 2.0, 0.5)
        self.uniforms = rng.random((n_months, n))
        self.params, self.links, self.tax_rate = params, links, tax_rate
        self.weights = np.array(links.market_portfolio, dtype=np.float64)
        self.consumption_rate: float | np.ndarray = params.consumption_rate
        self.premium = np.zeros(n)
        if params.heterogeneous:
            self.consumption_rate = np.clip(
                params.consumption_rate + params.saving_rank_slope * (0.5 - self.rank), 0.5, 1.0
            )
            self.premium = params.top_return_premium * np.clip((self.rank - 0.9) / 0.1, 0.0, 1.0)
        self.income_growth = (
            params.top_income_growth / 1200.0 * np.clip((self.rank - 0.5) / 0.5, 0.0, 1.0) ** 2
        )
        self.depositors = self.rank >= 1.0 - links.top_depositor_share

    def snapshot(self) -> HouseholdFlow:
        top10, bottom50 = shares(self.wealth)
        return HouseholdFlow(
            consumption=0.0,
            tax_share=0.0,
            transfer_share=0.0,
            gini=gini(self.wealth),
            top10_share=top10,
            bottom50_share=bottom50,
            mean_wealth=float(self.wealth.mean()),
            income=float(self.income.sum()),
        )

    def step(
        self,
        t: int,
        asset_returns: np.ndarray,
        inflation: float,
        unemployment: float,
        deposit_loss_rate: float,
        spend_shock: float,
    ) -> HouseholdFlow:
        params, links = self.params, self.links
        jobless = self.uniforms[t] < unemployment / 100.0 * self.exposure
        self.income = self.income * (1.0 + inflation / 1200.0 + self.income_growth)
        employed = np.where(jobless, 0.0, self.income)
        benefit = np.where(jobless, params.unemployment_benefit * self.income, 0.0)
        mean_employed = max(float(employed.sum()) / max(int((~jobless).sum()), 1), 1e-12)
        tax = self.tax_rate * employed * (employed / mean_employed) ** links.tax_progressivity
        wealth_tax = np.zeros_like(self.wealth)
        if links.wealth_tax_rate > 0.0:
            floor = links.wealth_tax_threshold * float(self.wealth.mean())
            wealth_tax = links.wealth_tax_rate / 12.0 * np.maximum(self.wealth - floor, 0.0)
        disposable = employed - tax + benefit
        spend = np.minimum(
            self.consumption_rate * disposable + params.wealth_consumption * self.wealth,
            disposable + 0.05 * self.wealth,
        ) * (1.0 - spend_shock)
        portfolio = float(self.weights @ asset_returns)
        growth = np.where(self.participant, portfolio + self.premium, asset_returns[3])
        self.wealth = np.clip(
            self.wealth * (1.0 + growth) + disposable - spend - wealth_tax, 0.0, None
        )
        if deposit_loss_rate > 0.0:
            hit = params.deposit_wealth_share * deposit_loss_rate
            self.wealth = np.where(self.depositors, self.wealth * (1.0 - hit), self.wealth)
        total_income = float(self.income.sum())
        top10, bottom50 = shares(self.wealth)
        return HouseholdFlow(
            consumption=float(spend.sum()),
            tax_share=float((tax.sum() + wealth_tax.sum()) / total_income),
            transfer_share=float(benefit.sum() / total_income),
            gini=gini(self.wealth),
            top10_share=top10,
            bottom50_share=bottom50,
            mean_wealth=float(self.wealth.mean()),
            income=total_income,
        )
