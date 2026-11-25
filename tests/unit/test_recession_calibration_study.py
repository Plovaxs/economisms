"""PR-217: out-of-fold recalibration of the recession classifier."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.orchestration import recession_calibration_study as study
from prometheus.recessionnet.dataset import RecessionDataset

COMMITTED = Path(__file__).resolve().parents[2] / "docs" / "numerics" / "recession_calibration.json"


def _months(first: date, n: int) -> tuple[date, ...]:
    out = []
    year, month = first.year, first.month
    for _ in range(n):
        out.append(date(year, month, 1))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return tuple(out)


def test_platt_recovers_an_overconfident_model() -> None:
    rng = np.random.default_rng(0)
    truth = rng.normal(size=4000)
    labels = (rng.random(4000) < 1.0 / (1.0 + np.exp(-truth))).astype(float)
    over = study.fit_platt(3.0 * truth, labels)  # logits three times too large
    assert 0.2 < over.a < 0.5


def test_platt_never_reverses_the_ordering() -> None:
    rng = np.random.default_rng(1)
    logits = rng.normal(size=500)
    labels = (logits < 0).astype(float)  # a model that is exactly backwards
    assert study.fit_platt(logits, labels).a == pytest.approx(0.0, abs=1e-6)


def test_platt_needs_both_classes() -> None:
    with pytest.raises(ValueError, match="both classes"):
        study.fit_platt(np.zeros(5), np.zeros(5))
    with pytest.raises(ValueError, match="1-D"):
        study.fit_platt(np.zeros((2, 2)), np.zeros((2, 2)))


def test_a_map_applied_to_zero_logit_is_the_sigmoid_of_the_intercept() -> None:
    p = study.PlattMap(2.0, -1.0).apply(np.array([0.0]))
    assert p[0] == pytest.approx(1.0 / (1.0 + np.exp(1.0)))


def test_blocks_cover_every_decision_month_exactly_once() -> None:
    months = _months(date(1968, 1, 1), 12 * 40)
    starts = study.block_starts(months, date(1985, 1, 1), 3)
    assert starts[0] == date(1985, 1, 1) and starts[1] == date(1988, 1, 1)
    assert starts[-1] <= months[-1] < date(starts[-1].year + 3, 1, 1)


def test_a_block_is_never_predicted_by_a_model_that_saw_its_own_positives() -> None:
    """The only positives are target months in 1990 (decision months 1989-07 .. 1990-06, inside the
    1988 block). A model trained before 1988 has no positive, so that block must be SKIPPED; a
    leaking implementation would have trained on the block's own labels and predicted it."""
    n = 12 * 30
    decision = _months(date(1980, 1, 1), n)
    target = _months(date(1980, 7, 1), n)
    labels = np.array([1.0 if date(1990, 1, 1) <= d < date(1990, 7, 1) else 0.0 for d in target])
    features = np.random.default_rng(2).normal(size=(n, 4))
    train = RecessionDataset(decision, target, features, labels, ("a",), 4, 6)
    _, y = study.out_of_fold_logits(train, epochs=20, seed=0)
    assert len(y) == sum(d >= date(1991, 1, 1) for d in decision)  # blocks 1985 and 1988 skipped
    assert y.sum() == 0.0  # no positive month was ever scored, because none could be learned from


def test_with_no_positive_months_there_is_nothing_to_calibrate() -> None:
    n = 12 * 30
    decision = _months(date(1980, 1, 1), n)
    target = _months(date(1980, 7, 1), n)
    features = np.random.default_rng(3).normal(size=(n, 4))
    train = RecessionDataset(decision, target, features, np.zeros(n), ("a",), 4, 6)
    with pytest.raises(ValueError, match="enough positive"):
        study.out_of_fold_logits(train, epochs=5, seed=0)


@pytest.mark.skipif(not COMMITTED.exists(), reason="committed study output is absent")
def test_the_committed_report_is_internally_consistent() -> None:
    report = json.loads(COMMITTED.read_text())
    assert report["config"]["n_test"] == 175 and report["config"]["n_test_positive"] == 14
    for row in report["comparisons"].values():
        assert row["ci_low"] <= row["brier_difference_first_minus_second"] <= row["ci_high"]
    assert report["test_roc_auc"]["raw"] == pytest.approx(report["test_roc_auc"]["calibrated"])
