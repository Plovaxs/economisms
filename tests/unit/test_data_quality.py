from datetime import date

from prometheus.econosim.data_quality import summarize_data_quality
from prometheus.econosim.pit import MacroObservation


def _obs(
    series_id: str, observation_at: date, published_at: date, value: float, revision_id: str = "r0"
) -> MacroObservation:
    return MacroObservation(
        series_id, observation_at=observation_at, published_at=published_at,
        value=value, revision_id=revision_id,
    )


def test_a_clean_series_has_no_alerts() -> None:
    observations = [
        _obs("gdp", date(2024, 1, 1), date(2024, 1, 15), 100.0),
        _obs("gdp", date(2024, 2, 1), date(2024, 2, 15), 101.0),
    ]
    summary = summarize_data_quality(
        observations, "gdp", as_of=date(2024, 2, 20), expected_count=2,
        staleness_threshold_days=10,
    )
    assert summary.alerts == ()
    assert summary.n_observations == 2
    assert summary.n_conflicting_duplicates == 0


def test_only_the_requested_series_is_counted() -> None:
    observations = [
        _obs("gdp", date(2024, 1, 1), date(2024, 1, 15), 100.0),
        _obs("cpi", date(2024, 1, 1), date(2024, 1, 10), 3.0),
    ]
    summary = summarize_data_quality(observations, "gdp", as_of=date(2024, 1, 20))
    assert summary.n_observations == 1


def test_a_conflicting_duplicate_is_flagged_with_the_value_count() -> None:
    """The discriminating case: the SAME (observation_at, published_at,
    revision_id) recorded twice with DIFFERENT values -- a genuine
    ingestion conflict, not a harmless re-ingestion of identical data."""
    observations = [
        _obs("gdp", date(2024, 1, 1), date(2024, 1, 15), 100.0),
        _obs("gdp", date(2024, 1, 1), date(2024, 1, 15), 999.0),
    ]
    summary = summarize_data_quality(observations, "gdp", as_of=date(2024, 1, 20))
    assert summary.n_conflicting_duplicates == 1
    assert len(summary.alerts) == 1
    assert "conflicting duplicate" in summary.alerts[0]


def test_an_identical_re_ingestion_is_not_flagged_as_a_conflict() -> None:
    """The converse: recording the exact same (key, value) twice is a
    harmless re-ingestion, not a conflict -- must not be flagged."""
    observations = [
        _obs("gdp", date(2024, 1, 1), date(2024, 1, 15), 100.0),
        _obs("gdp", date(2024, 1, 1), date(2024, 1, 15), 100.0),
    ]
    summary = summarize_data_quality(observations, "gdp", as_of=date(2024, 1, 20))
    assert summary.n_conflicting_duplicates == 0
    assert summary.alerts == ()


def test_a_genuine_revision_is_counted_but_not_itself_an_alert() -> None:
    """Multiple vintages of the same observation_at (a later, corrected
    publication) is ordinarily LEGITIMATE and must be counted but not
    treated as a problem by itself."""
    observations = [
        _obs("gdp", date(2024, 2, 1), date(2024, 2, 15), 101.0),
        _obs("gdp", date(2024, 2, 1), date(2024, 3, 1), 102.0, revision_id="r1"),
    ]
    summary = summarize_data_quality(observations, "gdp", as_of=date(2024, 3, 2))
    assert summary.n_revised_observation_dates == 1
    assert summary.alerts == ()


def test_staleness_is_flagged_only_past_the_threshold() -> None:
    observations = [_obs("gdp", date(2024, 1, 1), date(2024, 1, 15), 100.0)]
    fresh = summarize_data_quality(
        observations, "gdp", as_of=date(2024, 1, 20), staleness_threshold_days=10
    )
    assert fresh.alerts == ()
    stale = summarize_data_quality(
        observations, "gdp", as_of=date(2024, 2, 1), staleness_threshold_days=10
    )
    assert stale.staleness_days == 17
    assert any("stale" in a for a in stale.alerts)


def test_incompleteness_is_flagged_only_below_the_expected_count() -> None:
    observations = [_obs("gdp", date(2024, 1, 1), date(2024, 1, 15), 100.0)]
    complete = summarize_data_quality(
        observations, "gdp", as_of=date(2024, 1, 20), expected_count=1
    )
    assert complete.alerts == ()
    incomplete = summarize_data_quality(
        observations, "gdp", as_of=date(2024, 1, 20), expected_count=5
    )
    assert any("incomplete" in a for a in incomplete.alerts)


def test_an_empty_series_reports_no_most_recent_eligible_at_or_staleness() -> None:
    summary = summarize_data_quality([], "gdp", as_of=date(2024, 1, 1))
    assert summary.n_observations == 0
    assert summary.most_recent_eligible_at is None
    assert summary.staleness_days is None


def test_most_recent_eligible_at_honors_asof_eligible_at_lag() -> None:
    """Freshness must use the SAME effective-eligibility gate (the later
    of published_at and asof_eligible_at) `econosim.pit` itself uses,
    not raw published_at alone."""
    observation = MacroObservation(
        "gdp", observation_at=date(2024, 1, 1), published_at=date(2024, 1, 15),
        value=100.0, asof_eligible_at=date(2024, 1, 20),
    )
    summary = summarize_data_quality([observation], "gdp", as_of=date(2024, 1, 25))
    assert summary.most_recent_eligible_at == date(2024, 1, 20)
    assert summary.staleness_days == 5
