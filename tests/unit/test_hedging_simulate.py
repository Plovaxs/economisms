from datetime import date

import numpy as np
import pytest

from prometheus.hedging.baseline import black_scholes_delta_hedge_ratios
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def test_rejects_mismatched_hedge_ratios_shape() -> None:
    paths = np.full((3, 6), 100.0)
    with pytest.raises(ValueError):
        simulate_self_financing_hedge(
            paths, 0.1, 100.0, "call", 0.05, 0.0, 10.0, hedge_ratios=np.zeros((3, 4))
        )


def test_rejects_negative_cost_rate() -> None:
    paths = np.full((3, 6), 100.0)
    ratios = np.zeros((3, 5))
    with pytest.raises(ValueError):
        simulate_self_financing_hedge(paths, 0.1, 100.0, "call", 0.05, -0.01, 10.0, ratios)


def test_zero_hedge_ratios_reduce_to_a_naked_short_option_position() -> None:
    """With holdings always zero, no trading ever happens, so the only cash
    flows are interest accrual on the premium and the payoff at maturity --
    an exact closed-form check: final_wealth = premium*e^{rT} - payoff(S_T)."""
    rng = np.random.default_rng(0)
    r, sigma, maturity, strike = 0.05, 0.2, 1.0, 100.0
    n_steps = 12
    dt = maturity / n_steps
    paths = simulate_gbm_paths(100.0, r, sigma, maturity, n_steps, 200, rng)
    premium = 10.0
    ratios = np.zeros((200, n_steps))

    result = simulate_self_financing_hedge(paths, dt, strike, "call", r, 0.0, premium, ratios)

    s_terminal = paths[:, -1]
    payoff = np.maximum(s_terminal - strike, 0.0)
    expected_final_wealth = premium * np.exp(r * maturity) - payoff
    assert np.allclose(-result.terminal_loss, expected_final_wealth)
    assert np.allclose(result.total_cost, 0.0)
    assert np.allclose(result.total_turnover, 0.0)


def test_self_financing_identity_matches_manual_recomputation() -> None:
    """Independently recompute the cash/holdings recursion in the test
    itself and confirm it matches the function's output exactly."""
    rng = np.random.default_rng(3)
    r, sigma, maturity, strike, cost_rate = 0.03, 0.25, 0.5, 100.0, 0.01
    n_steps = 8
    dt = maturity / n_steps
    paths = simulate_gbm_paths(100.0, r, sigma, maturity, n_steps, 50, rng)
    ratios = black_scholes_delta_hedge_ratios(paths, dt, strike, maturity, r, sigma, "call")
    premium = 8.0

    result = simulate_self_financing_hedge(paths, dt, strike, "call", r, cost_rate, premium, ratios)

    holdings = np.zeros(50)
    cash = np.full(50, premium)
    accrual = np.exp(r * dt)
    for t in range(n_steps):
        s_t = paths[:, t]
        target = ratios[:, t]
        trade = target - holdings
        cost = cost_rate * np.abs(trade) * s_t
        cash = cash * accrual - trade * s_t - cost
        holdings = target
    s_terminal = paths[:, -1]
    payoff = np.maximum(s_terminal - strike, 0.0)
    manual_loss = -(cash + holdings * s_terminal - payoff)

    assert np.allclose(manual_loss, result.terminal_loss)


def test_finer_discretization_reduces_hedging_error_under_zero_cost() -> None:
    """HDG-02: under zero frictions, the Black-Scholes delta hedge's
    terminal P&L shape should converge toward zero bias and zero variance
    as the rehedging frequency increases (standard discrete-hedging-error
    result, e.g. Boyle & Emanuel 1980)."""
    s0, r, sigma, maturity, strike = 100.0, 0.05, 0.2, 1.0, 100.0
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=s0, risk_free_rate=r, volatility=sigma)
    premium = black_scholes_price(market, EuropeanOption(strike, maturity, "call"))

    stds = []
    for n_steps in (10, 50, 250):
        dt = maturity / n_steps
        rng = np.random.default_rng(42)
        paths = simulate_gbm_paths(s0, r, sigma, maturity, n_steps, 20_000, rng)
        ratios = black_scholes_delta_hedge_ratios(paths, dt, strike, maturity, r, sigma, "call")
        result = simulate_self_financing_hedge(paths, dt, strike, "call", r, 0.0, premium, ratios)
        stds.append(result.terminal_loss.std())

    assert stds[0] > stds[1] > stds[2]


def test_holdings_path_records_target_holdings_at_each_step() -> None:
    paths = np.full((2, 4), 100.0)
    ratios = np.array([[0.3, 0.5, 0.7], [0.1, 0.1, 0.9]])
    result = simulate_self_financing_hedge(paths, 0.1, 100.0, "call", 0.0, 0.0, 10.0, ratios)
    assert np.allclose(result.holdings_path[:, :3], ratios)
    assert np.allclose(result.holdings_path[:, 3], ratios[:, -1])  # held through to liquidation
