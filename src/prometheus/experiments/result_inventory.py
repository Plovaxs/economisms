"""A result inventory that retains failed experiment evidence, not
just the best outcome (AUD-12: "retain failed experiment evidence, not
just best outcomes"; acceptance criterion: "result inventory contains
exclusions and documented reasons").

`experiments.hedge_benchmark` already retains every seed's own result
(`HedgeBenchmarkResult.per_seed_results`), but that is a flat list of
results that all succeeded on their own terms -- there is no concept
there of an ATTEMPT that was tried and explicitly discarded, with a
documented reason, as distinct from one that was tried and kept. That
is what this module adds: `ExperimentAttempt` records one attempt
either way, `included` (with a `metric_value`) or excluded (with a
`reason` naming why, and no metric value to accidentally be mistaken
for a kept result), and `ResultInventory` is the append-only collection
of them, queryable separately by `.included`/`.excluded`.

`build_result_inventory` is demonstrated here against this
repository's own real, previously undocumented-as-DATA history, not a
synthetic toy example: `stochastica.historical_calibration`'s own
module docstring narrates that three different GARCH(1,1) optimizer
configurations (Nelder-Mead with a reparameterization, SLSQP,
trust-constr) were each tried and abandoned for genuine non-robustness,
before the GBM closed-form MLE actually implemented there was adopted
instead -- prose, previously, not a structured, queryable inventory
entry per attempt with its own reason. This module does not change
`historical_calibration.py` itself; it gives that same real history a
second, structured representation that AUD-12 asks for.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExperimentAttempt:
    attempt_id: str
    included: bool
    reason: str
    metric_value: float | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise ValueError("attempt_id must not be empty")
        if not self.reason:
            raise ValueError(
                "reason must not be empty -- every attempt, kept or not, is documented"
            )
        if self.included and self.metric_value is None:
            raise ValueError(f"included attempt {self.attempt_id!r} must carry a metric_value")
        if not self.included and self.metric_value is not None:
            raise ValueError(
                f"excluded attempt {self.attempt_id!r} must not carry a metric_value "
                "-- an excluded attempt has no result to report, only a reason"
            )


@dataclass(frozen=True, slots=True)
class ResultInventory:
    attempts: tuple[ExperimentAttempt, ...]

    @property
    def included(self) -> tuple[ExperimentAttempt, ...]:
        return tuple(a for a in self.attempts if a.included)

    @property
    def excluded(self) -> tuple[ExperimentAttempt, ...]:
        return tuple(a for a in self.attempts if not a.included)


def build_result_inventory(attempts: Sequence[ExperimentAttempt]) -> ResultInventory:
    if not attempts:
        raise ValueError("a result inventory needs at least one attempt")
    ids = [a.attempt_id for a in attempts]
    if len(ids) != len(set(ids)):
        duplicates = sorted({aid for aid in ids if ids.count(aid) > 1})
        raise ValueError(f"attempt_id values must be unique, duplicates: {duplicates}")
    return ResultInventory(attempts=tuple(attempts))
