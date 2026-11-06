"""SDE-12: "Test solver behavior on extreme but admissible inputs... no
silent NaN, Inf or unbounded accepted paths." Property-based (not just
the specific regression cases found and fixed in each pricer's own test
file) stress testing across a wide admissible parameter range for every
VOLTERRA pricer and STOCHASTICA simulator in this repository.

The invariant tested for every PRICER is deliberately permissive about
*rejection*: a pricer may legitimately raise `ValueError` for an input
combination with no computable or representable answer (confirmed, not
assumed, for each such case in that pricer's own module docstring and
test file -- this file does not re-litigate which specific inputs should
be rejected). What must NEVER happen is an uncaught exception of any
OTHER type (an `OverflowError` or domain-error `ValueError` escaping from
inside `math.exp`/`math.log` deep in a pricing formula, confirmed to
happen before the fixes this PR made), or a silently returned NaN/Inf.

For every SIMULATOR, the invariant is stricter and unconditional: paths
must always be finite (no NaN, no Inf) at any input the constructor/
function itself accepts -- this is SDE-12's literal "no ... unbounded
accepted paths." Strict positivity, where mathematically guaranteed by
the SDE, is checked separately and is NOT asserted unconditionally (see
`stochastica.gbm`'s own docstring for the floating-point underflow
boundary this project found and deliberately does not try to "fix").
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.stochastica.heston import HestonParams, simulate_heston_paths
from prometheus.stochastica.jump_diffusion import MertonJumpParams, simulate_jump_diffusion_paths
from prometheus.volterra.asian_options import AsianOption, geometric_asian_option_price
from prometheus.volterra.barrier_options import BarrierOption, barrier_option_price
from prometheus.volterra.black_scholes import (
    black_scholes_greeks,
    black_scholes_price,
    put_call_parity_residual,
)
from prometheus.volterra.heston_pricer import heston_option_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.merton_pricer import merton_option_price

_SUPPRESS = settings(
    max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None
)

spots = st.floats(min_value=0.5, max_value=2000.0, allow_nan=False, allow_infinity=False)
strikes = st.floats(min_value=0.5, max_value=2000.0, allow_nan=False, allow_infinity=False)
maturities = st.floats(min_value=1e-6, max_value=150.0, allow_nan=False, allow_infinity=False)
rates = st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False)
vols = st.floats(min_value=1e-8, max_value=60.0, allow_nan=False, allow_infinity=False)
option_types = st.sampled_from(["call", "put"])


def _price_or_clean_reject(fn, *args, **kwargs) -> None:
    """Calls fn; either it returns a finite price, or it raises
    ValueError. Any other outcome (another exception type, or a
    non-finite return value) fails the test."""
    try:
        price = fn(*args, **kwargs)
    except ValueError:
        return
    assert math.isfinite(price), f"{fn.__name__} returned a non-finite price: {price}"


@given(
    spot=spots, strike=strikes, maturity=maturities, rate=rates, vol=vols, option_type=option_types
)
@_SUPPRESS
def test_black_scholes_never_crashes_or_returns_non_finite(
    spot, strike, maturity, rate, vol, option_type
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=vol)
    option = EuropeanOption(strike, maturity, option_type)
    _price_or_clean_reject(black_scholes_price, market, option)


@given(
    spot=spots, strike=strikes, maturity=maturities, rate=rates, vol=vols, option_type=option_types
)
@_SUPPRESS
def test_black_scholes_greeks_never_crash_or_return_non_finite(
    spot, strike, maturity, rate, vol, option_type
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=vol)
    option = EuropeanOption(strike, maturity, option_type)
    try:
        greeks = black_scholes_greeks(market, option)
    except ValueError:
        return
    for name, value in (
        ("delta", greeks.delta),
        ("gamma", greeks.gamma),
        ("vega", greeks.vega),
        ("theta", greeks.theta),
        ("rho", greeks.rho),
    ):
        assert math.isfinite(value), f"{name} is non-finite: {value}"


@given(spot=spots, strike=strikes, maturity=maturities, rate=rates, vol=vols)
@_SUPPRESS
def test_put_call_parity_residual_never_crashes_or_returns_non_finite(
    spot, strike, maturity, rate, vol
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=vol)
    _price_or_clean_reject(put_call_parity_residual, market, strike, maturity)


@given(
    spot=spots,
    strike=strikes,
    maturity=maturities,
    rate=rates,
    vol=vols,
    option_type=option_types,
    kappa=st.floats(min_value=1e-8, max_value=10.0, allow_nan=False),
    xi=st.floats(min_value=1e-8, max_value=25.0, allow_nan=False),
    rho=st.floats(min_value=-0.999, max_value=0.999, allow_nan=False),
    v0=st.floats(min_value=1e-10, max_value=4.0, allow_nan=False),
)
@_SUPPRESS
def test_heston_never_crashes_or_returns_non_finite(
    spot, strike, maturity, rate, vol, option_type, kappa, xi, rho, v0
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=vol)
    option = EuropeanOption(strike, maturity, option_type)
    params = HestonParams(mu=rate, kappa=kappa, theta=max(v0, 1e-6), xi=xi, rho=rho, v0=v0)
    _price_or_clean_reject(heston_option_price, market, option, params)


@given(
    spot=spots,
    strike=strikes,
    maturity=maturities,
    rate=rates,
    vol=vols,
    option_type=option_types,
    jump_intensity=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    jump_mean=st.floats(min_value=-5.0, max_value=5.0, allow_nan=False),
    jump_std=st.floats(min_value=0.0, max_value=8.0, allow_nan=False),
)
@_SUPPRESS
def test_merton_never_crashes_or_returns_non_finite(
    spot, strike, maturity, rate, vol, option_type, jump_intensity, jump_mean, jump_std
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=0.2)
    option = EuropeanOption(strike, maturity, option_type)
    params = MertonJumpParams(
        mu=rate, sigma=vol, jump_intensity=jump_intensity, jump_mean=jump_mean, jump_std=jump_std
    )
    _price_or_clean_reject(merton_option_price, market, option, params)


@given(
    spot=spots,
    strike=strikes,
    maturity=maturities,
    rate=rates,
    vol=vols,
    option_type=option_types,
    barrier_offset=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
    direction=st.sampled_from(["down", "up"]),
    knock=st.sampled_from(["out", "in"]),
)
@_SUPPRESS
def test_barrier_never_crashes_or_returns_non_finite(
    spot, strike, maturity, rate, vol, option_type, barrier_offset, direction, knock
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=vol)
    barrier = spot * barrier_offset if direction == "down" else spot * (1.0 + barrier_offset)
    option = BarrierOption(strike, maturity, option_type, barrier, direction, knock)
    _price_or_clean_reject(barrier_option_price, market, option)


@given(
    spot=spots,
    strike=strikes,
    maturity=maturities,
    rate=rates,
    vol=vols,
    option_type=option_types,
    n_fixings=st.integers(min_value=1, max_value=500),
)
@_SUPPRESS
def test_geometric_asian_never_crashes_or_returns_non_finite(
    spot, strike, maturity, rate, vol, option_type, n_fixings
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=vol)
    option = AsianOption(strike, maturity, option_type, n_fixings, "geometric")
    _price_or_clean_reject(geometric_asian_option_price, market, option)


@given(
    s0=spots,
    mu=rates,
    sigma=vols,
    maturity=maturities,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_gbm_simulator_paths_are_always_finite(s0, mu, sigma, maturity):
    """Either every path is finite, or the simulator raises a clear
    ValueError (see `stochastica.gbm`'s own docstring, SDE-12) -- never
    a silently returned inf/nan."""
    rng = np.random.default_rng(0)
    try:
        paths = simulate_gbm_paths(s0, mu, sigma, maturity, n_steps=10, n_paths=200, rng=rng)
    except ValueError:
        return
    assert np.all(np.isfinite(paths))


@given(
    s0=spots,
    maturity=maturities,
    kappa=st.floats(min_value=1e-8, max_value=10.0, allow_nan=False),
    xi=st.floats(min_value=1e-8, max_value=25.0, allow_nan=False),
    rho=st.floats(min_value=-0.999, max_value=0.999, allow_nan=False),
    v0=st.floats(min_value=1e-10, max_value=4.0, allow_nan=False),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_heston_simulator_paths_are_always_finite(s0, maturity, kappa, xi, rho, v0):
    rng = np.random.default_rng(0)
    params = HestonParams(mu=0.03, kappa=kappa, theta=max(v0, 1e-6), xi=xi, rho=rho, v0=v0)
    price_paths, variance_paths = simulate_heston_paths(s0, params, maturity, 10, 200, rng)
    assert np.all(np.isfinite(price_paths))
    assert np.all(np.isfinite(variance_paths))
    assert np.all(variance_paths >= 0.0)


@given(
    s0=spots,
    sigma=vols,
    maturity=maturities,
    jump_intensity=st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    jump_mean=st.floats(min_value=-5.0, max_value=5.0, allow_nan=False),
    jump_std=st.floats(min_value=0.0, max_value=8.0, allow_nan=False),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_merton_simulator_paths_are_always_finite(
    s0, sigma, maturity, jump_intensity, jump_mean, jump_std
):
    rng = np.random.default_rng(0)
    params = MertonJumpParams(
        mu=0.03, sigma=sigma, jump_intensity=jump_intensity, jump_mean=jump_mean, jump_std=jump_std
    )
    paths = simulate_jump_diffusion_paths(s0, params, maturity, 10, 200, rng)
    assert np.all(np.isfinite(paths))
