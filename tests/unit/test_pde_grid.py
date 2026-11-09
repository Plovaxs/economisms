"""PDE-02: classical grid solver, validated against VOLTERRA's
closed-form Black-Scholes price/Delta/Gamma (the "analytically solved
example" the acceptance criterion asks for)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from prometheus.pde_solvers.grid import solve_crank_nicolson
from prometheus.pde_solvers.problem import BlackScholesPDESpec
from prometheus.volterra.black_scholes import black_scholes_greeks, black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _market(spot: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(as_of=date(2024, 1, 1), spot=spot, risk_free_rate=0.05, volatility=0.2)


def _spec(option_type: str = "call") -> BlackScholesPDESpec:
    return BlackScholesPDESpec(
        risk_free_rate=0.05, volatility=0.2, maturity=1.0, strike=100.0, option_type=option_type
    )


def test_call_price_matches_closed_form_within_tight_tolerance() -> None:
    spec = _spec("call")
    solution = solve_crank_nicolson(spec, n_space=400, n_time=400)
    closed_form = black_scholes_price(_market(), EuropeanOption(100.0, 1.0, "call"))
    assert solution.price_at(100.0) == pytest.approx(closed_form, abs=0.02)


def test_put_price_matches_closed_form_within_tight_tolerance() -> None:
    spec = _spec("put")
    solution = solve_crank_nicolson(spec, n_space=400, n_time=400)
    closed_form = black_scholes_price(_market(), EuropeanOption(100.0, 1.0, "put"))
    assert solution.price_at(100.0) == pytest.approx(closed_form, abs=0.02)


def test_delta_and_gamma_match_closed_form() -> None:
    spec = _spec("call")
    solution = solve_crank_nicolson(spec, n_space=400, n_time=400)
    greeks = black_scholes_greeks(_market(), EuropeanOption(100.0, 1.0, "call"))
    assert solution.delta_at(100.0) == pytest.approx(greeks.delta, abs=0.01)
    assert solution.gamma_at(100.0) == pytest.approx(greeks.gamma, abs=0.002)


def test_price_converges_monotonically_toward_closed_form_as_grid_refines() -> None:
    """The real convergence test: error at a sequence of refining grids
    should shrink, not merely be small at one arbitrarily chosen
    resolution -- the same discipline as this session's Heston
    weak-convergence check."""
    closed_form = black_scholes_price(_market(), EuropeanOption(100.0, 1.0, "call"))
    spec = _spec("call")
    errors = []
    for n in (20, 40, 80, 160):
        solution = solve_crank_nicolson(spec, n_space=n, n_time=n)
        errors.append(abs(solution.price_at(100.0) - closed_form))
    assert errors[-1] < errors[0]
    assert all(e2 <= e1 * 1.01 for e1, e2 in zip(errors, errors[1:], strict=False))


def test_multiple_strikes_and_maturities_match_closed_form() -> None:
    for strike in (80.0, 100.0, 120.0):
        for maturity in (0.25, 1.0, 2.0):
            spec = BlackScholesPDESpec(
                risk_free_rate=0.05,
                volatility=0.2,
                maturity=maturity,
                strike=strike,
                option_type="call",
            )
            solution = solve_crank_nicolson(spec, n_space=200, n_time=200)
            closed_form = black_scholes_price(_market(), EuropeanOption(strike, maturity, "call"))
            assert solution.price_at(100.0) == pytest.approx(closed_form, abs=0.05)


def test_rejects_too_small_grid() -> None:
    with pytest.raises(ValueError, match="n_space"):
        solve_crank_nicolson(_spec(), n_space=2, n_time=10)
    with pytest.raises(ValueError, match="n_time"):
        solve_crank_nicolson(_spec(), n_space=10, n_time=0)


def test_spot_outside_domain_rejected() -> None:
    solution = solve_crank_nicolson(_spec(), n_space=50, n_time=50)
    with pytest.raises(ValueError, match="outside"):
        solution.price_at(-1.0)
    with pytest.raises(ValueError, match="outside"):
        solution.price_at(solution.spec.s_max + 1.0)


def test_prices_at_t0_are_finite_and_non_negative_for_a_call() -> None:
    solution = solve_crank_nicolson(_spec("call"), n_space=200, n_time=200)
    assert np.all(np.isfinite(solution.prices_at_t0))
    assert np.all(solution.prices_at_t0 >= -1e-8)
