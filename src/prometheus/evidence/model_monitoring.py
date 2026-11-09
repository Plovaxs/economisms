"""Model drift, risk-metric calibration and tail-breach monitoring,
composed from existing primitives, with an investigation playbook
(OPS-08: "Monitor model drift, risk metric calibration and tail
breach"; acceptance criterion: "Model monitoring dashboard and
investigation playbook").

Composes three independently-evidenced signals rather than reinventing
any of them:

- "tail breach" -> `titan.risk_metrics.var_exception_coverage_test`
  (RISK-08), a real Kupiec-style VaR exceedance test.
- "risk metric calibration" -> the SAME `RetrainingEscalation` framing
  `evidence.retraining_trigger` (MLO-13) already uses, itself built on
  `titan.risk_metrics.es_unconditional_calibration_test` (RISK-09).
- "model drift" -> `experiments.bootstrap.paired_bootstrap_difference`
  (the same primitive `evidence.champion_challenger` (MLO-14) uses),
  applied to a hedging strategy's own terminal-loss distribution at
  two configuration snapshots evaluated on the SAME simulated price
  paths via `hedging.simulate.simulate_self_financing_hedge` -- the
  identical matched-data pattern `test_champion_challenger.py` already
  uses.

The investigation playbook is the one genuinely new structure here: an
ordered, caller-extensible response action for each signal that fires,
each one carrying a required owner, so a monitoring breach never
produces a vague "investigate" with no concrete next action or
accountable person.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from prometheus.evidence.retraining_trigger import RetrainingEscalation
from prometheus.experiments.bootstrap import BootstrapResult
from prometheus.titan.risk_metrics import VarCoverageResult

SignalName = Literal["tail_breach", "calibration", "drift"]

_PLAYBOOK_ACTIONS: dict[SignalName, str] = {
    "tail_breach": (
        "VaR exception rate deviates from the expected rate: freeze "
        "VaR-dependent position sizing and recompute VaR over the latest window."
    ),
    "calibration": (
        "Expected Shortfall calibration p-value fell below threshold: "
        "suspend auto-promotion for this model and rerun the calibration backtest."
    ),
    "drift": (
        "Strategy's measured loss distribution moved by a statistically "
        "significant amount: open a champion/challenger comparison against "
        "the last approved champion."
    ),
}


@dataclass(frozen=True, slots=True)
class MonitoringSignal:
    name: SignalName
    triggered: bool
    detail: str


@dataclass(frozen=True, slots=True)
class InvestigationStep:
    signal: SignalName
    action: str
    owner: str

    def __post_init__(self) -> None:
        if not self.action:
            raise ValueError("action must not be empty")
        if not self.owner:
            raise ValueError("owner must not be empty")


@dataclass(frozen=True, slots=True)
class ModelMonitoringReport:
    signals: tuple[MonitoringSignal, ...]
    playbook: tuple[InvestigationStep, ...]

    @property
    def any_triggered(self) -> bool:
        return any(signal.triggered for signal in self.signals)


def tail_breach_signal(coverage: VarCoverageResult, *, min_p_value: float) -> MonitoringSignal:
    if not 0.0 < min_p_value < 1.0:
        raise ValueError("min_p_value must be in (0, 1)")
    triggered = coverage.p_value < min_p_value
    detail = (
        f"{coverage.n_exceptions}/{coverage.n_observations} exceptions "
        f"(observed {coverage.observed_exception_rate:.4f} vs expected "
        f"{coverage.expected_exception_rate:.4f}), p={coverage.p_value:.4g}"
    )
    return MonitoringSignal(name="tail_breach", triggered=triggered, detail=detail)


def calibration_signal(escalation: RetrainingEscalation) -> MonitoringSignal:
    detail = f"{escalation.metric_name}: observed p={escalation.observed_p_value:.4g}"
    return MonitoringSignal(name="calibration", triggered=escalation.escalate, detail=detail)


def drift_signal(comparison: BootstrapResult) -> MonitoringSignal:
    detail = (
        f"{comparison.confidence:.0%} CI for the loss-distribution difference: "
        f"[{comparison.ci_low:.4g}, {comparison.ci_high:.4g}] over "
        f"{comparison.n_resamples} resamples"
    )
    return MonitoringSignal(name="drift", triggered=comparison.excludes_zero(), detail=detail)


def build_investigation_playbook(
    signals: Sequence[MonitoringSignal], *, owner: str
) -> tuple[InvestigationStep, ...]:
    if not owner:
        raise ValueError("owner must not be empty")
    return tuple(
        InvestigationStep(signal=signal.name, action=_PLAYBOOK_ACTIONS[signal.name], owner=owner)
        for signal in signals
        if signal.triggered
    )


def build_model_monitoring_report(
    signals: Sequence[MonitoringSignal], *, owner: str
) -> ModelMonitoringReport:
    return ModelMonitoringReport(
        signals=tuple(signals),
        playbook=build_investigation_playbook(signals, owner=owner),
    )
