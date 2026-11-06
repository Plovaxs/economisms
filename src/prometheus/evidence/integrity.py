"""Whole-artifact checksum seals; consistency, never signatures or approval.

The checksum covers every top-level section except the seal itself. A
caller with an independently trusted expected digest can pin an artifact;
self-consistent checksums alone do not establish who authored the content.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from prometheus.evidence.jsonio import strict_json_loads
from prometheus.experiments.manifest import compute_result_hash, json_default

INTEGRITY_KEY = "artifact_integrity"
CANONICALIZATION = "python-json-sorted-keys-default-separators-v1"
_FIELDS = {"schema_version", "algorithm", "canonicalization", "content_sha256"}


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def artifact_content_hash(bundle: Mapping[str, Any]) -> str:
    return compute_result_hash(
        {key: value for key, value in bundle.items() if key != INTEGRITY_KEY}
    )


def verify_artifact_integrity(
    bundle: Mapping[str, Any],
    *,
    require: bool = False,
    expected_sha256: str | None = None,
) -> str:
    """Validate a seal when present; optionally require one or an external content pin."""
    seal = bundle.get(INTEGRITY_KEY)
    if INTEGRITY_KEY not in bundle:
        if require:
            raise ValueError(
                "artifact integrity seal is required; this is an unsealed legacy artifact"
            )
        status = "legacy_unsealed"
    else:
        if not isinstance(seal, dict) or set(seal) != _FIELDS:
            raise ValueError("artifact integrity seal requires exactly its schema fields")
        if type(seal["schema_version"]) is not int or seal["schema_version"] != 1:
            raise ValueError("unsupported artifact integrity schema_version")
        if seal["algorithm"] != "sha256" or seal["canonicalization"] != CANONICALIZATION:
            raise ValueError("unsupported artifact integrity algorithm/canonicalization")
        if not is_sha256(seal["content_sha256"]):
            raise ValueError("artifact integrity digest must be lowercase SHA-256")
        if artifact_content_hash(bundle) != seal["content_sha256"]:
            raise ValueError("artifact integrity checksum mismatch; content changed after sealing")
        status = "sha256_verified"
    if expected_sha256 is not None:
        if not is_sha256(expected_sha256):
            raise ValueError("expected artifact digest must be lowercase SHA-256")
        if artifact_content_hash(bundle) != expected_sha256:
            raise ValueError(
                "artifact content differs from the externally supplied expected digest"
            )
    return status


def seal_evidence_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached JSON snapshot, refusing to bless an invalid existing seal."""
    sealed: dict[str, Any] = strict_json_loads(
        json.dumps(dict(bundle), default=json_default, allow_nan=False)
    )
    verify_artifact_integrity(sealed)
    sealed[INTEGRITY_KEY] = {
        "schema_version": 1,
        "algorithm": "sha256",
        "canonicalization": CANONICALIZATION,
        "content_sha256": artifact_content_hash(sealed),
    }
    return sealed
