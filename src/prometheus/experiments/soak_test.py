"""Long-horizon simulator stability and memory-leak soak testing
(REL-09: "test long-horizon simulator stability and memory leaks";
acceptance criterion: "extended soak test meets numerical and memory
thresholds").

`run_soak_test` repeats a caller-supplied `step_fn` many times,
checking every single returned array for finiteness (the "numerical"
threshold -- no NaN/Inf drift accumulating over a long horizon) and
sampling traced memory at regular intervals (the "memory" threshold --
a genuine leak shows up as memory that keeps growing roughly linearly
with iteration count, not as a one-time allocation that then
plateaus). `memory_growth_bytes` is deliberately the LAST sample minus
the FIRST, after the run has had a chance to reach its steady-state
working set, not the raw allocation at iteration zero -- a function
that legitimately allocates once and then reuses that memory should
not be flagged as leaking merely for having a nonzero baseline.
"""

from __future__ import annotations

import gc
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SoakTestResult:
    n_iterations: int
    all_finite: bool
    memory_samples_bytes: tuple[int, ...]
    memory_growth_bytes: int
    within_memory_threshold: bool


def run_soak_test(
    step_fn: Callable[[int], np.ndarray],
    n_iterations: int,
    sample_every: int,
    max_memory_growth_bytes: int,
) -> SoakTestResult:
    if n_iterations < 1:
        raise ValueError("n_iterations must be at least 1")
    if sample_every < 1:
        raise ValueError("sample_every must be at least 1")
    if max_memory_growth_bytes <= 0:
        raise ValueError("max_memory_growth_bytes must be positive")

    all_finite = True
    memory_samples: list[int] = []
    tracemalloc.start()
    try:
        for iteration in range(n_iterations):
            result = step_fn(iteration)
            if not np.all(np.isfinite(result)):
                all_finite = False
            if iteration % sample_every == 0:
                gc.collect()
                current, _peak = tracemalloc.get_traced_memory()
                memory_samples.append(current)
    finally:
        tracemalloc.stop()

    growth = memory_samples[-1] - memory_samples[0] if len(memory_samples) >= 2 else 0
    return SoakTestResult(
        n_iterations=n_iterations,
        all_finite=all_finite,
        memory_samples_bytes=tuple(memory_samples),
        memory_growth_bytes=growth,
        within_memory_threshold=growth <= max_memory_growth_bytes,
    )
