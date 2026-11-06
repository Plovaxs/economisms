import numpy as np
import pytest

from prometheus.hedging.position_constraints import PositionLimits, project_onto_feasible_region


def test_rejects_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="max_position"):
        PositionLimits(max_position=0.0, max_leverage=5.0, capital=1000.0)
    with pytest.raises(ValueError, match="max_leverage"):
        PositionLimits(max_position=1.0, max_leverage=0.0, capital=1000.0)
    with pytest.raises(ValueError, match="capital"):
        PositionLimits(max_position=1.0, max_leverage=5.0, capital=0.0)


def test_a_holding_within_both_bounds_is_unchanged() -> None:
    limits = PositionLimits(max_position=1.0, max_leverage=5.0, capital=1000.0)
    proposed = np.array([0.4])
    spot = np.array([100.0])
    out = project_onto_feasible_region(proposed, spot, limits)
    assert out == pytest.approx(proposed)


def test_position_cap_binds_when_leverage_is_loose() -> None:
    """Discriminating: the position cap, not the (here, much looser)
    leverage bound, must be the one that actually clips the result."""
    limits = PositionLimits(max_position=1.0, max_leverage=5.0, capital=1000.0)
    proposed = np.array([5.0])
    spot = np.array([10.0])  # leverage bound = 1000*5/10 = 500, far looser than 1.0
    out = project_onto_feasible_region(proposed, spot, limits)
    assert out == pytest.approx([1.0])


def test_leverage_bound_binds_when_the_position_cap_is_loose() -> None:
    """Discriminating in the other direction: a high spot price makes
    even a modest holding notionally large, so the leverage-implied
    bound becomes the tighter one."""
    limits = PositionLimits(max_position=100.0, max_leverage=5.0, capital=1000.0)
    proposed = np.array([6.0])
    spot = np.array([1000.0])  # leverage bound = 1000*5/1000 = 5.0, tighter than 100.0
    out = project_onto_feasible_region(proposed, spot, limits)
    assert out == pytest.approx([5.0])


def test_projection_is_symmetric_for_short_positions() -> None:
    limits = PositionLimits(max_position=1.0, max_leverage=5.0, capital=1000.0)
    proposed = np.array([-5.0])
    spot = np.array([10.0])
    out = project_onto_feasible_region(proposed, spot, limits)
    assert out == pytest.approx([-1.0])


def test_applies_elementwise_across_a_full_paths_by_steps_grid() -> None:
    """The realistic shape this is meant for: project an entire
    (n_paths, n_steps) hedge-ratio grid (as produced by
    hedging.baseline/deep_hedge) against its own paired spot-price
    grid in one call."""
    limits = PositionLimits(max_position=1.0, max_leverage=100.0, capital=1000.0)
    proposed = np.array([[0.3, 1.5, -2.0], [0.9, 0.5, 1.2]])
    spot = np.full((2, 3), 50.0)
    out = project_onto_feasible_region(proposed, spot, limits)
    expected = np.array([[0.3, 1.0, -1.0], [0.9, 0.5, 1.0]])
    assert out == pytest.approx(expected)


def test_rejects_a_spot_shape_mismatch() -> None:
    limits = PositionLimits(max_position=1.0, max_leverage=5.0, capital=1000.0)
    with pytest.raises(ValueError, match="shape"):
        project_onto_feasible_region(np.zeros((2, 3)), np.zeros((2, 4)), limits)
