import numpy as np
import pytest

from prometheus.experiments.block_bootstrap import BlockBootstrapResult, moving_block_bootstrap


def _exact_ar1_mean_variance(phi: float, sigma_eps: float, n: int) -> float:
    """Exact finite-sample variance of the sample mean of a stationary
    AR(1) process, from its known covariance structure Cov(X_i, X_j) =
    sigma_x^2 * phi^|i-j| -- a ground truth computed analytically, not
    by simulation, so it carries no Monte Carlo error of its own."""
    sigma_x2 = sigma_eps**2 / (1 - phi**2)
    indices = np.arange(n)
    lag_matrix = np.abs(indices[:, None] - indices[None, :])
    cov = sigma_x2 * (phi**lag_matrix)
    return float(cov.sum() / n**2)


def _simulate_ar1(phi: float, sigma_eps: float, n: int, rng: np.random.Generator) -> np.ndarray:
    sigma_x = np.sqrt(sigma_eps**2 / (1 - phi**2))
    x = np.empty(n)
    x[0] = rng.normal(0.0, sigma_x)
    eps = rng.normal(0.0, sigma_eps, size=n - 1)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + eps[t - 1]
    return x


def test_moving_block_bootstrap_estimates_the_known_ar1_mean_se_far_better_than_iid() -> None:
    """EXP-09's own acceptance criterion: "inference verified on
    correlated synthetic test cases." An i.i.d. bootstrap (block_length=1)
    on an autocorrelated AR(1) series systematically UNDER-estimates the
    true standard error of the sample mean (it throws away the positive
    serial dependence that inflates the true variance); the moving block
    bootstrap, with a longer block, must recover a value substantially
    closer to the exact, analytically-known truth. This is the
    discriminating comparison -- not just "the block bootstrap runs
    without crashing," but "it is measurably more correct than the
    naive alternative on a case where the right answer is known.\""""
    phi, sigma_eps, n = 0.7, 1.0, 300
    true_se = np.sqrt(_exact_ar1_mean_variance(phi, sigma_eps, n))
    block_length = round(n**0.5)

    rng = np.random.default_rng(0)
    n_trials = 40
    iid_widths = []
    block_widths = []
    for _ in range(n_trials):
        sample = _simulate_ar1(phi, sigma_eps, n, rng)
        iid_result = moving_block_bootstrap(np.mean, sample, 1, rng, n_resamples=400)
        block_result = moving_block_bootstrap(np.mean, sample, block_length, rng, n_resamples=400)
        iid_widths.append(iid_result.ci_high - iid_result.ci_low)
        block_widths.append(block_result.ci_high - block_result.ci_low)

    # A 95% percentile CI width is approximately 2 * 1.96 * SE for a
    # roughly symmetric bootstrap distribution; convert the exact SE to
    # that same comparable scale.
    mean_iid_width = float(np.mean(iid_widths))
    mean_block_width = float(np.mean(block_widths))
    true_width_scale = 2.0 * 1.959964 * true_se

    assert mean_block_width > mean_iid_width * 1.5
    # the i.i.d. version must badly underestimate relative to the truth...
    assert mean_iid_width / true_width_scale < 0.6
    # ...while the block version lands much closer to it.
    assert 0.6 < mean_block_width / true_width_scale < 1.3


def test_moving_block_bootstrap_ci_coverage_is_closer_to_nominal_than_iid() -> None:
    """A direct coverage-rate check (same style as the Monte Carlo
    confidence-interval coverage test elsewhere in this repository):
    over many independent AR(1) draws, how often does each method's
    nominal-95% CI actually contain the TRUE mean (0, by construction)?
    The block bootstrap must cover meaningfully more often than the
    i.i.d. bootstrap, which is known to be badly miscalibrated here."""
    phi, sigma_eps, n = 0.7, 1.0, 200
    block_length = round(n**0.5)
    rng = np.random.default_rng(1)
    n_trials = 150
    iid_covers = 0
    block_covers = 0
    for _ in range(n_trials):
        sample = _simulate_ar1(phi, sigma_eps, n, rng)
        iid_result = moving_block_bootstrap(np.mean, sample, 1, rng, n_resamples=300)
        block_result = moving_block_bootstrap(np.mean, sample, block_length, rng, n_resamples=300)
        if iid_result.ci_low <= 0.0 <= iid_result.ci_high:
            iid_covers += 1
        if block_result.ci_low <= 0.0 <= block_result.ci_high:
            block_covers += 1

    iid_rate = iid_covers / n_trials
    block_rate = block_covers / n_trials
    assert block_rate > iid_rate + 0.15
    assert iid_rate < 0.80  # badly under nominal 0.95
    assert block_rate > 0.70  # much closer, though not claimed exact


def test_block_length_one_is_equivalent_to_plain_iid_resampling() -> None:
    """block_length=1 degenerates to resampling single observations with
    replacement -- the ordinary i.i.d. bootstrap, as a special case."""
    sample = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = moving_block_bootstrap(
        np.mean, sample, block_length=1, rng=np.random.default_rng(5), n_resamples=1000
    )
    assert result.point_estimate == pytest.approx(3.0)
    assert 1.0 <= result.ci_low <= result.ci_high <= 5.0


def test_block_length_equal_to_sample_length_always_reproduces_the_original() -> None:
    """With exactly one possible block (the whole series itself), every
    resample IS the original sample -- a fully degenerate, zero-width CI,
    not an error."""
    sample = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = moving_block_bootstrap(
        np.mean, sample, block_length=5, rng=np.random.default_rng(6), n_resamples=100
    )
    assert result.ci_low == result.ci_high == pytest.approx(3.0)


def test_rejects_non_1d_or_empty_sample() -> None:
    with pytest.raises(ValueError):
        moving_block_bootstrap(np.mean, np.array([]), 1, np.random.default_rng(0))
    with pytest.raises(ValueError):
        moving_block_bootstrap(np.mean, np.zeros((2, 2)), 1, np.random.default_rng(0))


def test_rejects_block_length_out_of_range() -> None:
    sample = np.arange(10, dtype=float)
    with pytest.raises(ValueError, match="block_length"):
        moving_block_bootstrap(np.mean, sample, 0, np.random.default_rng(0))
    with pytest.raises(ValueError, match="block_length"):
        moving_block_bootstrap(np.mean, sample, 11, np.random.default_rng(0))


def test_rejects_bad_confidence_and_n_resamples() -> None:
    sample = np.arange(10, dtype=float)
    with pytest.raises(ValueError, match="confidence"):
        moving_block_bootstrap(np.mean, sample, 2, np.random.default_rng(0), confidence=1.5)
    with pytest.raises(ValueError, match="n_resamples"):
        moving_block_bootstrap(np.mean, sample, 2, np.random.default_rng(0), n_resamples=0)


def test_excludes_zero_matches_the_ci_bounds() -> None:
    sample = np.full(20, 5.0)
    result = moving_block_bootstrap(np.mean, sample, 3, np.random.default_rng(7))
    assert result.excludes_zero()
    assert result == BlockBootstrapResult(
        point_estimate=5.0,
        ci_low=5.0,
        ci_high=5.0,
        confidence=result.confidence,
        n_resamples=result.n_resamples,
        block_length=3,
    )


def test_deterministic_given_a_fixed_rng_seed() -> None:
    sample = np.arange(50, dtype=float)
    result_a = moving_block_bootstrap(np.mean, sample, 5, np.random.default_rng(42))
    result_b = moving_block_bootstrap(np.mean, sample, 5, np.random.default_rng(42))
    assert result_a == result_b
