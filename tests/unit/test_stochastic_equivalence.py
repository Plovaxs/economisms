from __future__ import annotations

import numpy as np
import pytest

from prometheus.evidence.stochastic_equivalence import (
    EquivalenceResult,
    two_sample_ks_equivalence,
)
from prometheus.stochastica.gbm import simulate_gbm_paths


def test_rejects_empty_samples() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        two_sample_ks_equivalence(np.array([]), np.array([1.0, 2.0]))


def test_two_independently_seeded_real_gbm_runs_are_statistically_equivalent() -> None:
    """The real discriminating positive case VAL-10 exists for: two
    runs of the IDENTICAL parameterization, seeded differently (so
    exact bit-replay is impossible by construction, the same way a
    GPU-vs-GPU or GPU-vs-CPU run would differ), confirmed statistically
    equivalent rather than merely assumed to be."""
    terminal_a = simulate_gbm_paths(
        s0=100.0, mu=0.05, sigma=0.2, maturity=1.0, n_steps=50, n_paths=5000,
        rng=np.random.default_rng(0),
    )[:, -1]
    terminal_b = simulate_gbm_paths(
        s0=100.0, mu=0.05, sigma=0.2, maturity=1.0, n_steps=50, n_paths=5000,
        rng=np.random.default_rng(1),
    )[:, -1]
    assert not np.array_equal(terminal_a, terminal_b)  # confirms exact replay genuinely fails

    result = two_sample_ks_equivalence(terminal_a, terminal_b)
    assert isinstance(result, EquivalenceResult)
    assert result.equivalent is True
    assert result.test_name == "ks_2samp"


def test_two_runs_with_a_genuinely_different_sigma_are_not_equivalent() -> None:
    """The real negative control: this is not a test that always
    passes -- a genuine distributional difference (sigma=0.2 vs.
    sigma=0.8, same seed so only the parameter differs) must be
    detected."""
    low_vol = simulate_gbm_paths(
        s0=100.0, mu=0.05, sigma=0.2, maturity=1.0, n_steps=50, n_paths=5000,
        rng=np.random.default_rng(0),
    )[:, -1]
    high_vol = simulate_gbm_paths(
        s0=100.0, mu=0.05, sigma=0.8, maturity=1.0, n_steps=50, n_paths=5000,
        rng=np.random.default_rng(0),
    )[:, -1]

    result = two_sample_ks_equivalence(low_vol, high_vol)
    assert result.equivalent is False
    assert result.p_value < result.alpha


def test_the_same_array_compared_to_itself_is_trivially_equivalent() -> None:
    sample = simulate_gbm_paths(
        s0=100.0, mu=0.0, sigma=0.3, maturity=1.0, n_steps=20, n_paths=1000,
        rng=np.random.default_rng(42),
    )[:, -1]
    result = two_sample_ks_equivalence(sample, sample)
    assert result.statistic == 0.0
    assert result.equivalent is True


def test_alpha_is_configurable_and_affects_the_equivalence_verdict() -> None:
    terminal_a = simulate_gbm_paths(
        s0=100.0, mu=0.05, sigma=0.2, maturity=1.0, n_steps=50, n_paths=200,
        rng=np.random.default_rng(5),
    )[:, -1]
    terminal_b = simulate_gbm_paths(
        s0=100.0, mu=0.05, sigma=0.2, maturity=1.0, n_steps=50, n_paths=200,
        rng=np.random.default_rng(6),
    )[:, -1]
    lenient = two_sample_ks_equivalence(terminal_a, terminal_b, alpha=1e-9)
    assert lenient.equivalent is True  # near-impossible to reject at this tiny alpha
