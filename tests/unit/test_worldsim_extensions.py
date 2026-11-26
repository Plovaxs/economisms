"""WORLDSIM extensions: off, the world is Finding 25's; on, each channel does its one job."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from prometheus.worldsim import calibration, learned_warning, monitor, sensitivity
from prometheus.worldsim.banks import initial_banks, step_banks
from prometheus.worldsim.config import (
    BankParams,
    PolicyParams,
    full_scenario,
    scenario,
)
from prometheus.worldsim.world import simulate_world

V1_PINS = {
    ("calm", 0): (0, 0, 0.000492, -39.3014),
    ("calm", 1): (8, 0, 0.004305, -12.3623),
    ("volatile", 0): (25, 0, -0.004992, -226.8171),
    ("volatile", 1): (9, 0, 0.003988, -50.9937),
    ("stressed", 0): (42, 10, -0.010679, -1684.4071),
    ("stressed", 1): (23, 0, -0.001196, -387.6584),
}


@pytest.mark.parametrize(("name", "seed"), list(V1_PINS))
def test_with_every_extension_off_the_world_is_the_one_finding_25_used(
    name: str, seed: int
) -> None:
    crisis, failed, mean_equity, gap_sum = V1_PINS[(name, seed)]
    path = simulate_world(scenario(name), seed)
    assert int((path.regime == 2).sum()) == crisis
    assert int(path.bank_failed[-1].sum()) == failed
    assert float(path.asset_returns[:, 0].mean()) == pytest.approx(mean_equity, abs=2e-6)
    assert float(path.output_gap.sum()) == pytest.approx(gap_sum, abs=2e-3)


def test_the_extension_series_are_flat_when_their_sector_is_off() -> None:
    path = simulate_world(scenario("stressed"), 1)
    assert np.all(path.fx_level == 0.0) and np.all(path.sovereign_spread == 0.0)
    assert np.all(path.firm_leverage == path.firm_leverage[0])
    assert np.all(path.debt_ratio == path.debt_ratio[0])
    assert path.injection.sum() == 0.0 and path.liquidity_support.sum() == 0.0


def test_unknown_extended_scenarios_are_rejected_and_the_names_work() -> None:
    with pytest.raises(ValueError, match="unknown extended scenario"):
        full_scenario("nope")
    config = full_scenario("stressed_full", mode="recapitalise")
    assert config.name == "stressed_full" and config.policy.mode == "recapitalise"
    assert config.firms.enabled and config.fiscal.enabled and config.foreign.enabled


def test_firm_leverage_stays_inside_its_bounds_and_the_exchange_rate_jumps_into_a_crisis() -> None:
    config = full_scenario("stressed_full")
    jumps, others = [], []
    for seed in range(15):
        path = simulate_world(config, seed)
        assert np.all((path.firm_leverage >= 0.2) & (path.firm_leverage <= 0.9))
        change = np.diff(path.fx_level)
        entering = (path.regime[1:] == 2) & (path.regime[:-1] != 2)
        jumps.extend(change[entering])
        others.extend(change[~entering])
    assert np.mean(jumps) > np.mean(others) + 0.03  # the risk-off depreciation


def test_a_counter_cyclical_rule_lifts_the_worst_output_gap() -> None:
    base = full_scenario("stressed_full")
    flat = replace(base, fiscal=replace(base.fiscal, countercyclical=0.0))
    seeds = range(12)
    with_rule = np.mean([simulate_world(base, s).output_gap.min() for s in seeds])
    without = np.mean([simulate_world(flat, s).output_gap.min() for s in seeds])
    assert with_rule > without


def test_firms_and_foreign_currency_debt_raise_bank_failures_on_average() -> None:
    stressed = full_scenario("stressed_full")
    no_fx = replace(stressed, foreign=replace(stressed.foreign, bank_fx_debt_share=0.0))
    seeds = range(30)
    failed = np.mean([simulate_world(stressed, s).bank_failed[-1].sum() for s in seeds])
    failed_no_fx = np.mean([simulate_world(no_fx, s).bank_failed[-1].sum() for s in seeds])
    assert failed >= failed_no_fx


def test_recapitalisation_stops_failures_and_costs_money_while_none_costs_nothing() -> None:
    seeds = range(15)
    none = [simulate_world(full_scenario("stressed_full", mode="none"), s) for s in seeds]
    recap = [simulate_world(full_scenario("stressed_full", mode="recapitalise"), s) for s in seeds]
    liquidity = [simulate_world(full_scenario("stressed_full", mode="liquidity"), s) for s in seeds]
    assert sum(p.injection.sum() for p in none) == 0.0
    assert sum(p.injection.sum() for p in recap) > 0.0
    assert sum(int(p.bank_failed[-1].sum()) for p in recap) <= sum(
        int(p.bank_failed[-1].sum()) for p in none
    )
    assert sum(p.liquidity_support.sum() for p in liquidity) > 0.0
    assert sum(int(p.bank_failed[-1].sum()) for p in liquidity) <= sum(
        int(p.bank_failed[-1].sum()) for p in none
    )


def test_the_regimes_are_the_same_in_every_arm_so_comparisons_are_paired() -> None:
    a = simulate_world(full_scenario("stressed_full", mode="none"), 4)
    b = simulate_world(full_scenario("stressed_full", mode="recapitalise"), 4)
    assert np.array_equal(a.regime, b.regime)


def test_an_injection_restores_a_weak_bank_to_the_target_ratio_and_fx_debt_costs_equity() -> None:
    params = BankParams(deposit_funding=80.0)
    policy = PolicyParams(mode="recapitalise", rescue_threshold=0.5, target_ratio=0.5)
    state = initial_banks(params, np.random.default_rng(0))
    step = step_banks(
        state,
        params,
        equity_return=0.0,
        bond_return=0.0,
        output_gap=0.0,
        market_size=1_000.0,
        policy=policy,
    )
    assert step.injection > 0.0
    plain = initial_banks(params, np.random.default_rng(0))
    shocked = initial_banks(params, np.random.default_rng(0))
    kwargs = dict(equity_return=0.0, bond_return=0.0, output_gap=0.0, market_size=1_000.0)
    base = step_banks(plain, params, **kwargs)
    hit = step_banks(shocked, params, fx_depreciation=0.10, fx_debt_share=0.2, **kwargs)
    assert np.all(hit.equity < base.equity)


def test_moral_hazard_makes_surviving_banks_lend_faster() -> None:
    params = BankParams(deposit_funding=80.0)
    kwargs = dict(equity_return=0.0, bond_return=0.0, output_gap=0.0, market_size=1_000.0)
    cautious = initial_banks(params, np.random.default_rng(1))
    reckless = initial_banks(params, np.random.default_rng(1))
    step_banks(cautious, params, **kwargs)
    step_banks(reckless, params, growth_boost=0.005, **kwargs)
    assert reckless.loans.sum() > cautious.loans.sum()


def test_the_logistic_warning_separates_separable_data_and_refuses_one_class() -> None:
    rng = np.random.default_rng(0)
    labels = rng.random(400) < 0.3
    features = rng.normal(size=(400, 3)) + 3.0 * labels[:, None]
    model = learned_warning.fit_logistic(features, labels)
    scores = model.score(features)
    assert np.all((scores > 0.0) & (scores < 1.0))
    assert monitor.auc(scores, labels) > 0.95
    with pytest.raises(ValueError, match="both classes"):
        learned_warning.fit_logistic(features, np.ones(400, dtype=bool))


def test_warning_samples_have_one_column_per_named_feature() -> None:
    x, y = learned_warning.sample_matrix(simulate_world(full_scenario("volatile_full"), 2))
    assert x.shape[1] == len(learned_warning.FEATURES) and x.shape[0] == y.size > 0
    assert not np.isnan(x).any()


def test_calibration_flags_what_is_out_of_range() -> None:
    inside = {name: (low + high) / 2.0 for name, (low, high) in calibration.TARGETS.items()}
    assert calibration.all_ok(inside)
    outside = {**inside, "equity_volatility_annual": 0.60}
    assert not calibration.all_ok(outside)
    assert calibration.check(outside)["equity_volatility_annual"]["ok"] is False
    assert calibration.check({})["mean_crisis_share"]["ok"] is False


def test_sensitivity_helpers_move_one_parameter_and_leave_the_rest() -> None:
    config = scenario("volatile")
    moved = sensitivity.scaled(config, "banks.loss_given_default", 1.2)
    assert moved.banks.loss_given_default == pytest.approx(0.6)
    assert moved.banks.capital_trigger == config.banks.capital_trigger
    leverage = sensitivity.scaled(config, "banks.deposit_funding", 1.5)
    assert leverage.banks.deposit_funding == pytest.approx(100.0 - 16.0 * 1.5)
    vol = sensitivity.scaled(config, "macro.regime_output_vol", 2.0)
    assert vol.macro.regime_output_vol == tuple(2.0 * v for v in config.macro.regime_output_vol)


def test_tornado_is_sorted_by_swing_and_deterministic() -> None:
    config = full_scenario("stressed_full")
    params = ("banks.deposit_funding", "market.price_impact", "banks.loss_given_default")
    first = sensitivity.tornado(config, range(6), params)
    second = sensitivity.tornado(config, range(6), params)
    assert first == second
    swings = [abs(r["swing_mean_failed_banks"]) for r in first]
    assert swings == sorted(swings, reverse=True)
    assert {r["parameter"] for r in first} == set(params)
