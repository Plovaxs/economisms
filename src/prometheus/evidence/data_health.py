"""Data staleness alerting (OPS-06: "Measure data staleness and
failed ingest counts"; acceptance criterion: "Alert exercise detects
stale critical series").

Only the staleness half is new here. "Failed ingest counts" reuses
`evidence.inference_metrics.run_inference_benchmark` as-is: an
ingestion attempt is just another zero-argument callable that either
returns observations or raises, so wrapping a real connector call
(e.g. `data_ingestion.french_factors.fetch_french_factors` against a
flaky transport) in that existing function already produces a real
`n_failures`/`failure_rate` for ingestion -- no second, duplicate
failure-tracking function is needed (see this item's test file for a
real demonstration against a real connector).

`measure_staleness` deliberately takes a plain
`Sequence[MacroObservation]` -- the SAME real tuple a connector's own
fetch result already carries -- rather than reaching into
`econosim.pit.PointInTimeStore`, whose own docstring is explicit that
it deliberately has no "give me the latest value regardless of date"
accessor so point-in-time discipline cannot be accidentally bypassed
elsewhere. Staleness is checked right after an ingest run, against the
observations that run just produced, not by querying simulation-time
eligibility.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from prometheus.econosim.pit import MacroObservation


@dataclass(frozen=True, slots=True)
class StalenessReport:
    series_id: str
    latest_observation_at: date
    as_of: date
    age_days: int
    is_stale: bool


def measure_staleness(
    series_id: str,
    observations: Sequence[MacroObservation],
    as_of: date,
    max_age_days: int,
) -> StalenessReport:
    if not series_id:
        raise ValueError("series_id must not be empty")
    if max_age_days < 0:
        raise ValueError("max_age_days must not be negative")
    matching = [o for o in observations if o.series_id == series_id]
    if not matching:
        raise ValueError(f"no observations found for series_id {series_id!r}")
    latest = max(o.observation_at for o in matching)
    if as_of < latest:
        raise ValueError("as_of must not precede the latest observation date")
    age_days = (as_of - latest).days
    return StalenessReport(
        series_id=series_id,
        latest_observation_at=latest,
        as_of=as_of,
        age_days=age_days,
        is_stale=age_days > max_age_days,
    )
