"""Power notes: the arithmetic is checked against an independent route wherever one exists.

E3's exact power is compared with a count-by-count enumeration that uses the endpoint's own
interval function; E1's simulated power with the textbook formula; E2 with the cases that must be
near 0 and near 1. All seeded.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from prometheus.confirmatory import __main__ as cli
from prometheus.confirmatory import power
from prometheus.confirmatory.intervals import bonferroni_confidence, exact_binomial_interval

_CONF = bonferroni_confidence()


def test_e1_power_matches_the_textbook_formula_at_the_formulas_own_effect() -> None:
    sd, n = 0.05, 50
    effect = power.analytic_e1_minimum_effect(sd, n, confidence=_CONF)
    row = power.power_e1(sd, n, [effect], confidence=_CONF, margin=0.0, n_sims=3000, seed=1)[0]
    assert row["power_better"] == pytest.approx(0.8, abs=0.04)
    assert effect == pytest.approx(
        (stats.t.ppf(0.5 + _CONF / 2, n - 1) + stats.t.ppf(0.8, n - 1)) * sd / np.sqrt(n)
    )


def test_e1_power_is_tiny_with_no_effect_and_near_one_with_a_large_one() -> None:
    rows = power.power_e1(
        0.05, 50, [0.0, 0.2], confidence=_CONF, margin=0.0488, n_sims=1500, seed=2
    )
    assert rows[0]["power_better"] < 0.02  # false-positive rate: about (1 - confidence) / 2
    assert rows[1]["power_better"] > 0.99


def test_a_tiny_spread_makes_an_effect_inside_the_margin_equivalent_not_better() -> None:
    row = power.power_e1(0.005, 50, [0.01], confidence=_CONF, margin=0.0488, n_sims=500, seed=3)[0]
    assert row["share_equivalent"] > 0.99 and row["power_better"] < 0.01


@pytest.mark.parametrize(("sd", "n"), [(0.0, 50), (0.05, 1)])
def test_e1_power_refuses_what_it_cannot_simulate(sd: float, n: int) -> None:
    with pytest.raises(ValueError, match="spread"):
        power.power_e1(sd, n, [0.1], confidence=_CONF, margin=0.05)


def test_e3_exact_power_equals_a_count_by_count_enumeration_with_the_endpoints_own_interval() -> (
    None
):
    nominal = 0.01
    # 600 days: with no exceedance at all the interval's upper end is below 1%, so a model that is
    # too CAUTIOUS is excluded as well as one that is too bold; 60 days cannot show that
    for n, rates in ((60, (0.01, 0.03, 0.08)), (600, (0.0005, 0.01, 0.02))):
        for rate in rates:
            expected = 0.0
            for k in range(n + 1):
                low, high = exact_binomial_interval(k, n, _CONF)
                if low > nominal or high < nominal:
                    expected += float(stats.binom.pmf(k, n, rate))
            got = power.power_e3([rate], n, nominal=nominal, confidence=_CONF)[0]
            assert got["power_to_exclude_nominal"] == pytest.approx(expected, abs=1e-12), (n, rate)
            assert got["expected_exceedances"] == pytest.approx(rate * n)
    too_cautious = power.power_e3([0.0005], 600, nominal=nominal, confidence=_CONF)[0]
    assert too_cautious["power_to_exclude_nominal"] > 0.5


def test_e3_false_alarm_rate_is_below_the_interval_level_and_power_grows_with_the_gap() -> None:
    rows = power.power_e3([0.01, 0.015, 0.02, 0.03], 880, nominal=0.01, confidence=_CONF)
    assert rows[0]["power_to_exclude_nominal"] <= 1.0 - _CONF
    powers = [r["power_to_exclude_nominal"] for r in rows]
    assert powers == sorted(powers) and powers[-1] > 0.9
    with pytest.raises(ValueError, match="at least one day"):
        power.power_e3([0.01], 0, nominal=0.01, confidence=_CONF)


def test_e2_power_is_low_with_no_effect_and_high_with_a_large_one_and_is_seeded() -> None:
    rng = np.random.default_rng(7)
    old = rng.normal(0.1, 0.2, size=277)
    kwargs = dict(confidence=_CONF, margin=0.03, block_length=3, n_sims=60, n_resamples=150, seed=4)
    none, large = power.power_e2(old, 30, [0.0, 0.4], **kwargs)  # type: ignore[arg-type]
    assert none["power_better"] < 0.1 and large["power_better"] > 0.9
    again, _ = power.power_e2(old, 30, [0.0, 0.4], **kwargs)  # type: ignore[arg-type]
    assert again == none
    with pytest.raises(ValueError, match="not enough old months"):
        power.power_e2(old[:5], 30, [0.1], **kwargs)  # type: ignore[arg-type]


def test_the_smallest_effect_and_the_verdict() -> None:
    rows = [
        {"true_theta": 0.02, "power_better": 0.30},
        {"true_theta": 0.05, "power_better": 0.81},
        {"true_theta": 0.10, "power_better": 0.99},
    ]
    assert power.smallest_effect(rows) == 0.05
    assert power.smallest_effect(rows[:1]) is None
    assert power.verdict(0.8).startswith("adequate")
    assert power.verdict(0.79).startswith("estimation-only")


def test_the_old_differences_come_from_the_reports_per_month_rows() -> None:
    report = {
        "per_month": [
            {"yoy": 3.0, "persistence": 3.5, "base_effect": 3.1},
            {"yoy": 2.0, "persistence": 1.9, "base_effect": 2.4},
        ]
    }
    np.testing.assert_allclose(power.old_e2_differences(report), [0.5 - 0.1, 0.1 - 0.4])


def test_the_planned_e2_sample_size_comes_from_the_sidecar_alone(tmp_path: Path) -> None:
    meta = tmp_path / "lock.meta.json"
    meta.write_text(json.dumps({"missing_months": ["2025-10"]}))
    # 2023-04 .. 2026-10 is 43 months; a gap in 2025-10 removes targets 2025-10 .. 2026-11
    assert cli.planned_e2_months(meta, date(2023, 4, 30), date(2026, 10, 31)) == 30
    # the gap reaches 13 months past itself: only a window that runs to 2026-12 can show it
    assert cli.planned_e2_months(meta, date(2023, 4, 30), date(2026, 12, 31)) == 45 - 14
    meta.write_text(json.dumps({"missing_months": []}))
    assert cli.planned_e2_months(meta, date(2023, 4, 30), date(2026, 10, 31)) == 43


def test_the_power_command_reports_without_training_when_asked(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    meta = tmp_path / "lock.meta.json"
    meta.write_text(json.dumps({"missing_months": ["2025-10"]}))
    out = tmp_path / "power.json"
    code = cli.main(["--output", str(out), "power", "--skip-e1", "--lock-meta", str(meta)])
    assert code == 0
    report = json.loads(out.read_text())
    assert "E1" not in report and set(report) >= {"E2", "E3", "assumption", "interval_confidence"}
    assert "30" in report["E2"]["by_sample_size"] and "24" in report["E2"]["by_sample_size"]
    assert report["E3"]["by_days"]["880"]["false_alarm_rate_at_nominal"] <= 1.0 - _CONF
    assert json.loads(capsys.readouterr().out) == report


def test_the_committed_power_note_agrees_with_what_the_protocol_says_about_it() -> None:
    root = Path(__file__).resolve().parents[2]
    note = json.loads((root / "docs" / "confirmatory" / "power_note.json").read_text())
    protocol = (root / "docs" / "CONFIRMATORY_PROTOCOL.md").read_text(encoding="utf-8")
    assert note["E1"]["verdict"].startswith("adequate")
    assert all(
        v["verdict"].startswith("estimation-only") for v in note["E2"]["by_sample_size"].values()
    )
    assert all(v["verdict"].startswith("estimation-only") for v in note["E3"]["by_days"].values())
    assert set(note["E2"]["by_sample_size"]) == {"30", "24"}  # the sample sizes the protocol quotes
    assert "adequate, it can support a verdict" in protocol
    assert protocol.count("estimation-only") >= 2
    assert note["E1"]["power_at_reference"] > 0.95
    assert 0.5 < note["E2"]["by_sample_size"]["30"]["power_at_reference"] < 0.7
