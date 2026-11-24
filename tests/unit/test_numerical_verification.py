"""Numerical verification (audit items M-02, M-03): measured rates and calibration, not just values.

Matching a closed form at one setting says a solver can be right; it does not say how its error
behaves as the work grows. These tests measure that, against the Black-Scholes closed form:

- the Monte Carlo estimator's STANDARD ERROR is calibrated (the z-scores of many independent
  replications have unit spread and the nominal 95% coverage) with and without the control variate,
  and its error shrinks like N^(-1/2);
- the Crank-Nicolson grid solver converges at second order in space, and its observed order in time
  is reported, not assumed: for a payoff with a kink at the strike it is closer to first order at
  the step sizes a user would pick (the usual loss of order without Rannacher start-up steps).

Every replication is seeded, so a failure is reproducible; tolerances are several standard errors of
the statistic being checked, so they are not tuned to pass.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from prometheus.pde_solvers.grid import solve_crank_nicolson
from prometheus.pde_solvers.problem import BlackScholesPDESpec
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.monte_carlo import monte_carlo_price_vanilla

MARKET = MarketSnapshot(as_of=date(2024, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2)


def _option(kind: str = "call") -> EuropeanOption:
    return EuropeanOption(strike=100.0, maturity=1.0, option_type=kind)  # type: ignore[arg-type]


def _replicate(n_paths: int, replications: int, *, control: bool, seed0: int, kind: str = "call"):
    option, reference = _option(kind), black_scholes_price(MARKET, _option(kind))
    results = [
        monte_carlo_price_vanilla(
            MARKET,
            option,
            n_paths,
            4,
            np.random.default_rng(seed0 + k),
            use_control_variate=control,
        )
        for k in range(replications)
    ]
    errors = np.array([r.price - reference for r in results])
    standard_errors = np.array([r.standard_error for r in results])
    return errors, standard_errors


@pytest.mark.parametrize("control", [False, True], ids=["plain", "control-variate"])
@pytest.mark.parametrize("kind", ["call", "put"])
def test_the_monte_carlo_standard_error_is_calibrated(control: bool, kind: str) -> None:
    errors, standard_errors = _replicate(1000, 1500, control=control, seed0=70_000, kind=kind)
    z = errors / standard_errors
    # 1500 replications: the spread of z has a standard error of about 0.018, coverage about 0.006
    assert abs(float(z.mean())) < 0.12
    assert float(z.std(ddof=1)) == pytest.approx(1.0, abs=0.07)
    assert float(np.mean(np.abs(z) < 1.96)) == pytest.approx(0.95, abs=0.025)


@pytest.mark.parametrize("control", [False, True], ids=["plain", "control-variate"])
def test_the_monte_carlo_error_shrinks_like_the_inverse_square_root_of_the_paths(
    control: bool,
) -> None:
    sizes = [250, 1000, 4000, 16000]
    rmse = [
        float(np.sqrt(np.mean(_replicate(n, 300, control=control, seed0=5_000 * (i + 1))[0] ** 2)))
        for i, n in enumerate(sizes)
    ]
    slope = float(np.polyfit(np.log(sizes), np.log(rmse), 1)[0])
    assert slope == pytest.approx(-0.5, abs=0.07)
    assert rmse == sorted(rmse, reverse=True)


def test_the_control_variate_earns_its_complexity_on_an_at_the_money_call() -> None:
    _, plain = _replicate(1000, 200, control=False, seed0=900)
    _, controlled = _replicate(1000, 200, control=True, seed0=900)
    assert float(plain.mean() / controlled.mean()) > 2.0  # measured: about 2.6


def _spec(kind: str) -> BlackScholesPDESpec:
    return BlackScholesPDESpec(
        risk_free_rate=0.05,
        volatility=0.2,
        maturity=1.0,
        strike=100.0,
        option_type=kind,  # type: ignore[arg-type]
    )


def _orders(errors: list[float]) -> list[float]:
    return [float(np.log2(a / b)) for a, b in zip(errors, errors[1:], strict=False)]


@pytest.mark.parametrize("kind", ["call", "put"])
def test_the_grid_solver_is_second_order_in_space(kind: str) -> None:
    reference = black_scholes_price(MARKET, _option(kind))
    errors = [
        abs(solve_crank_nicolson(_spec(kind), n_space=n, n_time=2000).price_at(100.0) - reference)
        for n in (100, 200, 400)
    ]
    assert errors == sorted(errors, reverse=True)
    assert all(order == pytest.approx(2.0, abs=0.2) for order in _orders(errors))


@pytest.mark.parametrize("kind", ["call", "put"])
def test_the_grid_solver_is_second_order_when_both_axes_are_refined_together(kind: str) -> None:
    reference = black_scholes_price(MARKET, _option(kind))
    errors = [
        abs(solve_crank_nicolson(_spec(kind), n_space=n, n_time=n).price_at(100.0) - reference)
        for n in (100, 200, 400, 800)
    ]
    assert all(order == pytest.approx(2.0, abs=0.15) for order in _orders(errors))


def test_the_observed_order_in_time_is_reported_not_assumed() -> None:
    """With a kink at the strike and no start-up smoothing, Crank-Nicolson shows roughly first order
    in time at 5-40 steps (measured 1.08, 1.12, 1.53): better than first-order schemes, short of the
    textbook second order. This pins what was measured; if a start-up fix ever lifts it to 2, this
    test is the one to update, deliberately."""
    reference = black_scholes_price(MARKET, _option("call"))
    errors = [
        abs(solve_crank_nicolson(_spec("call"), n_space=1600, n_time=n).price_at(100.0) - reference)
        for n in (5, 10, 20, 40)
    ]
    assert errors == sorted(errors, reverse=True)
    assert all(0.9 < order < 2.2 for order in _orders(errors))
    assert _orders(errors)[0] < 1.5  # not yet second order at the coarse end
