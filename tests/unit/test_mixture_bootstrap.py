import math
from dataclasses import asdict

import numpy as np
import pytest

from prometheus.experiments.mixture_bootstrap import (
    mixture_cvar_point,
    nested_mixture_cvar_bootstrap,
)
from prometheus.titan.risk_metrics import historical_expected_shortfall


def test_macro_mixture_can_reverse_the_mean_conditional_risk_conclusion():
    a = np.broadcast_to(np.array([[[0.0, 0.0], [10.0, 10.0]]]), (2, 2, 2))
    b = np.full_like(a, 8.0)
    result = mixture_cvar_point(a, b, cvar_alpha=0.5)
    assert result.comparator_cvars == (10.0, 10.0)
    assert result.policy_cvars == (8.0, 8.0)
    assert result.mean_difference == 2.0
    assert result.mean_cell_cvar_difference == -3.0


def test_fitted_policies_are_not_pooled_into_an_ensemble_before_cvar():
    a = np.array([np.zeros((2, 2)), np.full((2, 2), 10.0)])
    b = np.zeros_like(a)
    point = mixture_cvar_point(a, b, cvar_alpha=0.5)
    assert point.mean_difference == 5.0
    assert historical_expected_shortfall(a.flatten(), 0.5) == 10.0


def test_fractional_tail_and_ties_match_an_independent_weighted_tail():
    a = np.tile(np.array([[[0.0, 2.0, 2.0], [2.0, 8.0, 10.0]]]), (2, 1, 1))
    b = np.zeros_like(a)
    point = mixture_cvar_point(a, b, cvar_alpha=0.75)
    assert point.mean_difference == pytest.approx((10 + 0.5 * 8) / 1.5)


def test_constant_shift_is_preserved_in_every_nested_and_conditional_resample():
    rng = np.random.default_rng(2)
    b = rng.integers(-50, 50, (3, 4, 12)).astype(float)
    result = nested_mixture_cvar_bootstrap(
        b + 7, b, np.random.default_rng(4), cvar_alpha=0.5, n_resamples=150
    )
    for interval in (result.nested, result.training_only, result.macro_only, result.market_only):
        assert interval.point_estimate == pytest.approx(7.0)
        assert interval.ci_low == pytest.approx(7.0)
        assert interval.ci_high == pytest.approx(7.0)


def test_nested_draws_match_a_separate_loop_based_reconstruction():
    a = np.random.default_rng(8).normal(size=(3, 3, 4))
    b = np.random.default_rng(9).normal(size=(3, 3, 4))
    result = nested_mixture_cvar_bootstrap(
        a, b, np.random.default_rng(7), cvar_alpha=0.625, n_resamples=40, confidence=0.8
    )
    rng = np.random.default_rng(7)
    draws = []

    def es(values):
        ordered = sorted(values)
        tail_mass = len(ordered) * 0.375
        full = math.floor(tail_mass)
        return (sum(ordered[-full:]) + (tail_mass - full) * ordered[-full - 1]) / tail_mass

    for _ in range(40):
        rows = rng.integers(0, 3, 3)
        banks = rng.integers(0, 3, 3)
        paths = rng.integers(0, 4, (3, 4))
        row_diffs = []
        for row in rows:
            left, right = [], []
            for occurrence, bank in enumerate(banks):
                for path in paths[occurrence]:
                    left.append(a[row, bank, path])
                    right.append(b[row, bank, path])
            row_diffs.append(es(left) - es(right))
        draws.append(np.mean(row_diffs))
    low, high = np.quantile(draws, [0.1, 0.9])
    assert result.nested.ci_low == pytest.approx(low)
    assert result.nested.ci_high == pytest.approx(high)


def test_training_uncertainty_does_not_disappear_with_more_paths_or_banks():
    base = np.array([np.full((2, 2), value) for value in (-10.0, 10.0)])
    expanded = np.repeat(np.repeat(base, 4, axis=1), 20, axis=2)
    for losses in (base, expanded):
        result = nested_mixture_cvar_bootstrap(
            losses, np.zeros_like(losses), np.random.default_rng(2), cvar_alpha=0.5, n_resamples=400
        )
        assert result.training_only.ci_low == -10.0
        assert result.training_only.ci_high == 10.0
        assert result.macro_only.ci_low == result.macro_only.ci_high == 0.0
        assert result.market_only.ci_low == result.market_only.ci_high == 0.0


def test_macro_uncertainty_does_not_disappear_with_more_conditional_market_paths():
    a = np.broadcast_to(np.array([[[0.0], [20.0]]]), (3, 2, 1))
    for losses in (a, np.repeat(a, 200, axis=2)):
        result = nested_mixture_cvar_bootstrap(
            losses, np.zeros_like(losses), np.random.default_rng(1), cvar_alpha=0.5, n_resamples=400
        )
        assert result.macro_only.ci_low == 0.0
        assert result.macro_only.ci_high == 20.0
        assert result.market_only.ci_low == result.market_only.ci_high == 20.0


def test_repeated_seed_reproduces_all_diagnostics():
    a = np.random.default_rng(1).normal(size=(2, 2, 6))
    kwargs = dict(cvar_alpha=0.9, n_resamples=10)
    x = nested_mixture_cvar_bootstrap(a, -a, np.random.default_rng(3), **kwargs)
    y = nested_mixture_cvar_bootstrap(a, -a, np.random.default_rng(3), **kwargs)
    assert asdict(x) == asdict(y)


@pytest.mark.parametrize("shape", [(2, 4), (1, 2, 3), (2, 1, 3), (2, 2, 0)])
def test_invalid_cube_shapes_are_rejected(shape):
    with pytest.raises(ValueError):
        mixture_cvar_point(np.zeros(shape), np.zeros(shape), cvar_alpha=0.9)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cvar_alpha": 1.0},
        {"cvar_alpha": np.nan},
        {"confidence": 1.0},
        {"n_resamples": True},
        {"n_resamples": 0},
    ],
)
def test_invalid_inference_settings_are_rejected(kwargs):
    a = np.zeros((2, 2, 4))
    with pytest.raises(ValueError):
        nested_mixture_cvar_bootstrap(
            a, a, np.random.default_rng(0), **({"cvar_alpha": 0.9} | kwargs)
        )


def test_nonfinite_and_unpaired_samples_are_rejected():
    a = np.zeros((2, 2, 4))
    with pytest.raises(ValueError):
        mixture_cvar_point(a, a[:, :, :2], cvar_alpha=0.9)
    a[0, 0, 0] = np.nan
    with pytest.raises(ValueError):
        mixture_cvar_point(a, a, cvar_alpha=0.9)


def test_numeric_overflow_is_rejected_instead_of_emitting_an_infinite_risk_claim():
    a = np.full((2, 2, 1), 1e308)
    with pytest.raises(ValueError, match="non-finite"):
        mixture_cvar_point(a, -a, cvar_alpha=0.5)
    with pytest.raises(ValueError, match="non-finite"):
        mixture_cvar_point(np.repeat(a, 10, axis=2), np.zeros((2, 2, 10)), cvar_alpha=0.1)
