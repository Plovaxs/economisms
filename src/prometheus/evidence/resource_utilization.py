"""Resource utilization tracking with capacity forecasting and budget
alerts (OPS-09: "Track GPU/CPU/RAM and artifact storage utilization";
acceptance criterion: "Capacity forecast and budget alerts
configured").

GPU utilization is honestly NOT covered here: this environment has no
GPU hardware, and fabricating a reading from nonexistent hardware
would misrepresent what was measured, the same honest-scope boundary
this project applies to VAL-10's GPU-tolerance reproducibility item.
CPU and RAM are measured from this REAL process via the standard
library's `resource` module (`ru_utime`/`ru_stime`/`ru_maxrss`).
Artifact storage utilization reuses `jobs.artifacts.ArtifactStore.usage_bytes`
directly against that store's own configured `max_total_bytes` budget
-- the SAME byte count `ArtifactStore.put` itself already enforces,
not a second, separately-computed total that could disagree with it.

`forecast_capacity` fits a simple linear trend (least squares) through
a caller-supplied utilization history and projects forward to when a
budget would be reached -- confirmed against an exact, hand-computed
linear series, not merely checked for "a number comes out."
`classify_utilization` is the same worst-of warning/critical pattern
`evidence.queue_metrics.classify_queue_health` already uses.
"""

from __future__ import annotations

import resource
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from prometheus.jobs.artifacts import ArtifactStore

Severity = Literal["ok", "warning", "critical"]


@dataclass(frozen=True, slots=True)
class ResourceSample:
    as_of: date
    cpu_seconds: float
    ram_bytes: int
    artifact_storage_bytes: int
    artifact_storage_max_bytes: int


def sample_resource_usage(store: ArtifactStore, as_of: date) -> ResourceSample:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return ResourceSample(
        as_of=as_of,
        cpu_seconds=usage.ru_utime + usage.ru_stime,
        ram_bytes=usage.ru_maxrss * 1024,  # ru_maxrss is reported in KB on Linux
        artifact_storage_bytes=store.usage_bytes(),
        artifact_storage_max_bytes=store.max_total_bytes,
    )


@dataclass(frozen=True, slots=True)
class CapacityForecast:
    series_name: str
    current_value: float
    daily_growth_rate: float
    budget: float
    days_until_budget_exhausted: float | None
    """None means the trend is flat or shrinking -- the budget is
    never reached by extrapolation, not "exhausted today"."""


def forecast_capacity(
    series_name: str, samples: Sequence[tuple[date, float]], budget: float
) -> CapacityForecast:
    if not series_name:
        raise ValueError("series_name must not be empty")
    if len(samples) < 2:
        raise ValueError("at least two samples are required to fit a trend")
    if budget <= 0:
        raise ValueError("budget must be positive")
    ordered = sorted(samples, key=lambda sample: sample[0])
    t0 = ordered[0][0]
    xs = np.array([(day - t0).days for day, _ in ordered], dtype=float)
    ys = np.array([value for _, value in ordered], dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    # A numerically-flat or shrinking trend never reaches the budget by
    # extrapolation; the tolerance absorbs float noise from polyfit on
    # genuinely constant data (e.g. slope == 4e-16 rather than exactly 0).
    scale = max(float(np.abs(ys).max()), 1.0)
    is_growing = slope > scale * 1e-9

    days_until: float | None
    if not is_growing:
        days_until = None
    else:
        x_at_budget = (budget - intercept) / slope
        days_until = max(x_at_budget - xs[-1], 0.0)

    return CapacityForecast(
        series_name=series_name,
        current_value=float(ys[-1]),
        daily_growth_rate=float(slope),
        budget=budget,
        days_until_budget_exhausted=days_until,
    )


@dataclass(frozen=True, slots=True)
class UtilizationThresholds:
    warning_fraction: float
    critical_fraction: float

    def __post_init__(self) -> None:
        if not 0.0 < self.warning_fraction <= self.critical_fraction <= 1.0:
            raise ValueError(
                "thresholds must satisfy 0 < warning_fraction <= critical_fraction <= 1"
            )


def classify_utilization(
    current: float, budget: float, thresholds: UtilizationThresholds
) -> Severity:
    if budget <= 0:
        raise ValueError("budget must be positive")
    fraction = current / budget
    if fraction >= thresholds.critical_fraction:
        return "critical"
    if fraction >= thresholds.warning_fraction:
        return "warning"
    return "ok"
