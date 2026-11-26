"""Estimating WORLDSIM's parameters from data: the estimators, on data whose answer is known."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from prometheus.worldsim.config import CRISIS, scenario
from prometheus.worldsim.real_calibration import (
    BURN_IN,
    EQUITY_MOMENTS,
    MACRO_MOMENTS,
    MACRO_PARAMETERS,
    HmmFit,
    all_moments,
    apply_credit,
    apply_direct,
    apply_macro,
    block_bootstrap_indices,
    bootstrap_moments,
    build_table,
    distance,
    fit_gaussian_hmm,
    hp_gap,
    okun_coefficient,
    simulated_moments,
    standard_errors,
    yoy_from_price_level,
)
from prometheus.worldsim.world import simulate_world


def _three_state_series(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    transition = np.array([[0.97, 0.025, 0.005], [0.10, 0.88, 0.02], [0.10, 0.15, 0.75]])
    mean, sigma = [0.010, 0.003, -0.030], [0.03, 0.05, 0.09]
    state, out = 0, []
    for _ in range(n):
        state = int(rng.choice(3, p=transition[state]))
        out.append(rng.normal(mean[state], sigma[state]))
    return np.array(out)


def test_the_hidden_markov_fit_recovers_the_volatility_ordering_and_valid_probabilities() -> None:
    fit = fit_gaussian_hmm(_three_state_series(3_000, 1), n_starts=6, iterations=400, seed=0)
    assert np.all(np.diff(fit.sigma) > 0.0), "states come out sorted by volatility"
    assert np.allclose(fit.transition.sum(axis=1), 1.0) and np.all(fit.transition >= 0.0)
    assert fit.share.sum() == pytest.approx(1.0)
    assert fit.sigma[0] == pytest.approx(0.03, rel=0.25)
    assert fit.sigma[2] == pytest.approx(0.09, rel=0.25)
    assert fit.mean[2] < fit.mean[0], "the most volatile state is the one with losses"


def test_the_hidden_markov_fit_is_deterministic_and_rejects_short_input() -> None:
    x = _three_state_series(600, 2)
    a = fit_gaussian_hmm(x, n_starts=3, iterations=50, seed=5)
    b = fit_gaussian_hmm(x, n_starts=3, iterations=50, seed=5)
    assert np.array_equal(a.transition, b.transition) and a.log_likelihood == b.log_likelihood
    with pytest.raises(ValueError):
        fit_gaussian_hmm(x[:30])


def test_the_hp_filter_removes_a_trend_and_keeps_a_cycle() -> None:
    t = np.arange(400.0)
    trend = 5.0 + 0.01 * t
    assert np.max(np.abs(hp_gap(trend))) < 1e-6
    cycle = np.sin(2.0 * np.pi * t / 60.0)
    recovered = hp_gap(trend + cycle)
    assert np.corrcoef(recovered, cycle)[0, 1] > 0.95
    with pytest.raises(ValueError):
        hp_gap(np.arange(5.0))


def test_the_table_keeps_each_months_current_and_lagged_values_together() -> None:
    n = 60
    u = np.linspace(5.0, 7.0, n)
    pi = np.linspace(2.0, 3.0, n)
    ff = np.linspace(1.0, 4.0, n)
    r = np.full(n, 0.01)
    table = build_table(u, pi, ff, r)
    assert table["gap"].size == n - 12
    assert np.allclose(table["pi_lag"], pi[11:-1]) and np.allclose(table["pi"], pi[12:])
    assert np.allclose(table["dff"], np.diff(ff)[11:])
    assert np.allclose(table["r12"], 12 * np.log1p(0.01))
    with pytest.raises(ValueError):
        build_table(u, pi[:-1], ff, r)


def test_the_macro_moments_recover_a_known_autoregression_and_taylor_rule() -> None:
    rng = np.random.default_rng(3)
    n = 4_000
    pi = np.zeros(n)
    for t in range(1, n):
        pi[t] = 0.9 * pi[t - 1] + rng.normal(0.0, 0.3)
    gap = np.zeros(n)
    for t in range(1, n):
        gap[t] = 0.8 * gap[t - 1] + rng.normal(0.0, 0.5)
    ff = np.zeros(n)
    for t in range(1, n):
        ff[t] = 0.9 * ff[t - 1] + 0.1 * (1.5 * pi[t] - 0.5 * gap[t]) + rng.normal(0.0, 0.02)
    table = build_table(5.0 + gap, pi, ff, rng.normal(0.01, 0.04, n))
    moments = all_moments(table)
    assert moments["infl_ar1"] == pytest.approx(0.9, abs=0.03)
    assert moments["taylor_rho"] == pytest.approx(0.9, abs=0.03)
    assert moments["taylor_inflation"] == pytest.approx(0.15, abs=0.03)
    assert set(MACRO_MOMENTS) <= set(moments) and set(EQUITY_MOMENTS) <= set(moments)
    assert all(np.isfinite(v) for k, v in moments.items() if not k.startswith("credit"))


def test_okun_is_minus_four_times_the_quarterly_slope() -> None:
    rng = np.random.default_rng(4)
    growth = rng.normal(3.0, 3.0, 400)
    change = -0.4 / 4.0 * (growth - growth.mean()) + rng.normal(0.0, 0.05, 400)
    assert okun_coefficient(change, growth) == pytest.approx(0.4, abs=0.03)


def test_direct_estimates_replace_the_chosen_values_without_double_counting_the_jump() -> None:
    base = scenario("volatile")
    hmm = HmmFit(
        mean=np.array([0.012, 0.004, -0.020]),
        sigma=np.array([0.03, 0.05, 0.10]),
        transition=np.array([[0.95, 0.04, 0.01], [0.05, 0.90, 0.05], [0.10, 0.10, 0.80]]),
        log_likelihood=0.0,
        share=np.array([0.5, 0.35, 0.15]),
        converged=True,
    )
    config = apply_direct(
        base,
        hmm=hmm,
        okun=0.3,
        base_unemployment=6.0,
        inflation_target=3.5,
        neutral_real_rate=2.0,
    )
    assert np.array_equal(config.transition, hmm.transition)
    assert np.array_equal(config.market.sigma[:, 0], hmm.sigma)
    spell = 1.0 / (1.0 - 0.80)
    expected = -0.020 - base.market.crisis_jump[0] / spell
    assert config.market.mu[CRISIS, 0] == pytest.approx(expected)
    assert config.market.mu[0, 0] == 0.012
    assert config.households.okun == 0.3 and config.households.base_unemployment == 6.0
    assert config.macro.inflation_target == 3.5 and config.macro.neutral_real_rate == 2.0
    # bond and real-asset columns are untouched: no data was used for them
    assert np.array_equal(config.market.mu[:, 1:], base.market.mu[:, 1:])
    floored = apply_direct(
        base, hmm=hmm, okun=-0.2, base_unemployment=6.0, inflation_target=2.0, neutral_real_rate=1.0
    )
    assert floored.households.okun > 0.0


def test_applying_macro_and_credit_values_changes_only_those_parameters() -> None:
    base = scenario("volatile")
    values = {
        "output_persistence": 0.97,
        "inflation_persistence": 0.95,
        "phillips_slope": 0.2,
        "inflation_vol": 0.4,
        "taylor_phi_pi": 1.1,
        "taylor_phi_y": 0.9,
        "rate_smoothing": 0.93,
        "output_vol_scale": 2.0,
        "output_shift_scale": 3.0,
    }
    config = apply_macro(base, values)
    assert config.macro.output_persistence == 0.97 and config.macro.rate_smoothing == 0.93
    assert config.macro.regime_output_vol == tuple(2.0 * v for v in base.macro.regime_output_vol)
    assert config.macro.regime_output_shift == tuple(
        3.0 * v for v in base.macro.regime_output_shift
    )
    assert config.market is base.market and config.banks is base.banks
    credit = apply_credit(base, {"loan_growth_base": 0.003})
    assert credit.banks.loan_growth_base == 0.003
    assert credit.banks.loan_growth_slope == base.banks.loan_growth_slope
    assert {name for name, _, _ in MACRO_PARAMETERS} == set(values)


def test_the_bootstrap_resamples_whole_blocks_and_gives_positive_errors() -> None:
    rng = np.random.default_rng(0)
    index = block_bootstrap_indices(100, 10, rng)
    assert index.size == 100 and index.min() >= 0 and index.max() < 100
    assert all(np.all(np.diff(index[i : i + 10]) == 1) for i in range(0, 100, 10))
    n = 300
    table = build_table(
        5.0 + rng.normal(0, 1, n).cumsum() * 0.05,
        rng.normal(2, 1, n),
        rng.normal(3, 1, n),
        rng.normal(0.01, 0.04, n),
    )
    replicates = bootstrap_moments(table, replications=20, block=12, seed=1)
    assert 10 <= len(replicates) <= 20
    errors = standard_errors(replicates, MACRO_MOMENTS)
    assert all(v > 0.0 for v in errors.values())


def test_the_distance_is_a_sum_of_squared_standardised_gaps() -> None:
    simulated = {"a": 3.0, "b": 1.0}
    real = {"a": 1.0, "b": 1.0}
    se = {"a": 2.0, "b": 1.0}
    assert distance(simulated, real, se, ("a", "b")) == pytest.approx(1.0)
    assert distance(real, real, se, ("a", "b")) == 0.0


def test_a_simulated_path_yields_finite_moments_and_twelve_month_inflation() -> None:
    config = replace(scenario("volatile"), n_months=300)
    path = simulate_world(config, 4)
    moments = simulated_moments(path)
    assert all(np.isfinite(v) for v in moments.values())
    yoy = yoy_from_price_level(path.price_level)
    assert np.all(np.isnan(yoy[:12])) and np.all(np.isfinite(yoy[12:]))
    assert BURN_IN >= 12
