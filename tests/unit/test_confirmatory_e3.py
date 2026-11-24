"""E3: GARCH with filtered historical simulation, scored on a window of days.

The forecaster is compared with the study's own (`market_risk_study.evaluate_baseline_models`)
on the committed Yahoo series, and the endpoint, run with Finding 15's own test window,
reproduces that finding's exceedance counts and scores. The rest is arithmetic pinned by hand:
the coverage reading, the pinball sign and the guards on new data.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np
import pytest

from prometheus.confirmatory.__main__ import reproduce_e3
from prometheus.confirmatory.e3_var import (
    analyse_window,
    committed_closes,
    coverage_report,
    first_untouched_day,
    forecast_thresholds,
    merge_closes,
    parse_new_closes,
    pinball_difference,
)
from prometheus.data_ingestion.kaggle_sp500 import load_daily_closes
from prometheus.orchestration.market_risk_study import (
    ALPHAS,
    DATA_PATH,
    Scoreboard,
    evaluate_baseline_models,
    prepare_market,
)


def _csv(rows: list[tuple[str, float]], header: str = "date,close") -> bytes:
    return (header + "\n" + "\n".join(f"{d},{c}" for d, c in rows) + "\n").encode()


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parsed(rows: list[tuple[str, float]]) -> tuple[tuple[date, ...], np.ndarray]:
    content = _csv(rows)
    return parse_new_closes(content, _digest(content))


def test_the_forecaster_is_the_studys_own_on_the_committed_yahoo_series() -> None:
    data = prepare_market(DATA_PATH)
    board = Scoreboard(data)
    evaluate_baseline_models(
        data, board, seeds=[0], max_epochs=1, patience=1, history_starts={"all": None}
    )
    mine = forecast_thresholds(*load_daily_closes(DATA_PATH))
    assert mine.return_dates == data.return_dates
    for alpha in ALPHAS:
        study_fhs = board.thresholds_by_model["garch_fhs@all"][alpha]
        study_hs = board.thresholds_by_model["historical_250"][alpha]
        np.testing.assert_array_equal(mine.garch_fhs[alpha][data.test_mask], study_fhs)
        np.testing.assert_array_equal(mine.historical_250[alpha][data.test_mask], study_hs)


def test_the_endpoint_reproduces_finding_15_with_that_findings_test_window() -> None:
    report = reproduce_e3()
    failed = [c for c in report["checks"] if not c["match"]]
    assert not failed, failed
    assert report["measured"]["n_test_days"] == 3235


def test_the_coverage_reading_needs_both_the_interval_and_the_test() -> None:
    n = 1000
    returns = np.zeros(n)

    def thresholds(hit_days: list[int]) -> np.ndarray:
        out = np.full(n, -1.0)
        out[hit_days] = 1.0  # 0 < 1: an exceedance on exactly those days
        return out

    spread = list(range(50, 1000, 100))  # 10 evenly spread exceedances = the nominal 1%
    good = coverage_report(returns, thresholds(spread), 0.99, 0.9833)
    assert good["n_exceedances"] == 10 and good["expected_exceedances"] == pytest.approx(10.0)
    assert good["rate_interval"][0] < 0.01 < good["rate_interval"][1]
    assert good["consistent_with_coverage"] is True
    assert good["conditional_coverage_test_level"] == pytest.approx(1 - 0.9833)

    too_many = coverage_report(returns, thresholds(list(range(10, 1000, 25))), 0.99, 0.9833)
    assert too_many["n_exceedances"] == 40
    assert too_many["rate_interval"][0] > 0.01
    assert too_many["consistent_with_coverage"] is False

    clustered = coverage_report(returns, thresholds(list(range(500, 510))), 0.99, 0.9833)
    assert clustered["n_exceedances"] == 10
    assert clustered["rate_interval"][0] < 0.01 < clustered["rate_interval"][1]
    assert clustered["christoffersen_independence_p"] < 0.0167  # the test sees the cluster
    assert clustered["consistent_with_coverage"] is False  # so the interval alone is not enough


def test_the_pinball_difference_is_first_minus_second_in_basis_points() -> None:
    returns = np.array([-0.03, 0.01])
    first = np.array([-0.02, -0.02])
    second = np.array([-0.04, -0.01])
    alpha = 0.99

    def score(r: float, threshold: float) -> float:
        loss, var = -r, -threshold
        return float((loss - var) * (alpha - (1.0 if loss < var else 0.0)))

    expected = [
        1e4 * (score(r, a) - score(r, b)) for r, a, b in zip(returns, first, second, strict=True)
    ]
    np.testing.assert_allclose(pinball_difference(returns, first, second, alpha), expected)
    assert expected[0] != 0.0 and expected[1] != 0.0


def test_new_closes_are_checked_against_the_stated_hash_before_anything_is_read() -> None:
    content = _csv([("2023-05-04", 4100.0), ("2023-05-05", 4120.5)])
    dates, closes = parse_new_closes(content, _digest(content).upper())
    assert dates == (date(2023, 5, 4), date(2023, 5, 5))
    assert closes.tolist() == [4100.0, 4120.5]
    with pytest.raises(ValueError, match="does not match the SHA-256 stated.*nothing was read"):
        parse_new_closes(content + b" ", _digest(content))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (_csv([("2023-05-04", 4100.0)], header="day,close"), "columns date,close"),
        (_csv([("2023-5-4x", 4100.0)]), "malformed row"),
        (_csv([("2023-05-05", 4100.0), ("2023-05-04", 4101.0)]), "strictly increasing"),
        (_csv([("2023-05-04", 4100.0), ("2023-05-04", 4101.0)]), "strictly increasing"),
        (_csv([("2023-05-04", 0.0)]), "finite and positive"),
        (_csv([("2023-05-04", float("nan"))]), "finite and positive"),
        (b"date,close\n", "empty"),
    ],
)
def test_malformed_new_closes_are_refused(content: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_new_closes(content, _digest(content))


def test_new_closes_must_start_after_the_committed_series_last_day() -> None:
    old = committed_closes()
    assert old[0][-1] == date(2023, 5, 3)
    assert first_untouched_day() == date(2023, 5, 4)
    dates, closes = merge_closes(old, _parsed([("2023-05-04", 4100.0)]))
    assert dates[-1] == date(2023, 5, 4) and len(closes) == len(old[1]) + 1
    with pytest.raises(ValueError, match="must start after 2023-05-03"):
        merge_closes(old, _parsed([("2023-05-03", 4090.0)]))  # overlap would let a revision in


def test_the_window_runs_end_to_end_on_the_committed_series_plus_new_days() -> None:
    old = committed_closes()
    rng = np.random.default_rng(3)
    days = [date(2023, 5, 4) + timedelta(days=i) for i in range(40)]
    prices = old[1][-1] * np.exp(np.cumsum(rng.normal(0.0, 0.01, size=40)))
    new = _parsed([(d.isoformat(), float(p)) for d, p in zip(days, prices, strict=True)])
    dates, closes = merge_closes(old, new)
    result = analyse_window(
        dates, closes, scored_from=days[0], scored_to=days[29], confidence=0.9833, n_resamples=40
    )
    assert result["n_days"] == 30
    assert (result["first_day"], result["last_day"]) == (days[0].isoformat(), days[29].isoformat())
    cell = result["coverage"]["alpha_0.99"]["garch_fhs"]
    assert cell["n_days"] == 30.0 and 0.0 <= cell["exceedance_rate"] <= 1.0
    assert result["primary_reading"] is cell["consistent_with_coverage"]
    assert set(result["pinball_difference"]) == {"alpha_0.99", "alpha_0.975"}
    assert result["pinball_difference"]["alpha_0.99"]["margin_bp"] == 0.2
    assert result["pinball_difference"]["alpha_0.975"]["margin_bp"] == 0.4
    with pytest.raises(ValueError, match="only 1 day"):
        analyse_window(
            dates, closes, scored_from=days[0], scored_to=days[0], confidence=0.9, n_resamples=10
        )


def test_a_window_whose_thresholds_are_not_all_defined_is_refused() -> None:
    dates, closes = load_daily_closes(DATA_PATH)
    with pytest.raises(ValueError, match="not finite"):
        # the 250-day historical simulation has no threshold for the very first days
        analyse_window(
            dates[:600], closes[:600], scored_from=date(1928, 1, 3), scored_to=None,
            confidence=0.9, n_resamples=10,
        )  # fmt: skip
