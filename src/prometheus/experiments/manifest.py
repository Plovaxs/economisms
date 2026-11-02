"""A lightweight reproducibility manifest.

Section 02's RunManifest integration contract calls for "code digest, data
hash, seed, dependency lock, result hash -- every benchmark reproduces from
manifest." This is a reduced local analog: it captures seed, config and a
result hash, but not a git commit digest, container image digest or
dependency lock file hash -- those belong to the CI/platform layer (CIQ,
MLO), which does not exist yet, not to a single experiment run. `run_id`
and `created_at` are wall-clock-derived and therefore NOT expected to
reproduce across runs; only `result_hash`, given the same seed and config,
is a reproducibility claim (AUD-01/AUD-02).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    created_at: str
    seed: int
    config: Mapping[str, Any]
    result_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "seed": self.seed,
            "config": dict(self.config),
            "result_hash": self.result_hash,
        }


def compute_result_hash(payload: Mapping[str, Any]) -> str:
    """A canonical (sorted-key) JSON hash of a results payload, so two runs
    with bit-identical numeric outputs produce an identical hash regardless
    of dict insertion order."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def new_run_id(prefix: str = "pmth-exp") -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    return f"{prefix}-{timestamp}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
