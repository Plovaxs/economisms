"""Model drift, calibration and retraining triggers (MLO-13: "track
model drift, calibration and retraining triggers"; acceptance
criterion: "thresholds and escalation recorded before deployment").

`RetrainingThreshold` is a frozen (immutable once constructed) record
of a calibration metric's name, its acceptable p-value floor, and the
date it was `recorded_before_deployment_at` -- "before deployment" is
enforced, not merely named: `evaluate_retraining_trigger` rejects any
monitoring observation dated earlier than the threshold's own
recorded date, so a threshold can never be back-dated to make an
already-known-bad observation look like it was anticipated in advance.
Because the threshold is frozen, it also cannot be loosened after the
fact once an unfavorable observation has been seen.

Demonstrated against `titan.risk_metrics.es_unconditional_calibration_test`
(RISK-09, reused rather than reinvented) with REAL p-values from a
genuinely well-calibrated and a genuinely miscalibrated Expected
Shortfall forecast, not fabricated numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class RetrainingThreshold:
    metric_name: str
    min_acceptable_p_value: float
    recorded_before_deployment_at: date

    def __post_init__(self) -> None:
        if not self.metric_name:
            raise ValueError("metric_name must not be empty")
        if not 0.0 < self.min_acceptable_p_value < 1.0:
            raise ValueError("min_acceptable_p_value must be in (0, 1)")


@dataclass(frozen=True, slots=True)
class RetrainingEscalation:
    metric_name: str
    observed_p_value: float
    observed_at: date
    threshold: RetrainingThreshold
    escalate: bool


def evaluate_retraining_trigger(
    threshold: RetrainingThreshold, observed_p_value: float, observed_at: date
) -> RetrainingEscalation:
    if observed_at < threshold.recorded_before_deployment_at:
        raise ValueError(
            f"observation dated {observed_at} precedes its own threshold's "
            f"recorded_before_deployment_at ({threshold.recorded_before_deployment_at}) -- "
            "a threshold must be recorded before deployment, not backdated to fit an "
            "already-known observation"
        )
    escalate = observed_p_value < threshold.min_acceptable_p_value
    return RetrainingEscalation(
        metric_name=threshold.metric_name,
        observed_p_value=observed_p_value,
        observed_at=observed_at,
        threshold=threshold,
        escalate=escalate,
    )
