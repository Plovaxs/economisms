import math
from datetime import date

import numpy as np
import pytest
from scipy.stats import norm

from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.volterra.asian_options import (
    AsianOption,
    geometric_asian_call_price,
    geometric_asian_option_price,
    geometric_average_forward,
    monte_carlo_price_asian,
)
from prometheus.volterra.market import MarketSnapshot


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.25)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _option(**overrides: object) -> AsianOption:
    defaults: dict = dict(
        strike=100.0, maturity=1.0, option_type="call", n_fixings=12, average_type="geometric"
    )
    defaults.update(overrides)
    return AsianOption(**defaults)  # type: ignore[arg-type]


def test_asian_option_rejects_invalid_fields() -> None:
    with pytest.raises(ValueError):
        _option(strike=-1.0)
    with pytest.raises(ValueError):
        _option(maturity=0.0)
    with pytest.raises(ValueError):
        _option(option_type="x")
    with pytest.raises(ValueError):
        _option(n_fixings=0)
    with pytest.raises(ValueError):
        _option(average_type="harmonic")


def test_asian_option_rejects_nan_and_inf_fields() -> None:
    """VAL-13 ("perform NaN/Inf injection and solver fail-closed
    tests... no invalid output promoted or silently cached"): an
    ordinary `if strike <= 0: raise` silently admits NaN (every
    comparison involving NaN is False under IEEE754)."""
    with pytest.raises(ValueError, match="finite"):
        _option(strike=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        _option(maturity=float("inf"))


def test_geometric_closed_form_rejects_non_positive_inputs() -> None:
    with pytest.raises(ValueError):
        geometric_asian_call_price(0.0, 100.0, 1.0, 0.03, 0.0, 0.25, 12)
    with pytest.raises(ValueError):
        geometric_asian_call_price(100.0, -1.0, 1.0, 0.03, 0.0, 0.25, 12)
    with pytest.raises(ValueError):
        geometric_asian_call_price(100.0, 100.0, 0.0, 0.03, 0.0, 0.25, 12)
    with pytest.raises(ValueError):
        geometric_asian_call_price(100.0, 100.0, 1.0, 0.03, 0.0, 0.25, 0)
    with pytest.raises(ValueError):
        geometric_average_forward(-1.0, 1.0, 0.03, 0.0, 0.25, 12)
    with pytest.raises(ValueError):
        geometric_average_forward(100.0, 0.0, 0.03, 0.0, 0.25, 12)
    with pytest.raises(ValueError):
        geometric_average_forward(100.0, 1.0, 0.03, 0.0, 0.25, 0)


@pytest.mark.parametrize(
    "s0,k,t,r,q,sigma,n",
    [
        (100.0, 100.0, 1.0, 0.03, 0.0, 0.25, 12),
        (100.0, 110.0, 1.0, 0.03, 0.01, 0.3, 50),
        (100.0, 90.0, 0.5, 0.02, 0.0, 0.4, 4),
    ],
)
def test_geometric_closed_form_matches_independent_monte_carlo(s0, k, t, r, q, sigma, n) -> None:
    """Cross-checks against the independently-written `stochastica.gbm`
    path simulator (fixing values taken directly from its own output
    columns, not re-derived from this module's formula)."""
    closed = geometric_asian_call_price(s0, k, t, r, q, sigma, n)
    rng = np.random.default_rng(7)
    n_paths = 500_000
    paths = simulate_gbm_paths(s0, r - q, sigma, t, n, n_paths, rng)
    fixings = paths[:, 1:]
    geo_mean = np.exp(np.mean(np.log(fixings), axis=1))
    payoff = math.exp(-r * t) * np.maximum(geo_mean - k, 0.0)
    mc_price = float(payoff.mean())
    mc_se = float(payoff.std(ddof=1) / math.sqrt(n_paths))
    assert abs(closed - mc_price) < 5 * mc_se


def test_geometric_closed_form_matches_brute_force_covariance_sum() -> None:
    """Re-derives Var(mean of W_{t_i}) by literally summing
    sum_{i,j} min(t_i, t_j) over all pairs -- not using the n(n+1)(2n+1)/6
    shortcut identity this module's formula relies on -- confirming that
    identity rather than assuming it."""
    s0, k, t, r, q, sigma, n = 100.0, 105.0, 1.0, 0.03, 0.005, 0.3, 17
    dt = t / n
    times = [(i + 1) * dt for i in range(n)]
    cov_sum = sum(min(ti, tj) for ti in times for tj in times)
    var_w_mean_brute = cov_sum / n**2
    mean_t_brute = sum(times) / n

    nu = r - q - 0.5 * sigma**2
    mu_g = math.log(s0) + nu * mean_t_brute
    var_g = sigma**2 * var_w_mean_brute
    forward_g = math.exp(mu_g + 0.5 * var_g)
    d1 = (mu_g + var_g - math.log(k)) / math.sqrt(var_g)
    d2 = d1 - math.sqrt(var_g)
    brute_force_price = math.exp(-r * t) * (forward_g * norm.cdf(d1) - k * norm.cdf(d2))

    production_price = geometric_asian_call_price(s0, k, t, r, q, sigma, n)
    assert production_price == pytest.approx(brute_force_price, abs=1e-10)


def test_geometric_put_call_parity_against_the_geometric_forward() -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.015, volatility=0.3)
    call_option = _option(strike=95.0, option_type="call", n_fixings=20)
    put_option = _option(strike=95.0, option_type="put", n_fixings=20)
    call = geometric_asian_option_price(market, call_option)
    put = geometric_asian_option_price(market, put_option)
    forward_g = geometric_average_forward(
        market.spot, 1.0, market.risk_free_rate, market.dividend_yield, market.volatility, 20
    )
    expected = math.exp(-market.risk_free_rate * 1.0) * (forward_g - 95.0)
    assert (call - put) == pytest.approx(expected, abs=1e-9)


def test_zero_volatility_limit_matches_deterministic_geometric_average_of_forwards() -> None:
    s0, k, t, r, q, sigma, n = 100.0, 95.0, 1.0, 0.03, 0.0, 1e-8, 10
    dt = t / n
    forwards = [s0 * math.exp((r - q) * (i + 1) * dt) for i in range(n)]
    geo_mean_forward = math.exp(sum(math.log(f) for f in forwards) / n)
    expected = math.exp(-r * t) * max(geo_mean_forward - k, 0.0)
    price = geometric_asian_call_price(s0, k, t, r, q, sigma, n)
    assert price == pytest.approx(expected, abs=1e-4)


def test_monte_carlo_geometric_matches_closed_form() -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=0.3)
    option = _option(strike=100.0, n_fixings=12, average_type="geometric")
    closed = geometric_asian_option_price(market, option)
    rng = np.random.default_rng(11)
    result = monte_carlo_price_asian(market, option, n_paths=400_000, rng=rng)
    assert result.control_variate_used is False
    assert abs(result.price - closed) < 5 * result.standard_error


def test_monte_carlo_arithmetic_control_variate_reduces_variance() -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=0.3)
    option = _option(strike=100.0, option_type="call", n_fixings=12, average_type="arithmetic")

    rng_plain = np.random.default_rng(21)
    plain = monte_carlo_price_asian(
        market, option, n_paths=200_000, rng=rng_plain, use_control_variate=False
    )
    assert plain.control_variate_used is False

    rng_cv = np.random.default_rng(21)
    cv = monte_carlo_price_asian(
        market, option, n_paths=200_000, rng=rng_cv, use_control_variate=True
    )
    assert cv.control_variate_used is True

    assert abs(plain.price - cv.price) < 5 * plain.standard_error
    assert cv.standard_error < plain.standard_error / 5.0


def test_arithmetic_price_is_at_least_geometric_price() -> None:
    """AM-GM: the arithmetic mean of any positive fixings is >= their
    geometric mean path-by-path, so an arithmetic-average call must be
    worth at least as much as the geometric-average call with otherwise
    identical terms, and never less."""
    market = _market(spot=100.0, risk_free_rate=0.02, dividend_yield=0.0, volatility=0.35)
    geo_option = _option(strike=100.0, option_type="call", n_fixings=20, average_type="geometric")
    arith_option = _option(
        strike=100.0, option_type="call", n_fixings=20, average_type="arithmetic"
    )

    geo_price = geometric_asian_option_price(market, geo_option)
    rng = np.random.default_rng(31)
    arith_result = monte_carlo_price_asian(market, arith_option, n_paths=300_000, rng=rng)

    assert arith_result.price >= geo_price - 5 * arith_result.standard_error


def test_monte_carlo_arithmetic_put_prices_are_sane() -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=0.3)
    call_option = _option(strike=100.0, option_type="call", n_fixings=12, average_type="arithmetic")
    put_option = _option(strike=100.0, option_type="put", n_fixings=12, average_type="arithmetic")

    rng_call = np.random.default_rng(41)
    rng_put = np.random.default_rng(41)
    call_result = monte_carlo_price_asian(market, call_option, n_paths=300_000, rng=rng_call)
    put_result = monte_carlo_price_asian(market, put_option, n_paths=300_000, rng=rng_put)

    assert call_result.price > 0
    assert put_result.price > 0


def test_negative_rate_long_maturity_call_resolves_to_zero_not_an_overflow_crash() -> None:
    """SDE-12 regression guard (see this module's docstring): the OLD code
    computed `forward_g = exp(mu_g + 0.5*log_var)` and the outer discount
    `exp(-r*maturity)` as two separate exponentials; at this input the
    strike leg's lone `exp(-r*maturity)` already overflows on its own
    before ever being combined with its (here, exactly-zero) risk-neutral
    weight. The fix combines exponents first, resolving cleanly to 0.0."""
    market = _market(risk_free_rate=-5.0, dividend_yield=0.0, volatility=1.0)
    option = _option(strike=1.0, maturity=142.0, option_type="call", n_fixings=1)
    price = geometric_asian_call_price(
        market.spot,
        option.strike,
        option.maturity,
        market.risk_free_rate,
        market.dividend_yield,
        market.volatility,
        option.n_fixings,
    )
    assert price == 0.0


def test_positive_rate_long_maturity_call_and_put_stay_finite_not_an_overflow_crash() -> None:
    """SDE-12 regression guard: the OLD code's standalone `forward_g`
    overflowed `math.exp` directly at this input (rate=5, maturity=142),
    even though the economically relevant, discounted quantity is
    representable (its exponent is exactly 0)."""
    market = _market(risk_free_rate=5.0, dividend_yield=0.0, volatility=1.0)
    call_option = _option(strike=1.0, maturity=142.0, option_type="call", n_fixings=1)
    put_option = _option(strike=1.0, maturity=142.0, option_type="put", n_fixings=1)
    call_price = geometric_asian_option_price(market, call_option)
    put_price = geometric_asian_option_price(market, put_option)
    assert math.isfinite(call_price)
    assert math.isfinite(put_price)


def test_geometric_average_forward_rejects_unrepresentable_drift() -> None:
    """SDE-12 regression guard: a clear ValueError, not a cryptic
    OverflowError, when the undiscounted forward itself (not combined
    with any offsetting discount factor) has no representable value."""
    with pytest.raises(ValueError, match="represent"):
        geometric_average_forward(1.0, 142.0, 5.0, 0.0, 1.0, 1)
