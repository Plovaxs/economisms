import dataclasses
import io

import pytest
import torch

from prometheus.evidence.model_package import (
    ModelPackage,
    PackageIntegrityError,
    build_model_package,
    verify_package_integrity,
)
from prometheus.hedging.deep_hedge import HedgePolicyMLP


def _real_model_artifact_bytes(seed: int = 0) -> bytes:
    """A genuine serialized artifact, not a synthetic byte string: the
    actual `torch.save`d `state_dict` of a real `HedgePolicyMLP`."""
    torch.manual_seed(seed)
    policy = HedgePolicyMLP()
    buffer = io.BytesIO()
    torch.save(policy.state_dict(), buffer)
    return buffer.getvalue()


def test_build_model_package_rejects_empty_artifact_bytes() -> None:
    with pytest.raises(ValueError, match="artifact_bytes"):
        build_model_package("gbm-policy", "v1", b"")


def test_model_package_rejects_an_empty_model_id() -> None:
    with pytest.raises(ValueError, match="model_id"):
        ModelPackage(model_id="", model_version="v1", content_hash="a" * 64)


def test_model_package_rejects_an_empty_model_version() -> None:
    with pytest.raises(ValueError, match="model_version"):
        ModelPackage(model_id="m", model_version="", content_hash="a" * 64)


def test_model_package_rejects_a_malformed_content_hash() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        ModelPackage(model_id="m", model_version="v1", content_hash="not-a-real-hash")


def test_model_package_is_immutable() -> None:
    package = build_model_package("gbm-policy", "v1", _real_model_artifact_bytes())
    with pytest.raises(dataclasses.FrozenInstanceError):
        package.content_hash = "0" * 64  # type: ignore[misc]


def test_a_real_model_artifact_resolves_to_a_deterministic_content_hash() -> None:
    """MLO-07's own acceptance criterion: "every model package resolves
    to unique content hash." Two SEPARATE packaging calls on
    INDEPENDENTLY serialized copies of the same real model state must
    resolve to the identical hash, grounded in a real `torch.save`d
    artifact, not a toy byte string."""
    package_a = build_model_package("gbm-policy", "v1", _real_model_artifact_bytes(seed=0))
    package_b = build_model_package("gbm-policy", "v1", _real_model_artifact_bytes(seed=0))
    assert package_a.content_hash == package_b.content_hash


def test_a_different_real_model_artifact_resolves_to_a_different_hash() -> None:
    """The discriminating half: a genuinely different model (different
    seed, different trained weights) must resolve to a different hash
    -- "unique" is a real property, not a tautological constant."""
    package_a = build_model_package("gbm-policy", "v1", _real_model_artifact_bytes(seed=0))
    package_b = build_model_package("gbm-policy", "v1", _real_model_artifact_bytes(seed=1))
    assert package_a.content_hash != package_b.content_hash


def test_verify_package_integrity_passes_for_the_artifact_it_was_built_from() -> None:
    artifact_bytes = _real_model_artifact_bytes()
    package = build_model_package("gbm-policy", "v1", artifact_bytes)
    verify_package_integrity(package, artifact_bytes)  # must not raise


def test_verify_package_integrity_passes_for_an_independently_reserialized_copy() -> None:
    """Immutability in practice: re-reading the "same" artifact from
    separate storage (here, re-serializing the same underlying model
    state independently) must still verify, since the bytes are
    genuinely identical."""
    package = build_model_package("gbm-policy", "v1", _real_model_artifact_bytes(seed=0))
    verify_package_integrity(package, _real_model_artifact_bytes(seed=0))  # must not raise


def test_verify_package_integrity_raises_for_tampered_bytes() -> None:
    """The actual immutability guarantee: an artifact that no longer
    matches its package's recorded hash -- because it was modified
    after packaging -- must be caught, not silently accepted."""
    artifact_bytes = _real_model_artifact_bytes()
    package = build_model_package("gbm-policy", "v1", artifact_bytes)
    tampered = artifact_bytes[:-1] + bytes([artifact_bytes[-1] ^ 0xFF])
    with pytest.raises(PackageIntegrityError, match="does not match"):
        verify_package_integrity(package, tampered)


def test_verify_package_integrity_raises_for_a_completely_different_artifact() -> None:
    package = build_model_package("gbm-policy", "v1", _real_model_artifact_bytes(seed=0))
    with pytest.raises(PackageIntegrityError):
        verify_package_integrity(package, _real_model_artifact_bytes(seed=1))
