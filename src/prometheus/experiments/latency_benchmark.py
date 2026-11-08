"""Latency percentile reporting with request mix and concurrency
(REL-02: "benchmark metadata API p95 against target on reference
hardware"; acceptance criterion: "load report includes request mix
and concurrency").

`build_load_report` computes p50/p95/p99 from real, caller-supplied
latency samples -- it never estimates or assumes a distribution shape.
`request_mix` and `concurrency` are required fields on the resulting
`LoadReport`, since REL-02's own acceptance criterion names both by
name: a load report that stated only "p95 = X" with no record of how
many requests of what kind, at what concurrency, produced that number
would not be reproducible evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class LoadReport:
    endpoint: str
    request_mix: Mapping[str, int]
    concurrency: int
    n_requests: int
    p50_seconds: float
    p95_seconds: float
    p99_seconds: float


def build_load_report(
    endpoint: str,
    request_mix: Mapping[str, int],
    concurrency: int,
    latencies_seconds: Sequence[float],
) -> LoadReport:
    if not endpoint:
        raise ValueError("endpoint must not be empty")
    if not request_mix:
        raise ValueError("request_mix must not be empty")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if not latencies_seconds:
        raise ValueError("latencies_seconds must not be empty")
    latencies = np.asarray(latencies_seconds, dtype=float)
    return LoadReport(
        endpoint=endpoint,
        request_mix=dict(request_mix),
        concurrency=concurrency,
        n_requests=len(latencies),
        p50_seconds=float(np.percentile(latencies, 50)),
        p95_seconds=float(np.percentile(latencies, 95)),
        p99_seconds=float(np.percentile(latencies, 99)),
    )


def meets_p95_target(report: LoadReport, max_p95_seconds: float) -> bool:
    return report.p95_seconds <= max_p95_seconds
