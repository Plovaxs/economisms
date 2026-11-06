import copy
import hashlib
import json
from datetime import date
from fractions import Fraction

import pytest

from prometheus.evidence.contracts import read_evidence_bundle
from prometheus.evidence.export import export_evidence_bundle
from prometheus.evidence.integrity import (
    artifact_content_hash,
    seal_evidence_bundle,
    verify_artifact_integrity,
)


def test_seal_matches_an_independent_full_body_hash_and_never_mutates_input(tmp_path):
    body = {"payload": {"price": 100}, "model_cards": [{"metric": 3.0}], "gate": "NO-GO"}
    original = copy.deepcopy(body)
    sealed = seal_evidence_bundle(body)
    expected = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    assert body == original and "artifact_integrity" not in body
    assert sealed["artifact_integrity"]["content_sha256"] == expected
    assert (
        verify_artifact_integrity(sealed, require=True, expected_sha256=expected)
        == "sha256_verified"
    )
    path = export_evidence_bundle(sealed, tmp_path / "sealed.json")
    assert read_evidence_bundle(path, require_integrity=True) == sealed


@pytest.mark.parametrize("section", ["payload", "model_cards", "gate", "runtime", "replay"])
def test_every_section_is_covered_and_stale_seals_cannot_be_reexported(tmp_path, section):
    body = {key: {"x": 1} for key in ("payload", "model_cards", "gate", "runtime", "replay")}
    sealed = seal_evidence_bundle(body)
    sealed[section]["x"] = 2
    path = tmp_path / "existing.json"
    path.write_text("previous artifact")
    with pytest.raises(ValueError, match="integrity checksum mismatch"):
        export_evidence_bundle(sealed, path)
    assert path.read_text() == "previous artifact"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "change", ["schema", "bool_schema", "algorithm", "canonicalization", "digest", "extra", "null"]
)
def test_malformed_seals_are_rejected(change):
    sealed = seal_evidence_bundle({"x": 1})
    stamp = sealed["artifact_integrity"]
    if change == "schema":
        stamp["schema_version"] = 2
    elif change == "bool_schema":
        stamp["schema_version"] = True
    elif change == "algorithm":
        stamp["algorithm"] = "md5"
    elif change == "canonicalization":
        stamp["canonicalization"] = "other"
    elif change == "digest":
        stamp["content_sha256"] = "ABC"
    elif change == "extra":
        stamp["unrecognized"] = 1
    else:
        sealed["artifact_integrity"] = None
    with pytest.raises(ValueError):
        verify_artifact_integrity(sealed)


def test_unsealed_legacy_is_explicit_and_strict_mode_prevents_seal_removal_downgrade():
    legacy = {"x": 1}
    assert verify_artifact_integrity(legacy) == "legacy_unsealed"
    with pytest.raises(ValueError, match="required"):
        verify_artifact_integrity(legacy, require=True)
    pin = artifact_content_hash(legacy)
    assert verify_artifact_integrity(legacy, expected_sha256=pin) == "legacy_unsealed"
    with pytest.raises(ValueError, match="externally supplied"):
        verify_artifact_integrity({"x": 2}, expected_sha256=pin)
    with pytest.raises(ValueError, match="lowercase"):
        verify_artifact_integrity(legacy, expected_sha256="invalid")


def test_date_fraction_and_tuple_encoding_retains_the_same_seal_after_json_read(tmp_path):
    body = {"date": date(2026, 11, 3), "ratio": Fraction(1, 3), "values": (1, 2)}
    sealed = seal_evidence_bundle(body)
    path = export_evidence_bundle(sealed, tmp_path / "encoded.json")
    loaded = read_evidence_bundle(path, require_integrity=True)
    assert artifact_content_hash(loaded) == artifact_content_hash(body)


def test_sealed_snapshot_is_detached_from_nested_input_mutation():
    body = {"nested": {"values": [1, 2, 3]}}
    sealed = seal_evidence_bundle(body)
    body["nested"]["values"].append(4)
    assert sealed["nested"]["values"] == [1, 2, 3]
    assert verify_artifact_integrity(sealed, require=True) == "sha256_verified"


def test_snapshot_refuses_key_collisions_instead_of_silently_discarding_data():
    with pytest.raises(ValueError, match="duplicate JSON key"):
        seal_evidence_bundle({"data": {"1": "first", 1: "second"}})


@pytest.mark.parametrize("number", ["1e9999", "-1e9999"])
def test_numeric_exponent_overflow_is_rejected_during_json_read(tmp_path, number):
    path = tmp_path / "overflow.json"
    path.write_text('{"value": ' + number + "}")
    with pytest.raises(ValueError, match="non-finite JSON number"):
        read_evidence_bundle(path)
