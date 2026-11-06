import dataclasses
from datetime import date

import pytest

from prometheus.econosim.pit import MacroObservation, PointInTimeStore
from prometheus.experiments.leakage_negative_control import (
    LeakageNegativeControlResult,
    assert_scoreboard_is_leakage_clean,
    run_future_data_negative_control,
)


def test_result_is_immutable() -> None:
    result = LeakageNegativeControlResult("metric", valid_score=1.0, leaked_score=2.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.leaked_score = 3.0  # type: ignore[misc]


def test_leakage_gap_is_leaked_minus_valid() -> None:
    result = LeakageNegativeControlResult("metric", valid_score=0.3, leaked_score=0.9)
    assert result.leakage_gap == pytest.approx(0.6)


def test_leakage_gap_can_be_zero_or_negative_when_there_is_no_leak_advantage() -> None:
    """A diagnostic that found no suspicious advantage is itself a
    legitimate, reportable outcome -- the gap is not clipped to be
    always non-negative."""
    result = LeakageNegativeControlResult("metric", valid_score=0.5, leaked_score=0.5)
    assert result.leakage_gap == 0.0
    worse = LeakageNegativeControlResult("metric", valid_score=0.5, leaked_score=0.2)
    assert worse.leakage_gap == pytest.approx(-0.3)


def test_run_future_data_negative_control_reports_both_scores() -> None:
    result = run_future_data_negative_control("metric", lambda: 0.4, lambda: 0.9)
    assert result.metric_name == "metric"
    assert result.valid_score == 0.4
    assert result.leaked_score == 0.9


def test_a_real_point_in_time_leak_produces_a_large_positive_gap() -> None:
    """The diagnostic exercised against a genuine `PointInTimeStore`
    scenario, not a toy float pair: a decision made before the target
    period's data is published can only fall back to a naive guess
    (large error); letting the SAME decision see the true future value
    directly (the deliberate leak) makes the error vanish. This large,
    positive gap is exactly the signature an accidental leak elsewhere
    in a real pipeline would also produce -- which is the entire point
    of running this diagnostic."""
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            "gdp", observation_at=date(2024, 1, 1), published_at=date(2024, 1, 15), value=100.0
        )
    )
    store.record(
        MacroObservation(
            "gdp", observation_at=date(2024, 2, 1), published_at=date(2024, 2, 15), value=50.0
        )
    )
    decision_time = date(2024, 1, 20)
    true_future_value = 50.0

    def valid_score() -> float:
        obs = store.as_of("gdp", date(2024, 2, 1), decision_time)
        naive_fallback_prediction = obs.value if obs is not None else 0.0
        return -abs(naive_fallback_prediction - true_future_value)

    def leaked_score() -> float:
        return -abs(true_future_value - true_future_value)

    result = run_future_data_negative_control("neg_abs_error", valid_score, leaked_score)
    assert result.valid_score == pytest.approx(-50.0)
    assert result.leaked_score == pytest.approx(0.0)
    assert result.leakage_gap == pytest.approx(50.0)


def test_a_genuinely_leak_free_pipeline_produces_a_small_gap() -> None:
    """The converse, equally necessary case: when `valid_score_fn` is
    ALREADY eligible to see the relevant data honestly (because enough
    time has passed), the deliberate "leak" grants no extra advantage
    at all -- confirming the diagnostic does not manufacture a false
    positive merely by existing."""
    store = PointInTimeStore()
    store.record(
        MacroObservation(
            "gdp", observation_at=date(2024, 2, 1), published_at=date(2024, 2, 15), value=50.0
        )
    )
    decision_time = date(2024, 3, 1)  # well after publication
    true_future_value = 50.0

    def valid_score() -> float:
        obs = store.as_of("gdp", date(2024, 2, 1), decision_time)
        prediction = obs.value if obs is not None else 0.0
        return -abs(prediction - true_future_value)

    def leaked_score() -> float:
        return -abs(true_future_value - true_future_value)

    result = run_future_data_negative_control("neg_abs_error", valid_score, leaked_score)
    assert result.leakage_gap == pytest.approx(0.0)


def test_assert_scoreboard_is_leakage_clean_passes_a_clean_collection() -> None:
    assert_scoreboard_is_leakage_clean([1.0, 2.0, 3.0])
    assert_scoreboard_is_leakage_clean([])


def test_assert_scoreboard_is_leakage_clean_rejects_an_embedded_diagnostic() -> None:
    """The isolation half of EXP-05's acceptance criterion: a diagnostic
    result must never be silently acceptable wherever a legitimate
    scored result is expected."""
    diagnostic = LeakageNegativeControlResult("metric", valid_score=0.4, leaked_score=0.9)
    with pytest.raises(ValueError, match="DIAGNOSTIC"):
        assert_scoreboard_is_leakage_clean([1.0, 2.0, diagnostic])


def test_assert_scoreboard_is_leakage_clean_reports_the_count_and_pluralizes_correctly() -> None:
    d1 = LeakageNegativeControlResult("m1", 0.1, 0.2)
    d2 = LeakageNegativeControlResult("m2", 0.3, 0.4)
    with pytest.raises(ValueError, match="2 LeakageNegativeControlResult entries"):
        assert_scoreboard_is_leakage_clean([d1, d2])
    with pytest.raises(ValueError, match="1 LeakageNegativeControlResult entry "):
        assert_scoreboard_is_leakage_clean([d1])
