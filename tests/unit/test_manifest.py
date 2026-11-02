from prometheus.experiments.manifest import compute_result_hash, new_run_id, now_iso


def test_result_hash_is_order_independent_over_dict_keys() -> None:
    payload_a = {"b": 2, "a": 1}
    payload_b = {"a": 1, "b": 2}
    assert compute_result_hash(payload_a) == compute_result_hash(payload_b)


def test_result_hash_differs_for_different_payloads() -> None:
    assert compute_result_hash({"a": 1}) != compute_result_hash({"a": 2})


def test_result_hash_is_deterministic() -> None:
    payload = {"x": [1, 2, 3], "y": "call"}
    assert compute_result_hash(payload) == compute_result_hash(payload)


def test_new_run_id_includes_prefix_and_is_unique() -> None:
    first = new_run_id("pmth-exp")
    second = new_run_id("pmth-exp")
    assert first.startswith("pmth-exp-")
    assert first != second


def test_now_iso_returns_a_parseable_timestamp() -> None:
    from datetime import datetime

    timestamp = now_iso()
    assert datetime.fromisoformat(timestamp) is not None
