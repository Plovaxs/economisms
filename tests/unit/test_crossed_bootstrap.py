import numpy as np
import pytest

from prometheus.experiments.crossed_bootstrap import (
    bonferroni_confidence,
    crossed_mean_bootstrap,
)


def test_constant_effect_has_exact_point_interval_for_every_axis() -> None:
    result = crossed_mean_bootstrap(np.full((3, 4), 2.5), np.random.default_rng(7), n_resamples=100)
    for interval in (result.crossed, result.training_only, result.evaluation_only):
        assert interval.point_estimate == interval.ci_low == interval.ci_high == 2.5
    assert result.training_seed_std == result.test_bank_std == 0


def test_more_test_banks_do_not_erase_training_variability() -> None:
    # Two fitted models differ by 10 units on every test bank. Treating
    # cells as independent would falsely tighten inference as banks grow.
    for n_banks in (2, 200):
        matrix = np.repeat(np.array([[-5.0], [5.0]]), n_banks, axis=1)
        result = crossed_mean_bootstrap(matrix, np.random.default_rng(42), n_resamples=500)
        assert result.crossed.ci_low == -5.0
        assert result.crossed.ci_high == 5.0
        assert result.training_only.ci_low == -5.0
        assert result.training_only.ci_high == 5.0
        assert result.evaluation_only.ci_low == result.evaluation_only.ci_high == 0.0
        assert result.training_seed_std == pytest.approx(np.sqrt(50.0))


def test_more_models_do_not_erase_shared_test_bank_variability() -> None:
    matrix = np.repeat(np.array([[-8.0, 8.0]]), 200, axis=0)
    result = crossed_mean_bootstrap(matrix, np.random.default_rng(2), n_resamples=500)
    assert result.crossed.ci_low == -8.0
    assert result.crossed.ci_high == 8.0
    assert result.training_only.ci_low == result.training_only.ci_high == 0.0
    assert result.evaluation_only.ci_low == -8.0
    assert result.evaluation_only.ci_high == 8.0


def test_crossing_resampled_rows_and_columns_includes_their_interaction() -> None:
    class KnownDraws:
        def __init__(self):
            self.draws = iter([np.array([0, 0]), np.array([1, 1])])

        def integers(self, *args, **kwargs):
            return next(self.draws)

    result = crossed_mean_bootstrap(np.array([[1.0, 9.0], [3.0, 7.0]]), KnownDraws(), n_resamples=1)
    assert result.crossed.point_estimate == 5.0
    assert result.crossed.ci_low == result.crossed.ci_high == 9.0
    assert result.training_only.ci_low == 5.0
    assert result.evaluation_only.ci_low == 8.0


def test_reproducible_at_fixed_seed_and_wider_nominal_intervals_nest() -> None:
    values = np.array([[1.0, 3.0, 2.0], [-3.0, 0.0, 4.0], [8.0, 5.0, 7.0]])
    first = crossed_mean_bootstrap(values, np.random.default_rng(99), n_resamples=500)
    second = crossed_mean_bootstrap(values, np.random.default_rng(99), n_resamples=500)
    wider = crossed_mean_bootstrap(
        values, np.random.default_rng(99), n_resamples=500, confidence=0.99
    )
    assert first == second
    assert first.crossed.point_estimate == pytest.approx(values.mean())
    assert wider.crossed.ci_low <= first.crossed.ci_low
    assert wider.crossed.ci_high >= first.crossed.ci_high


@pytest.mark.parametrize(
    "matrix",
    [
        np.zeros(4),
        np.zeros((1, 3)),
        np.zeros((3, 1)),
        np.empty((0, 0)),
        np.array([[0.0, 1.0], [2.0, float("nan")]]),
    ],
)
def test_missing_or_nonfinite_seed_levels_are_rejected(matrix) -> None:
    with pytest.raises(ValueError):
        crossed_mean_bootstrap(matrix, np.random.default_rng(0))


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_resamples": 0},
        {"n_resamples": True},
        {"confidence": 1.0},
    ],
)
def test_invalid_bootstrap_settings_are_rejected(overrides) -> None:
    with pytest.raises(ValueError):
        crossed_mean_bootstrap(np.zeros((2, 2)), np.random.default_rng(0), **overrides)


def test_nominal_bonferroni_tail_allocation_and_validation() -> None:
    assert bonferroni_confidence(0.95, 1) == 0.95
    assert bonferroni_confidence(0.95, 5) == 0.99
    for confidence, count in ((1.0, 3), (0.95, 0), (0.95, True)):
        with pytest.raises(ValueError):
            bonferroni_confidence(confidence, count)
