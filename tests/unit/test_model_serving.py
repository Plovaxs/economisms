from datetime import date

import pytest

from prometheus.evidence.model_package import build_model_package
from prometheus.evidence.model_registry import ModelRegistryEntry
from prometheus.evidence.model_serving import (
    ModelServingSlot,
    RetiredModelDeploymentError,
    UnhealthyServiceError,
)


def test_cached_predict_calls_compute_only_once_for_a_repeated_request() -> None:
    package = build_model_package("m", "v1", b"weights-v1")
    slot = ModelServingSlot(current=package)
    calls = {"n": 0}

    def compute() -> str:
        calls["n"] += 1
        return "result"

    assert slot.cached_predict("x", compute) == "result"
    assert slot.cached_predict("x", compute) == "result"
    assert calls["n"] == 1


def test_the_same_input_under_two_different_models_caches_separately() -> None:
    """A cache entry is keyed by (content_hash, input), not input
    alone -- the same input key under a DIFFERENT model must not reuse
    the other model's cached prediction."""
    package_a = build_model_package("m", "v1", b"weights-v1")
    package_b = build_model_package("m", "v2", b"weights-v2")
    slot = ModelServingSlot(current=package_a)
    slot.cached_predict("x", lambda: "prediction-under-a")
    slot.deploy(package_b)
    result = slot.cached_predict("x", lambda: "prediction-under-b")
    assert result == "prediction-under-b"
    assert slot.cache_size() == 2


def test_rollback_restores_the_exact_target_package() -> None:
    """MLO-12's own acceptance criterion, first half: "rollback test
    confirms restored model" -- the slot's current package must match
    the target's content hash exactly after rollback."""
    package_a = build_model_package("m", "v1", b"weights-v1")
    package_b = build_model_package("m", "v2", b"weights-v2")
    slot = ModelServingSlot(current=package_a)
    slot.deploy(package_b)
    assert slot.current.content_hash == package_b.content_hash

    slot.rollback_to(package_a)
    assert slot.current.content_hash == package_a.content_hash
    assert slot.current.model_version == "v1"


def test_rollback_purges_cache_entries_belonging_to_the_abandoned_model() -> None:
    """The second half: "stale-cache purge" -- a prediction cached under
    the model being rolled AWAY from must no longer be present after
    rollback, so it can never be served again under a false identity."""
    package_a = build_model_package("m", "v1", b"weights-v1")
    package_b = build_model_package("m", "v2", b"weights-v2")
    slot = ModelServingSlot(current=package_a)
    slot.cached_predict("x", lambda: "prediction-under-a")
    slot.deploy(package_b)
    slot.cached_predict("y", lambda: "prediction-under-b")
    assert slot.cache_size() == 2

    slot.rollback_to(package_a)
    assert slot.cache_size() == 1


def test_rollback_preserves_cache_entries_still_valid_for_the_restored_model() -> None:
    """The discriminating half: the purge is SELECTIVE, not a blunt
    full-cache clear -- an entry already computed under the model being
    restored TO remains valid and must be preserved, not recomputed."""
    package_a = build_model_package("m", "v1", b"weights-v1")
    package_b = build_model_package("m", "v2", b"weights-v2")
    slot = ModelServingSlot(current=package_a)
    calls = {"n": 0}

    def compute_under_a() -> str:
        calls["n"] += 1
        return "prediction-under-a"

    slot.cached_predict("x", compute_under_a)
    slot.deploy(package_b)
    slot.cached_predict("y", lambda: "prediction-under-b")

    slot.rollback_to(package_a)
    result = slot.cached_predict("x", compute_under_a)
    assert result == "prediction-under-a"
    assert calls["n"] == 1  # not recomputed -- the cached entry survived the rollback


def test_rollback_to_a_package_never_previously_served_starts_with_an_empty_relevant_cache() -> (
    None
):
    package_a = build_model_package("m", "v1", b"weights-v1")
    package_c = build_model_package("m", "v3", b"weights-v3")
    slot = ModelServingSlot(current=package_a)
    slot.cached_predict("x", lambda: "prediction-under-a")

    slot.rollback_to(package_c)
    assert slot.current.content_hash == package_c.content_hash
    assert slot.cache_size() == 0


def test_deploy_if_not_retired_allows_a_non_retired_package() -> None:
    package = build_model_package("m", "v1", b"weights-v1")
    entry = ModelRegistryEntry("m")
    slot = ModelServingSlot(current=package)
    package_v2 = build_model_package("m", "v2", b"weights-v2")
    entry.transition("evaluated", "ci", date(2026, 1, 1), "auto-eval", approved_by="n/a")
    slot.deploy_if_not_retired(package_v2, entry)
    assert slot.current.content_hash == package_v2.content_hash


def test_deploy_if_not_retired_refuses_a_retired_package() -> None:
    """MGR-12: "retired version not served" -- a package whose registry
    entry has been retired must be refused, not silently deployed."""
    package = build_model_package("m", "v1", b"weights-v1")
    entry = ModelRegistryEntry("m")
    entry.transition("retired", "ops", date(2026, 1, 1), "superseded", approved_by="ops-lead")
    slot = ModelServingSlot(current=package)
    retired_package = build_model_package("m", "v2", b"weights-v2")
    with pytest.raises(RetiredModelDeploymentError):
        slot.deploy_if_not_retired(retired_package, entry)
    # refused -- the slot still serves whatever it served before the attempt
    assert slot.current.content_hash == package.content_hash


def test_deploy_if_not_retired_rejects_a_mismatched_model_id() -> None:
    package = build_model_package("other-model", "v1", b"weights")
    entry = ModelRegistryEntry("m")
    slot = ModelServingSlot(current=package)
    with pytest.raises(ValueError, match="does not match"):
        slot.deploy_if_not_retired(package, entry)


def test_deploy_if_not_retired_preserves_the_full_retirement_history() -> None:
    """"Historical evidence preserved" -- retiring a model must not
    erase how it got there; the registry's own append-only history is
    reused, not replaced by a second, parallel retirement flag."""
    entry = ModelRegistryEntry("m")
    entry.transition("evaluated", "ci", date(2026, 1, 1), "auto-eval", approved_by="n/a")
    entry.transition(
        "approved",
        "reviewer",
        date(2026, 1, 2),
        "passed validation",
        approved_by="reviewer",
        content_hash="a" * 64,
    )
    entry.transition("retired", "ops", date(2026, 1, 3), "superseded", approved_by="ops-lead")
    assert [t.to_state for t in entry.history] == ["evaluated", "approved", "retired"]
    assert entry.state == "retired"


def test_a_healthy_slot_serves_normally() -> None:
    package = build_model_package("m", "v1", b"weights-v1")
    slot = ModelServingSlot(current=package)
    assert slot.is_healthy is True
    assert slot.cached_predict("x", lambda: "ok") == "ok"


def test_marking_unhealthy_requires_a_non_empty_reason() -> None:
    slot = ModelServingSlot(current=build_model_package("m", "v1", b"weights"))
    with pytest.raises(ValueError, match="empty"):
        slot.mark_unhealthy("")


def test_an_unhealthy_slot_refuses_to_serve_any_output() -> None:
    """DRI-12: "unhealthy model service stops serving unapproved
    outputs" -- compute() must never even be called once unhealthy."""
    package = build_model_package("m", "v1", b"weights-v1")
    slot = ModelServingSlot(current=package)
    slot.mark_unhealthy("numerical integrity violation detected")
    assert slot.is_healthy is False

    calls = {"n": 0}

    def compute() -> str:
        calls["n"] += 1
        return "should never be returned"

    with pytest.raises(UnhealthyServiceError, match="numerical integrity violation"):
        slot.cached_predict("x", compute)
    assert calls["n"] == 0  # refused before computing anything


def test_mark_healthy_restores_service_explicitly() -> None:
    slot = ModelServingSlot(current=build_model_package("m", "v1", b"weights"))
    slot.mark_unhealthy("temporary issue")
    assert slot.is_healthy is False
    slot.mark_healthy()
    assert slot.is_healthy is True
    assert slot.cached_predict("x", lambda: "ok") == "ok"


def test_a_cached_entry_from_before_the_outage_is_still_refused_while_unhealthy() -> None:
    """Fail-closed means ALL output is refused while unhealthy, even a
    value that was already safely cached before the outage began --
    this module does not try to distinguish "safe" from "unsafe" cached
    entries once the service itself is declared unhealthy."""
    slot = ModelServingSlot(current=build_model_package("m", "v1", b"weights"))
    slot.cached_predict("x", lambda: "cached-before-outage")
    slot.mark_unhealthy("incident in progress")
    with pytest.raises(UnhealthyServiceError):
        slot.cached_predict("x", lambda: "should not be reached")
