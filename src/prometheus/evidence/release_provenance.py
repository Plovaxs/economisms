"""Signed release provenance statements (CIQ-07: "sign artifacts and
attach release provenance statement"; acceptance criterion: "independent
signature and source verification succeeds").

A REAL Ed25519 digital signature (`cryptography`, already an optional
dependency of this project via the `recovery` extra for AES-256-GCM --
reused here, not a new dependency added for this one item), not a
checksum-only seal: `evidence.integrity`'s own docstring already
disclaims that its artifact checksums are "consistency, never
signatures or approval" -- this module is what actually closes that
gap. "Independent... verification succeeds" is satisfied literally:
`verify_statement` takes only the PUBLIC key, the statement, and the
signature -- it needs nothing the signer alone holds, so verification
is genuinely independent of signing, and a tampered statement (any
single byte of the canonical payload changed) is confirmed, by test, to
fail verification rather than silently pass.

`ReleaseProvenanceStatement` carries exactly the fields a release
provenance statement needs to be checkable: `artifact_content_hash`
(reused from `tools.reproducible_build`'s own double-independent-
rebuild hash, not re-derived here), `source_commit`, `built_at`, and
`builder_identity` -- all required, non-optional fields, the same
"no silently-defaulted provenance field" discipline this project
applies elsewhere (e.g. `evidence.gate_report.GateDecisionForm`'s
required approvals).

Honest scope: this signs with a release key this repository's own
process controls, not a certificate chain rooted in an external,
independently-audited certificate authority (e.g. Sigstore/cosign's
transparency log) -- a real signature with real cryptographic
guarantees, but "independent verification" here means "verifiable by
anyone holding the public key without needing the private key," not
"notarized by a third party." If/when this project adopts a real
distribution channel, upgrading to a transparency-log-backed scheme
(Sigstore) would be the natural next step, not a parallel mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from prometheus.experiments.manifest import compute_result_hash


@dataclass(frozen=True, slots=True)
class ReleaseProvenanceStatement:
    artifact_content_hash: str
    source_commit: str
    built_at: date
    builder_identity: str

    def __post_init__(self) -> None:
        for name, value in (
            ("artifact_content_hash", self.artifact_content_hash),
            ("source_commit", self.source_commit),
            ("builder_identity", self.builder_identity),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")

    def canonical_payload(self) -> bytes:
        """The exact bytes a signature covers -- content-hashed with the
        same canonical-JSON convention every other manifest in this
        project uses (`experiments.manifest.compute_result_hash`), so a
        verifier re-derives this independently rather than trusting a
        caller-supplied byte string."""
        digest = compute_result_hash(
            {
                "artifact_content_hash": self.artifact_content_hash,
                "source_commit": self.source_commit,
                "built_at": self.built_at,
                "builder_identity": self.builder_identity,
            }
        )
        return digest.encode("ascii")


def generate_release_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def sign_statement(private_key: Ed25519PrivateKey, statement: ReleaseProvenanceStatement) -> bytes:
    return private_key.sign(statement.canonical_payload())


def verify_statement(
    public_key: Ed25519PublicKey, statement: ReleaseProvenanceStatement, signature: bytes
) -> bool:
    """Returns True/False rather than letting `cryptography`'s own
    `InvalidSignature` propagate -- a verification CHECK should hand
    back a checkable result, not force every caller into a try/except
    just to ask a yes/no question."""
    try:
        public_key.verify(signature, statement.canonical_payload())
        return True
    except InvalidSignature:
        return False


def public_key_hex(public_key: Ed25519PublicKey) -> str:
    """A stable, human-comparable representation of the public key, the
    same role a fingerprint plays for any public-key scheme -- so a
    release provenance statement can be checked against a KNOWN,
    previously-published key, not merely against whichever key happens
    to be supplied at verification time."""
    return public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
