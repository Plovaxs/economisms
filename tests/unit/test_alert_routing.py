from datetime import date

import numpy as np
import pytest
from scipy import stats

from prometheus.evidence.alert_routing import (
    AlertRoute,
    RoutingTable,
    UnroutedSeverityError,
    canonical_severity,
    route_alert,
    severity_from_triggered,
)
from prometheus.evidence.model_monitoring import calibration_signal
from prometheus.evidence.queue_metrics import (
    QueueThresholds,
    classify_queue_health,
    compute_queue_metrics,
)
from prometheus.evidence.resource_utilization import UtilizationThresholds, classify_utilization
from prometheus.evidence.retraining_trigger import RetrainingThreshold, evaluate_retraining_trigger
from prometheus.jobs.store import Job
from prometheus.titan.risk_metrics import es_unconditional_calibration_test

_REAL_TABLE = RoutingTable(
    routes=(
        AlertRoute(
            severity="P0", owner="risk-oncall", escalation_contact="risk-oncall@example.com"
        ),
        AlertRoute(severity="P1", owner="platform-oncall", escalation_contact="#platform-alerts"),
    )
)


def test_canonical_severity_maps_the_three_legacy_levels() -> None:
    assert canonical_severity("critical") == "P0"
    assert canonical_severity("warning") == "P1"
    assert canonical_severity("ok") == "P2"


def test_canonical_severity_rejects_an_unrecognized_level() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        canonical_severity("catastrophic")


def test_severity_from_triggered() -> None:
    assert severity_from_triggered(True) == "P1"
    assert severity_from_triggered(False) == "P2"


def test_alert_route_rejects_an_empty_owner() -> None:
    with pytest.raises(ValueError, match="owner"):
        AlertRoute(severity="P0", owner="", escalation_contact="x")


def test_alert_route_rejects_an_empty_escalation_contact() -> None:
    with pytest.raises(ValueError, match="escalation_contact"):
        AlertRoute(severity="P0", owner="x", escalation_contact="")


def test_routing_table_rejects_duplicate_severities() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        RoutingTable(
            routes=(
                AlertRoute(severity="P0", owner="a", escalation_contact="x"),
                AlertRoute(severity="P0", owner="b", escalation_contact="y"),
            )
        )


def test_route_alert_resolves_a_configured_p0() -> None:
    route = route_alert("P0", _REAL_TABLE)
    assert route is not None
    assert route.owner == "risk-oncall"


def test_route_alert_raises_for_an_unconfigured_p0() -> None:
    empty_table = RoutingTable(routes=())
    with pytest.raises(UnroutedSeverityError, match="P0"):
        route_alert("P0", empty_table)


def test_route_alert_raises_for_an_unconfigured_p1() -> None:
    empty_table = RoutingTable(routes=())
    with pytest.raises(UnroutedSeverityError, match="P1"):
        route_alert("P1", empty_table)


def test_route_alert_returns_none_for_an_unconfigured_p2() -> None:
    """The discriminating half: P2 (informational) is explicitly NOT
    covered by this item's own acceptance criterion -- an unrouted P2
    is not an error."""
    empty_table = RoutingTable(routes=())
    assert route_alert("P2", empty_table) is None


def _make_job(status: str, created_ns: int, updated_ns: int, job_id: str = "j") -> Job:
    return Job(
        job_id=job_id, owner="alice", trace_id="t", kind="economy", config_json="{}",
        recipe_sha256="0" * 64, runtime_json="{}", estimate_json="{}", status=status,
        created_ns=created_ns, updated_ns=updated_ns, attempts=1,
        cancel_requested=status == "cancelled", timeout_seconds=60.0, artifact_sha256=None,
        result_hash=None, error_code=None, diagnostic_id=None, version=1,
    )


def test_a_real_critical_queue_metrics_severity_routes_to_a_configured_owner() -> None:
    """End-to-end against a REAL signal from `evidence.queue_metrics`:
    a genuinely overloaded queue's 'critical' severity, converted to
    the canonical taxonomy, resolves to a real configured owner."""
    jobs = [_make_job("queued", 0, 0, f"q{i}") for i in range(20)]
    thresholds = QueueThresholds(
        warning_queue_depth=5, critical_queue_depth=10,
        warning_p95_runtime_seconds=30.0, critical_p95_runtime_seconds=120.0,
    )
    metrics = compute_queue_metrics(jobs)
    legacy_severity = classify_queue_health(metrics, thresholds)
    assert legacy_severity == "critical"  # sanity

    route = route_alert(canonical_severity(legacy_severity), _REAL_TABLE)
    assert route is not None
    assert route.owner == "risk-oncall"


def test_a_real_critical_utilization_severity_routes_to_a_configured_owner() -> None:
    thresholds = UtilizationThresholds(warning_fraction=0.7, critical_fraction=0.9)
    legacy_severity = classify_utilization(95, 100, thresholds)
    assert legacy_severity == "critical"  # sanity

    route = route_alert(canonical_severity(legacy_severity), _REAL_TABLE)
    assert route is not None
    assert route.owner == "risk-oncall"


def test_a_real_triggered_calibration_signal_routes_to_a_configured_owner() -> None:
    """End-to-end against a REAL signal from `evidence.model_monitoring`,
    itself grounded in a real `es_unconditional_calibration_test`
    p-value, converted through the boolean-triggered taxonomy."""
    rng = np.random.default_rng(0)
    losses = rng.normal(0, 1, 2000)
    alpha = 0.95
    true_var = float(stats.norm.ppf(alpha))
    true_es = float(stats.norm.pdf(true_var) / (1 - alpha))
    result = es_unconditional_calibration_test(
        losses, true_var, true_es * 3.0, alpha, np.random.default_rng(1)
    )
    threshold = RetrainingThreshold("es_calibration", 0.05, date(2026, 1, 1))
    escalation = evaluate_retraining_trigger(threshold, result.p_value, date(2026, 2, 1))
    signal = calibration_signal(escalation)
    assert signal.triggered is True  # sanity

    route = route_alert(severity_from_triggered(signal.triggered), _REAL_TABLE)
    assert route is not None
    assert route.owner == "platform-oncall"
