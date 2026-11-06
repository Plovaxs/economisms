import numpy as np
import pytest

from prometheus.titan.portfolio import (
    PortfolioConstraints,
    cvar_optimal_portfolio,
    minimum_variance_portfolio,
    target_return_portfolio,
)
from prometheus.titan.risk_metrics import historical_expected_shortfall


def _three_asset_covariance() -> np.ndarray:
    return np.array([[0.04, 0.01, 0.0], [0.01, 0.09, 0.02], [0.0, 0.02, 0.16]])


def test_constraints_reject_inverted_bounds() -> None:
    with pytest.raises(ValueError):
        PortfolioConstraints(min_weight=0.5, max_weight=0.2)


def test_minimum_variance_matches_closed_form_global_min_var_portfolio() -> None:
    """w* = Sigma^-1 1 / (1' Sigma^-1 1) is the exact unconstrained global
    minimum-variance portfolio; with box bounds wide enough not to bind,
    the SLSQP solve must match it to near machine precision."""
    cov = _three_asset_covariance()
    result = minimum_variance_portfolio(cov, PortfolioConstraints(min_weight=-5.0, max_weight=5.0))
    assert result.success

    ones = np.ones(3)
    inv_cov = np.linalg.inv(cov)
    closed_form = inv_cov @ ones / (ones @ inv_cov @ ones)
    assert result.weights == pytest.approx(closed_form, abs=1e-7)
    assert result.weights.sum() == pytest.approx(1.0)


def test_minimum_variance_respects_a_feasible_box_constraint() -> None:
    cov = _three_asset_covariance()
    result = minimum_variance_portfolio(cov, PortfolioConstraints(min_weight=0.0, max_weight=0.5))
    assert result.success
    assert np.all(result.weights >= -1e-9)
    assert np.all(result.weights <= 0.5 + 1e-9)
    assert result.weights.sum() == pytest.approx(1.0)


def test_minimum_variance_reports_failure_for_an_infeasible_box() -> None:
    """max_weight=0.3 across 3 assets caps the achievable total at 0.9 --
    strictly less than budget=1.0 -- so no valid portfolio exists. The
    solver must report success=False, not silently return an invalid
    (non-summing-to-budget) allocation as if it were optimal (OPT-09)."""
    cov = _three_asset_covariance()
    result = minimum_variance_portfolio(cov, PortfolioConstraints(min_weight=0.0, max_weight=0.3))
    assert not result.success
    assert len(result.status_message) > 0


def test_minimum_variance_rejects_non_square_covariance() -> None:
    with pytest.raises(ValueError):
        minimum_variance_portfolio(np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))


def test_minimum_variance_turnover_penalty_reduces_turnover_vs_prior() -> None:
    cov = _three_asset_covariance()
    prior = np.array([0.5, 0.3, 0.2])

    no_penalty = minimum_variance_portfolio(cov)
    with_penalty = minimum_variance_portfolio(cov, prior_weights=prior, turnover_penalty=0.5)

    assert no_penalty.success and with_penalty.success
    turnover_without = np.sum(np.abs(no_penalty.weights - prior))
    turnover_with = np.sum(np.abs(with_penalty.weights - prior))
    assert turnover_with < turnover_without


def test_minimum_variance_turnover_penalty_requires_prior_weights() -> None:
    cov = _three_asset_covariance()
    with pytest.raises(ValueError):
        minimum_variance_portfolio(cov, turnover_penalty=0.5)


def test_minimum_variance_turnover_penalty_rejects_negative_value() -> None:
    cov = _three_asset_covariance()
    with pytest.raises(ValueError):
        minimum_variance_portfolio(cov, prior_weights=np.zeros(3), turnover_penalty=-0.1)


def test_minimum_variance_zero_turnover_penalty_still_matches_closed_form() -> None:
    """turnover_penalty=0.0 must not change the (jac-based, exact) result
    from before this parameter existed."""
    cov = _three_asset_covariance()
    result = minimum_variance_portfolio(cov, PortfolioConstraints(min_weight=-5.0, max_weight=5.0))
    ones = np.ones(3)
    inv_cov = np.linalg.inv(cov)
    closed_form = inv_cov @ ones / (ones @ inv_cov @ ones)
    assert result.weights == pytest.approx(closed_form, abs=1e-7)


def test_target_return_matches_closed_form_two_fund_formula() -> None:
    cov = _three_asset_covariance()
    mu = np.array([0.06, 0.09, 0.12])
    target = 0.08
    result = target_return_portfolio(
        mu, cov, target, PortfolioConstraints(min_weight=-5.0, max_weight=5.0)
    )
    assert result.success

    ones = np.ones(3)
    inv_cov = np.linalg.inv(cov)
    a = ones @ inv_cov @ ones
    b = ones @ inv_cov @ mu
    c = mu @ inv_cov @ mu
    d = a * c - b * b
    closed_form = inv_cov @ ((c - b * target) * ones + (a * target - b) * mu) / d

    assert result.weights == pytest.approx(closed_form, abs=1e-7)
    assert result.weights @ mu == pytest.approx(target, abs=1e-7)
    assert result.weights.sum() == pytest.approx(1.0)


def test_target_return_rejects_mismatched_expected_returns_shape() -> None:
    cov = _three_asset_covariance()
    with pytest.raises(ValueError):
        target_return_portfolio(np.array([0.05, 0.1]), cov, 0.08)


def test_turnover_penalty_pulls_the_solution_toward_the_prior_portfolio() -> None:
    cov = _three_asset_covariance()
    mu = np.array([0.06, 0.09, 0.12])
    prior = np.array([0.5, 0.3, 0.2])

    no_penalty = target_return_portfolio(mu, cov, 0.08)
    with_penalty = target_return_portfolio(mu, cov, 0.08, prior_weights=prior, turnover_penalty=0.5)

    assert no_penalty.success and with_penalty.success
    turnover_without = np.sum(np.abs(no_penalty.weights - prior))
    turnover_with = np.sum(np.abs(with_penalty.weights - prior))
    assert turnover_with < turnover_without


def test_turnover_penalty_requires_prior_weights() -> None:
    cov = _three_asset_covariance()
    mu = np.array([0.06, 0.09, 0.12])
    with pytest.raises(ValueError):
        target_return_portfolio(mu, cov, 0.08, turnover_penalty=0.5)


def test_turnover_penalty_rejects_negative_value() -> None:
    cov = _three_asset_covariance()
    mu = np.array([0.06, 0.09, 0.12])
    with pytest.raises(ValueError):
        target_return_portfolio(mu, cov, 0.08, prior_weights=np.zeros(3), turnover_penalty=-0.1)


def test_cvar_optimal_portfolio_matches_brute_force_grid_search() -> None:
    """Independent verification: grid-search a 2-asset weight (w, 1-w) and
    compute CVaR at each point with titan.risk_metrics'
    historical_expected_shortfall directly -- a different code path from
    the LP solver -- and confirm the LP's optimum matches the grid's."""
    rng = np.random.default_rng(0)
    n_scenarios = 2000
    returns = np.column_stack(
        [
            rng.normal(0.08, 0.15, n_scenarios),
            rng.standard_t(df=4, size=n_scenarios) * 0.25 + 0.10,
        ]
    )
    alpha = 0.95
    result = cvar_optimal_portfolio(returns, alpha)
    assert result.success

    grid = np.linspace(0.0, 1.0, 2001)
    grid_cvars = np.array(
        [
            historical_expected_shortfall(-(w * returns[:, 0] + (1 - w) * returns[:, 1]), alpha)
            for w in grid
        ]
    )
    best_grid_w = grid[np.argmin(grid_cvars)]
    best_grid_cvar = grid_cvars.min()

    assert abs(result.weights[0] - best_grid_w) < 0.01
    assert abs(result.objective_value - best_grid_cvar) < 1e-3


def test_cvar_optimal_portfolio_respects_target_return() -> None:
    rng = np.random.default_rng(2)
    returns = np.column_stack([rng.normal(0.08, 0.15, 2000), rng.normal(0.05, 0.10, 2000)])
    result = cvar_optimal_portfolio(returns, 0.95, target_return=0.06)
    assert result.success
    assert result.weights @ returns.mean(axis=0) >= 0.06 - 1e-6


def test_cvar_optimal_portfolio_reports_failure_for_unachievable_target() -> None:
    rng = np.random.default_rng(2)
    returns = np.column_stack([rng.normal(0.08, 0.15, 500), rng.normal(0.05, 0.10, 500)])
    result = cvar_optimal_portfolio(returns, 0.95, target_return=1.0)
    assert not result.success


def test_cvar_optimal_portfolio_rejects_bad_alpha() -> None:
    returns = np.zeros((10, 2))
    with pytest.raises(ValueError):
        cvar_optimal_portfolio(returns, 1.5)


def test_cvar_optimal_portfolio_rejects_empty_scenarios() -> None:
    with pytest.raises(ValueError):
        cvar_optimal_portfolio(np.empty((0, 2)), 0.95)


def test_cvar_optimal_portfolio_rejects_non_2d_input() -> None:
    with pytest.raises(ValueError):
        cvar_optimal_portfolio(np.zeros(10), 0.95)


def test_cvar_weights_sum_to_budget() -> None:
    rng = np.random.default_rng(3)
    returns = rng.normal(0.05, 0.1, (1000, 4))
    result = cvar_optimal_portfolio(returns, 0.9, PortfolioConstraints(budget=1.0))
    assert result.success
    assert result.weights.sum() == pytest.approx(1.0, abs=1e-6)


def _liquidity_constrained_covariance() -> np.ndarray:
    """Asset 0 has the lowest variance, so an unconstrained minimum-
    variance solve concentrates heavily in it -- exactly the situation a
    liquidity/participation cap (OPT-06) is meant to prevent."""
    return np.array(
        [
            [0.01, 0.002, 0.001],
            [0.002, 0.04, 0.003],
            [0.001, 0.003, 0.09],
        ]
    )


def test_constraints_reject_a_per_asset_cap_below_min_weight() -> None:
    with pytest.raises(ValueError, match="max_weight_per_asset"):
        PortfolioConstraints(min_weight=0.2, max_weight_per_asset=np.array([0.1, 1.0, 1.0]))


def test_constraints_reject_a_non_1d_per_asset_cap() -> None:
    with pytest.raises(ValueError, match="1-D"):
        PortfolioConstraints(max_weight_per_asset=np.zeros((2, 2)))


def test_minimum_variance_rejects_a_per_asset_cap_of_the_wrong_length() -> None:
    cov = _liquidity_constrained_covariance()
    with pytest.raises(ValueError, match="max_weight_per_asset"):
        minimum_variance_portfolio(
            cov, PortfolioConstraints(max_weight_per_asset=np.array([0.1, 1.0]))
        )


def test_minimum_variance_never_violates_a_tight_liquidity_cap_on_the_optimal_asset() -> None:
    """OPT-06's own acceptance criterion, read literally: "no portfolio
    violates pre-approved participation limits." The discriminating part
    is not merely obeying the cap, but obeying it on the one asset the
    unconstrained optimum actually wants to overweight -- otherwise the
    cap could trivially "pass" a case it never binds on."""
    cov = _liquidity_constrained_covariance()
    uncapped = minimum_variance_portfolio(cov)
    assert uncapped.success
    assert uncapped.weights[0] > 0.10  # the uncapped optimum WOULD breach this cap

    caps = np.array([0.10, 1.0, 1.0])
    capped = minimum_variance_portfolio(cov, PortfolioConstraints(max_weight_per_asset=caps))
    assert capped.success
    assert capped.weights[0] <= 0.10 + 1e-8
    assert not np.allclose(capped.weights, uncapped.weights)


def test_minimum_variance_per_asset_cap_is_the_tighter_of_itself_and_max_weight() -> None:
    """A per-asset cap looser than the uniform max_weight must not loosen
    it -- min(max_weight, cap) applies, not the cap alone."""
    cov = _liquidity_constrained_covariance()
    caps = np.array([0.95, 1.0, 1.0])  # looser than max_weight=0.5 below
    result = minimum_variance_portfolio(
        cov, PortfolioConstraints(max_weight=0.5, max_weight_per_asset=caps)
    )
    assert result.success
    assert np.all(result.weights <= 0.5 + 1e-8)


def test_target_return_portfolio_respects_a_liquidity_cap() -> None:
    cov = _liquidity_constrained_covariance()
    expected_returns = np.array([0.08, 0.05, 0.03])
    caps = np.array([0.10, 1.0, 1.0])
    result = target_return_portfolio(
        expected_returns,
        cov,
        target_return=0.045,
        constraints=PortfolioConstraints(max_weight_per_asset=caps),
    )
    assert result.success
    assert result.weights[0] <= 0.10 + 1e-8
    assert result.weights @ expected_returns == pytest.approx(0.045, abs=1e-6)


def test_target_return_portfolio_reports_failure_when_the_cap_makes_the_target_unreachable() -> (
    None
):
    """OPT-09 ("no infeasible solution silently labeled optimal") must
    still hold once a liquidity cap is added: capping the only
    high-return asset at 10% makes a 6% target return genuinely
    unreachable here (max achievable is 0.08*0.10 + 0.05*0.90 = 0.053),
    and the solver must report that honestly, not silently clip."""
    cov = _liquidity_constrained_covariance()
    expected_returns = np.array([0.08, 0.05, 0.03])
    caps = np.array([0.10, 1.0, 1.0])
    result = target_return_portfolio(
        expected_returns,
        cov,
        target_return=0.06,
        constraints=PortfolioConstraints(max_weight_per_asset=caps),
    )
    assert not result.success


def test_cvar_optimal_portfolio_respects_a_liquidity_cap() -> None:
    cov = _liquidity_constrained_covariance()
    rng = np.random.default_rng(4)
    scenario_returns = rng.multivariate_normal(mean=np.zeros(3), cov=cov, size=2000)
    caps = np.array([0.10, 1.0, 1.0])
    result = cvar_optimal_portfolio(
        scenario_returns, alpha=0.95, constraints=PortfolioConstraints(max_weight_per_asset=caps)
    )
    assert result.success
    assert result.weights[0] <= 0.10 + 1e-6
