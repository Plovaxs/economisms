"""Audit item M-04: the grid against Monte Carlo as the dimension grows, on a problem with an exact
answer in every dimension (a call on the geometric average of d independent lognormal assets)."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from prometheus.pde_solvers import dimension_scaling as ds
from prometheus.pde_solvers.dimension_scaling import (
    BasketProblem,
    paths_for_half_width,
    run_monte_carlo,
    run_study,
    solve_grid,
)
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

ROOT = Path(__file__).resolve().parents[2]


def test_one_dimension_is_black_scholes() -> None:
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2)
    reference = black_scholes_price(market, EuropeanOption(100.0, 1.0, "call"))
    assert BasketProblem(1).exact_price() == pytest.approx(reference, rel=1e-12)


@pytest.mark.parametrize("dimension", [2, 3, 5])
def test_the_closed_form_matches_a_large_monte_carlo(dimension: int) -> None:
    problem = BasketProblem(dimension)
    point = run_monte_carlo(problem, 600_000, np.random.default_rng(dimension))
    assert point.standard_error is not None
    assert abs(point.error) < 4 * point.standard_error
    assert point.exact_price == pytest.approx(problem.exact_price())


def test_the_price_falls_with_dimension_because_the_average_is_less_volatile() -> None:
    prices = [BasketProblem(d).exact_price() for d in (1, 2, 3, 4)]
    assert all(a > b for a, b in zip(prices, prices[1:], strict=False))


@pytest.mark.parametrize("dimension, ladder", [(1, (41, 81, 161)), (2, (21, 41, 81))])
def test_the_grid_is_second_order_in_space(dimension: int, ladder: tuple[int, ...]) -> None:
    errors = [abs(solve_grid(BasketProblem(dimension), m, m).error) for m in ladder]
    assert errors[0] > errors[1] > errors[2]
    for coarse, fine in zip(errors, errors[1:], strict=False):
        # halving the spacing (nodes m -> 2m - 1) cuts a second-order error by about 4
        assert 3.2 < coarse / fine < 4.8


def test_the_domain_width_does_not_move_the_price() -> None:
    """The boundary values are an approximation (the discounted payoff at the edge); at +-6 standard
    deviations that cannot matter. Same spacing, a wider box: the price moves by 3e-6, against a
    grid error of about 0.1 at this resolution."""
    narrow = solve_grid(BasketProblem(2), 21, 21, half_width=6.0)
    wide = solve_grid(BasketProblem(2), 31, 21, half_width=9.0)
    assert narrow.resolution == 21 and wide.resolution == 31
    assert narrow.price == pytest.approx(wide.price, abs=1e-4)


def test_direct_factorization_fill_in_grows_faster_than_the_node_count() -> None:
    """Roughly the same number of unknowns, more dimensions, much bigger factors: the cost is the
    fill-in of the direct solver, not just the node count."""
    flat = solve_grid(BasketProblem(2), 81, 20)  # 6,561 unknowns
    cube = solve_grid(BasketProblem(3), 19, 20)  # 6,859 unknowns
    assert flat.factor_nnz is not None and cube.factor_nnz is not None
    assert abs(cube.unknowns - flat.unknowns) < 0.1 * flat.unknowns
    assert cube.factor_nnz > 2 * flat.factor_nnz


def test_the_node_cap_refuses_instead_of_exhausting_memory() -> None:
    with pytest.raises(ValueError, match="cap"):
        solve_grid(BasketProblem(3), 61, 20)  # 226,981 nodes


@pytest.mark.parametrize(
    "nodes, n_time, width",
    [(20, 20, 6.0), (3, 20, 6.0), (21, 2, 6.0), (21, 20, 0.0), (21, 20, -1.0)],
)
def test_the_grid_refuses_bad_inputs(nodes: int, n_time: int, width: float) -> None:
    with pytest.raises(ValueError):
        solve_grid(BasketProblem(1), nodes, n_time, half_width=width)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dimension": 0},
        {"dimension": 1, "spot": 0.0},
        {"dimension": 1, "volatility": -0.1},
        {"dimension": 1, "maturity": 0.0},
        {"dimension": 1, "rate": float("nan")},
    ],
)
def test_a_malformed_problem_is_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        BasketProblem(**kwargs)  # type: ignore[arg-type]


def test_monte_carlo_refuses_bad_inputs_and_sizes_itself_by_the_target() -> None:
    problem = BasketProblem(2)
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        run_monte_carlo(problem, 1, rng)
    with pytest.raises(ValueError):
        paths_for_half_width(problem, 0.0, rng)
    wide = paths_for_half_width(problem, 0.04, np.random.default_rng(1))
    narrow = paths_for_half_width(problem, 0.02, np.random.default_rng(1))
    assert 3.4 < narrow / wide < 4.6  # half the interval needs four times the paths
    point = run_monte_carlo(problem, narrow, np.random.default_rng(2), batch=50_000)
    assert 1.96 * (point.standard_error or 0.0) == pytest.approx(0.02, rel=0.1)


def test_the_study_reports_the_cheapest_grid_within_the_target_or_none() -> None:
    result = run_study({1: (21, 41, 81, 161), 2: (11, 21)}, target_error=0.02, seed=3)
    matched = {row["dimension"]: row for row in result["matched"]}  # type: ignore[attr-defined]
    one = matched[1]["grid"]
    assert one is not None and abs(one["error"]) <= 0.02
    assert one["resolution"] == 161  # 81 has error 0.0205, just over the target
    assert matched[2]["grid"] is None  # the ladder never reaches it
    assert matched[2]["grid_best_error_reached"] > 0.02
    assert matched[1]["monte_carlo"]["method"] == "monte_carlo"
    with pytest.raises(ValueError):
        run_study({1: (21,)}, target_error=0.0)


def test_the_committed_study_reproduces_in_its_errors() -> None:
    """The timings in `docs/numerics/dimension_scaling.json` are one machine's; the errors are
    deterministic and must come back. The cheap rows are recomputed."""
    committed = json.loads((ROOT / "docs" / "numerics" / "dimension_scaling.json").read_text())
    grid_rows = {
        (p["dimension"], p["resolution"]): p for p in committed["points"] if p["method"] == "grid"
    }
    for dimension, nodes in ((1, 81), (2, 41), (3, 15), (4, 7)):
        row = grid_rows[(dimension, nodes)]
        fresh = solve_grid(BasketProblem(dimension), nodes, max(nodes, 20))
        assert fresh.error == pytest.approx(row["error"], abs=1e-9)
        assert fresh.factor_nnz == row["factor_nnz"]
        assert row["unknowns"] == nodes**dimension
    assert math.isfinite(sum(p["seconds"] for p in committed["points"]))
    assert ds.MAX_NODES >= 68_921  # the committed d = 3, 41-node row fits under the cap
