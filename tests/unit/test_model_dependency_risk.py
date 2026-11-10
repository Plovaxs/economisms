from __future__ import annotations

import numpy as np

from prometheus.evidence.model_dependency_risk import (
    MODEL_DEPENDENCY_GRAPH,
    propagate_pde_delta_error_to_portfolio_es,
)
from prometheus.pde_solvers.problem import BlackScholesPDESpec


def _gbm_paths(n_paths: int, n_steps: int, dt: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    spot0, mu, sigma = 100.0, 0.05, 0.2
    paths = np.empty((n_paths, n_steps + 1))
    paths[:, 0] = spot0
    for t in range(n_steps):
        z = rng.standard_normal(n_paths)
        paths[:, t + 1] = paths[:, t] * np.exp(
            (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
        )
    return paths


def test_the_dependency_graph_names_a_real_upstream_and_downstream_model() -> None:
    assert len(MODEL_DEPENDENCY_GRAPH) >= 1
    edge = MODEL_DEPENDENCY_GRAPH[0]
    assert edge.upstream_model == "pde-solvers"
    assert edge.downstream_model == "deep-hedge"
    assert edge.interaction


def test_a_coarser_grid_produces_a_larger_local_error_and_a_larger_aggregate_shift() -> None:
    """MGR-06's own acceptance wording: "system-level error propagation
    analyzed, not just local scores." A coarser PDE grid has a larger
    local Delta error (PDE-08's own score); this confirms that the
    same coarser grid also produces a larger shift in the downstream,
    AGGREGATE portfolio Expected Shortfall once that Delta is actually
    carried through the real self-financing hedge simulator -- i.e.
    the propagation is real and directionally consistent, not merely
    two unrelated numbers reported side by side."""
    n_steps, dt = 20, 1.0 / 252
    paths = _gbm_paths(n_paths=200, n_steps=n_steps, dt=dt, seed=0)
    spec = BlackScholesPDESpec(
        risk_free_rate=0.03, volatility=0.2, maturity=n_steps * dt,
        strike=100.0, option_type="call",
    )

    fine = propagate_pde_delta_error_to_portfolio_es(
        spec, paths, dt, cost_rate=0.001, alpha=0.95, n_space=400, n_time=400
    )
    coarse = propagate_pde_delta_error_to_portfolio_es(
        spec, paths, dt, cost_rate=0.001, alpha=0.95, n_space=10, n_time=10
    )

    assert abs(coarse.local_delta_error) > abs(fine.local_delta_error)
    assert abs(coarse.aggregate_es_shift) > abs(fine.aggregate_es_shift)
    assert np.isfinite(fine.aggregate_es_shift)
    assert np.isfinite(coarse.aggregate_es_shift)


def test_using_the_exact_delta_on_both_sides_yields_zero_local_error_and_zero_shift() -> None:
    """Sanity bound: if the upstream model had no error at all, there
    would be nothing to propagate -- a resolution fine enough to all
    but eliminate the grid's own Delta error should leave the
    downstream aggregate Expected Shortfall all but unchanged."""
    n_steps, dt = 20, 1.0 / 252
    paths = _gbm_paths(n_paths=200, n_steps=n_steps, dt=dt, seed=1)
    spec = BlackScholesPDESpec(
        risk_free_rate=0.03, volatility=0.2, maturity=n_steps * dt,
        strike=100.0, option_type="call",
    )

    report = propagate_pde_delta_error_to_portfolio_es(
        spec, paths, dt, cost_rate=0.001, alpha=0.95, n_space=400, n_time=400
    )

    assert abs(report.local_delta_error) < 1e-2
    assert abs(report.aggregate_es_shift) < 1e-1


def test_rejects_malformed_price_paths() -> None:
    import pytest

    spec = BlackScholesPDESpec(
        risk_free_rate=0.03, volatility=0.2, maturity=1.0, strike=100.0, option_type="call"
    )
    with pytest.raises(ValueError, match="price_paths"):
        propagate_pde_delta_error_to_portfolio_es(
            spec, np.zeros((5,)), 1.0 / 252, cost_rate=0.001
        )
