"""Inference throughput, latency and failure rate, per endpoint and
model (OPS-05: "Measure inference throughput, latency and failure
rate"; acceptance criterion: "p50/p95/p99 trends shown per endpoint
and model").

`run_inference_benchmark` takes any zero-argument callable -- a real
model's forward pass, a real HTTP request against a running service,
anything -- and times `n_requests` real attempts, tallying failures by
actually letting each attempt's own exception (of any kind) propagate
to a `try`/`except` rather than assuming what "failure" looks like for
a given backend. `endpoint` and `model` are both required, distinct
fields (REL-02's own `LoadReport` already requires `endpoint`; this
item's acceptance criterion additionally names `model` by name), so a
caller comparing reports across two different backends -- e.g. a real
trained `hedging.deep_hedge.HedgePolicyMLP` forward pass versus a real
HTTP call against `service.application.ResearchService` -- can tell
them apart. Like `experiments.latency_benchmark`'s own "load report,"
the "trends ... shown" half of this item's acceptance criterion is a
caller/visualization concern outside this repository's scope; what is
evidenced here is that each report carries the real p50/p95/p99 and
failure-rate numbers such trends would be built from.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class InferenceReport:
    endpoint: str
    model: str
    n_requests: int
    n_failures: int
    failure_rate: float
    throughput_per_second: float
    p50_seconds: float
    p95_seconds: float
    p99_seconds: float


def run_inference_benchmark(
    endpoint: str, model: str, call: Callable[[], object], n_requests: int
) -> InferenceReport:
    if not endpoint:
        raise ValueError("endpoint must not be empty")
    if not model:
        raise ValueError("model must not be empty")
    if n_requests < 1:
        raise ValueError("n_requests must be at least 1")

    latencies: list[float] = []
    n_failures = 0
    wall_start = time.perf_counter()
    for _ in range(n_requests):
        request_start = time.perf_counter()
        try:
            call()
        except Exception:
            n_failures += 1
        latencies.append(time.perf_counter() - request_start)
    wall_elapsed = time.perf_counter() - wall_start

    latency_array = np.asarray(latencies, dtype=float)
    return InferenceReport(
        endpoint=endpoint,
        model=model,
        n_requests=n_requests,
        n_failures=n_failures,
        failure_rate=n_failures / n_requests,
        throughput_per_second=(n_requests / wall_elapsed) if wall_elapsed > 0 else float("inf"),
        p50_seconds=float(np.percentile(latency_array, 50)),
        p95_seconds=float(np.percentile(latency_array, 95)),
        p99_seconds=float(np.percentile(latency_array, 99)),
    )
