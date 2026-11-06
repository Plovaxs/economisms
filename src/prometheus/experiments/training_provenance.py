"""Training provenance manifest: config, environment and RNG state
(AUD-03: "capture model training config, environment and RNG state";
acceptance criterion: "stored manifest sufficient for replay at pinned
environment").

`capture_training_provenance` bundles exactly the three things AUD-03
names -- the training `config` (whatever hyperparameters a caller's own
training function takes, as a plain mapping), the integer `seed` that
determines all of that training run's RNG state (this repository's
`hedging.deep_hedge.train_deep_hedge` seeds both `torch.manual_seed`
and its own minibatch-sampling `torch.Generator` from this single
value, so it alone is sufficient to pin the RNG state), and
`environment`, reusing `experiments.manifest.runtime_provenance`
(Python version, platform string, pinned dependency versions, and a
SHA256 hash of this repository's own source tree) rather than
reinventing environment capture. `manifest_id` is a `compute_result_hash`
over all three, the same canonical-JSON SHA256 convention `evidence.
integrity`, `service.reports` and `experiments.holdout_manifest`
already use.

"Sufficient for replay" is not merely asserted: this module's own test
file captures a manifest from one real `train_deep_hedge` call, then
calls `train_deep_hedge` a SECOND time unpacking exactly the manifest's
own stored `config` and `seed` (nothing else), and confirms the
resulting `objective_history` is bit-identical to the original run --
the manifest alone, with no other information, reproduces the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from prometheus.experiments.manifest import compute_result_hash, runtime_provenance


@dataclass(frozen=True, slots=True)
class TrainingProvenanceManifest:
    config: Mapping[str, Any]
    seed: int
    environment: Mapping[str, Any]
    manifest_id: str


def capture_training_provenance(
    config: Mapping[str, Any], seed: int
) -> TrainingProvenanceManifest:
    environment = runtime_provenance()
    config = dict(config)
    manifest_id = compute_result_hash({"config": config, "seed": seed, "environment": environment})
    return TrainingProvenanceManifest(
        config=config, seed=seed, environment=environment, manifest_id=manifest_id
    )
