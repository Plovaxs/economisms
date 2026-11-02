from datetime import date

from prometheus.econosim.pit import MacroObservation, PointInTimeStore


def test_as_of_returns_none_before_publication() -> None:
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 9, 1),
            published_at=date(2026, 10, 15),
            value=3.1,
        )
    )
    assert store.as_of("CPI", date(2026, 9, 1), date(2026, 10, 14)) is None


def test_as_of_returns_value_on_and_after_publication() -> None:
    store = PointInTimeStore()
    obs = MacroObservation(
        series_id="CPI", observation_at=date(2026, 9, 1), published_at=date(2026, 10, 15), value=3.1
    )
    store.record(obs)
    assert store.as_of("CPI", date(2026, 9, 1), date(2026, 10, 15)) == obs
    assert store.as_of("CPI", date(2026, 9, 1), date(2026, 11, 1)) == obs


def test_as_of_returns_latest_eligible_revision() -> None:
    store = PointInTimeStore()
    first_release = MacroObservation(
        series_id="GDP",
        observation_at=date(2026, 6, 1),
        published_at=date(2026, 7, 30),
        value=2.0,
        revision_id="r0",
    )
    revision = MacroObservation(
        series_id="GDP",
        observation_at=date(2026, 6, 1),
        published_at=date(2026, 8, 30),
        value=2.3,
        revision_id="r1",
    )
    store.record(first_release)
    store.record(revision)

    # Before the revision is published, only the first release is visible --
    # this is exactly what prevents lookahead leakage (R-03).
    assert store.as_of("GDP", date(2026, 6, 1), date(2026, 8, 1)) == first_release
    # After the revision is published, it supersedes the first release.
    assert store.as_of("GDP", date(2026, 6, 1), date(2026, 9, 1)) == revision


def test_all_eligible_as_of_filters_future_publications() -> None:
    store = PointInTimeStore()
    early = MacroObservation(
        series_id="UNRATE",
        observation_at=date(2026, 8, 1),
        published_at=date(2026, 9, 5),
        value=4.1,
    )
    future = MacroObservation(
        series_id="PCE",
        observation_at=date(2026, 10, 1),
        published_at=date(2026, 11, 20),
        value=1.9,
    )
    store.record(early)
    store.record(future)

    eligible = store.all_eligible_as_of(date(2026, 10, 1))
    assert early in eligible
    assert future not in eligible


def test_all_eligible_as_of_picks_latest_revision_per_series() -> None:
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 1, 1),
            published_at=date(2026, 2, 10),
            value=3.0,
        )
    )
    revised = MacroObservation(
        series_id="CPI", observation_at=date(2026, 1, 1), published_at=date(2026, 3, 1), value=3.2
    )
    store.record(revised)

    eligible = store.all_eligible_as_of(date(2026, 4, 1))
    assert eligible == (revised,)
