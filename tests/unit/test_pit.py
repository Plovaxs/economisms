from datetime import date

import pytest

from prometheus.econosim.pit import (
    FutureDataError,
    MacroObservation,
    PointInTimeStore,
    build_feature_vector,
    require_eligible,
)


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


def test_rejects_published_before_observation_period() -> None:
    with pytest.raises(ValueError):
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 9, 1),
            published_at=date(2026, 8, 1),
            value=3.1,
        )


@pytest.mark.parametrize("field_name", ["vintage_at", "asof_eligible_at", "ingested_at"])
def test_rejects_provenance_dates_before_published_at(field_name: str) -> None:
    with pytest.raises(ValueError):
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 9, 1),
            published_at=date(2026, 10, 15),
            value=3.1,
            **{field_name: date(2026, 10, 14)},
        )


def test_rejects_malformed_raw_hash() -> None:
    with pytest.raises(ValueError):
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 9, 1),
            published_at=date(2026, 10, 15),
            value=3.1,
            raw_hash="not-a-sha256-digest",
        )


def test_accepts_full_schema_with_valid_provenance_fields() -> None:
    obs = MacroObservation(
        series_id="CPI",
        observation_at=date(2026, 9, 1),
        published_at=date(2026, 10, 15),
        value=3.1,
        vintage_at=date(2026, 10, 15),
        asof_eligible_at=date(2026, 10, 16),
        ingested_at=date(2026, 10, 16),
        unit="percent",
        frequency="M",
        source_url="https://example.invalid/cpi",
        source_license="public-domain",
        raw_hash="a" * 64,
        transformation_id="yoy-change-v1",
        timezone="UTC",
        quality_flags=("preliminary",),
    )
    assert obs.raw_hash == "a" * 64
    assert obs.quality_flags == ("preliminary",)


def test_effective_eligible_at_defaults_to_published_at() -> None:
    obs = MacroObservation(
        series_id="CPI", observation_at=date(2026, 9, 1), published_at=date(2026, 10, 15), value=3.1
    )
    assert obs.effective_eligible_at == date(2026, 10, 15)


def test_effective_eligible_at_uses_the_later_of_published_and_ingestion_gate() -> None:
    obs = MacroObservation(
        series_id="CPI",
        observation_at=date(2026, 9, 1),
        published_at=date(2026, 10, 15),
        value=3.1,
        asof_eligible_at=date(2026, 10, 20),
    )
    assert obs.effective_eligible_at == date(2026, 10, 20)


def test_as_of_also_gates_on_internal_ingestion_lag_not_just_publication() -> None:
    """A source can publish a value before this system has finished
    ingesting/validating it -- the predicate must respect BOTH gates, not
    just published_at, or a caller could see data before it is actually
    usable internally."""
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 9, 1),
            published_at=date(2026, 10, 15),
            value=3.1,
            asof_eligible_at=date(2026, 10, 20),
        )
    )
    assert store.as_of("CPI", date(2026, 9, 1), date(2026, 10, 16)) is None
    assert store.as_of("CPI", date(2026, 9, 1), date(2026, 10, 20)) is not None


def test_require_eligible_raises_future_data_error_when_not_yet_available() -> None:
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            series_id="CPI",
            observation_at=date(2026, 9, 1),
            published_at=date(2026, 10, 15),
            value=3.1,
        )
    )
    with pytest.raises(FutureDataError):
        require_eligible(store, "CPI", date(2026, 9, 1), date(2026, 10, 14))


def test_require_eligible_returns_the_observation_when_available() -> None:
    store = PointInTimeStore()
    obs = MacroObservation(
        series_id="CPI", observation_at=date(2026, 9, 1), published_at=date(2026, 10, 15), value=3.1
    )
    store.record(obs)
    assert require_eligible(store, "CPI", date(2026, 9, 1), date(2026, 10, 15)) == obs


def test_build_feature_vector_returns_all_requested_values_when_all_eligible() -> None:
    store = PointInTimeStore()
    store.record(MacroObservation("CPI", date(2026, 9, 1), date(2026, 10, 15), 3.1))
    store.record(MacroObservation("UNRATE", date(2026, 9, 1), date(2026, 10, 3), 4.2))

    features = build_feature_vector(
        store, [("CPI", date(2026, 9, 1)), ("UNRATE", date(2026, 9, 1))], date(2026, 10, 15)
    )
    assert features == {"CPI": 3.1, "UNRATE": 4.2}


def test_build_feature_vector_rejects_unavailable_features_instead_of_partial_data() -> None:
    """The literal FP-03 acceptance criterion: a no-future-data fixture
    rejects unavailable features -- it must fail closed on the WHOLE
    request, not silently hand back a partial feature vector missing the
    one series that isn't eligible yet, which a model could easily treat
    as a legitimate (if incomplete) input."""
    store = PointInTimeStore()
    store.record(MacroObservation("CPI", date(2026, 9, 1), date(2026, 10, 15), 3.1))
    # UNRATE for this period has not been published as of the decision date.
    store.record(MacroObservation("UNRATE", date(2026, 9, 1), date(2026, 11, 20), 4.2))

    with pytest.raises(FutureDataError, match="UNRATE"):
        build_feature_vector(
            store, [("CPI", date(2026, 9, 1)), ("UNRATE", date(2026, 9, 1))], date(2026, 10, 15)
        )
