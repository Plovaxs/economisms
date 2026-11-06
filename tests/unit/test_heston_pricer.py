import cmath
import math
from datetime import date

import numpy as np
import pytest
from scipy import integrate
from scipy.stats import norm

from prometheus.stochastica.heston import HestonParams, simulate_heston_paths
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.heston_pricer import (
    heston_call_price,
    heston_characteristic_function,
    heston_option_price,
    heston_risk_neutral_probabilities,
)
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _params(**overrides: float) -> HestonParams:
    defaults: dict = dict(mu=0.03, kappa=1.5, theta=0.04, xi=0.3, rho=-0.6, v0=0.045)
    defaults.update(overrides)
    return HestonParams(**defaults)


def test_characteristic_function_at_zero_is_one() -> None:
    p = _params()
    phi0 = heston_characteristic_function(0.0, 100.0, 1.0, 0.03, 0.0, p)
    assert phi0 == pytest.approx(1.0 + 0.0j, abs=1e-10)


def test_characteristic_function_at_negative_i_equals_forward_price() -> None:
    """phi(-i) = E[exp(i*(-i)*ln(S_T))] = E[S_T] = S0*exp((r-q)*T) -- an
    exact algebraic identity any correct characteristic function must
    satisfy, independent of the integration machinery below it."""
    p = _params()
    s0, t, r, q = 100.0, 1.0, 0.03, 0.01
    phi_neg_i = heston_characteristic_function(-1j, s0, t, r, q, p)
    expected = s0 * math.exp((r - q) * t)
    assert phi_neg_i == pytest.approx(expected + 0.0j, abs=1e-6)


@pytest.mark.parametrize("strike", [60.0, 80.0, 100.0, 120.0, 160.0])
def test_risk_neutral_probabilities_are_in_unit_interval(strike: float) -> None:
    """P2 = Q(S_T > K) is a genuine probability, not merely a number that
    happens to produce a plausible-looking price."""
    p = _params()
    p1, p2 = heston_risk_neutral_probabilities(100.0, strike, 1.0, 0.03, 0.0, p)
    assert 0.0 <= p1 <= 1.0
    assert 0.0 <= p2 <= 1.0


def test_rejects_non_positive_s0_strike_or_maturity() -> None:
    p = _params()
    with pytest.raises(ValueError):
        heston_call_price(0.0, 100.0, 1.0, 0.03, 0.0, p)
    with pytest.raises(ValueError):
        heston_call_price(100.0, -1.0, 1.0, 0.03, 0.0, p)
    with pytest.raises(ValueError):
        heston_call_price(100.0, 100.0, 0.0, 0.03, 0.0, p)


def test_put_call_parity_against_an_independently_mirrored_put_formula() -> None:
    """heston_option_price derives its put price from the call via
    put-call parity (a shortcut, by design -- see the module docstring).
    This test does NOT use that shortcut: it computes the put price
    through a SEPARATE, independently-written P1'/P2' integral (the
    mirror image of the call's own decomposition) and confirms the two
    routes agree -- real cross-validation, not a tautology against the
    production code's own definition."""
    p = _params()
    s0, k, t, r, q = 100.0, 95.0, 0.75, 0.03, 0.01
    call = heston_call_price(s0, k, t, r, q, p)

    log_k = math.log(k)

    def integrand_p2(u: float) -> float:
        phi = heston_characteristic_function(u, s0, t, r, q, p)
        value = cmath.exp(-1j * u * log_k) * phi / (1j * u)
        return float(value.real)

    def integrand_p1(u: float) -> float:
        phi_shifted = heston_characteristic_function(u - 1j, s0, t, r, q, p)
        phi_neg_i = heston_characteristic_function(-1j, s0, t, r, q, p)
        value = cmath.exp(-1j * u * log_k) * phi_shifted / (1j * u * phi_neg_i)
        return float(value.real)

    p2_integral, _ = integrate.quad(integrand_p2, 1e-10, np.inf, limit=200)
    p1_integral, _ = integrate.quad(integrand_p1, 1e-10, np.inf, limit=200)
    p2 = 0.5 + p2_integral / math.pi
    p1 = 0.5 + p1_integral / math.pi
    independent_put = k * math.exp(-r * t) * (1 - p2) - s0 * math.exp(-q * t) * (1 - p1)

    market = _market(spot=s0, risk_free_rate=r, dividend_yield=q)
    option_put = heston_option_price(market, EuropeanOption(k, t, "put"), p)
    assert option_put == pytest.approx(independent_put, abs=1e-8)

    forward_value = s0 * math.exp(-q * t) - k * math.exp(-r * t)
    assert (call - independent_put) == pytest.approx(forward_value, abs=1e-8)


def test_converges_to_black_scholes_in_the_zero_vol_of_vol_limit() -> None:
    """With vol-of-vol near zero and v0 == theta == sigma^2, the variance
    process is (almost) deterministically constant at sigma^2, and Heston
    must collapse to the existing closed-form Black-Scholes price."""
    sigma_bs = 0.2
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=sigma_bs)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    bs_price = black_scholes_price(market, option)

    p = _params(kappa=3.0, theta=sigma_bs**2, xi=1e-4, rho=0.0, v0=sigma_bs**2)
    heston_price = heston_option_price(market, option, p)
    assert heston_price == pytest.approx(bs_price, abs=1e-3)


def test_matches_black_scholes_put_in_the_zero_vol_of_vol_limit_too() -> None:
    sigma_bs = 0.25
    market = _market(spot=90.0, risk_free_rate=0.02, dividend_yield=0.01, volatility=sigma_bs)
    option = EuropeanOption(strike=100.0, maturity=0.5, option_type="put")
    bs_price = black_scholes_price(market, option)

    p = _params(kappa=4.0, theta=sigma_bs**2, xi=1e-4, rho=0.0, v0=sigma_bs**2)
    heston_price = heston_option_price(market, option, p)
    assert heston_price == pytest.approx(bs_price, abs=1e-3)


def test_matches_monte_carlo_simulation() -> None:
    """Agreement with an INDEPENDENTLY written module
    (stochastica.heston.simulate_heston_paths, not derived from this
    pricer) is the strongest available check here, short of an external
    published reference table."""
    p = _params()
    s0, t, r, q, k = 100.0, 1.0, 0.03, 0.0, 100.0
    fourier_price = heston_call_price(s0, k, t, r, q, p)

    rng = np.random.default_rng(99)
    n_paths, n_steps = 200_000, 200
    paths, _ = simulate_heston_paths(s0, p, t, n_steps, n_paths, rng)
    terminal = paths[:, -1]
    payoffs = np.maximum(terminal - k, 0.0)
    mc_price = math.exp(-r * t) * payoffs.mean()
    mc_stderr = math.exp(-r * t) * payoffs.std(ddof=1) / math.sqrt(n_paths)

    assert abs(fourier_price - mc_price) < 4 * mc_stderr


def test_market_volatility_field_is_ignored_in_favor_of_heston_params() -> None:
    """Documented, deliberate behavior (see the module docstring): the
    variance process comes entirely from `params`, not `market.volatility`.
    Two markets differing ONLY in `.volatility` must price identically."""
    p = _params()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    price_a = heston_option_price(_market(volatility=0.1), option, p)
    price_b = heston_option_price(_market(volatility=0.9), option, p)
    assert price_a == price_b


def test_price_increases_with_initial_variance() -> None:
    """A basic monotonicity sanity check: all else equal, more initial
    variance means a more valuable call option (higher expected upside
    variability), independent of the exact pricing machinery."""
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    market = _market()
    low_variance_price = heston_option_price(market, option, _params(v0=0.01, theta=0.01))
    high_variance_price = heston_option_price(market, option, _params(v0=0.09, theta=0.09))
    assert high_variance_price > low_variance_price


def test_european_call_price_matches_norm_cdf_based_black_scholes_reference() -> None:
    """A second, from-scratch Black-Scholes computation (not calling
    volterra.black_scholes at all) in the degenerate limit, so this
    module's correctness does not implicitly depend on that sibling
    module also being correct."""
    sigma_bs = 0.3
    s0, k, t, r, q = 120.0, 110.0, 2.0, 0.015, 0.0
    d1 = (math.log(s0 / k) + (r - q + 0.5 * sigma_bs**2) * t) / (sigma_bs * math.sqrt(t))
    d2 = d1 - sigma_bs * math.sqrt(t)
    bs_call = s0 * math.exp(-q * t) * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)

    p = _params(kappa=2.5, theta=sigma_bs**2, xi=1e-4, rho=0.0, v0=sigma_bs**2)
    heston_call = heston_call_price(s0, k, t, r, q, p)
    assert heston_call == pytest.approx(bs_call, abs=1e-3)


def test_characteristic_function_at_negative_i_is_exact_when_kappa_equals_rho_times_xi() -> None:
    """SDE-12 regression guard: at u=-i, `iu + u**2` is identically 0 for
    ANY parameters, so `d = sqrt(b**2) == |b|`; whenever kappa == rho*xi
    exactly, `b` is ALSO exactly 0, making both `b+d` and `b-d` exactly
    0 -- a genuine removable 0/0 singularity in the `g = (b-d)/(b+d)`
    formulation that used to raise `ZeroDivisionError`. `HestonParams`
    does not reject kappa == rho*xi (nothing makes it implausible), and
    this exact value is hit directly (not merely approached) by
    `heston_risk_neutral_probabilities`' own `phi_neg_i` normalizing
    constant, so this is a reachable crash, not a theoretical one."""
    p = _params(kappa=0.5, xi=1.0, rho=0.5, theta=1.0, v0=1.0)
    assert p.kappa == pytest.approx(p.rho * p.xi)
    s0, t, r, q = 100.0, 1.0, 0.03, 0.01
    phi_neg_i = heston_characteristic_function(-1j, s0, t, r, q, p)
    expected = s0 * math.exp((r - q) * t)
    assert phi_neg_i == pytest.approx(expected + 0.0j, abs=1e-6)
    price = heston_call_price(s0, 100.0, t, r, q, p)
    assert math.isfinite(price)
    assert price > 0.0


def test_very_negative_rate_with_long_maturity_raises_a_clear_error_not_an_overflow_crash() -> None:
    """SDE-12 regression guard: the strike leg's plain discount factor
    `math.exp(-r*maturity)` overflows unconditionally here, the same
    class of bug already fixed in `volterra.black_scholes`."""
    p = _params()
    with pytest.raises(ValueError, match="represent"):
        heston_call_price(1.0, 1.0, 142.0, -5.0, 0.0, p)


def test_phi_neg_i_identity_rejects_an_unrepresentable_forward() -> None:
    """SDE-12 regression guard: `(risk_free_rate - dividend_yield) *
    maturity` alone can push the phi(-i) identity shortcut's own
    exponential past float64's range."""
    p = _params()
    with pytest.raises(ValueError, match="represent"):
        heston_characteristic_function(-1j, 1.0, 142.0, 5.0, 0.0, p)


def test_long_maturity_numerical_instability_raises_a_clear_error_not_a_bare_crash() -> None:
    """SDE-12 regression guard: at a long enough maturity, the adaptive
    quadrature probes large real u where the little-trap formula's `c`/
    `cap_d` terms suffer catastrophic cancellation (an OverflowError or
    ZeroDivisionError deep inside scipy's quad), even though the TRUE
    characteristic function satisfies |phi(u)| <= 1 for every real u.
    That escaping exception is now converted to a clear, named
    ValueError rather than crashing with a cryptic traceback."""
    p = _params(kappa=1.0, theta=1.0, xi=1.0, rho=0.0, v0=1.0)
    with pytest.raises(ValueError, match="numerically unstable"):
        heston_call_price(1.0, 1.0, 145.0, -5.0, 0.0, p)
