from prometheus.evidence.model_package import build_model_package
from prometheus.evidence.model_serving import ModelServingSlot


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
