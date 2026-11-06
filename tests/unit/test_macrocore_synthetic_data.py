from datetime import date, timedelta

import numpy as np
import pytest

from prometheus.econosim.pit import require_eligible
from prometheus.macrocore.synthetic_data import (
    SYNTHETIC_QUALITY_FLAG,
    SYNTHETIC_SOURCE_LICENSE,
    generate_synthetic_macro_var_series,
)


def _default_panel(n_periods: int = 24, publication_lag_days: int = 20):
    rng = np.random.default_rng(5)
    phi1 = np.array([[0.5, 0.1], [0.05, 0.4]])
    sigma = np.array([[1.0, 0.2], [0.2, 0.7]])
    return generate_synthetic_macro_var_series(
        series_ids=["SYN_GDP", "SYN_UNRATE"],
        phi_matrices=[phi1],
        sigma=sigma,
        n_periods=n_periods,
        start_date=date(2020, 1, 1),
        publication_lag_days=publication_lag_days,
        rng=rng,
    )


def test_generate_rejects_invalid_inputs() -> None:
    rng = np.random.default_rng(0)
    phi = np.array([[0.5, 0.0], [0.0, 0.4]])
    sigma = np.array([[1.0, 0.0], [0.0, 1.0]])
    with pytest.raises(ValueError):
        generate_synthetic_macro_var_series([], [phi], sigma, 10, date(2020, 1, 1), 10, rng)
    with pytest.raises(ValueError):
        generate_synthetic_macro_var_series(
            ["A", "B"], [np.eye(3)], sigma, 10, date(2020, 1, 1), 10, rng
        )
    with pytest.raises(ValueError):
        generate_synthetic_macro_var_series(
            ["A", "B"], [phi], np.eye(3), 10, date(2020, 1, 1), 10, rng
        )
    with pytest.raises(ValueError):
        generate_synthetic_macro_var_series(["A", "B"], [phi], sigma, 0, date(2020, 1, 1), 10, rng)
    with pytest.raises(ValueError):
        generate_synthetic_macro_var_series(["A", "B"], [phi], sigma, 10, date(2020, 1, 1), -1, rng)


def test_panel_shapes_and_dates_are_consistent() -> None:
    panel = _default_panel(n_periods=12, publication_lag_days=15)
    assert panel.levels.shape == (12, 2)
    assert len(panel.observation_dates) == 12
    assert len(panel.known_at_dates) == 12
    assert panel.known_at_dates[0] == panel.observation_dates[0] + timedelta(days=15)
    # Monthly spacing, one month after start_date for the first period.
    assert panel.observation_dates[0] == date(2020, 2, 1)
    assert panel.observation_dates[1] == date(2020, 3, 1)


def test_store_observations_are_explicitly_labeled_synthetic() -> None:
    panel = _default_panel()
    obs = require_eligible(
        panel.store, "SYN_GDP", panel.observation_dates[0], panel.known_at_dates[0]
    )
    assert obs.source_license == SYNTHETIC_SOURCE_LICENSE
    assert obs.quality_flags == (SYNTHETIC_QUALITY_FLAG,)


def test_store_values_match_the_returned_ground_truth_array() -> None:
    panel = _default_panel(n_periods=6)
    for t in range(6):
        for idx, series_id in enumerate(panel.series_ids):
            obs = require_eligible(
                panel.store, series_id, panel.observation_dates[t], panel.known_at_dates[t]
            )
            assert obs.value == pytest.approx(panel.levels[t, idx])


def test_store_respects_publication_lag() -> None:
    panel = _default_panel(n_periods=6, publication_lag_days=20)
    from prometheus.econosim.pit import FutureDataError

    almost_there = panel.known_at_dates[2] - timedelta(days=1)
    with pytest.raises(FutureDataError):
        require_eligible(panel.store, "SYN_GDP", panel.observation_dates[2], almost_there)
    # But it IS available exactly on the known_at date.
    require_eligible(panel.store, "SYN_GDP", panel.observation_dates[2], panel.known_at_dates[2])
