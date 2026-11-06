import numpy as np
import pytest

from prometheus.experiments.cost_benchmark import benchmark_method_cost
from prometheus.experiments.scale_benchmark import (
    ScaleBenchmarkResult,
    ScaleBudget,
    check_scale_budgets,
    walltimes_are_monotonically_increasing,
)
from prometheus.stochastica.gbm import simulate_gbm_paths


def _gbm_run(n_paths: int, n_steps: int):
    def run() -> None:
        rng = np.random.default_rng(0)
        simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=n_steps, n_paths=n_paths, rng=rng)

    return run


def _real_scale_profiles():
    """A genuine small/medium/large GBM simulation benchmark, not
    synthetic numbers. A throwaway warm-up call runs first (standard
    benchmarking practice, confirmed necessary here: the very first
    timed call in a session otherwise absorbs a one-time numpy/BLAS
    warm-up cost large enough to make "small" appear slower than
    "medium" -- verified directly before trusting the measurements)."""
    _gbm_run(10, 5)()
    return [
        benchmark_method_cost("small", _gbm_run(200, 20), "float64"),
        benchmark_method_cost("medium", _gbm_run(2000, 100), "float64"),
        benchmark_method_cost("large", _gbm_run(10_000, 300), "float64"),
    ]


def _budgets():
    return {
        "small": ScaleBudget("small", max_walltime_seconds=1.0, max_peak_memory_bytes=10_000_000),
        "medium": ScaleBudget(
            "medium", max_walltime_seconds=1.0, max_peak_memory_bytes=50_000_000
        ),
        "large": ScaleBudget(
            "large", max_walltime_seconds=1.0, max_peak_memory_bytes=200_000_000
        ),
    }


def test_scale_budget_rejects_an_empty_scale_label() -> None:
    with pytest.raises(ValueError, match="scale"):
        ScaleBudget("", max_walltime_seconds=1.0, max_peak_memory_bytes=1)


def test_scale_budget_rejects_a_non_positive_walltime() -> None:
    with pytest.raises(ValueError, match="max_walltime_seconds"):
        ScaleBudget("small", max_walltime_seconds=0.0, max_peak_memory_bytes=1)


def test_scale_budget_rejects_a_non_positive_memory_ceiling() -> None:
    with pytest.raises(ValueError, match="max_peak_memory_bytes"):
        ScaleBudget("small", max_walltime_seconds=1.0, max_peak_memory_bytes=0)


def test_real_gbm_walltime_curve_is_monotonically_increasing_with_scale() -> None:
    """REL-03's own "time ... curves" requirement, checked as a real
    property of a genuine small/medium/large GBM simulation, not
    plotted from assumed numbers."""
    profiles = _real_scale_profiles()
    assert walltimes_are_monotonically_increasing(profiles, ["small", "medium", "large"])


def test_real_gbm_memory_curve_is_monotonically_increasing_with_scale() -> None:
    """REL-03's "memory curves" half, likewise measured, not assumed."""
    profiles = _real_scale_profiles()
    by_name = {p.method_name: p.peak_memory_bytes for p in profiles}
    assert by_name["small"] < by_name["medium"] < by_name["large"]


def test_check_scale_budgets_passes_when_every_scale_is_within_its_own_budget() -> None:
    profiles = _real_scale_profiles()
    results = check_scale_budgets(profiles, _budgets())
    assert all(r.within_budget for r in results)
    assert all(isinstance(r, ScaleBenchmarkResult) for r in results)


def test_check_scale_budgets_flags_a_genuine_budget_violation() -> None:
    """The discriminating half: a deliberately unrealistic (too tight)
    published budget for the large scale must be reported as violated,
    not silently passed."""
    profiles = _real_scale_profiles()
    budgets = _budgets()
    tight_large = ScaleBudget("large", max_walltime_seconds=1e-9, max_peak_memory_bytes=1)
    budgets["large"] = tight_large
    results = check_scale_budgets(profiles, budgets)
    by_scale = {r.scale: r.within_budget for r in results}
    assert by_scale["small"] is True
    assert by_scale["medium"] is True
    assert by_scale["large"] is False


def test_check_scale_budgets_rejects_a_profile_with_no_published_budget() -> None:
    profiles = _real_scale_profiles()
    budgets = _budgets()
    del budgets["large"]
    with pytest.raises(ValueError, match="no published budget"):
        check_scale_budgets(profiles, budgets)


def test_walltimes_are_monotonically_increasing_is_false_for_a_violating_order() -> None:
    profiles = _real_scale_profiles()
    assert not walltimes_are_monotonically_increasing(profiles, ["large", "small", "medium"])
