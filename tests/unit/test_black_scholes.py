import math
from datetime import date

import pytest

from prometheus.volterra.black_scholes import (
    black_scholes_greeks,
    black_scholes_price,
    put_call_parity_residual,
)
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _standard_market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def test_market_snapshot_rejects_non_q_measure() -> None:
    with pytest.raises(ValueError):
        MarketSnapshot(
            as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2, measure="P"
        )


def test_market_snapshot_rejects_non_positive_spot_or_vol() -> None:
    with pytest.raises(ValueError):
        _standard_market(spot=0.0)
    with pytest.raises(ValueError):
        _standard_market(volatility=-0.1)


def test_option_rejects_invalid_fields() -> None:
    with pytest.raises(ValueError):
        EuropeanOption(strike=0.0, maturity=1.0, option_type="call")
    with pytest.raises(ValueError):
        EuropeanOption(strike=100.0, maturity=-1.0, option_type="call")


def test_market_snapshot_and_option_reject_nan_and_inf_fields() -> None:
    """VAL-13 ("perform NaN/Inf injection and solver fail-closed
    tests... no invalid output promoted or silently cached"): an
    ordinary `if spot <= 0: raise` silently admits NaN (every
    comparison involving NaN is False under IEEE754), so before
    `require_finite` was added, `MarketSnapshot(spot=float("nan"), ...)`
    raised nothing at all and the NaN propagated silently into every
    downstream pricing formula."""
    with pytest.raises(ValueError, match="finite"):
        _standard_market(spot=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        _standard_market(risk_free_rate=float("inf"))
    with pytest.raises(ValueError, match="finite"):
        EuropeanOption(strike=float("nan"), maturity=1.0, option_type="call")
    with pytest.raises(ValueError, match="finite"):
        EuropeanOption(strike=100.0, maturity=float("inf"), option_type="call")


def test_matches_known_textbook_reference_value() -> None:
    """S=100, K=100, r=5%, sigma=20%, T=1, no dividends -- a standard
    textbook example with a well-known call price near 10.4506."""
    market = _standard_market()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    price = black_scholes_price(market, option)
    assert price == pytest.approx(10.450583572185565, abs=1e-9)


def test_put_call_parity_holds_to_floating_point_precision() -> None:
    market = _standard_market(dividend_yield=0.01)
    residual = put_call_parity_residual(market, strike=95.0, maturity=0.75)
    assert abs(residual) < 1e-10


def test_call_price_increases_with_spot() -> None:
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    low = black_scholes_price(_standard_market(spot=90.0), option)
    high = black_scholes_price(_standard_market(spot=110.0), option)
    assert high > low


def test_call_price_decreases_with_strike() -> None:
    market = _standard_market()
    cheap_strike = black_scholes_price(market, EuropeanOption(80.0, 1.0, "call"))
    expensive_strike = black_scholes_price(market, EuropeanOption(120.0, 1.0, "call"))
    assert cheap_strike > expensive_strike


def test_put_price_increases_with_strike() -> None:
    market = _standard_market()
    low_strike = black_scholes_price(market, EuropeanOption(80.0, 1.0, "put"))
    high_strike = black_scholes_price(market, EuropeanOption(120.0, 1.0, "put"))
    assert high_strike > low_strike


def test_option_value_is_never_negative() -> None:
    market = _standard_market()
    deep_otm_call = black_scholes_price(market, EuropeanOption(500.0, 0.1, "call"))
    deep_otm_put = black_scholes_price(market, EuropeanOption(10.0, 0.1, "put"))
    assert deep_otm_call >= 0.0
    assert deep_otm_put >= 0.0


def test_call_price_respects_lower_arbitrage_bound() -> None:
    """A European call must be worth at least max(0, S*e^{-qT} - K*e^{-rT})."""
    import math

    market = _standard_market()
    option = EuropeanOption(strike=90.0, maturity=1.0, option_type="call")
    price = black_scholes_price(market, option)
    lower_bound = max(
        0.0,
        market.spot * math.exp(-market.dividend_yield * option.maturity)
        - option.strike * math.exp(-market.risk_free_rate * option.maturity),
    )
    assert price >= lower_bound - 1e-10


def test_call_delta_is_in_zero_one_and_put_delta_in_minus_one_zero() -> None:
    market = _standard_market()
    call_greeks = black_scholes_greeks(market, EuropeanOption(100.0, 1.0, "call"))
    put_greeks = black_scholes_greeks(market, EuropeanOption(100.0, 1.0, "put"))
    assert 0.0 < call_greeks.delta < 1.0
    assert -1.0 < put_greeks.delta < 0.0


def test_gamma_and_vega_are_positive_and_shared_between_call_and_put() -> None:
    market = _standard_market()
    call_greeks = black_scholes_greeks(market, EuropeanOption(100.0, 1.0, "call"))
    put_greeks = black_scholes_greeks(market, EuropeanOption(100.0, 1.0, "put"))
    assert call_greeks.gamma > 0.0
    assert call_greeks.vega > 0.0
    assert call_greeks.gamma == pytest.approx(put_greeks.gamma, rel=1e-9)
    assert call_greeks.vega == pytest.approx(put_greeks.vega, rel=1e-9)


def test_put_call_delta_difference_is_discounted_one() -> None:
    """delta_call - delta_put = e^{-qT} is an exact identity."""
    market = _standard_market(dividend_yield=0.02)
    option_params = (100.0, 1.0)
    call_delta = black_scholes_greeks(market, EuropeanOption(*option_params, "call")).delta
    put_delta = black_scholes_greeks(market, EuropeanOption(*option_params, "put")).delta
    expected = math.exp(-market.dividend_yield * option_params[1])
    assert (call_delta - put_delta) == pytest.approx(expected, abs=1e-9)


def test_very_negative_rate_with_long_maturity_raises_a_clear_error_not_an_overflow_crash() -> None:
    """SDE-12 finding (see this module's docstring): math.exp(-r*t) alone
    overflows float64 at this rate/maturity -- the strike's risk-neutral
    weight (norm.cdf(d2)) is nonzero here, so the discounted term is
    genuinely unrepresentable, not just a spurious inf*0.0 artifact."""
    market = _standard_market(risk_free_rate=-5.0, volatility=1.0)
    option = EuropeanOption(strike=1.0, maturity=142.0, option_type="put")
    with pytest.raises(ValueError, match="represent"):
        black_scholes_price(market, option)
    with pytest.raises(ValueError, match="represent"):
        black_scholes_greeks(market, option)


def test_near_zero_probability_term_with_huge_discount_factor_gives_zero_not_nan() -> None:
    """SDE-12 finding (see this module's docstring): at this input, the
    strike leg's discount factor alone overflows math.exp, but
    norm.cdf(d2) has independently underflowed to exactly 0.0 -- the old
    code's `k * math.exp(-r*t) * norm.cdf(d2)` computed `inf * 0.0 ==
    nan` silently; the true contribution of a zero-probability term is
    unambiguously 0, confirmed here directly rather than merely not
    crashing."""
    market = _standard_market(risk_free_rate=-4.90625, volatility=1.0)
    option = EuropeanOption(strike=27.0, maturity=144.0, option_type="call")
    price = black_scholes_price(market, option)
    assert price == 0.0
    greeks = black_scholes_greeks(market, option)
    assert (greeks.delta, greeks.gamma, greeks.vega, greeks.theta, greeks.rho) == (
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def test_put_call_parity_residual_rejects_the_same_unrepresentable_input() -> None:
    market = _standard_market(risk_free_rate=-5.0, volatility=1.0)
    with pytest.raises(ValueError, match="represent"):
        put_call_parity_residual(market, strike=1.0, maturity=142.0)
