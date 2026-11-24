"""The interval and decision rules of the confirmatory protocol (rules 4 and 5).

Each interval is compared with an independent implementation (scipy's t and exact-binomial
intervals, the repository's own block bootstrap), and the outcome classes are pinned on both sides
of every boundary, because the whole point of a pre-declared rule is that it cannot bend.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from prometheus.confirmatory.intervals import (
    Interval,
    block_interval,
    bonferroni_confidence,
    classify_effect,
    exact_binomial_interval,
    t_interval,
)
from prometheus.experiments.block_bootstrap import moving_block_bootstrap


def _interval(low: float, high: float) -> Interval:
    return Interval((low + high) / 2.0, low, high, 0.98, 10, "test")


def test_three_primary_endpoints_get_a_bonferroni_interval_level() -> None:
    assert bonferroni_confidence() == pytest.approx(1.0 - 0.05 / 3.0)
    assert bonferroni_confidence(0.05, 1) == pytest.approx(0.95)
    with pytest.raises(ValueError, match="familywise_alpha"):
        bonferroni_confidence(1.5)
    with pytest.raises(ValueError, match="n_endpoints"):
        bonferroni_confidence(0.05, 0)


@pytest.mark.parametrize(
    ("low", "high", "margin", "expected"),
    [
        (-0.01, 0.01, 0.03, "equivalent"),
        (0.001, 0.02, 0.03, "equivalent"),  # a real but negligible difference is "equivalent"
        (-0.02, -0.001, 0.03, "equivalent"),
        (0.01, 0.05, 0.03, "better"),
        (-0.05, -0.01, 0.03, "worse"),
        (-0.05, 0.05, 0.03, "inconclusive"),
        (-0.02, 0.04, 0.03, "inconclusive"),  # one end beyond the margin and zero inside
        (-0.03, 0.01, 0.03, "inconclusive"),  # the margin is strict: low == -margin is not inside
        (0.02, 0.03, 0.03, "better"),  # high == margin is not inside either, so not equivalent
        (0.01, 0.05, 0.0, "better"),  # no margin: equivalence is impossible
        (-0.01, 0.01, 0.0, "inconclusive"),
    ],
)
def test_outcome_classes_on_both_sides_of_every_boundary(
    low: float, high: float, margin: float, expected: str
) -> None:
    assert classify_effect(_interval(low, high), margin) == expected


def test_an_interval_containing_zero_is_never_called_equivalent_unless_it_fits_the_margin() -> None:
    assert classify_effect(_interval(-0.10, 0.10), 0.03) == "inconclusive"


@pytest.mark.parametrize("margin", [-0.1, float("nan"), float("inf")])
def test_a_bad_margin_is_refused(margin: float) -> None:
    with pytest.raises(ValueError, match="margin"):
        classify_effect(_interval(-0.1, 0.1), margin)


def test_an_inverted_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="low end"):
        classify_effect(Interval(0.0, 0.2, -0.2, 0.95, 5, "bad"), 0.1)


def test_the_t_interval_matches_scipys() -> None:
    sample = np.array([0.04, 0.07, 0.01, 0.09, 0.05, 0.06, 0.02])
    got = t_interval(sample, 0.95)
    low, high = stats.t.interval(0.95, len(sample) - 1, loc=sample.mean(), scale=stats.sem(sample))
    assert got.estimate == pytest.approx(sample.mean())
    assert (got.low, got.high) == pytest.approx((low, high))
    assert got.n == 7


@pytest.mark.parametrize("sample", [[1.0], [1.0, float("nan")], [[1.0, 2.0], [3.0, 4.0]]])
def test_the_t_interval_refuses_a_sample_it_cannot_use(sample: list[object]) -> None:
    with pytest.raises(ValueError, match="sample"):
        t_interval(sample, 0.95)  # type: ignore[arg-type]


def test_the_block_interval_is_the_repositorys_block_bootstrap_with_its_own_generator() -> None:
    sample = np.sin(np.arange(60) / 4.0) + 0.1
    got = block_interval(sample, block_length=5, confidence=0.9, n_resamples=300, seed=7)
    expected = moving_block_bootstrap(
        np.mean, sample, 5, np.random.default_rng(7), n_resamples=300, confidence=0.9
    )
    assert (got.estimate, got.low, got.high) == (
        expected.point_estimate,
        expected.ci_low,
        expected.ci_high,
    )
    assert "block 5" in got.method and "seed 7" in got.method
    again = block_interval(sample, block_length=5, confidence=0.9, n_resamples=300, seed=7)
    other = block_interval(sample, block_length=5, confidence=0.9, n_resamples=300, seed=8)
    assert again == got and other != got


def test_the_block_interval_refuses_a_sample_with_a_non_finite_value() -> None:
    with pytest.raises(ValueError, match="finite"):
        block_interval(
            np.array([1.0, np.inf, 2.0]), block_length=1, confidence=0.9, n_resamples=10, seed=0
        )


@pytest.mark.parametrize(
    ("successes", "trials", "confidence"),
    [
        (0, 50, 0.95),
        (3, 900, 0.9833),
        (9, 900, 0.9833),
        (48, 3235, 0.95),
        (50, 50, 0.95),
        (1, 2, 0.8),
    ],
)
def test_the_exact_binomial_interval_matches_scipys_clopper_pearson(
    successes: int, trials: int, confidence: float
) -> None:
    expected = stats.binomtest(successes, trials).proportion_ci(
        confidence_level=confidence, method="exact"
    )
    low, high = exact_binomial_interval(successes, trials, confidence)
    assert (low, high) == pytest.approx((expected.low, expected.high), abs=1e-9)


@pytest.mark.parametrize(("successes", "trials"), [(-1, 10), (11, 10), (0, 0)])
def test_the_exact_binomial_interval_refuses_impossible_counts(successes: int, trials: int) -> None:
    with pytest.raises(ValueError, match="trials"):
        exact_binomial_interval(successes, trials, 0.95)
