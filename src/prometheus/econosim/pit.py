"""Point-in-time macro observations.

Implements the "strict data inclusion predicate" from section 09 of the
specification: for a forecast/decision issued at time T, include an
observation only when published_at <= T. This is a minimal, in-memory
analog of the full point-in-time data schema (DAT-02..DAT-14 -- FRED-MD/QD
ingestion, ALFRED vintages, hashing, quality monitoring); those are
unimplemented. What is implemented and tested is the predicate itself and
revision handling, which is the part that prevents lookahead leakage
(R-03 in the risk register).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class MacroObservation:
    series_id: str
    observation_at: date
    """The period this value describes (e.g. "2026-09" CPI)."""
    published_at: date
    """The date this particular vintage became public."""
    value: float
    revision_id: str = "r0"


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
        """The latest vintage of (series_id, observation_at) with
        published_at <= t, or None if nothing is eligible yet."""
        eligible = [
            o
            for o in self._observations
            if o.series_id == series_id
            and o.observation_at == observation_at
            and o.published_at <= t
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda o: o.published_at)

    def all_eligible_as_of(self, t: date) -> tuple[MacroObservation, ...]:
        """The latest eligible vintage, as of t, of every (series_id,
        observation_at) pair ever recorded -- used by the time engine's
        "release information" step."""
        latest: dict[tuple[str, date], MacroObservation] = {}
        for o in self._observations:
            if o.published_at > t:
                continue
            key = (o.series_id, o.observation_at)
            current_best = latest.get(key)
            if current_best is None or o.published_at > current_best.published_at:
                latest[key] = o
        return tuple(latest.values())
