"""Verify an evidence payload, rerun its complete recipe, and compare results.

A matching file hash establishes payload consistency, not authenticity or
scientific approval. Replay additionally recomputes training and simulation.
Runtime/source differences are reported separately from the result match.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prometheus.evidence.contracts import CONVENTIONS as CONVENTIONS
from prometheus.evidence.contracts import read_evidence_bundle as read_evidence_bundle
from prometheus.evidence.contracts import verified_payload as verified_payload
from prometheus.evidence.export import export_evidence_bundle


@dataclass(frozen=True, slots=True)
class ReplayResult:
    expected_hash: str
    observed_hash: str
    matches: bool
    runtime_changes: tuple[str, ...]
    evidence_bundle: dict[str, Any]
    input_integrity: str


def replay_evidence_bundle(
    bundle: Mapping[str, Any], *, require_integrity: bool = False
) -> ReplayResult:
    key, payload, expected = verified_payload(bundle, require_integrity=require_integrity)
    integrity_status = "sha256_verified" if "artifact_integrity" in bundle else "legacy_unsealed"
    from prometheus.orchestration.recipes import execute_recipe

    run = execute_recipe(key, payload["config"])
    observed = run.manifest.result_hash
    replayed = run.evidence_bundle
    previous_runtime = bundle.get("runtime")
    current_runtime = replayed["runtime"]
    changes = (
        ("runtime metadata absent",)
        if not isinstance(previous_runtime, dict)
        else tuple(
            name
            for name in sorted(set(previous_runtime) | set(current_runtime))
            if previous_runtime.get(name) != current_runtime.get(name)
        )
    )
    replayed["replay"] = {
        "input_integrity": integrity_status,
        "source_run_id": bundle["run_manifest"].get("run_id"),
        "expected_hash": expected,
        "observed_hash": observed,
        "matches": expected == observed,
        "runtime_changes": changes,
    }
    return ReplayResult(
        expected, observed, expected == observed, changes, replayed, integrity_status
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--require-integrity", action="store_true", help="Reject unsealed legacy artifacts"
    )
    parser.add_argument(
        "--output", type=Path, help="Save the recomputed bundle and replay comparison"
    )
    args = parser.parse_args(argv)
    if args.output is not None and args.output.resolve() == args.bundle.resolve():
        parser.error("replay output must differ from the source artifact")
    try:
        result = replay_evidence_bundle(
            read_evidence_bundle(args.bundle), require_integrity=args.require_integrity
        )
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        export_evidence_bundle(result.evidence_bundle, args.output)
    print(
        json.dumps(
            {
                "matches": result.matches,
                "input_integrity": result.input_integrity,
                "expected_hash": result.expected_hash,
                "observed_hash": result.observed_hash,
                "runtime_changes": result.runtime_changes,
                "evidence_path": str(args.output) if args.output else None,
            },
            indent=2,
        )
    )
    return 0 if result.matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
