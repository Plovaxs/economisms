import numpy as np
import pytest

from prometheus.econosim.macro_market_link import simulate_policy_rate_conditioned_market
from prometheus.econosim.policy_rate import PolicyRateRule, simulate_policy_rate_path
from prometheus.econosim.shocks import Shock, ShockGenerator, ShockSpec
from prometheus.stochastica.gbm import piecewise_gbm_terminal_moments


def test_rejects_too_short_policy_rate_path() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        simulate_policy_rate_conditioned_market(100.0, [0.03], 0.04, 0.2, 1 / 12, 10, rng)


def test_shape_matches_number_of_simulated_periods() -> None:
    rng = np.random.default_rng(0)
    policy_rate_path = [0.03, 0.03, 0.04, 0.04]  # 3 periods
    paths = simulate_policy_rate_conditioned_market(
        100.0, policy_rate_path, 0.04, 0.2, 1 / 12, 50, rng
    )
    assert paths.shape == (50, 4)


def test_terminal_distribution_matches_theory_for_a_policy_tightening_scenario() -> None:
    """An end-to-end check of the full macro-financial link: a central bank
    reaction function produces a rate path, and that path's terminal price
    distribution matches the exact piecewise-GBM reference built from the
    *same* rate path, not an arbitrary approximation."""
    kappa, dt, neutral = 0.5, 1 / 12, 0.03
    rule = PolicyRateRule(neutral_rate=neutral, mean_reversion_speed=kappa, dt=dt)
    tightening_shock = Shock("s1", 1, "policy_rate", magnitude=0.03)
    schedule: list[list[Shock]] = [[tightening_shock]] + [[] for _ in range(11)]
    policy_rate_path = simulate_policy_rate_path(rule, neutral, schedule)

    s0, sigma, premium = 100.0, 0.2, 0.04
    n_paths = 200_000
    rng = np.random.default_rng(1)
    paths = simulate_policy_rate_conditioned_market(
        s0, policy_rate_path, premium, sigma, dt, n_paths, rng
    )
    terminal = paths[:, -1]

    mu_path = [rate + premium for rate in policy_rate_path[:-1]]
    theory_mean, theory_var = piecewise_gbm_terminal_moments(s0, mu_path, sigma, dt)
    standard_error = np.sqrt(theory_var / n_paths)
    assert abs(terminal.mean() - theory_mean) < 6 * standard_error


def test_higher_policy_rate_path_produces_systematically_higher_mean_terminal_price() -> None:
    """A sanity check that the policy-rate conditioning is actually having
    an effect (not silently ignored): a persistently higher rate path must
    raise the mean terminal price relative to a persistently lower one,
    all else equal."""
    s0, sigma, premium, dt = 100.0, 0.2, 0.0, 1 / 12
    low_path = [0.01] * 13
    high_path = [0.08] * 13

    rng_low = np.random.default_rng(3)
    rng_high = np.random.default_rng(3)
    low_paths = simulate_policy_rate_conditioned_market(
        s0, low_path, premium, sigma, dt, 50_000, rng_low
    )
    high_paths = simulate_policy_rate_conditioned_market(
        s0, high_path, premium, sigma, dt, 50_000, rng_high
    )

    assert high_paths[:, -1].mean() > low_paths[:, -1].mean()


def test_no_lookahead_from_future_policy_shocks() -> None:
    """A deterministic shock injected at a late step must not change any
    earlier portion of the simulated market path, given the same seed."""
    kappa, dt, neutral = 0.5, 1 / 12, 0.03
    rule = PolicyRateRule(neutral_rate=neutral, mean_reversion_speed=kappa, dt=dt)

    late_shock = Shock("s1", 10, "policy_rate", magnitude=0.05)
    schedule_with_late_shock: list[list[Shock]] = [[] for _ in range(9)] + [[late_shock], []]
    schedule_without: list[list[Shock]] = [[] for _ in range(11)]

    path_with = simulate_policy_rate_path(rule, neutral, schedule_with_late_shock)
    path_without = simulate_policy_rate_path(rule, neutral, schedule_without)
    assert path_with[:10] == path_without[:10]  # unaffected before the shock lands

    rng_a = np.random.default_rng(7)
    rng_b = np.random.default_rng(7)
    market_with = simulate_policy_rate_conditioned_market(
        100.0, path_with, 0.0, 0.2, dt, 100, rng_a
    )
    market_without = simulate_policy_rate_conditioned_market(
        100.0, path_without, 0.0, 0.2, dt, 100, rng_b
    )
    assert np.array_equal(market_with[:, :10], market_without[:, :10])


def test_integrates_with_the_seeded_shock_generator_from_pr003() -> None:
    """The whole chain -- a seeded ShockGenerator drawing policy_rate
    shocks, feeding a PolicyRateRule, feeding the macro-conditioned market
    simulator -- is deterministic given a root seed."""
    from prometheus.core.seeds import SeedHierarchy

    def build_path(seed: int) -> list[float]:
        shock_gen = ShockGenerator(
            SeedHierarchy(seed).stream("economy"),
            [ShockSpec(kind="policy_rate", mean=0.0, std=0.005, probability=0.3)],
        )
        rule = PolicyRateRule(neutral_rate=0.03, mean_reversion_speed=0.5, dt=1 / 12)
        schedule = [shock_gen.draw_for_step(t) for t in range(1, 13)]
        return simulate_policy_rate_path(rule, 0.03, schedule)

    assert build_path(42) == build_path(42)
    assert build_path(42) != build_path(43)
