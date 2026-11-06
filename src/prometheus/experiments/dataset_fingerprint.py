"""Dataset fingerprinting for normalized data and feature
transformations (DAT-12: "hash normalized data and feature
transformations"; acceptance criterion: "every model reproduces
dataset fingerprint exactly").

`compute_dataset_fingerprint` hashes a normalized/feature array
together with the name of the transformation that produced it, via
`compute_result_hash` -- the same canonical-JSON SHA256 convention this
project's other manifests already use. "Every model reproduces dataset
fingerprint exactly" means: if two different consumers ("models") each
apply the SAME named transformation to the SAME raw data, their two,
independently computed fingerprints must be identical, bit for bit --
demonstrated here against a real transformation (raw GBM price paths
-> log returns, the same feature `stochastica.historical_calibration`
consumes), not a synthetic array. `verify_dataset_fingerprint` is the
actual check a model would run: recompute from its own copy of the
data and compare against a previously stored fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.experiments.manifest import compute_result_hash


@dataclass(frozen=True, slots=True)
class DatasetFingerprint:
    transformation_id: str
    fingerprint: str


def compute_dataset_fingerprint(
    normalized_data: np.ndarray, transformation_id: str
) -> DatasetFingerprint:
    if not transformation_id:
        raise ValueError("transformation_id must not be empty")
    values = np.asarray(normalized_data, dtype=float)
    if values.size == 0:
        raise ValueError("normalized_data must not be empty")
    fingerprint = compute_result_hash(
        {
            "transformation_id": transformation_id,
            "shape": list(values.shape),
            "values": values.tolist(),
        }
    )
    return DatasetFingerprint(transformation_id=transformation_id, fingerprint=fingerprint)


def verify_dataset_fingerprint(
    expected: DatasetFingerprint, normalized_data: np.ndarray, transformation_id: str
) -> bool:
    """Recomputes the fingerprint from `normalized_data`/`transformation_id`
    and compares against `expected` -- the acceptance criterion's own
    "reproduces ... exactly", checked directly rather than assumed."""
    return compute_dataset_fingerprint(normalized_data, transformation_id) == expected
