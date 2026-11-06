import numpy as np
import pytest

from prometheus.stochastica.gbm import simulate_correlated_gbm_paths
from prometheus.titan.portfolio import PortfolioConstraints
from prometheus.titan.rebalancing import (
    RebalancingConfig,
    RebalancingFailure,
    simulate_rebalancing,
)


def _correlated_returns(seed: int = 0, n_assets: int = 5, total_steps: int = 120) -> np.ndarray:
    rng = np.random.default_rng(seed)
    s0 = np.full(n_assets, 100.0)
    mu = np.full(n_assets, 0.06)
    sigma = np.full(n_assets, 0.2)
    corr = np.eye(n_assets) * 0.6 + np.full((n_assets, n_assets), 0.4)
    maturity = total_steps / 12
    paths = simulate_correlated_gbm_paths(s0, mu, sigma, corr, maturity, total_steps, 1, rng)[0]
    returns: np.ndarray = paths[1:] / paths[:-1] - 1.0
    return returns


def test_config_rejects_invalid_fields() -> None:
    with pytest.raises(ValueError):
        RebalancingConfig(n_periods=0, estimation_window=10)
    with pytest.raises(ValueError):
        RebalancingConfig(n_periods=10, estimation_window=1)
    with pytest.raises(ValueError):
        RebalancingConfig(n_periods=10, estimation_window=10, rebalance_every=0)
    with pytest.raises(ValueError):
        RebalancingConfig(n_periods=10, estimation_window=10, cost_rate=-0.01)
    with pytest.raises(ValueError):
        RebalancingConfig(n_periods=10, estimation_window=10, turnover_penalty=-0.01)


def test_rejects_non_2d_returns() -> None:
    with pytest.raises(ValueError):
        simulate_rebalancing(np.zeros(10), RebalancingConfig(n_periods=5, estimation_window=5))


def test_rejects_insufficient_returns_length() -> None:
    returns = np.zeros((25, 3))
    config = RebalancingConfig(n_periods=20, estimation_window=10)
    with pytest.raises(ValueError):
        simulate_rebalancing(returns, config)


def test_runs_end_to_end_with_realistic_correlated_returns() -> None:
    returns = _correlated_returns()
    config = RebalancingConfig(
        n_periods=100,
        estimation_window=20,
        cost_rate=0.001,
        constraints=PortfolioConstraints(min_weight=0.0, max_weight=1.0),
    )
    result = simulate_rebalancing(returns, config)

    assert len(result.periods) == 100
    assert result.final_wealth > 0.0
    assert result.total_cost >= 0.0
    assert result.total_turnover >= 0.0
    assert result.max_drawdown <= 0.0
    for record in result.periods:
        assert record.weights.sum() == pytest.approx(1.0, abs=1e-6)
        assert record.shrinkage_intensity is not None  # shrinkage on by default


def test_wealth_evolves_consistently_period_by_period() -> None:
    """Independently recompute wealth from each period's return and cost,
    starting from 1.0, and confirm it matches the reported wealth path
    exactly -- not just that final_wealth looks plausible."""
    returns = _correlated_returns(seed=2)
    config = RebalancingConfig(n_periods=50, estimation_window=20, cost_rate=0.002)
    result = simulate_rebalancing(returns, config)

    wealth = 1.0
    for record in result.periods:
        wealth = wealth * (1.0 + record.period_return) - record.transaction_cost
        assert wealth == pytest.approx(record.wealth, abs=1e-10)
    assert wealth == pytest.approx(result.final_wealth, abs=1e-10)


def test_higher_transaction_costs_reduce_final_wealth() -> None:
    returns = _correlated_returns(seed=3)
    low_cost = simulate_rebalancing(
        returns, RebalancingConfig(n_periods=80, estimation_window=20, cost_rate=0.0005)
    )
    high_cost = simulate_rebalancing(
        returns, RebalancingConfig(n_periods=80, estimation_window=20, cost_rate=0.05)
    )
    assert high_cost.final_wealth < low_cost.final_wealth
    assert high_cost.total_cost > low_cost.total_cost


def test_less_frequent_rebalancing_reduces_total_turnover() -> None:
    returns = _correlated_returns(seed=4)
    frequent = simulate_rebalancing(
        returns, RebalancingConfig(n_periods=80, estimation_window=20, rebalance_every=1)
    )
    rare = simulate_rebalancing(
        returns, RebalancingConfig(n_periods=80, estimation_window=20, rebalance_every=6)
    )
    assert rare.total_turnover < frequent.total_turnover
    non_rebalanced_periods = [p for p in rare.periods if not p.rebalanced]
    assert len(non_rebalanced_periods) > 0
    for period in non_rebalanced_periods:
        assert period.turnover == 0.0
        assert period.transaction_cost == 0.0


def test_a_future_return_cannot_change_any_earlier_period_decision() -> None:
    """No-lookahead: period t's weights are decided from
    returns[t:t+estimation_window] only. Blowing up returns far beyond the
    horizon any early period's estimation window could reach must leave
    every early period's weights, turnover and cost bit-identical."""
    returns = _correlated_returns(seed=5)
    config = RebalancingConfig(n_periods=100, estimation_window=20)

    baseline = simulate_rebalancing(returns, config)

    perturbed_returns = returns.copy()
    perturbed_returns[90:] += 5.0
    perturbed = simulate_rebalancing(perturbed_returns, config)

    for i in range(30):  # well before period 90's estimation window could reach
        assert np.array_equal(baseline.periods[i].weights, perturbed.periods[i].weights)
        assert baseline.periods[i].period_return == perturbed.periods[i].period_return
        assert baseline.periods[i].wealth == perturbed.periods[i].wealth


def test_infeasible_constraints_raise_rebalancing_failure() -> None:
    rng = np.random.default_rng(1)
    returns = rng.normal(0.01, 0.05, (50, 5))
    # 5 assets, max_weight=0.1 -> max achievable total 0.5 < budget 1.0
    config = RebalancingConfig(
        n_periods=20, estimation_window=10, constraints=PortfolioConstraints(max_weight=0.1)
    )
    with pytest.raises(RebalancingFailure):
        simulate_rebalancing(returns, config)


def test_shrinkage_can_be_disabled() -> None:
    returns = _correlated_returns(seed=6)
    config = RebalancingConfig(n_periods=20, estimation_window=20, use_shrinkage=False)
    result = simulate_rebalancing(returns, config)
    for record in result.periods:
        assert record.shrinkage_intensity is None


def test_target_return_mode_hits_the_requested_period_return_on_average() -> None:
    rng = np.random.default_rng(8)
    n_assets = 4
    returns = rng.normal(0.01, 0.04, (60, n_assets))
    config = RebalancingConfig(
        n_periods=30,
        estimation_window=20,
        target_return=0.012,
        constraints=PortfolioConstraints(min_weight=-2.0, max_weight=2.0),
    )
    result = simulate_rebalancing(returns, config)
    for record in result.periods:
        if record.rebalanced:
            expected_return_at_decision_time = (
                returns[record.period : record.period + config.estimation_window].mean(axis=0)
                @ record.weights
            )
            assert expected_return_at_decision_time == pytest.approx(0.012, abs=1e-6)


def test_turnover_penalty_reduces_total_turnover_in_min_variance_mode() -> None:
    returns = _correlated_returns(seed=9)
    no_penalty = simulate_rebalancing(
        returns, RebalancingConfig(n_periods=60, estimation_window=20, turnover_penalty=0.0)
    )
    with_penalty = simulate_rebalancing(
        returns, RebalancingConfig(n_periods=60, estimation_window=20, turnover_penalty=2.0)
    )
    assert with_penalty.total_turnover < no_penalty.total_turnover
