import numpy as np
import pytest
import torch
from scipy import integrate, stats

from prometheus.neural_sde.scoring import (
    gaussian_crps,
    gaussian_log_score,
    marginal_crps_report,
    moment_diagnostics,
)
from prometheus.neural_sde.training import gaussian_transition_nll


def test_gaussian_log_score_matches_torch_gaussian_transition_nll_on_a_shared_toy_case() -> None:
    """Cross-checks the two independent (numpy vs torch) implementations
    of the same Gaussian NLL math agree -- see scoring.gaussian_log_score's
    docstring for why both exist."""

    class _FixedOutputModel(torch.nn.Module):
        def forward(self, t, state, regime):  # noqa: ANN001
            batch = state.shape[0]
            drift = torch.zeros(batch, 2)
            sigma = torch.tensor([[2.0, 0.3], [0.3, 1.0]]).unsqueeze(0).expand(batch, -1, -1)
            return drift, sigma

    model = _FixedOutputModel()
    t = torch.zeros(5, 1)
    state = torch.zeros(5, 2)
    regime = torch.zeros(5, 1)
    next_state = torch.tensor([[0.5, -0.2], [1.0, 0.1], [-0.3, 0.4], [0.0, 0.0], [2.0, -1.0]])

    torch_nll = gaussian_transition_nll(model, t, state, regime, next_state, dt_scaled=1.0).item()

    mu = np.zeros((5, 2))
    sigma = np.tile(np.array([[2.0, 0.3], [0.3, 1.0]]), (5, 1, 1))
    numpy_score = gaussian_log_score(mu, sigma, next_state.numpy())

    assert numpy_score == pytest.approx(torch_nll, abs=1e-5)


def test_gaussian_crps_matches_brute_force_numerical_integration() -> None:
    """Cross-checks the closed-form CRPS formula against the CRPS
    definition itself (integral of (F(x) - 1[x >= y])^2 dx), computed by
    numerical quadrature -- independent verification of the formula, not
    just a regression check against itself."""
    mu, sigma, observed = 0.3, 1.7, -0.5

    def integrand(x: float) -> float:
        cdf = stats.norm.cdf(x, loc=mu, scale=sigma)
        indicator = 1.0 if x >= observed else 0.0
        return (cdf - indicator) ** 2

    numerical, _ = integrate.quad(integrand, -40, 40, limit=200)
    closed_form = gaussian_crps(mu, sigma, observed)
    assert closed_form == pytest.approx(numerical, abs=1e-4)


def test_gaussian_crps_requires_positive_sigma() -> None:
    with pytest.raises(ValueError, match="sigma"):
        gaussian_crps(0.0, 0.0, 1.0)


def test_marginal_crps_report_shape_and_keys() -> None:
    mu = np.zeros((4, 2))
    sigma_diag = np.ones((4, 2))
    observed = np.array([[0.1, -0.1], [0.5, 0.0], [-0.3, 0.2], [0.0, 0.0]])
    report = marginal_crps_report(mu, sigma_diag, observed)
    assert set(report) == {"mean_crps", "crps_dim_0", "crps_dim_1"}
    assert report["mean_crps"] == pytest.approx((report["crps_dim_0"] + report["crps_dim_1"]) / 2)


def test_marginal_crps_report_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="shape"):
        marginal_crps_report(np.zeros((3, 2)), np.ones((3, 2)), np.zeros((4, 2)))


def test_moment_diagnostics_detects_real_positive_skew() -> None:
    """A lognormal sample has a known, strongly positive skew (>1 for
    sigma=0.5) -- the diagnostic's point estimate and bootstrap CI
    should both land clearly above zero."""
    rng = np.random.default_rng(0)
    terminal = rng.lognormal(mean=0.0, sigma=0.5, size=500)
    paths = np.tile(terminal[:, None], (1, 5))  # trivial "path" for the API shape

    result = moment_diagnostics(terminal, paths, n_bootstrap=200, seed=1)
    assert result.skew > 0.5
    assert result.skew_ci_low > 0
    assert result.n_paths == 500


def test_moment_diagnostics_near_symmetric_normal_sample_has_small_point_estimate_skew() -> None:
    """A symmetric (Gaussian) sample's point-estimate skew should be
    close to zero and its CI narrow around it -- checked against a
    fixed small tolerance rather than requiring the CI to straddle
    exactly zero, which is itself a ~90%-confidence event (expected to
    fail ~1 run in 10 at this sample size) and would make this test
    flaky by construction."""
    rng = np.random.default_rng(2)
    terminal = rng.normal(loc=0.0, scale=1.0, size=1000)
    paths = np.tile(terminal[:, None], (1, 5))

    result = moment_diagnostics(terminal, paths, n_bootstrap=300, seed=3)
    assert abs(result.skew) < 0.3
    assert result.skew_ci_high - result.skew_ci_low < 0.6


def test_moment_diagnostics_requires_minimum_paths() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        moment_diagnostics(np.zeros(3), np.zeros((3, 2)))
