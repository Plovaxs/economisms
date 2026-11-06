"""Per-series data quality monitoring: freshness, completeness,
duplicates and revisions (DAT-11: "monitor freshness, completeness,
duplicates and revisions"; acceptance criterion: "alerts and quality
summary visible per dataset").

Operates on a plain `Sequence[MacroObservation]` the CALLER already
holds (an ingestion pipeline naturally has the full list of records it
just parsed), rather than reading `econosim.pit.PointInTimeStore`'s own
internals: that store deliberately exposes no "give me everything"
accessor (see its own module docstring) specifically so decision code
cannot bypass the point-in-time rule, and a monitoring tool has no
special exemption from that boundary. `all_eligible_as_of` would also
not suffice even if it were used instead -- it collapses to only the
LATEST eligible vintage per (series_id, observation_at), which loses
exactly the "how many vintages/duplicates exist" signal this module
needs to report.

"Duplicate" means the exact same (observation_at, published_at,
revision_id) triple recorded more than once with a DIFFERENT value --
an ingestion bug re-recording a record with conflicting content, not a
legitimate re-ingestion of identical data (which this module does not
flag, since recording the same true value twice causes no harm).
"Revision" means more than one distinct `effective_eligible_at` exists
for the same `observation_at` -- ordinarily legitimate (many real
series are revised after initial publication) and reported as a count,
not an alert by itself.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from prometheus.econosim.pit import MacroObservation


@dataclass(frozen=True, slots=True)
class DataQualitySummary:
    series_id: str
    n_observations: int
    n_conflicting_duplicates: int
    n_revised_observation_dates: int
    most_recent_eligible_at: date | None
    staleness_days: int | None
    alerts: tuple[str, ...]


def summarize_data_quality(
    observations: Sequence[MacroObservation],
    series_id: str,
    as_of: date,
    expected_count: int | None = None,
    staleness_threshold_days: int | None = None,
) -> DataQualitySummary:
    relevant = [o for o in observations if o.series_id == series_id]
    alerts: list[str] = []

    conflicting_duplicates = 0
    by_key: dict[tuple[date, date, str], set[float]] = {}
    for o in relevant:
        key = (o.observation_at, o.published_at, o.revision_id)
        by_key.setdefault(key, set()).add(o.value)
    for key, values in by_key.items():
        if len(values) > 1:
            conflicting_duplicates += 1
            alerts.append(
                f"conflicting duplicate for observation_at={key[0]} published_at={key[1]} "
                f"revision_id={key[2]!r}: {len(values)} distinct values recorded"
            )

    eligible_counts: Counter[date] = Counter(o.observation_at for o in relevant)
    revised_dates = [d for d, count in eligible_counts.items() if count > 1]
    n_revised = 0
    for obs_date in revised_dates:
        distinct_eligible_ats = {
            o.effective_eligible_at for o in relevant if o.observation_at == obs_date
        }
        if len(distinct_eligible_ats) > 1:
            n_revised += 1

    most_recent_eligible_at = (
        max(o.effective_eligible_at for o in relevant) if relevant else None
    )
    staleness_days = (as_of - most_recent_eligible_at).days if most_recent_eligible_at else None
    if (
        staleness_threshold_days is not None
        and staleness_days is not None
        and staleness_days > staleness_threshold_days
    ):
        alerts.append(
            f"stale: most recent eligible observation is {staleness_days} days old, "
            f"threshold is {staleness_threshold_days}"
        )

    if expected_count is not None and len(relevant) < expected_count:
        alerts.append(
            f"incomplete: expected at least {expected_count} observations, found {len(relevant)}"
        )

    return DataQualitySummary(
        series_id=series_id,
        n_observations=len(relevant),
        n_conflicting_duplicates=conflicting_duplicates,
        n_revised_observation_dates=n_revised,
        most_recent_eligible_at=most_recent_eligible_at,
        staleness_days=staleness_days,
        alerts=tuple(alerts),
    )
