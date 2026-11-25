"""E4: the shock-by-shock analysis on re-used data. The split could leak, so it is pinned."""

from __future__ import annotations

from datetime import date

import pytest

from prometheus.confirmatory import __main__ as cli
from prometheus.confirmatory import e4_shocks as e4
from prometheus.confirmatory.freeze import E4_RESERVED_SEEDS, NotFrozenError, require_seeds_allowed


@pytest.fixture(scope="module")
def examples():  # type: ignore[no-untyped-def]
    return e4._examples(e4.DEFAULT_CSV_PATH)


def test_the_events_are_the_three_prespecified_ones_and_only_covid_is_contaminated() -> None:
    assert [(ev.name, ev.contaminated) for ev in e4.EVENTS] == [
        ("dotcom_2001", False),
        ("financial_crisis_2008", False),
        ("covid_2020", True),
    ]
    assert e4.LEGACY_RECIPE.patience == e4.PATIENCE == 20
    assert e4.E4_SEEDS == tuple(range(20_000, 20_010))
    assert tuple(e4.E4_SEEDS) == tuple(E4_RESERVED_SEEDS)


@pytest.mark.parametrize("event", e4.EVENTS, ids=lambda ev: ev.name)
def test_training_data_come_strictly_before_the_event_and_the_window_is_inclusive(
    examples,
    event,  # type: ignore[no-untyped-def]
) -> None:
    before, window = e4.split_for_event(examples, event)
    assert before and window
    assert all(e.decision_time < event.start for e in before)
    assert all(event.start <= e.decision_time <= event.end for e in window)
    assert not {id(e) for e in before} & {id(e) for e in window}
    after = [e for e in examples if e.decision_time > event.end]
    assert after and not any(id(e) in {id(x) for x in before + window} for e in after)


def test_a_later_event_trains_on_more_history_and_the_windows_do_not_overlap() -> None:
    windows = sorted((ev.start, ev.end) for ev in e4.EVENTS)
    assert all(
        a_end < b_start for (_, a_end), (b_start, _) in zip(windows, windows[1:], strict=False)
    )
    assert e4.EVENTS[0].start == date(2001, 3, 31) and e4.EVENTS[1].end == date(2009, 6, 30)


def test_covid_seed_zero_reproduces_finding_5_through_the_event_code(examples) -> None:  # type: ignore[no-untyped-def]
    covid = next(ev for ev in e4.EVENTS if ev.name == "covid_2020")
    result = e4.run_event_seed(examples, covid, 0, recipe=e4.LEGACY_RECIPE)
    assert round(result.neural_degradation, 2) == 6.99
    assert round(result.baseline_degradation, 2) == 26.45
    assert result.advantage == pytest.approx(
        result.baseline_degradation - result.neural_degradation
    )
    assert e4.run_event_seed(examples, covid, 0, recipe=e4.LEGACY_RECIPE) == result  # deterministic


def test_the_summary_is_per_event_with_no_pooled_score_or_interval(examples) -> None:  # type: ignore[no-untyped-def]
    report = e4.run_e4((0, 1))
    assert [row["event"] for row in report["events"]] == [ev.name for ev in e4.EVENTS]
    assert set(report) == {"endpoint", "label", "patience", "recipe", "events"}
    assert report["recipe"] == {
        "learning_rate": 0.003,
        "hidden_size": 16,
        "max_epochs": 300,
        "patience": 50,
    }
    for row in report["events"]:
        assert row["n_seeds"] == 2 and len(row["per_seed"]) == 2
        assert "interval" not in row and "pooled" not in row
        assert row["advantage_min"] <= row["advantage_median"] <= row["advantage_max"]
        assert 0 <= row["seeds_where_neural_degraded_less"] <= 2
    assert report["events"][2]["selection_contaminated"] is True


def test_the_reserved_seeds_wait_for_the_freeze_but_exploratory_seeds_do_not(tmp_path) -> None:  # type: ignore[no-untyped-def]
    unfrozen = tmp_path / "p.md"
    unfrozen.write_text(
        "## Freeze record\n\n| Field | Value |\n| --- | --- |\n| Freeze date | not frozen |\n"
    )
    require_seeds_allowed(range(10), unfrozen)
    with pytest.raises(NotFrozenError):
        require_seeds_allowed([20_000], unfrozen)
    assert cli.main(["--protocol", str(unfrozen), "e4"]) == 2  # refused before anything trains


def test_the_reproduction_report_includes_the_e4_check() -> None:
    report = cli.reproduce_e4()
    assert all(c["match"] for c in report["checks"]) and len(report["checks"]) == 2
