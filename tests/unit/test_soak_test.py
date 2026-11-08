import numpy as np
import pytest

from prometheus.experiments.soak_test import run_soak_test
from prometheus.stochastica.gbm import simulate_gbm_paths


def test_rejects_a_non_positive_iteration_count() -> None:
    with pytest.raises(ValueError, match="n_iterations"):
        run_soak_test(
            lambda i: np.array([1.0]), n_iterations=0, sample_every=1, max_memory_growth_bytes=1
        )


def test_rejects_a_non_positive_sample_interval() -> None:
    with pytest.raises(ValueError, match="sample_every"):
        run_soak_test(
            lambda i: np.array([1.0]), n_iterations=1, sample_every=0, max_memory_growth_bytes=1
        )


def test_rejects_a_non_positive_memory_threshold() -> None:
    with pytest.raises(ValueError, match="max_memory_growth_bytes"):
        run_soak_test(
            lambda i: np.array([1.0]), n_iterations=1, sample_every=1, max_memory_growth_bytes=0
        )


def test_a_real_long_horizon_gbm_simulation_is_numerically_stable_and_leak_free() -> None:
    """REL-09's own acceptance criterion: "extended soak test meets
    numerical and memory thresholds," run against a genuine, repeated
    `stochastica.gbm.simulate_gbm_paths` call (a stateless function
    that should legitimately plateau in memory, not accumulate), not a
    toy loop."""

    def step(iteration: int) -> np.ndarray:
        rng = np.random.default_rng(iteration)
        return simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=50, n_paths=200, rng=rng)

    result = run_soak_test(
        step, n_iterations=60, sample_every=5, max_memory_growth_bytes=5_000_000
    )
    assert result.all_finite is True
    assert result.within_memory_threshold is True
    assert result.n_iterations == 60
    assert len(result.memory_samples_bytes) == 12  # 60 / 5


def test_a_deliberately_retaining_step_function_is_flagged_as_leaking() -> None:
    """The discriminating half: a step function that deliberately
    retains every array it allocates (a real leak, not a figure of
    speech) must be caught -- `within_memory_threshold` becomes False
    against a threshold the clean case above comfortably satisfies."""
    retained: list[np.ndarray] = []

    def leaky_step(iteration: int) -> np.ndarray:
        array = np.ones(100_000)
        retained.append(array)
        return array

    result = run_soak_test(
        leaky_step, n_iterations=60, sample_every=5, max_memory_growth_bytes=5_000_000
    )
    assert result.all_finite is True  # the leak is a memory problem, not a numerical one
    assert result.within_memory_threshold is False
    assert result.memory_growth_bytes > 5_000_000


def test_a_single_non_finite_value_anywhere_in_the_horizon_is_detected() -> None:
    """The numerical half's own discriminating case: a single NaN
    injected partway through a long horizon, surrounded by otherwise
    perfectly finite iterations, must still be caught -- not averaged
    away or missed because most iterations were fine."""

    def step_with_one_bad_iteration(iteration: int) -> np.ndarray:
        array = np.ones(10)
        if iteration == 37:
            array[3] = np.nan
        return array

    result = run_soak_test(
        step_with_one_bad_iteration, n_iterations=60, sample_every=5,
        max_memory_growth_bytes=5_000_000,
    )
    assert result.all_finite is False


def test_memory_samples_are_collected_at_the_requested_interval() -> None:
    calls = {"n": 0}

    def step(iteration: int) -> np.ndarray:
        calls["n"] += 1
        return np.ones(5)

    result = run_soak_test(step, n_iterations=20, sample_every=4, max_memory_growth_bytes=5_000_000)
    assert calls["n"] == 20
    assert len(result.memory_samples_bytes) == 5  # iterations 0, 4, 8, 12, 16
