"""VAL-01: "define golden analytical test suite for GBM and
Black-Scholes... CI matches known reference values."

Deliberately NOT testing anything new -- `black_scholes_price` and
`stochastica.gbm` are already extensively tested elsewhere in this
repository, for other reasons. This file exists to consolidate and
explicitly LABEL a small, dedicated "golden" suite: every expected value
below is either a widely-cited, independently-verifiable reference (the
classic S=100/K=100/r=5%/sigma=20%/T=1 Black-Scholes textbook example)
or an EXACT closed-form algebraic identity (put-call parity; GBM's
driftless martingale property; GBM's degenerate zero-volatility limit),
computed here via a SEPARATE code path from the production formula
(`scipy.stats.norm.cdf` and `math.exp` called directly, not through
`black_scholes._d1_d2` or `gbm.terminal_moments`) rather than merely
re-asserting the same formula against itself. This runs under this
project's existing CI (`.github/workflows/ci.yml`, every push/PR, 4
Python versions), satisfying the literal "CI matches known reference
values" clause.

An earlier attempt elsewhere in this project's history incorrectly
tagged VAL-01 onto unrelated forecasting work (see `CHECKLIST_STATUS.md`
PR-056's own account of that misattribution, caught and corrected before
being committed anywhere permanent) -- this file is the first time VAL-01
is claimed for what it actually, literally names: GBM and Black-Scholes.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest
from scipy.stats import norm

from prometheus.stochastica.gbm import simulate_gbm_paths, terminal_moments
from prometheus.volterra.black_scholes import black_scholes_price, put_call_parity_residual
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def test_black_scholes_call_matches_the_classic_textbook_reference_value() -> None:
    """S=100, K=100, r=5%, sigma=20%, T=1 -- the single most widely cited
    Black-Scholes worked example in finance textbooks and online
    calculators, independently re-derived here via a direct N(d1)/N(d2)
    computation rather than calling this project's own `_d1_d2` helper."""
    s, k, r, sigma, t = 100.0, 100.0, 0.05, 0.2, 1.0
    d1 = (math.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    expected_call = s * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)
    assert expected_call == pytest.approx(10.450583572185565, abs=1e-9)

    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=s, risk_free_rate=r, volatility=sigma)
    price = black_scholes_price(market, EuropeanOption(k, t, "call"))
    assert price == pytest.approx(expected_call, abs=1e-9)


def test_black_scholes_put_matches_the_same_reference_parameters() -> None:
    """Same (S, K, r, sigma, T) as the call above; the put's own
    independently re-derived N(-d1)/N(-d2) value."""
    s, k, r, sigma, t = 100.0, 100.0, 0.05, 0.2, 1.0
    d1 = (math.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    expected_put = k * math.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1)
    assert expected_put == pytest.approx(5.573526022256971, abs=1e-9)

    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=s, risk_free_rate=r, volatility=sigma)
    price = black_scholes_price(market, EuropeanOption(k, t, "put"))
    assert price == pytest.approx(expected_put, abs=1e-9)


def test_put_call_parity_holds_exactly_at_the_golden_parameters() -> None:
    """Call - Put = S - K*exp(-rT) is an EXACT algebraic identity (no
    tolerance needed beyond floating-point rounding), independent of
    this project's own pricer -- a stronger check than matching one
    hardcoded number, since it must hold for ANY correct implementation."""
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2)
    residual = put_call_parity_residual(market, strike=100.0, maturity=1.0)
    assert residual == pytest.approx(0.0, abs=1e-9)


def test_gbm_driftless_terminal_mean_is_exactly_s0() -> None:
    """E[S_T] = S0*exp(mu*T); at mu=0 this is EXACTLY S0 for any sigma or
    T, a zero-free-parameter algebraic identity (the driftless-GBM
    martingale property), not an approximation to check within a
    tolerance band."""
    for sigma, maturity in [(0.1, 1.0), (0.5, 5.0), (1.0, 10.0)]:
        mean, _ = terminal_moments(s0=100.0, mu=0.0, sigma=sigma, maturity=maturity)
        assert mean == pytest.approx(100.0, abs=1e-9)


def test_gbm_terminal_variance_matches_an_independently_computed_value() -> None:
    """s0=100, mu=0, sigma=0.3, T=1: Var(S_T) = s0^2*(exp(sigma^2*T)-1),
    computed here via `math.exp` directly rather than calling
    `terminal_moments` to produce the expected value (that would just
    re-assert the formula against itself)."""
    expected_variance = 100.0**2 * (math.exp(0.3**2 * 1.0) - 1.0)
    assert expected_variance == pytest.approx(941.7428370521042, abs=1e-6)

    _, variance = terminal_moments(s0=100.0, mu=0.0, sigma=0.3, maturity=1.0)
    assert variance == pytest.approx(expected_variance, abs=1e-9)


def test_gbm_zero_volatility_path_matches_the_exact_deterministic_value() -> None:
    """At sigma=0, S_T = S0*exp(mu*T) EXACTLY, with zero sampling noise
    (every path is bit-for-bit identical) -- the only point in GBM's
    parameter space where a SIMULATED path can be checked against a
    golden value with no statistical tolerance at all."""
    rng = np.random.default_rng(0)
    s0, mu, maturity = 100.0, 0.08, 5.0
    paths = simulate_gbm_paths(s0, mu, 0.0, maturity, n_steps=4, n_paths=10, rng=rng)
    expected_terminal = s0 * math.exp(mu * maturity)
    assert expected_terminal == pytest.approx(149.18246976412703, abs=1e-9)
    assert paths[:, -1].tolist() == pytest.approx([expected_terminal] * 10, abs=1e-9)
