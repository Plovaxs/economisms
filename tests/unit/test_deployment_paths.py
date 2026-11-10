from __future__ import annotations

import pytest

from prometheus.evidence.deployment_paths import (
    AutoRollbackMonitor,
    RollbackEvent,
    ShadowDeployment,
)
from prometheus.evidence.model_package import build_model_package
from prometheus.evidence.model_serving import ModelServingSlot


def test_shadow_deployment_only_ever_returns_the_champion_output() -> None:
    """CIQ-09: a shadow deployment's challenger output must never be
    served, even when it differs from the champion's."""
    champion = build_model_package("m", "v1", b"champion-weights")
    challenger = build_model_package("m", "v2-candidate", b"challenger-weights")
    shadow = ShadowDeployment(serving=ModelServingSlot(current=champion), challenger=challenger)

    result = shadow.predict_with_shadow(
        "x",
        champion_compute=lambda: "champion-says-A",
        challenger_compute=lambda: "challenger-says-B",
    )
    assert result == "champion-says-A"


def test_shadow_deployment_records_every_comparison() -> None:
    champion = build_model_package("m", "v1", b"w1")
    challenger = build_model_package("m", "v2", b"w2")
    shadow = ShadowDeployment(serving=ModelServingSlot(current=champion), challenger=challenger)

    shadow.predict_with_shadow("a", lambda: "X", lambda: "X")
    shadow.predict_with_shadow("b", lambda: "Y", lambda: "Z")
    assert len(shadow.comparisons) == 2
    assert shadow.comparisons[0].outputs_match is True
    assert shadow.comparisons[1].outputs_match is False
    assert shadow.agreement_rate() == 0.5


def test_agreement_rate_requires_at_least_one_comparison() -> None:
    shadow = ShadowDeployment(
        serving=ModelServingSlot(current=build_model_package("m", "v1", b"w")),
        challenger=build_model_package("m", "v2", b"w2"),
    )
    with pytest.raises(ValueError, match="no shadow comparisons"):
        shadow.agreement_rate()


def _monitor(slot: ModelServingSlot, good: object, **kwargs: object) -> AutoRollbackMonitor:
    return AutoRollbackMonitor(slot=slot, last_known_good=good, **kwargs)  # type: ignore[arg-type]


def test_a_single_noisy_spike_does_not_trigger_rollback() -> None:
    """Requires CONSECUTIVE breaches -- one outlier must not roll back
    a healthy service."""
    good = build_model_package("m", "v1", b"good-weights")
    bad = build_model_package("m", "v2", b"bad-weights")
    slot = ModelServingSlot(current=bad)
    monitor = AutoRollbackMonitor(
        slot=slot, last_known_good=good, critical_threshold=0.5, n_consecutive_breaches=3
    )
    assert monitor.observe(0.9) is None  # one spike
    assert monitor.observe(0.1) is None  # recovers
    assert slot.current.content_hash == bad.content_hash  # never rolled back
    assert monitor.rollback_events == []


def test_fault_injection_demonstrates_automatic_rollback_within_a_recovery_target() -> None:
    """CIQ-10's own acceptance wording: "fault injection demonstrates
    reversal within recovery target." A real injected fault (3
    consecutive critical-metric breaches) must trigger an automatic
    rollback -- no human call to rollback_to anywhere in this test."""
    good = build_model_package("m", "v1", b"good-weights")
    bad = build_model_package("m", "v2", b"bad-weights")
    slot = ModelServingSlot(current=bad)
    monitor = AutoRollbackMonitor(
        slot=slot, last_known_good=good, critical_threshold=0.5, n_consecutive_breaches=3
    )

    # Inject a fault: a sustained critical-metric regression.
    assert monitor.observe(0.9) is None
    assert monitor.observe(0.95) is None
    event = monitor.observe(0.99)

    assert isinstance(event, RollbackEvent)
    assert event.observation_index == 3  # recovery target: within 3 observations of fault onset
    assert slot.current.content_hash == good.content_hash  # genuinely rolled back
    assert monitor.rollback_events == [event]


def test_recovery_resets_the_consecutive_breach_counter_so_a_second_fault_also_triggers() -> None:
    good = build_model_package("m", "v1", b"good-weights")
    bad = build_model_package("m", "v2", b"bad-weights")
    slot = ModelServingSlot(current=bad)
    monitor = AutoRollbackMonitor(
        slot=slot, last_known_good=good, critical_threshold=0.5, n_consecutive_breaches=2
    )
    assert monitor.observe(0.9) is None
    assert monitor.observe(0.9) is not None  # first rollback fires
    # A fresh fault after recovery must still be caught, not silently ignored.
    slot.deploy(bad)
    assert monitor.observe(0.9) is None
    second = monitor.observe(0.9)
    assert second is not None
    assert len(monitor.rollback_events) == 2


def test_a_lower_is_worse_metric_is_supported() -> None:
    """Not every critical metric breaches by going UP (e.g. a
    calibration/coverage statistic breaches by dropping too low)."""
    good = build_model_package("m", "v1", b"good")
    bad = build_model_package("m", "v2", b"bad")
    slot = ModelServingSlot(current=bad)
    monitor = AutoRollbackMonitor(
        slot=slot,
        last_known_good=good,
        critical_threshold=0.2,
        n_consecutive_breaches=2,
        higher_is_worse=False,
    )
    assert monitor.observe(0.1) is None
    event = monitor.observe(0.05)
    assert event is not None
    assert slot.current.content_hash == good.content_hash
