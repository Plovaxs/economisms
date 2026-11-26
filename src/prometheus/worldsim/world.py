"""The exogenous path of the world: regimes, macro variables, asset returns and the banks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.worldsim.banks import initial_banks, step_banks
from prometheus.worldsim.config import CRISIS, WorldConfig


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

    @property
    def n_months(self) -> int:
        return int(self.regime.size)


def _correlation(config: WorldConfig, regime: int) -> np.ndarray:
    m = config.market
    eb, er, br = m.equity_bond_corr[regime], m.equity_real_corr[regime], m.bond_real_corr[regime]
    return np.array([[1.0, eb, er], [eb, 1.0, br], [er, br, 1.0]])


def simulate_world(config: WorldConfig, seed: int) -> WorldPath:
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

    for t in range(1, n):
        r = int(regime[t])
        real_rate = rate[t - 1] - pi[t - 1]
        y[t] = (
            macro.output_persistence * y[t - 1]
            - macro.rate_sensitivity * (real_rate - macro.neutral_real_rate)
            + macro.regime_output_shift[r]
            + macro.regime_output_vol[r] * eps_y[t]
            - macro.credit_crunch_drag * crunch[t - 1]
        )
        pi[t] = (
            macro.inflation_persistence * pi[t - 1]
            + (1.0 - macro.inflation_persistence) * macro.inflation_target
            + macro.phillips_slope * y[t]
            + macro.inflation_vol * eps_pi[t]
            + supply[t]
        )
        target = (
            macro.neutral_real_rate
            + pi[t]
            + macro.taylor_phi_pi * (pi[t] - macro.inflation_target)
            + macro.taylor_phi_y * y[t]
        )
        rate[t] = float(
            np.clip(
                macro.rate_smoothing * rate[t - 1] + (1.0 - macro.rate_smoothing) * target,
                0.0,
                macro.rate_max,
            )
        )
        unemployment[t] = float(
            np.clip(config.households.base_unemployment - config.households.okun * y[t], 3.0, 15.0)
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
        equity -= impact
        real -= 0.5 * impact
        returns[t] = (max(equity, -0.95), bond, max(real, -0.95), rate[t - 1] / 1200.0)

        step = step_banks(
            banks,
            config.banks,
            equity_return=float(returns[t, 0]),
            bond_return=float(returns[t, 1]),
            output_gap=float(y[t]),
            market_size=market.market_size,
        )
        ratio[t], failed[t], constrained[t] = step.capital_ratio, step.failed, step.constrained
        new_failures[t], contagion[t] = step.new_failures, step.contagion_defaults
        fire_sale[t], crunch[t], loans[t] = (
            step.fire_sale_volume,
            step.credit_crunch,
            step.total_loans,
        )
        impact = market.price_impact * step.fire_sale_volume / market.market_size

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
    )
