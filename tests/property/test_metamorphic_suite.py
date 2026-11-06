"""VAL-11: "perform property-based and metamorphic test suites...
scaling, parity, relabeling and zero-shock tests documented."

A metamorphic test does not check a result against a known reference
value (that is `tests/unit/test_golden_reference_values.py`'s job,
VAL-01); it checks that a KNOWN RELATIONSHIP between two inputs holds
for whatever the underlying function computes, for a wide
(Hypothesis-generated, not hand-picked) range of inputs. The four named
here are each a genuinely different kind of relationship:

  - SCALING: aggregating `titan.portfolio_greeks`' per-line Greeks is
    linear in `quantity` -- doubling every line's quantity must exactly
    double the portfolio total, since `LineGreeks.scaled` is
    `quantity * per_unit` and aggregation is a plain sum.
  - PARITY: Call - Put = S*exp(-qT) - K*exp(-rT) is a model-independent
    algebraic identity that must hold EXACTLY (to floating-point
    rounding) for Black-Scholes, Heston and Merton alike, across a wide
    admissible parameter range -- not just the few hand-picked cases
    each pricer's own unit tests already check.
  - RELABELING: aggregating the SAME set of portfolio lines in a
    DIFFERENT order must produce the SAME total (summation is
    commutative); likewise for `stress_scenario_loss_from_asset_shock`
    under a consistent permutation of asset weights and their shocks.
  - ZERO-SHOCK: a stress scenario with an all-zero shock vector must
    produce EXACTLY zero loss (the dot product of any exposure with the
    zero vector is zero) -- for both the factor-shock and asset-shock
    paths in `titan.stress_testing`.
"""

from __future__ import annotations

import math
import random
from datetime import date

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.stochastica.heston import HestonParams
from prometheus.stochastica.jump_diffusion import MertonJumpParams
from prometheus.titan.portfolio_greeks import LineGreeks, aggregate_portfolio_greeks
from prometheus.titan.stress_testing import (
    stress_scenario_loss_from_asset_shock,
    stress_scenario_loss_from_factor_shock,
)
from prometheus.volterra.black_scholes import Greeks, black_scholes_price
from prometheus.volterra.heston_pricer import heston_option_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.merton_pricer import merton_option_price

_SUPPRESS = settings(max_examples=100, deadline=None)

_greeks_values = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False)
_quantities = st.floats(
    min_value=-1_000.0, max_value=1_000.0, allow_nan=False, allow_infinity=False
).filter(lambda q: abs(q) > 1e-6)
_scale_factors = st.floats(min_value=-5.0, max_value=5.0, allow_nan=False).filter(
    lambda k: abs(k) > 1e-6
)


@st.composite
def greeks_values(draw: st.DrawFn) -> Greeks:
    return Greeks(
        delta=draw(_greeks_values),
        gamma=draw(_greeks_values),
        vega=draw(_greeks_values),
        theta=draw(_greeks_values),
        rho=draw(_greeks_values),
    )


@st.composite
def line_portfolios(draw: st.DrawFn) -> list[LineGreeks]:
    n_lines = draw(st.integers(min_value=1, max_value=10))
    return [
        LineGreeks(position_id=f"P{i}", quantity=draw(_quantities), per_unit=draw(greeks_values()))
        for i in range(n_lines)
    ]


@given(lines=line_portfolios(), k=_scale_factors)
@_SUPPRESS
def test_scaling_every_quantity_by_k_scales_the_portfolio_total_by_k(lines, k):
    base_total = aggregate_portfolio_greeks(lines, date(2026, 1, 1)).total
    scaled_lines = [
        LineGreeks(position_id=line.position_id, quantity=line.quantity * k, per_unit=line.per_unit)
        for line in lines
    ]
    scaled_total = aggregate_portfolio_greeks(scaled_lines, date(2026, 1, 1)).total
    for field in ("delta", "gamma", "vega", "theta", "rho"):
        assert getattr(scaled_total, field) == pytest.approx(
            k * getattr(base_total, field), abs=1e-6, rel=1e-9
        )


@given(lines=line_portfolios())
@_SUPPRESS
def test_relabeling_portfolio_line_order_does_not_change_the_total(lines):
    base_total = aggregate_portfolio_greeks(lines, date(2026, 1, 1)).total
    shuffled = lines[:]
    random.Random(0).shuffle(shuffled)
    shuffled_total = aggregate_portfolio_greeks(shuffled, date(2026, 1, 1)).total
    for field in ("delta", "gamma", "vega", "theta", "rho"):
        assert getattr(shuffled_total, field) == pytest.approx(
            getattr(base_total, field), abs=1e-9, rel=1e-9
        )


@given(
    n_assets=st.integers(min_value=1, max_value=8),
    n_factors=st.integers(min_value=1, max_value=4),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@_SUPPRESS
def test_zero_factor_shock_produces_exactly_zero_loss(n_assets, n_factors, seed):
    rng = np.random.default_rng(seed)
    weights = rng.normal(size=n_assets)
    betas = rng.normal(size=(n_assets, n_factors))
    zero_shocks = np.zeros(n_factors)
    assert stress_scenario_loss_from_factor_shock(weights, betas, zero_shocks) == 0.0


@given(
    n_assets=st.integers(min_value=1, max_value=8),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@_SUPPRESS
def test_zero_asset_shock_produces_exactly_zero_loss(n_assets, seed):
    rng = np.random.default_rng(seed)
    weights = rng.normal(size=n_assets)
    zero_shocks = np.zeros(n_assets)
    assert stress_scenario_loss_from_asset_shock(weights, zero_shocks) == 0.0


@given(
    n_assets=st.integers(min_value=2, max_value=8),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@_SUPPRESS
def test_relabeling_asset_order_does_not_change_the_asset_shock_loss(n_assets, seed):
    rng = np.random.default_rng(seed)
    weights = rng.normal(size=n_assets)
    shocks = rng.normal(size=n_assets)
    base_loss = stress_scenario_loss_from_asset_shock(weights, shocks)

    permutation = rng.permutation(n_assets)
    permuted_loss = stress_scenario_loss_from_asset_shock(weights[permutation], shocks[permutation])
    assert permuted_loss == pytest.approx(base_loss, abs=1e-9, rel=1e-9)


_parity_spots = st.floats(min_value=1.0, max_value=1000.0, allow_nan=False)
_parity_strikes = st.floats(min_value=1.0, max_value=1000.0, allow_nan=False)
_parity_maturities = st.floats(min_value=0.01, max_value=5.0, allow_nan=False)
_parity_rates = st.floats(min_value=-0.1, max_value=0.2, allow_nan=False)
_parity_vols = st.floats(min_value=0.01, max_value=2.0, allow_nan=False)


@given(
    spot=_parity_spots,
    strike=_parity_strikes,
    maturity=_parity_maturities,
    rate=_parity_rates,
    vol=_parity_vols,
)
@_SUPPRESS
def test_black_scholes_put_call_parity_holds_across_a_wide_parameter_range(
    spot, strike, maturity, rate, vol
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=vol)
    call = black_scholes_price(market, EuropeanOption(strike, maturity, "call"))
    put = black_scholes_price(market, EuropeanOption(strike, maturity, "put"))
    forward_value = spot - strike * math.exp(-rate * maturity)
    assert (call - put) == pytest.approx(forward_value, abs=1e-6, rel=1e-9)


@given(
    spot=_parity_spots,
    strike=_parity_strikes,
    maturity=_parity_maturities,
    rate=_parity_rates,
    kappa=st.floats(min_value=0.1, max_value=5.0, allow_nan=False),
    xi=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
    rho=st.floats(min_value=-0.9, max_value=0.9, allow_nan=False),
    v0=st.floats(min_value=0.01, max_value=0.5, allow_nan=False),
)
@_SUPPRESS
def test_heston_put_call_parity_holds_across_a_wide_parameter_range(
    spot, strike, maturity, rate, kappa, xi, rho, v0
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=0.2)
    params = HestonParams(mu=rate, kappa=kappa, theta=v0, xi=xi, rho=rho, v0=v0)
    call = heston_option_price(market, EuropeanOption(strike, maturity, "call"), params)
    put = heston_option_price(market, EuropeanOption(strike, maturity, "put"), params)
    forward_value = spot - strike * math.exp(-rate * maturity)
    assert (call - put) == pytest.approx(forward_value, abs=1e-4, rel=1e-6)


@given(
    spot=_parity_spots,
    strike=_parity_strikes,
    maturity=_parity_maturities,
    rate=_parity_rates,
    sigma=st.floats(min_value=0.01, max_value=1.0, allow_nan=False),
    jump_intensity=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
    jump_mean=st.floats(min_value=-0.3, max_value=0.3, allow_nan=False),
    jump_std=st.floats(min_value=0.0, max_value=0.5, allow_nan=False),
)
@_SUPPRESS
def test_merton_put_call_parity_holds_across_a_wide_parameter_range(
    spot, strike, maturity, rate, sigma, jump_intensity, jump_mean, jump_std
):
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=spot, risk_free_rate=rate, volatility=0.2)
    params = MertonJumpParams(
        mu=rate, sigma=sigma, jump_intensity=jump_intensity, jump_mean=jump_mean, jump_std=jump_std
    )
    call = merton_option_price(market, EuropeanOption(strike, maturity, "call"), params)
    put = merton_option_price(market, EuropeanOption(strike, maturity, "put"), params)
    forward_value = spot - strike * math.exp(-rate * maturity)
    assert (call - put) == pytest.approx(forward_value, abs=1e-4, rel=1e-6)
