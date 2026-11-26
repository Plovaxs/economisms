"""WORLDSIM: the world is reproducible, the allocation rules cannot see the future, bank failure is
absorbing, fire sales only ever hurt, and the monitor's AUC is the textbook one."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from prometheus.worldsim import allocation, monitor
from prometheus.worldsim.banks import initial_banks, step_banks
from prometheus.worldsim.config import (
    CRISIS,
    SCENARIOS,
    BankParams,
    WorldConfig,
    scale_crisis_entry,
    scenario,
)
from prometheus.worldsim.households import gini, simulate_households
from prometheus.worldsim.world import simulate_world


def test_scenarios_exist_and_transition_rows_are_probabilities() -> None:
    for name in SCENARIOS:
        config = scenario(name)
        assert config.name == name
        assert np.allclose(config.transition.sum(axis=1), 1.0)
        assert np.all(config.transition >= 0.0)
    with pytest.raises(ValueError, match="unknown scenario"):
        scenario("nope")
    with pytest.raises(ValueError, match="at least 24"):
        WorldConfig(n_months=12)


def test_scaling_crisis_entry_moves_only_the_crisis_column_and_the_diagonal() -> None:
    base = WorldConfig().transition
    scaled = scale_crisis_entry(base, 2.0)
    assert scaled[0, CRISIS] == pytest.approx(2.0 * base[0, CRISIS])
    assert scaled[0, 1] == base[0, 1]
    assert np.allclose(scaled.sum(axis=1), 1.0)
    assert np.array_equal(scaled[CRISIS], base[CRISIS])


def test_the_world_is_deterministic_and_seeds_differ() -> None:
    config = scenario("volatile")
    first, second = simulate_world(config, 5), simulate_world(config, 5)
    assert np.array_equal(first.asset_returns, second.asset_returns)
    assert np.array_equal(first.bank_failed, second.bank_failed)
    assert not np.array_equal(first.asset_returns, simulate_world(config, 6).asset_returns)


def test_the_world_looks_like_a_volatile_economy() -> None:
    returns = np.concatenate(
        [simulate_world(scenario("volatile"), s).asset_returns[:, 0] for s in range(30)]
    )
    annual_vol = returns.std() * np.sqrt(12.0)
    assert 0.10 < annual_vol < 0.25
    centred = returns - returns.mean()
    assert np.mean(centred**4) / np.mean(centred**2) ** 2 > 3.0  # fat tails
    path = simulate_world(scenario("stressed"), 1)
    assert path.policy_rate.min() >= 0.0 and path.policy_rate.max() <= 15.0
    assert np.all(path.unemployment >= 3.0) and np.all(path.price_level > 0.0)


def test_crisis_regimes_are_deeper_and_more_frequent_when_stressed() -> None:
    def crisis_share(name: str) -> float:
        return float(
            np.mean(
                [(simulate_world(scenario(name), s).regime == CRISIS).mean() for s in range(40)]
            )
        )

    assert crisis_share("calm") < crisis_share("volatile") < crisis_share("stressed")


def test_allocation_weights_are_a_valid_portfolio_and_never_use_the_future() -> None:
    rng = np.random.default_rng(0)
    returns = rng.normal(0.004, 0.04, size=(120, 4))
    for rule in allocation.RULES:
        for t in (0, 5, 12, 60, 119):
            weights = allocation.weights_for(rule, returns[:t])
            assert weights.shape == (4,) and np.all(weights >= 0.0)
            assert weights.sum() == pytest.approx(1.0)
        altered = returns.copy()
        altered[60:] += 1.0  # change only the future relative to t = 60
        assert np.array_equal(
            allocation.weights_for(rule, returns[:60]), allocation.weights_for(rule, altered[:60])
        )
    with pytest.raises(ValueError, match="unknown rule"):
        allocation.weights_for("nope", returns)


def test_vol_target_holds_less_risk_when_volatility_is_high() -> None:
    rng = np.random.default_rng(1)
    calm = rng.normal(0.005, 0.01, size=(60, 4))
    wild = rng.normal(0.005, 0.10, size=(60, 4))
    assert allocation.vol_target(wild)[3] > allocation.vol_target(calm)[3]


def test_gini_of_equal_and_concentrated_wealth() -> None:
    assert gini(np.ones(100)) == pytest.approx(0.0)
    concentrated = np.zeros(100)
    concentrated[0] = 1.0
    assert gini(concentrated) == pytest.approx(0.99)


def test_households_do_not_change_the_world_and_compare_rules_on_the_same_path() -> None:
    config = scenario("volatile")
    path = simulate_world(config, 2)
    before = path.asset_returns.copy()
    first = simulate_households(path, "equal_weight", config.households, 2)
    again = simulate_households(path, "equal_weight", config.households, 2)
    other = simulate_households(path, "sixty_forty", config.households, 2)
    assert np.array_equal(path.asset_returns, before)
    assert np.array_equal(first.gini, again.gini)
    assert first.gini[0] == other.gini[0]  # the same households start every rule
    assert 0.0 < first.gini[-1] < 1.0 and first.portfolio_value[0] == 1.0
    assert first.final_real_wealth_participants > first.final_real_wealth_others


def test_banks_start_solvent_and_failure_is_absorbing() -> None:
    config = scenario("stressed")
    path = simulate_world(config, 3)
    assert not path.bank_failed[0].any()
    assert np.all(path.bank_capital_ratio[0] > 0.0)
    for t in range(1, path.n_months):
        assert np.all(path.bank_failed[t] >= path.bank_failed[t - 1])
    assert path.new_failures.sum() == path.bank_failed[-1].sum()
    assert np.all(path.contagion_defaults <= path.new_failures + 1_000)


def test_a_large_loss_makes_a_bank_fail_and_a_calm_month_does_not() -> None:
    params = BankParams(deposit_funding=80.0)  # a well-capitalised system
    rng = np.random.default_rng(0)
    healthy = initial_banks(params, rng)
    step = step_banks(
        healthy, params, equity_return=0.01, bond_return=0.0, output_gap=0.5, market_size=1_000.0
    )
    assert not step.failed.any() and step.fire_sale_volume == 0.0
    wrecked = initial_banks(params, np.random.default_rng(0))
    wrecked.securities = wrecked.securities * 0.2  # a 80% write-down of securities
    crash = step_banks(
        wrecked, params, equity_return=-0.5, bond_return=-0.2, output_gap=-5.0, market_size=1_000.0
    )
    assert crash.failed.any()


def test_a_bank_below_its_capital_trigger_sells_securities_and_stops_lending() -> None:
    params = BankParams(capital_trigger=0.5)  # above every bank's starting ratio
    state = initial_banks(params, np.random.default_rng(0))
    loans_before = state.loans.copy()
    step = step_banks(
        state, params, equity_return=0.0, bond_return=0.0, output_gap=1.0, market_size=1_000.0
    )
    assert step.fire_sale_volume > 0.0 and step.credit_crunch > 0.0
    assert np.all(state.loans <= loans_before)  # losses only; no new lending


def test_fire_sale_feedback_never_raises_equity_returns() -> None:
    config = scenario("stressed")
    off = replace(config, market=replace(config.market, price_impact=0.0))
    for seed in range(5):
        with_feedback = simulate_world(config, seed)
        without = simulate_world(off, seed)
        assert np.array_equal(with_feedback.regime, without.regime)
        assert with_feedback.asset_returns[:, 0].sum() <= without.asset_returns[:, 0].sum() + 1e-9


def test_auc_is_the_textbook_probability() -> None:
    labels = np.array([True, True, False, False])
    assert monitor.auc(np.array([3.0, 4.0, 1.0, 2.0]), labels) == 1.0
    assert monitor.auc(np.array([1.0, 2.0, 3.0, 4.0]), labels) == 0.0
    assert monitor.auc(np.ones(4), labels) == 0.5
    assert np.isnan(monitor.auc(np.ones(3), np.ones(3, dtype=bool)))


def test_the_composite_is_undefined_only_before_the_burn_in_and_alerts_follow_thresholds() -> None:
    path = simulate_world(scenario("stressed"), 4)
    indicators = monitor.indicators(path)
    assert np.isnan(indicators.composite[: monitor.BURN_IN]).all()
    assert not np.isnan(indicators.composite[monitor.BURN_IN :]).any()
    defined = ~np.isnan(indicators.composite)
    assert np.all(indicators.alert[defined & (indicators.composite >= monitor.RED)] == 2)
    assert np.all(indicators.alert[defined & (indicators.composite < monitor.AMBER)] == 0)


def test_warning_samples_exclude_months_already_in_a_crisis() -> None:
    path = simulate_world(scenario("stressed"), 4)
    indicators = monitor.indicators(path)
    scores, labels = monitor.warning_samples(path, indicators.composite)
    eligible = [
        t
        for t in range(monitor.BURN_IN, path.n_months - monitor.HORIZON)
        if path.regime[t] != CRISIS
    ]
    assert scores.size == labels.size == len(eligible)


def test_dashboard_page_and_json_for_the_world() -> None:
    from prometheus.dashboard.worldsim_view import render_worldsim, worldsim_as_json

    summary = worldsim_as_json(name="stressed", seed=3, rule="min_variance")
    assert summary["synthetic"] is True and summary["scenario"] == "stressed"
    assert summary["final"]["alert"] in {"green", "amber", "red"}
    assert 0.0 < summary["final"]["gini"] < 1.0
    html = render_worldsim(name="calm", seed=1)
    assert "SYNTHETIC" in html and "Economic monitoring" in html and "<svg" in html
    with pytest.raises(ValueError, match="scenario"):
        worldsim_as_json(name="nope")
    with pytest.raises(ValueError, match="rule"):
        worldsim_as_json(rule="nope")
