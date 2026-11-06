import numpy as np
import pytest

from prometheus.titan.covariance import shrink_covariance_ledoit_wolf
from prometheus.titan.factor_model import estimate_factor_exposures
from prometheus.titan.portfolio import minimum_variance_portfolio
from prometheus.titan.risk_metrics import historical_var
from prometheus.titan.stress_testing import (
    ScenarioResult,
    StressScenario,
    historical_scenario_losses,
    run_stress_tests,
    stress_scenario_factor_attribution,
    stress_scenario_loss_from_asset_shock,
    stress_scenario_loss_from_factor_shock,
)


def test_scenario_rejects_both_shock_kinds_given() -> None:
    with pytest.raises(ValueError):
        StressScenario("bad", factor_shocks=np.array([0.1]), asset_return_shocks=np.array([0.1]))


def test_scenario_rejects_neither_shock_kind_given() -> None:
    with pytest.raises(ValueError):
        StressScenario("bad")


def test_scenario_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        StressScenario("", factor_shocks=np.array([0.1]))


def test_factor_shock_loss_matches_sign_convention() -> None:
    """A positive factor shock that only helps the portfolio (all betas
    positive, shock positive) must produce a NEGATIVE loss (i.e. a gain)."""
    weights = np.array([0.5, 0.5])
    betas = np.array([[1.0, 0.0], [1.0, 0.0]])
    loss = stress_scenario_loss_from_factor_shock(weights, betas, np.array([0.1, 0.0]))
    assert loss == pytest.approx(-0.1)


def test_factor_shock_loss_rejects_mismatched_weights_shape() -> None:
    betas = np.eye(3, 2)
    with pytest.raises(ValueError):
        stress_scenario_loss_from_factor_shock(np.ones(2), betas, np.array([0.1, 0.2]))


def test_factor_shock_loss_rejects_mismatched_factor_shocks_shape() -> None:
    betas = np.eye(3, 2)
    with pytest.raises(ValueError):
        stress_scenario_loss_from_factor_shock(np.ones(3) / 3, betas, np.array([0.1]))


def test_factor_attribution_sums_exactly_to_total_loss() -> None:
    rng = np.random.default_rng(0)
    weights = rng.dirichlet(np.ones(5))
    betas = rng.normal(0, 1, (5, 3))
    factor_shocks = rng.normal(0, 0.2, 3)

    total_loss = stress_scenario_loss_from_factor_shock(weights, betas, factor_shocks)
    contributions = stress_scenario_factor_attribution(weights, betas, factor_shocks)

    assert contributions.sum() == pytest.approx(total_loss, abs=1e-12)


def test_factor_attribution_rejects_mismatched_weights_shape() -> None:
    betas = np.eye(3, 2)
    with pytest.raises(ValueError):
        stress_scenario_factor_attribution(np.ones(2), betas, np.array([0.1, 0.2]))


def test_factor_attribution_rejects_mismatched_factor_shocks_shape() -> None:
    betas = np.eye(3, 2)
    with pytest.raises(ValueError):
        stress_scenario_factor_attribution(np.ones(3) / 3, betas, np.array([0.1]))


def test_asset_shock_loss_matches_direct_dot_product() -> None:
    weights = np.array([0.3, 0.7])
    shocks = np.array([-0.1, 0.05])
    loss = stress_scenario_loss_from_asset_shock(weights, shocks)
    assert loss == pytest.approx(-(weights @ shocks))


def test_asset_shock_loss_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError):
        stress_scenario_loss_from_asset_shock(np.ones(3), np.ones(2))


def test_factor_shock_matches_the_equivalent_implied_asset_shock() -> None:
    """Independent cross-check: composing a factor shock through betas to
    get an implied asset-level shock (betas @ factor_shocks) and applying
    it via the asset-shock path must match the factor-shock path exactly
    -- two different code paths over the same economic scenario."""
    rng = np.random.default_rng(1)
    weights = rng.dirichlet(np.ones(4))
    betas = rng.normal(0, 1, (4, 2))
    factor_shocks = rng.normal(0, 0.15, 2)

    via_factors = stress_scenario_loss_from_factor_shock(weights, betas, factor_shocks)
    implied_asset_shock = betas @ factor_shocks
    via_assets = stress_scenario_loss_from_asset_shock(weights, implied_asset_shock)

    assert via_factors == pytest.approx(via_assets, abs=1e-12)


def test_historical_scenario_losses_matches_direct_computation() -> None:
    rng = np.random.default_rng(2)
    returns = rng.normal(0, 0.05, (10, 3))
    weights = rng.dirichlet(np.ones(3))
    losses = historical_scenario_losses(returns, weights)
    assert losses == pytest.approx(-(returns @ weights))


def test_historical_scenario_losses_rejects_non_2d_returns() -> None:
    with pytest.raises(ValueError):
        historical_scenario_losses(np.ones(5), np.ones(3))


def test_historical_scenario_losses_rejects_mismatched_weights_shape() -> None:
    with pytest.raises(ValueError):
        historical_scenario_losses(np.ones((5, 3)), np.ones(4))


def test_run_stress_tests_rejects_empty_scenario_list() -> None:
    with pytest.raises(ValueError):
        run_stress_tests(np.ones(3) / 3, [])


def test_run_stress_tests_rejects_factor_scenario_without_betas() -> None:
    scenario = StressScenario("s", factor_shocks=np.array([0.1, 0.2]))
    with pytest.raises(ValueError):
        run_stress_tests(np.ones(3) / 3, [scenario], betas=None)


def test_run_stress_tests_rejects_negative_var_threshold() -> None:
    scenario = StressScenario("s", asset_return_shocks=np.array([0.1, 0.0, -0.1]))
    with pytest.raises(ValueError):
        run_stress_tests(np.ones(3) / 3, [scenario], value_at_risk_threshold=-1.0)


def test_run_stress_tests_ranks_scenarios_and_flags_var_breach() -> None:
    weights = np.array([0.5, 0.5])
    betas = np.array([[1.0, 0.0], [0.5, 0.5]])
    scenarios = [
        StressScenario("mild", factor_shocks=np.array([-0.01, 0.0])),
        StressScenario("severe", factor_shocks=np.array([-0.5, 0.0])),
        StressScenario("moderate", factor_shocks=np.array([-0.1, 0.0])),
    ]
    report = run_stress_tests(weights, scenarios, betas=betas, value_at_risk_threshold=0.1)

    assert len(report.scenario_results) == 3
    assert report.worst_case == ScenarioResult("severe", pytest.approx(0.375))
    assert report.worst_case_exceeds_var is True


def test_run_stress_tests_no_breach_when_losses_stay_under_threshold() -> None:
    weights = np.array([0.5, 0.5])
    scenario = StressScenario("mild", asset_return_shocks=np.array([-0.01, 0.0]))
    report = run_stress_tests(weights, [scenario], value_at_risk_threshold=1.0)
    assert report.worst_case_exceeds_var is False


def test_run_stress_tests_mixes_factor_and_asset_scenarios() -> None:
    weights = np.array([0.5, 0.5])
    betas = np.array([[1.0, 0.0], [0.0, 1.0]])
    scenarios = [
        StressScenario("factor_based", factor_shocks=np.array([-0.2, 0.0])),
        StressScenario("asset_based", asset_return_shocks=np.array([-0.2, 0.0])),
    ]
    report = run_stress_tests(weights, scenarios, betas=betas)
    # both scenarios describe the identical underlying shock through
    # different mechanisms (identity betas) -- losses must match exactly.
    assert report.scenario_results[0].loss == pytest.approx(report.scenario_results[1].loss)


def test_connects_to_factor_model_covariance_and_portfolio_modules() -> None:
    """A full pipeline: simulate a known factor model, estimate exposures
    (PR-027), shrink the covariance (PR-024), build a minimum-variance
    portfolio (PR-023), then stress-test it and cross-check the result
    against a direct computation using the TRUE betas -- composing four
    TITAN modules in one scenario."""
    rng = np.random.default_rng(3)
    n_obs, n_assets = 1000, 4
    true_betas = np.array([[1.2, 0.3], [0.8, -0.2], [1.0, 0.0], [0.5, 0.5]])
    factor_cov = np.array([[0.04, 0.01], [0.01, 0.02]])
    resid_var = np.array([0.0009, 0.0016, 0.0004, 0.0025])
    factors = rng.multivariate_normal(np.zeros(2), factor_cov, n_obs)
    noise = rng.normal(0.0, 1.0, (n_obs, n_assets)) * np.sqrt(resid_var)
    asset_returns = factors @ true_betas.T + noise

    exposures = estimate_factor_exposures(asset_returns, factors)
    shrunk = shrink_covariance_ledoit_wolf(asset_returns)
    opt_result = minimum_variance_portfolio(shrunk.covariance)
    assert opt_result.success

    factor_shock = np.array([-0.3, 0.1])
    loss_via_estimated_betas = stress_scenario_loss_from_factor_shock(
        opt_result.weights, exposures.betas, factor_shock
    )
    loss_via_true_betas = stress_scenario_loss_from_factor_shock(
        opt_result.weights, true_betas, factor_shock
    )
    # estimated betas (from 1000 observations) should be close to the true
    # ones, so the two stress losses should be close too -- not identical.
    assert loss_via_estimated_betas == pytest.approx(loss_via_true_betas, abs=0.05)


def test_worst_case_scenario_exceeding_historical_var_is_flagged() -> None:
    """A full scenario: build a historical loss series for a fixed
    portfolio, compute its 95% historical VaR, then confirm a stress
    scenario engineered to lose more than that VaR is correctly flagged as
    a breach, and one engineered to lose less is not."""
    rng = np.random.default_rng(4)
    returns = rng.normal(0.0005, 0.02, (500, 3))
    weights = np.array([0.4, 0.3, 0.3])
    losses = historical_scenario_losses(returns, weights)
    var95 = historical_var(losses, 0.95)

    breaching = StressScenario("breach", asset_return_shocks=np.full(3, -(var95 + 0.05)))
    safe = StressScenario("safe", asset_return_shocks=np.full(3, -(var95 - 0.05) / 3))

    breach_report = run_stress_tests(weights, [breaching], value_at_risk_threshold=var95)
    safe_report = run_stress_tests(weights, [safe], value_at_risk_threshold=var95)

    assert breach_report.worst_case_exceeds_var is True
    assert safe_report.worst_case_exceeds_var is False
