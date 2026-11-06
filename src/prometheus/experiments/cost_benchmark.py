"""Computational cost and memory benchmarking across methods (EXP-11:
"benchmark computational cost and memory across methods"; acceptance
criterion: "hardware, GPU driver, dtype and walltime logged").

`capture_hardware_info` reports the platform string, Python version,
and GPU availability/driver -- honestly: this repository has no GPU
code anywhere (confirmed directly, see VAL-10's own documented
limitation), and this environment's own PyTorch build is CPU-only
(confirmed directly: `torch.cuda.is_available()` is `False`,
`torch.version.cuda` is `None`), so `gpu_available` is `False` and
`gpu_driver` is `None` here -- the field is present and logged, per the
acceptance criterion, not silently omitted merely because there is
nothing to report. When a GPU IS available, `gpu_driver` reports the
CUDA runtime version PyTorch itself was built against
(`torch.version.cuda`), not an `nvidia-smi`-queried driver string (that
would need a new dependency, `pynvml`, to query something this
environment has no way to verify against real hardware).

`benchmark_method_cost` times one callable with `time.perf_counter`
(monotonic, appropriate for wall-clock elapsed time) and measures its
peak memory via the standard library's `tracemalloc` (no new
dependency), alongside the caller-declared `dtype` describing what
numeric type the benchmarked computation used (not auto-detected --
genuinely impossible to infer in general from an arbitrary callable).
`benchmark_methods_cost` runs several named methods and returns their
profiles sorted by walltime, the "across methods" half of EXP-11.
"""

from __future__ import annotations

import platform
import time
import tracemalloc
from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HardwareInfo:
    platform: str
    python_version: str
    gpu_available: bool
    gpu_driver: str | None

    def __post_init__(self) -> None:
        if self.gpu_driver is not None and not self.gpu_available:
            raise ValueError("gpu_driver must be None when gpu_available is False")


def capture_hardware_info() -> HardwareInfo:
    gpu_available = False
    gpu_driver: str | None = None
    try:
        import torch

        gpu_available = bool(torch.cuda.is_available())
        if gpu_available:
            gpu_driver = torch.version.cuda
    except ImportError:
        pass
    return HardwareInfo(
        platform=platform.platform(),
        python_version=platform.python_version(),
        gpu_available=gpu_available,
        gpu_driver=gpu_driver,
    )


@dataclass(frozen=True, slots=True)
class MethodCostProfile:
    method_name: str
    dtype: str
    walltime_seconds: float
    peak_memory_bytes: int
    hardware: HardwareInfo

    def __post_init__(self) -> None:
        if not self.method_name:
            raise ValueError("method_name must not be empty")
        if not self.dtype:
            raise ValueError("dtype must not be empty")
        if self.walltime_seconds < 0:
            raise ValueError(f"walltime_seconds must be non-negative, got {self.walltime_seconds}")
        if self.peak_memory_bytes < 0:
            raise ValueError(
                f"peak_memory_bytes must be non-negative, got {self.peak_memory_bytes}"
            )


def benchmark_method_cost(
    method_name: str, fn: Callable[[], object], dtype: str
) -> MethodCostProfile:
    """Runs `fn()` exactly once, measuring its wall-clock time and peak
    traced-memory allocation. `tracemalloc` is started fresh for this
    call (any prior tracking state is reset), so nested or concurrent
    use of this function in the same process would corrupt the
    measurement -- callers benchmark one method at a time, sequentially,
    as `benchmark_methods_cost` below does."""
    tracemalloc.start()
    try:
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return MethodCostProfile(
        method_name=method_name,
        dtype=dtype,
        walltime_seconds=elapsed,
        peak_memory_bytes=peak_bytes,
        hardware=capture_hardware_info(),
    )


def benchmark_methods_cost(
    methods: Mapping[str, tuple[Callable[[], object], str]],
) -> list[MethodCostProfile]:
    """Benchmarks every (fn, dtype) pair in `methods`, keyed by method
    name, and returns the resulting profiles sorted by walltime
    ascending (fastest first) -- the cross-method comparison EXP-11
    itself asks for."""
    if not methods:
        raise ValueError("benchmark_methods_cost needs at least one method")
    profiles = [
        benchmark_method_cost(name, fn, dtype) for name, (fn, dtype) in methods.items()
    ]
    return sorted(profiles, key=lambda p: p.walltime_seconds)
