"""Benchmarking simulation jobs at small/medium/large scales (REL-03:
"benchmark simulation jobs at small/medium/large scales"; acceptance
criterion: "time/memory curves and resource budget published").

Reuses `experiments.cost_benchmark.benchmark_methods_cost` (EXP-11)
rather than reimplementing timing/memory measurement -- this module
adds only the "scale" framing REL-03 itself asks for: a named
`ScaleBudget` per scale (walltime and peak-memory ceilings, PUBLISHED
by the caller before running anything, not fitted after the fact to
whatever the run happened to produce) and `check_scale_budgets`, which
reports whether each measured profile stayed within its own declared
budget.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from prometheus.experiments.cost_benchmark import MethodCostProfile


@dataclass(frozen=True, slots=True)
class ScaleBudget:
    scale: str
    max_walltime_seconds: float
    max_peak_memory_bytes: int

    def __post_init__(self) -> None:
        if not self.scale:
            raise ValueError("scale must not be empty")
        if self.max_walltime_seconds <= 0:
            raise ValueError("max_walltime_seconds must be positive")
        if self.max_peak_memory_bytes <= 0:
            raise ValueError("max_peak_memory_bytes must be positive")


@dataclass(frozen=True, slots=True)
class ScaleBenchmarkResult:
    scale: str
    profile: MethodCostProfile
    budget: ScaleBudget
    within_budget: bool


def check_scale_budgets(
    profiles: Sequence[MethodCostProfile], budgets: Mapping[str, ScaleBudget]
) -> list[ScaleBenchmarkResult]:
    """Pairs each profile with the budget declared for its own
    `method_name` (the scale label) and reports whether it was met.
    Raises if any profile names a scale with no published budget --
    every measured scale must have been budgeted in advance."""
    results = []
    for profile in profiles:
        if profile.method_name not in budgets:
            raise ValueError(f"no published budget for scale {profile.method_name!r}")
        budget = budgets[profile.method_name]
        within = (
            profile.walltime_seconds <= budget.max_walltime_seconds
            and profile.peak_memory_bytes <= budget.max_peak_memory_bytes
        )
        results.append(
            ScaleBenchmarkResult(
                scale=profile.method_name, profile=profile, budget=budget, within_budget=within
            )
        )
    return results


def walltimes_are_monotonically_increasing(
    profiles: Sequence[MethodCostProfile], scale_order: Sequence[str]
) -> bool:
    """True if walltime strictly increases from the smallest to the
    largest named scale, in `scale_order` -- the actual "time curve"
    REL-03 asks for, checked as a real property of the measurements
    rather than merely plotted."""
    by_name = {p.method_name: p for p in profiles}
    ordered = [by_name[name].walltime_seconds for name in scale_order]
    return all(earlier < later for earlier, later in zip(ordered, ordered[1:], strict=False))
