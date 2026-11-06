"""Point-in-time macro observations (ECONOSIM-X/PROMETHEUS-X addendum
FP-02/FP-03, extending the original PROMETHEUS DAT-07/DAT-09 and R-03
leakage-prevention primitives already implemented here).

Implements the "strict data inclusion predicate" from section 09 of the
specification: for a forecast/decision issued at time T, include an
observation only when published_at <= T. This is a minimal, in-memory
analog of the full point-in-time data schema (DAT-02..DAT-14 -- FRED-MD/QD
ingestion, ALFRED vintages, hashing, quality monitoring); those are
unimplemented. What is implemented and tested is the predicate itself,
revision handling, the fuller point-in-time record schema (FP-02:
licenses, raw hashes, published_at and vintage_at), and an explicit
fail-closed "no-future-data" fixture (FP-03) a forecasting pipeline's
feature-vector builder can call.

`MacroObservation` additionally carries `asof_eligible_at`, distinct from
`published_at`: the former is when the external source made the vintage
public, the latter is when THIS system's own ingestion pipeline makes it
usable internally (which can lag publication, e.g. while a transformation
or quality check runs). Both gates must pass -- a caller cannot see data
before the source published it, nor before this system finished ingesting
it. When `asof_eligible_at` is left unset (the default), eligibility
reduces exactly to the original published_at-only predicate, so every
pre-existing caller and test is unaffected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class MacroObservation:
    series_id: str
    observation_at: date
    """The period this value describes (e.g. "2026-09" CPI)."""
    published_at: date
    """The date this particular vintage became public from the source."""
    value: float
    revision_id: str = "r0"
    vintage_at: date | None = None
    """Which dated source snapshot/vintage this value was read from, if
    tracked separately from published_at (e.g. an ALFRED realtime-period
    label); must not precede published_at -- a snapshot cannot contain a
    vintage that did not exist yet."""
    asof_eligible_at: date | None = None
    """When THIS system's own ingestion pipeline makes the observation
    usable internally; must not precede published_at. None means "assume
    no extra ingestion lag," i.e. eligibility is published_at alone."""
    ingested_at: date | None = None
    """When this system actually pulled the observation in; must not
    precede published_at. Pure provenance -- not used by any predicate."""
    unit: str = ""
    frequency: str = ""
    source_url: str = ""
    source_license: str = ""
    raw_hash: str | None = None
    """SHA256 hex digest of the raw source payload this value was parsed
    from, if recorded."""
    transformation_id: str = ""
    timezone: str = "UTC"
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.published_at < self.observation_at:
            raise ValueError(
                f"published_at {self.published_at} precedes observation_at "
                f"{self.observation_at}: a value cannot be published before "
                "the period it describes has occurred"
            )
        for field_name, field_value in (
            ("vintage_at", self.vintage_at),
            ("asof_eligible_at", self.asof_eligible_at),
            ("ingested_at", self.ingested_at),
        ):
            if field_value is not None and field_value < self.published_at:
                raise ValueError(
                    f"{field_name} {field_value} precedes published_at "
                    f"{self.published_at}: cannot predate external publication"
                )
        if self.raw_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", self.raw_hash):
            raise ValueError("raw_hash must be a 64-character lowercase hex SHA256 digest")

    @property
    def effective_eligible_at(self) -> date:
        """The later (more conservative) of published_at and
        asof_eligible_at -- the single gate the predicate below uses."""
        if self.asof_eligible_at is None:
            return self.published_at
        return max(self.published_at, self.asof_eligible_at)


class FutureDataError(ValueError):
    """Raised by `require_eligible`/`build_feature_vector` when code asks
    for a point-in-time observation that is not yet eligible as of the
    given decision time -- the active-rejection counterpart to
    `PointInTimeStore.as_of`'s silent `None`, for callers that must fail
    closed (FP-03's "no-future-data fixture") rather than silently
    proceeding with missing data."""


class PointInTimeStore:
    """An append-only collection of (possibly revised) macro observations,
    queryable only through the as-of predicate -- there is deliberately no
    "give me the latest value regardless of date" accessor, so a caller
    cannot accidentally bypass the point-in-time rule."""

    def __init__(self) -> None:
        self._observations: list[MacroObservation] = []

    def record(self, observation: MacroObservation) -> None:
        self._observations.append(observation)

    def as_of(
        self, series_id: str, observation_at: date, t: date
    ) -> MacroObservation | None:
        """The latest vintage of (series_id, observation_at) eligible as
        of t (see `MacroObservation.effective_eligible_at`), or None if
        nothing is eligible yet."""
        eligible = [
            o
            for o in self._observations
            if o.series_id == series_id
            and o.observation_at == observation_at
            and o.effective_eligible_at <= t
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda o: o.effective_eligible_at)

    def all_eligible_as_of(self, t: date) -> tuple[MacroObservation, ...]:
        """The latest eligible vintage, as of t, of every (series_id,
        observation_at) pair ever recorded -- used by the time engine's
        "release information" step."""
        latest: dict[tuple[str, date], MacroObservation] = {}
        for o in self._observations:
            if o.effective_eligible_at > t:
                continue
            key = (o.series_id, o.observation_at)
            current_best = latest.get(key)
            if current_best is None or o.effective_eligible_at > current_best.effective_eligible_at:
                latest[key] = o
        return tuple(latest.values())


def require_eligible(
    store: PointInTimeStore, series_id: str, observation_at: date, t: date
) -> MacroObservation:
    """Like `store.as_of(...)`, but raises `FutureDataError` instead of
    returning None when the observation is not yet eligible."""
    result = store.as_of(series_id, observation_at, t)
    if result is None:
        raise FutureDataError(
            f"{series_id!r} observation for period {observation_at} is not "
            f"eligible as of {t}: either it has not been published/ingested "
            "yet, or it was never recorded"
        )
    return result


def build_feature_vector(
    store: PointInTimeStore, requests: list[tuple[str, date]], t: date
) -> dict[str, float]:
    """FP-03's "no-future-data fixture [that] rejects unavailable
    features": builds a {series_id: value} feature vector strictly from
    observations eligible as of `t`, via `require_eligible` for every
    requested (series_id, observation_at) pair, so a forecasting
    pipeline's input builder fails loudly (FutureDataError) rather than
    silently feeding a model a None/NaN or, worse, a value that does not
    yet exist as of the decision time. Built generically here (no
    forecasting model exists yet) so the leakage gate is in place and
    tested before any model is built to consume it."""
    features: dict[str, float] = {}
    for series_id, observation_at in requests:
        obs = require_eligible(store, series_id, observation_at, t)
        features[series_id] = obs.value
    return features
