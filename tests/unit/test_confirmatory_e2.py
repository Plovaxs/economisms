"""E2: the base-effect rule against persistence, scored on a window of target months.

Three kinds of evidence: the level-based builder agrees with the study's own on the committed data;
a hand computation from the defining formulas (no shared code) fixes the arithmetic and the sign;
and the endpoint, run with Finding 18's own settings on the same months, reproduces that finding.
"""

from __future__ import annotations

import hashlib
from datetime import date

import numpy as np
import pytest

from prometheus.confirmatory.__main__ import reproduce_e2
from prometheus.confirmatory.e2_inflation import (
    analyse_window,
    committed_levels,
    first_untouched_month,
    impute_single_gaps,
    nowcast_data_from_levels,
    parse_new_levels,
    vintage_overlap,
)
from prometheus.orchestration.inflationcast_long_study import build_nowcast_data


def _month_ends(first_year: int, first_month: int, n: int) -> tuple[date, ...]:
    out = []
    year, month = first_year, first_month
    for _ in range(n):
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        out.append(date.fromordinal(nxt.toordinal() - 1))
        year, month = nxt.year, nxt.month
    return tuple(out)


_GROWTH = [0.0, 0.002, 0.004, 0.001, 0.003, 0.0025, 0.0005, 0.0035, 0.002, 0.004, 0.003, 0.001]
_GROWTH += [0.005, 0.006, 0.0045]
_LEVELS = 100.0 * np.cumprod(1.0 + np.array(_GROWTH))
_MONTHS = _month_ends(2022, 1, len(_LEVELS))


def _csv(rows: list[tuple[str, float]], header: str = "month,level") -> bytes:
    return (header + "\n" + "\n".join(f"{m},{v}" for m, v in rows) + "\n").encode()


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_the_level_builder_agrees_with_the_studys_on_the_committed_data() -> None:
    months, levels = committed_levels()
    mine = nowcast_data_from_levels(months, levels)
    study = build_nowcast_data()
    assert mine.months == study.months
    for field in ("yoy", "mom", "previous_yoy", "base_level", "year_ago_level", "mom_history"):
        np.testing.assert_array_equal(getattr(mine, field), getattr(study, field), err_msg=field)


def test_hand_computed_errors_fix_the_arithmetic_and_the_sign() -> None:
    levels = _LEVELS

    def yoy(i: int) -> float:
        return 100.0 * (levels[i] / levels[i - 12] - 1.0)

    def mom(i: int) -> float:
        return 100.0 * (levels[i] / levels[i - 1] - 1.0)

    rows = []
    for t in (13, 14):
        mean_mom = sum(mom(k) for k in range(t - 12, t)) / 12.0
        rule = 100.0 * (levels[t - 1] * (1.0 + mean_mom / 100.0) / levels[t - 12] - 1.0)
        rows.append((yoy(t), yoy(t - 1), rule))
    e_persistence = np.array([p - a for a, p, _ in rows])
    e_rule = np.array([r - a for a, _, r in rows])

    result = analyse_window(
        _MONTHS,
        levels,
        scored_from=_MONTHS[13],
        scored_to=None,
        confidence=0.9,
        block_length=1,
        n_resamples=50,
    )
    assert result["n_months"] == 2
    assert result["first_month"] == _MONTHS[13].isoformat()
    assert result["last_month"] == _MONTHS[14].isoformat()
    assert result["mae_persistence"] == pytest.approx(np.mean(np.abs(e_persistence)))
    assert result["mae_base_effect"] == pytest.approx(np.mean(np.abs(e_rule)))
    # positive means the rule is better: persistence's error minus the rule's
    assert result["interval"]["estimate"] == pytest.approx(
        np.mean(np.abs(e_persistence) - np.abs(e_rule))
    )
    for entry, (actual, persistence, rule) in zip(result["per_month"], rows, strict=True):
        assert entry["yoy"] == pytest.approx(actual)
        assert entry["persistence"] == pytest.approx(persistence)
        assert entry["base_effect"] == pytest.approx(rule)
    assert result["sensitivity"] == {}  # blocks of 6 and 12 do not fit in 2 months


def test_the_scored_window_is_inclusive_and_needs_two_months() -> None:
    both = analyse_window(
        _MONTHS, _LEVELS, scored_from=_MONTHS[13], scored_to=_MONTHS[14],
        confidence=0.9, block_length=1, n_resamples=20,
    )  # fmt: skip
    assert both["n_months"] == 2
    with pytest.raises(ValueError, match="only 1 target month"):
        analyse_window(
            _MONTHS, _LEVELS, scored_from=_MONTHS[13], scored_to=_MONTHS[13],
            confidence=0.9, block_length=1, n_resamples=20,
        )  # fmt: skip
    with pytest.raises(ValueError, match="consecutive months"):
        nowcast_data_from_levels(_MONTHS[:13], _LEVELS[:13])


def test_the_first_untouched_month_follows_the_committed_snapshots_last_month() -> None:
    assert committed_levels()[0][-1] == date(2023, 3, 31)
    assert first_untouched_month() == date(2023, 4, 30)


def test_new_levels_are_checked_against_the_stated_hash_before_anything_is_read() -> None:
    content = _csv([("2023-04", 301.5), ("2023-05", 302.0)])
    months, levels = parse_new_levels(content, _digest(content).upper())
    assert months == (date(2023, 4, 30), date(2023, 5, 31))
    assert levels.tolist() == [301.5, 302.0]
    with pytest.raises(ValueError, match="does not match the SHA-256 stated.*nothing was read"):
        parse_new_levels(content + b" ", _digest(content))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (_csv([("2023-04", 301.5)], header="when,level"), "columns month,level"),
        (_csv([("2023-13", 301.5)]), "malformed row"),
        (_csv([("2023-04", -1.0)]), "finite and positive"),
        (_csv([("2023-04", float("inf"))]), "finite and positive"),
        (_csv([("2023-04", 1.0), ("2023-06", 1.0)]), "must be consecutive"),
        (b"month,level\n", "empty"),
    ],
)
def test_malformed_new_levels_are_refused(content: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_new_levels(content, _digest(content))


def _parsed(rows: list[tuple[str, float]]) -> tuple[tuple[date, ...], np.ndarray]:
    content = _csv(rows)
    return parse_new_levels(content, _digest(content))


def test_the_vintage_overlap_measures_the_revision_on_months_both_series_contain() -> None:
    old = committed_levels()
    by_month = dict(zip(old[0], old[1].tolist(), strict=True))
    feb, mar = date(2023, 2, 28), date(2023, 3, 31)
    revised = _parsed(
        [
            ("2023-02", by_month[feb] * 1.002),
            ("2023-03", by_month[mar]),
            ("2023-04", 301.0),
        ]
    )
    report = vintage_overlap(old, revised)
    assert report["n_overlap_months"] == 2
    assert (report["first_overlap_month"], report["last_overlap_month"]) == (
        "2023-02-28",
        "2023-03-31",
    )
    assert report["max_relative_difference"] == pytest.approx(0.002)
    assert report["mean_relative_difference"] == pytest.approx(0.001)
    assert vintage_overlap(old, _parsed([("2024-01", 310.0)])) == {"n_overlap_months": 0}


def test_a_window_that_would_silently_lose_its_first_months_is_refused() -> None:
    # 15 months of levels support targets only from the 14th month on (2023-02)
    with pytest.raises(ValueError, match="supports target months only from 2023-02.*2023-01"):
        analyse_window(
            _MONTHS, _LEVELS, scored_from=date(2023, 1, 1), scored_to=None,
            confidence=0.9, block_length=1, n_resamples=20,
        )  # fmt: skip
    ok = analyse_window(
        _MONTHS, _LEVELS, scored_from=date(2023, 2, 1), scored_to=None,
        confidence=0.9, block_length=1, n_resamples=20,
    )  # fmt: skip
    assert ok["first_month"] == "2023-02-28"


def test_the_endpoint_reproduces_finding_18_with_that_findings_settings() -> None:
    report = reproduce_e2()
    failed = [c for c in report["checks"] if not c["match"]]
    assert not failed, failed
    assert report["measured"]["n_months"] == 277


def test_a_blank_level_is_a_gap_and_a_gap_removes_exactly_the_fourteen_targets_that_need_it() -> (
    None
):
    months = _month_ends(2022, 1, 29)  # 2022-01 .. 2024-05
    growth = [0.002 + 0.001 * (i % 3) for i in range(29)]
    levels = 281.0 * np.cumprod(1.0 + np.array(growth))
    gap = 21  # 2023-10 has no published index
    with_gap = levels.copy()
    with_gap[gap] = np.nan
    report = analyse_window(
        months, with_gap, scored_from=date(2023, 4, 1), scored_to=None,
        confidence=0.9, block_length=3, n_resamples=50,
    )  # fmt: skip
    # a level at index k is needed by the targets k .. k+13 (this month, last month, and the
    # twelve months of growth history and the year-ago level behind them)
    assert report["excluded_months"] == [m.isoformat() for m in months[21:29]]
    assert report["n_months_in_window"] == 14 and report["n_months"] == 6
    assert report["last_month"] == months[20].isoformat()
    assert set(report["sensitivity"]) == {"6"}  # a block of 12 does not fit in 6 months

    imputed = report["sensitivity_imputed"]
    assert imputed["n_months"] == 14 and imputed["excluded_months"] == []
    assert imputed["outcome"] in {"better", "worse", "equivalent", "inconclusive"}
    assert "sensitivity_imputed" not in analyse_window(
        months, levels, scored_from=date(2023, 4, 1), scored_to=None,
        confidence=0.9, block_length=3, n_resamples=50,
    )  # fmt: skip


def test_imputation_fills_only_an_isolated_gap_with_the_geometric_mean() -> None:
    filled = impute_single_gaps(np.array([100.0, np.nan, 121.0, np.nan, np.nan, 130.0, np.nan]))
    assert filled[1] == pytest.approx(110.0)
    assert np.isnan(filled[3]) and np.isnan(filled[4])  # a longer gap stays a gap
    assert np.isnan(filled[6])  # an end point has no second neighbour
