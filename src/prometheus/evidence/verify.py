"""Offline artifact consistency/metadata audit; no training or simulation.

A successful audit establishes the listed structural/hash checks only.
It does not authenticate an author or validate numerical/model conclusions.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from prometheus.evidence.constants import SOURCE_TAG
from prometheus.evidence.contracts import CONVENTIONS, read_evidence_bundle, verified_payload
from prometheus.evidence.integrity import artifact_content_hash, verify_artifact_integrity
from prometheus.evidence.validation import validate_evidence_metadata


@dataclass(frozen=True, slots=True)
class ArtifactAudit:
    valid: bool
    artifact_integrity: str
    content_sha256: str
    external_digest_matched: bool
    payload_kind: str | None
    result_hash: str | None
    model_card_count: int
    gate_decision: str
    scope: str = (
        "Checksum, metadata schema and declared fingerprint consistency; no numerical replay"
    )


def audit_evidence_bundle(
    bundle: Mapping[str, Any],
    *,
    require_integrity: bool = True,
    expected_sha256: str | None = None,
) -> ArtifactAudit:
    status = verify_artifact_integrity(
        bundle, require=require_integrity, expected_sha256=expected_sha256
    )
    if bundle.get("source_tag") != SOURCE_TAG:
        raise ValueError("unsupported evidence source_tag")
    keys = [key for key in CONVENTIONS if key in bundle]
    kind, result_hash = None, None
    if keys or bundle.get("run_manifest") is not None:
        kind, _, result_hash = verified_payload(bundle, require_integrity=require_integrity)
    else:
        validate_evidence_metadata(bundle)
    return ArtifactAudit(
        True,
        status,
        artifact_content_hash(bundle),
        expected_sha256 is not None,
        kind,
        result_hash,
        len(bundle["model_cards"]),
        bundle["gate_report"]["decision"],
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--require-integrity", action="store_true", dest="require_integrity")
    group.add_argument("--allow-legacy", action="store_false", dest="require_integrity")
    parser.set_defaults(require_integrity=True)
    parser.add_argument("--expected-content-sha256")
    args = parser.parse_args(argv)
    try:
        audit = audit_evidence_bundle(
            read_evidence_bundle(args.artifact),
            require_integrity=args.require_integrity,
            expected_sha256=args.expected_content_sha256,
        )
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(audit), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
