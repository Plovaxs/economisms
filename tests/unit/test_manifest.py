from datetime import date
from fractions import Fraction

import pytest

from prometheus.experiments.manifest import (
    RunManifest,
    compute_result_hash,
    new_run_id,
    now_iso,
    runtime_provenance,
)


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


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_results_cannot_be_hashed_as_valid_json(value) -> None:
    with pytest.raises(ValueError):
        compute_result_hash({"loss": value})


def test_date_round_trip_preserves_hash_but_unknown_objects_are_rejected() -> None:
    assert compute_result_hash({"date": date(2026, 1, 2)}) == compute_result_hash(
        {"date": "2026-01-02"}
    )
    with pytest.raises(TypeError, match="unsupported JSON value"):
        compute_result_hash({"unknown": object()})


def test_runtime_provenance_observes_source_and_dependency_versions() -> None:
    first = runtime_provenance()
    assert first == runtime_provenance()
    assert len(first["source_sha256"]) == 64
    assert set(first["dependencies"]) == {"numpy", "scipy", "torch"}


def test_exact_rational_json_round_trip_preserves_hash() -> None:
    assert compute_result_hash({"quantity": Fraction(2, 3)}) == compute_result_hash(
        {"quantity": {"numerator": 2, "denominator": 3}}
    )


def _manifest(**overrides: object) -> RunManifest:
    defaults: dict = dict(
        run_id="pmth-exp-test", created_at=now_iso(), seed=0, config={}, result_hash="x" * 64
    )
    defaults.update(overrides)
    return RunManifest(**defaults)  # type: ignore[arg-type]


def test_run_manifest_optional_provenance_fields_default_to_none() -> None:
    manifest = _manifest()
    assert manifest.code_hash is None
    assert manifest.data_hash is None
    assert manifest.model_id is None
    assert manifest.to_dict()["code_hash"] is None


def test_run_manifest_accepts_representative_provenance_values() -> None:
    manifest = _manifest(code_hash="a" * 64, data_hash="b" * 64, model_id="macrocore-v0-untrained")
    as_dict = manifest.to_dict()
    assert as_dict["code_hash"] == "a" * 64
    assert as_dict["data_hash"] == "b" * 64
    assert as_dict["model_id"] == "macrocore-v0-untrained"


@pytest.mark.parametrize("field_name", ["code_hash", "data_hash"])
def test_run_manifest_rejects_malformed_hash_fields(field_name: str) -> None:
    with pytest.raises(ValueError):
        _manifest(**{field_name: "not-a-sha256-digest"})


def test_run_manifest_code_hash_can_carry_runtime_provenance_source_sha256() -> None:
    """Confirms the intended integration point actually fits the new
    field's validation -- `runtime_provenance()['source_sha256']` is a
    real SHA256 hex digest, so it is accepted as a `code_hash` without
    any reformatting."""
    provenance = runtime_provenance()
    manifest = _manifest(code_hash=provenance["source_sha256"])
    assert manifest.code_hash == provenance["source_sha256"]
