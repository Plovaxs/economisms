"""A lightweight reproducibility manifest.

Section 02's RunManifest integration contract calls for "code digest, data
hash, seed, dependency lock, result hash -- every benchmark reproduces from
manifest." This is a reduced local analog: it captures seed, config and a
result hash. Evidence bundles additionally observe a source-tree digest
and dependency versions; the benchmark runner hashes its training data.
There is no dependency lock, container digest or signed git identity. `run_id`
and `created_at` are wall-clock-derived and therefore NOT expected to
reproduce across runs; only `result_hash`, given the same seed and config,
is a reproducibility claim (AUD-01/AUD-02).

`code_hash`, `data_hash` and `model_id` (ECONOSIM-X addendum FP-20: "Run
manifest includes code hash, data hash, seed and model ID") are optional,
defaulting to `None` so every one of this dataclass's 11 pre-existing
call sites across `experiments`/`orchestration` is unaffected. `code_hash`
is intended to carry `runtime_provenance()['source_sha256']` (already
computed, just not previously threaded into a RunManifest field) when a
caller wants it; `data_hash` is intended for whatever dataset/training-
data fingerprint a caller has; NEITHER is actually wired into any of the
11 existing orchestration call sites yet -- that would mean touching each
one, out of scope for this PR. `model_id` has no real value to carry
anywhere in this repository today: no trained model exists (MACROCORE/
RECESSIONNET/INFLATIONCAST are all still NOT VERIFIED), so this field
exists and is tested with a representative value, but is not yet
exercised by any actual model.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from importlib.metadata import version
from pathlib import Path
from typing import Any

_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    created_at: str
    seed: int
    config: Mapping[str, Any]
    result_hash: str
    code_hash: str | None = None
    data_hash: str | None = None
    model_id: str | None = None

    def __post_init__(self) -> None:
        hash_fields = (("code_hash", self.code_hash), ("data_hash", self.data_hash))
        for field_name, field_value in hash_fields:
            if field_value is not None and not _SHA256_HEX_PATTERN.fullmatch(field_value):
                raise ValueError(f"{field_name} must be a 64-character lowercase hex SHA256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "seed": self.seed,
            "config": dict(self.config),
            "result_hash": self.result_hash,
            "code_hash": self.code_hash,
            "data_hash": self.data_hash,
            "model_id": self.model_id,
        }


def json_default(value: object) -> str | dict[str, int]:
    """Encode dates and exact rational quantities; reject unsupported objects."""
    from datetime import date

    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Fraction):
        return {"numerator": value.numerator, "denominator": value.denominator}
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def compute_result_hash(payload: Mapping[str, Any]) -> str:
    """A canonical (sorted-key) JSON hash of a results payload, so two runs
    with bit-identical numeric outputs produce an identical hash regardless
    of dict insertion order."""
    canonical = json.dumps(payload, sort_keys=True, default=json_default, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def runtime_provenance() -> dict[str, Any]:
    """Observe source/dependency versions, without claiming a dependency lock or signature."""
    root = Path(__file__).resolve().parents[1]
    hasher = hashlib.sha256()
    for source in sorted(root.rglob("*.py")):
        hasher.update(source.relative_to(root).as_posix().encode())
        hasher.update(b"\0")
        hasher.update(source.read_bytes())
        hasher.update(b"\0")
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {name: version(name) for name in ("numpy", "scipy", "torch")},
        "source_sha256": hasher.hexdigest(),
    }


def new_run_id(prefix: str = "pmth-exp") -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    return f"{prefix}-{timestamp}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
