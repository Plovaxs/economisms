"""The exogenous path of the world: regimes, macro variables, asset returns and the banks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from prometheus.worldsim.banks import initial_banks, step_banks
from prometheus.worldsim.config import CRISIS, Shock, WorldConfig
from prometheus.worldsim.households_block import AggregateHouseholds, HouseholdFlow


@dataclass(frozen=True, slots=True)
class WorldPath:
    config_name: str
    seed: int
    regime: np.ndarray
    output_gap: np.ndarray
    inflation: np.ndarray
    policy_rate: np.ndarray
    unemployment: np.ndarray
    asset_returns: np.ndarray  # columns: equity, bond, real, cash (monthly, decimal)
    price_level: np.ndarray
    bank_capital_ratio: np.ndarray
    bank_failed: np.ndarray
    bank_constrained: np.ndarray
    new_failures: np.ndarray
    contagion_defaults: np.ndarray
    fire_sale_volume: np.ndarray
    credit_crunch: np.ndarray
    total_loans: np.ndarray
    firm_leverage: np.ndarray
    debt_ratio: np.ndarray
    sovereign_spread: np.ndarray
    fx_level: np.ndarray  # log exchange rate, up = domestic currency weaker
    injection: np.ndarray
    liquidity_support: np.ndarray
    gini: np.ndarray
    top10_share: np.ndarray
    bottom50_share: np.ndarray
    consumption: np.ndarray
    tax_share: np.ndarray
    sovereign_default: np.ndarray
    deposit_insurance_cost: np.ndarray
    uninsured_loss: np.ndarray

    @property
    def n_months(self) -> int:
        return int(self.regime.size)


def _correlation(config: WorldConfig, regime: int) -> np.ndarray:
    m = config.market
    eb, er, br = m.equity_bond_corr[regime], m.equity_real_corr[regime], m.bond_real_corr[regime]
    return np.array([[1.0, eb, er], [eb, 1.0, br], [er, br, 1.0]])


def simulate_world(config: WorldConfig, seed: int, shocks: Sequence[Shock] = ()) -> WorldPath:
    rng = np.random.default_rng(seed)
    n = config.n_months
    macro, market = config.macro, config.market

    regime = np.zeros(n, dtype=np.int64)
    for t in range(1, n):
        regime[t] = rng.choice(3, p=config.transition[regime[t - 1]])
    eps_y = rng.standard_normal(n)
    eps_pi = rng.standard_normal(n)
    supply = (
        (rng.random(n) < macro.supply_shock_probability)
        * rng.choice([-1.0, 1.0], size=n)
        * macro.supply_shock_size
    )
    asset_noise = rng.standard_normal((n, 3))
    jump_scale = rng.uniform(0.5, 1.5, size=n)
    cholesky = [np.linalg.cholesky(_correlation(config, r)) for r in range(3)]

    ext_rng = np.random.default_rng(seed + 7_000_003)
    fx_noise = ext_rng.standard_normal(n)
    fx_jump = ext_rng.uniform(0.5, 1.5, size=n)
    firms, fiscal, foreign, policy = config.firms, config.fiscal, config.foreign, config.policy
    links = config.links
    link_rng = np.random.default_rng(seed + 9_000_011)
    default_draw = link_rng.random(n)
    events: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for shock_event in shocks:
        events[shock_event.month].append((shock_event.kind, shock_event.size))
    block: AggregateHouseholds | None = None
    flow: HouseholdFlow | None = None
    if links.enabled:
        block = AggregateHouseholds(config.households, links, fiscal.tax_rate, seed, n)
        flow = block.snapshot()

    banks = initial_banks(config.banks, rng)
    n_banks = config.banks.n_banks

    y = np.zeros(n)
    pi = np.full(n, macro.inflation_target)
    rate = np.full(n, macro.neutral_real_rate + macro.inflation_target)
    unemployment = np.full(n, config.households.base_unemployment)
    returns = np.zeros((n, 4))
    price_level = np.ones(n)
    ratio = np.zeros((n, n_banks))
    failed = np.zeros((n, n_banks), dtype=bool)
    constrained = np.zeros((n, n_banks), dtype=bool)
    new_failures = np.zeros(n, dtype=np.int64)
    contagion = np.zeros(n, dtype=np.int64)
    fire_sale = np.zeros(n)
    crunch = np.zeros(n)
    loans = np.zeros(n)
    initial = banks.equity / np.maximum(banks.assets, 1e-9)
    ratio[0], loans[0] = initial, banks.loans.sum()
    impact = 0.0
    leverage = np.full(n, firms.initial_leverage)
    debt = np.full(n, fiscal.initial_debt)
    spread = np.zeros(n)
    fx = np.zeros(n)
    injection = np.zeros(n)
    liquidity = np.zeros(n)
    cumulative_injection = 0.0
    gini_path = np.zeros(n)
    top10_path = np.zeros(n)
    bottom50_path = np.zeros(n)
    consumption = np.zeros(n)
    tax_share = np.zeros(n)
    default_event = np.zeros(n, dtype=bool)
    insurance_cost = np.zeros(n)
    uninsured = np.zeros(n)
    if flow is not None:
        gini_path[0], top10_path[0], bottom50_path[0] = (
            flow.gini,
            flow.top10_share,
            flow.bottom50_share,
        )
    transfer_reference: float | None = None
    excluded_until = 0
    default_premium = 0.0
    demand_gap = 0.0
    real_consumption_trend = 0.0

    for t in range(1, n):
        todays = events.get(t, [])
        shock_size = {kind: size for kind, size in todays}
        r = int(regime[t])
        real_rate = rate[t - 1] - pi[t - 1]
        depreciation = 0.0
        if foreign.enabled:
            depreciation = (
                -foreign.carry_response * (rate[t - 1] - foreign.foreign_rate) / 1200.0
                + foreign.fx_volatility[r] * fx_noise[t]
            )
            if r == CRISIS and regime[t - 1] != CRISIS:
                depreciation += foreign.crisis_depreciation * fx_jump[t]
            fx[t] = fx[t - 1] + depreciation
        if "fx_crash" in shock_size:
            depreciation += shock_size["fx_crash"]
            fx[t] = fx[t - 1] + depreciation
        default_now = False
        if links.enabled and links.sovereign_default and fiscal.enabled and t >= excluded_until:
            hazard = min(0.5, links.hazard_slope * max(0.0, debt[t - 1] - links.default_threshold))
            default_now = bool(default_draw[t] < hazard) or "sovereign_default" in shock_size
        elif "sovereign_default" in shock_size and fiscal.enabled and links.enabled:
            default_now = True
        debt_before = debt[t - 1]
        if default_now:
            debt_before = debt[t - 1] * (1.0 - links.haircut)
            excluded_until = t + links.exclusion_months
            default_premium += links.default_spread_jump
            default_event[t] = True
            depreciation += links.default_fx_jump
            fx[t] = fx[t - 1] + depreciation
        spending = fiscal.spending_share
        if fiscal.enabled:
            spending = (
                fiscal.spending_share
                - fiscal.countercyclical * y[t - 1] / 100.0
                - (fiscal.austerity_cut if debt[t - 1] > fiscal.austerity_threshold else 0.0)
            )
            if links.enabled and transfer_reference is not None and flow is not None:
                spending += flow.transfer_share - transfer_reference
            if links.enabled and t < excluded_until:
                spending = min(spending, tax_share[t - 1] if tax_share[t - 1] > 0.0 else spending)
        extension_output = (
            -firms.output_drag * (leverage[t - 1] - firms.initial_leverage) * firms.enabled
            + fiscal.impulse_scale * fiscal.multiplier * 100.0 * (spending - fiscal.spending_share)
            + foreign.trade_effect * depreciation * 100.0
            + links.demand_coupling * 100.0 * demand_gap * links.enabled
            + (links.default_output_shock if default_now else 0.0)
        )
        y[t] = (
            macro.output_persistence * y[t - 1]
            - macro.rate_sensitivity * (real_rate - macro.neutral_real_rate)
            + macro.regime_output_shift[r]
            + macro.regime_output_vol[r] * eps_y[t]
            - macro.credit_crunch_drag * crunch[t - 1]
            + extension_output
        )
        pi[t] = (
            macro.inflation_persistence * pi[t - 1]
            + (1.0 - macro.inflation_persistence) * macro.inflation_target
            + macro.phillips_slope * y[t]
            + macro.inflation_vol * eps_pi[t]
            + supply[t]
            + foreign.inflation_pass_through * depreciation * 100.0
            + shock_size.get("supply_shock", 0.0)
        )
        target = (
            macro.neutral_real_rate
            + pi[t]
            + macro.taylor_phi_pi * (pi[t] - macro.inflation_target)
            + macro.taylor_phi_y * y[t]
            + links.financial_stability_phi * (leverage[t - 1] - firms.initial_leverage) * 100.0
        )
        rate[t] = float(
            np.clip(
                macro.rate_smoothing * rate[t - 1]
                + (1.0 - macro.rate_smoothing) * target
                + shock_size.get("rate_hike", 0.0),
                0.0,
                macro.rate_max,
            )
        )
        firm_multiplier = float(
            np.exp(firms.default_sensitivity * (leverage[t - 1] - firms.initial_leverage))
            if firms.enabled
            else 1.0
        )
        unemployment[t] = float(
            np.clip(
                config.households.base_unemployment
                - config.households.okun * y[t]
                + (links.firm_unemployment * (firm_multiplier - 1.0) if links.enabled else 0.0),
                3.0,
                15.0,
            )
        )
        price_level[t] = price_level[t - 1] * (1.0 + pi[t] / 1200.0)

        shock = cholesky[r] @ asset_noise[t]
        equity = market.mu[r, 0] + market.sigma[r, 0] * shock[0]
        bond = market.mu[r, 1] + market.sigma[r, 1] * shock[1]
        real = market.mu[r, 2] + market.sigma[r, 2] * shock[2]
        bond -= macro.bond_duration * (rate[t] - rate[t - 1]) / 100.0
        if r == CRISIS and regime[t - 1] != CRISIS:
            equity += market.crisis_jump[0] * jump_scale[t]
            bond += market.crisis_jump[1] * jump_scale[t]
            real += market.crisis_jump[2] * jump_scale[t]
        if fiscal.enabled:
            default_premium *= links.spread_decay if links.enabled else 1.0
            spread[t] = (
                fiscal.spread_slope * max(0.0, (debt[t - 1] - fiscal.spread_threshold) * 100.0)
                + default_premium
            )
            bond -= macro.bond_duration * (spread[t] - spread[t - 1]) / 100.0
        if foreign.enabled:
            equity -= foreign.equity_flight * max(depreciation, 0.0)
        equity -= impact
        real -= 0.5 * impact
        equity -= shock_size.get("equity_crash", 0.0)
        returns[t] = (max(equity, -0.95), bond, max(real, -0.95), rate[t - 1] / 1200.0)

        step = step_banks(
            banks,
            config.banks,
            equity_return=float(returns[t, 0]),
            bond_return=float(returns[t, 1]),
            output_gap=float(y[t]),
            market_size=market.market_size,
            default_multiplier=firm_multiplier,
            fx_depreciation=depreciation,
            fx_debt_share=foreign.bank_fx_debt_share if foreign.enabled else 0.0,
            growth_boost=policy.moral_hazard * cumulative_injection / fiscal.gdp_scale,
            policy=policy,
            extra_loss=shock_size.get("bank_loss", 0.0),
            securities_haircut=links.bank_sovereign_share * links.haircut if default_now else 0.0,
            loan_recovery=links.loan_recovery
            if links.enabled and links.deposit_insurance
            else None,
        )
        ratio[t], failed[t], constrained[t] = step.capital_ratio, step.failed, step.constrained
        new_failures[t], contagion[t] = step.new_failures, step.contagion_defaults
        fire_sale[t], crunch[t], loans[t] = (
            step.fire_sale_volume,
            step.credit_crunch,
            step.total_loans,
        )
        impact = market.price_impact * step.fire_sale_volume / market.market_size
        injection[t], liquidity[t] = step.injection, step.liquidity_support
        cumulative_injection += step.injection
        insured_cost = links.insured_share * step.deposit_shortfall
        insurance_cost[t] = insured_cost
        uninsured[t] = (1.0 - links.insured_share) * step.deposit_shortfall
        if block is not None:
            flow = block.step(
                t,
                returns[t],
                float(pi[t]),
                float(unemployment[t]),
                uninsured[t] / max(step.total_deposits, 1e-9),
                shock_size.get("demand_shock", 0.0),
            )
            consumption[t] = flow.consumption
            tax_share[t] = flow.tax_share
            gini_path[t], top10_path[t], bottom50_path[t] = (
                flow.gini,
                flow.top10_share,
                flow.bottom50_share,
            )
            if transfer_reference is None:
                transfer_reference = flow.transfer_share
            spending_ratio = flow.consumption / max(flow.income, 1e-12)
            if real_consumption_trend <= 0.0:
                real_consumption_trend = spending_ratio
            demand_gap = spending_ratio / real_consumption_trend - 1.0
            real_consumption_trend = 0.97 * real_consumption_trend + 0.03 * spending_ratio
        if firms.enabled:
            leverage[t] = float(
                np.clip(
                    leverage[t - 1]
                    + firms.leverage_build * y[t]
                    + firms.leverage_bust * max(0.0, -y[t])
                    - firms.leverage_reversion * (leverage[t - 1] - firms.initial_leverage),
                    0.2,
                    0.9,
                )
            )
        if fiscal.enabled:
            revenue = fiscal.tax_rate * (1.0 + y[t] / 100.0)
            if block is not None and flow is not None:
                revenue = flow.tax_share
            carry = (rate[t] + spread[t] - pi[t] - fiscal.trend_growth) / 1200.0
            debt[t] = (
                debt_before * (1.0 + carry)
                + (spending - revenue) / 12.0
                + (step.injection + insured_cost) / fiscal.gdp_scale
            )
        else:
            debt[t] = debt[t - 1]

    return WorldPath(
        config_name=config.name,
        seed=seed,
        regime=regime,
        output_gap=y,
        inflation=pi,
        policy_rate=rate,
        unemployment=unemployment,
        asset_returns=returns,
        price_level=price_level,
        bank_capital_ratio=ratio,
        bank_failed=failed,
        bank_constrained=constrained,
        new_failures=new_failures,
        contagion_defaults=contagion,
        fire_sale_volume=fire_sale,
        credit_crunch=crunch,
        total_loans=loans,
        firm_leverage=leverage,
        debt_ratio=debt,
        sovereign_spread=spread,
        fx_level=fx,
        injection=injection,
        liquidity_support=liquidity,
        gini=gini_path,
        top10_share=top10_path,
        bottom50_share=bottom50_path,
        consumption=consumption,
        tax_share=tax_share,
        sovereign_default=default_event,
        deposit_insurance_cost=insurance_cost,
        uninsured_loss=uninsured,
    )
