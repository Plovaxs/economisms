from __future__ import annotations

from datetime import date

import pytest

from prometheus.evidence.release_provenance import (
    ReleaseProvenanceStatement,
    generate_release_keypair,
    public_key_hex,
    sign_statement,
    verify_statement,
)


def _real_statement() -> ReleaseProvenanceStatement:
    return ReleaseProvenanceStatement(
        artifact_content_hash="a" * 64,
        source_commit="8cbf84a",
        built_at=date(2026, 11, 10),
        builder_identity="ci-release-build",
    )


def test_a_statement_requires_non_empty_fields() -> None:
    with pytest.raises(ValueError, match="source_commit"):
        ReleaseProvenanceStatement(
            artifact_content_hash="a" * 64,
            source_commit="  ",
            built_at=date(2026, 11, 10),
            builder_identity="ci",
        )


def test_a_genuine_signature_verifies_independently_with_only_the_public_key() -> None:
    """CIQ-07's own acceptance wording: "independent signature and
    source verification succeeds" -- verification here uses ONLY the
    public key and the statement, never the private key."""
    private_key, public_key = generate_release_keypair()
    statement = _real_statement()
    signature = sign_statement(private_key, statement)
    assert verify_statement(public_key, statement, signature) is True


def test_a_tampered_statement_fails_verification() -> None:
    """The discriminating case: verification must genuinely depend on
    the statement's real content, not just on a signature's presence."""
    private_key, public_key = generate_release_keypair()
    statement = _real_statement()
    signature = sign_statement(private_key, statement)

    tampered = ReleaseProvenanceStatement(
        artifact_content_hash="b" * 64,  # a different, real-shaped hash
        source_commit=statement.source_commit,
        built_at=statement.built_at,
        builder_identity=statement.builder_identity,
    )
    assert verify_statement(public_key, tampered, signature) is False


def test_a_signature_from_a_different_keypair_fails_verification() -> None:
    private_key_a, _ = generate_release_keypair()
    _, public_key_b = generate_release_keypair()
    statement = _real_statement()
    signature = sign_statement(private_key_a, statement)
    assert verify_statement(public_key_b, statement, signature) is False


def test_public_key_hex_is_a_stable_64_character_hex_fingerprint() -> None:
    _, public_key = generate_release_keypair()
    fingerprint = public_key_hex(public_key)
    assert len(fingerprint) == 64  # Ed25519 public key is 32 bytes = 64 hex chars
    int(fingerprint, 16)  # must be valid hex
    assert public_key_hex(public_key) == fingerprint  # deterministic, not re-randomized


def test_two_independently_generated_keypairs_have_different_fingerprints() -> None:
    _, public_key_a = generate_release_keypair()
    _, public_key_b = generate_release_keypair()
    assert public_key_hex(public_key_a) != public_key_hex(public_key_b)
