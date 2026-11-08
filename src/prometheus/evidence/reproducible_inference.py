"""Reproducible inference and input contracts (MLO-11: "implement
reproducible inference container and input contracts"; acceptance
criterion: "same reference inputs produce approved outputs").

`InputContract` names exactly the features an inference function
expects, in order, and `validate` rejects any input whose shape does
not match -- not a Docker container (this repository has none and does
not claim one), but the input-contract half the acceptance criterion
also names explicitly, applied to a real model's own inference
function. `ReferenceCase` pairs one input with its APPROVED output --
recorded once, presumably at model-approval time (`model_registry`'s
`approved` state) -- and `verify_reproducible_inference` re-runs
inference on each reference input today and reports any case whose
output no longer matches exactly, rather than trusting that it still
would.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class InputContract:
    model_id: str
    feature_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("model_id must not be empty")
        if not self.feature_names:
            raise ValueError("feature_names must not be empty")

    def validate(self, features: np.ndarray) -> None:
        if features.shape[-1] != len(self.feature_names):
            raise ValueError(
                f"{self.model_id}: expected {len(self.feature_names)} features "
                f"{self.feature_names}, got shape {features.shape}"
            )


@dataclass(frozen=True, slots=True)
class ReferenceCase:
    inputs: tuple[float, ...]
    approved_output: float


@dataclass(frozen=True, slots=True)
class ReproducibilityMismatch:
    inputs: tuple[float, ...]
    approved_output: float
    actual_output: float


def verify_reproducible_inference(
    infer_fn: Callable[[np.ndarray], float],
    contract: InputContract,
    reference_cases: Sequence[ReferenceCase],
) -> list[ReproducibilityMismatch]:
    """Runs `infer_fn` on each reference case's `inputs` (validated
    against `contract` first) and reports every case whose output no
    longer matches `approved_output` EXACTLY -- an empty list means the
    model reproduces every approved reference output today, not merely
    "close enough."""
    mismatches = []
    for case in reference_cases:
        features = np.asarray(case.inputs, dtype=float)
        contract.validate(features)
        actual = infer_fn(features)
        if actual != case.approved_output:
            mismatches.append(
                ReproducibilityMismatch(
                    inputs=case.inputs, approved_output=case.approved_output, actual_output=actual
                )
            )
    return mismatches
