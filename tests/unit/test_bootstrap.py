import numpy as np
import pytest

from prometheus.experiments.bootstrap import paired_bootstrap_difference


def test_paired_constant_shift_gives_a_degenerate_ci_at_the_exact_shift() -> None:
    """If sample_a is sample_b plus a constant shift everywhere, every
    possible resample of paired indices reproduces that exact shift --
    this is the crux property that makes it a *paired* bootstrap: an
    unpaired (independently resampled) bootstrap would not collapse to a
    point here."""
    rng = np.random.default_rng(0)
    baseline = rng.standard_normal(2000) * 5 + 50
    shift = 3.0
    sample_a = baseline + shift
    sample_b = baseline

    result = paired_bootstrap_difference(
        np.mean, sample_a, sample_b, np.random.default_rng(1), n_resamples=1000
    )
    assert result.point_estimate == pytest.approx(shift, abs=1e-9)
    assert result.ci_low == pytest.approx(shift, abs=1e-8)
    assert result.ci_high == pytest.approx(shift, abs=1e-8)
    assert result.excludes_zero()


def test_identical_samples_never_exclude_zero() -> None:
    rng = np.random.default_rng(2)
    sample = rng.standard_normal(500)
    result = paired_bootstrap_difference(
        np.mean, sample, sample.copy(), np.random.default_rng(3), n_resamples=500
    )
    assert result.point_estimate == 0.0
    assert not result.excludes_zero()


def test_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap_difference(
            np.mean, np.zeros(5), np.zeros(4), np.random.default_rng(0)
        )


def test_rejects_empty_samples() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap_difference(
            np.mean, np.array([]), np.array([]), np.random.default_rng(0)
        )


def test_rejects_bad_confidence() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap_difference(
            np.mean, np.zeros(5), np.zeros(5), np.random.default_rng(0), confidence=1.5
        )


def test_deterministic_given_a_fixed_rng_seed() -> None:
    sample_a = np.arange(100, dtype=float)
    sample_b = np.arange(100, dtype=float) * 0.5
    result_1 = paired_bootstrap_difference(
        np.mean, sample_a, sample_b, np.random.default_rng(42), n_resamples=300
    )
    result_2 = paired_bootstrap_difference(
        np.mean, sample_a, sample_b, np.random.default_rng(42), n_resamples=300
    )
    assert result_1 == result_2
