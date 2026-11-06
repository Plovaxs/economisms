from datetime import date

import pytest

from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.calibration import (
    CalibrationError,
    calibrate_implied_volatility,
    calibrate_volatility_smile,
)
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _bs_price(
    spot: float, strike: float, r: float, sigma: float, maturity: float, option_type
) -> float:
    market = MarketSnapshot(as_of=date.today(), spot=spot, risk_free_rate=r, volatility=sigma)
    return black_scholes_price(market, EuropeanOption(strike, maturity, option_type))


@pytest.mark.parametrize("option_type", ["call", "put"])
@pytest.mark.parametrize("moneyness", [80.0, 100.0, 120.0])
@pytest.mark.parametrize("true_vol", [0.1, 0.27, 0.8])
def test_round_trip_recovers_the_exact_volatility(option_type, moneyness, true_vol) -> None:
    """Price at a known volatility, then calibrate from that price: the
    recovered volatility must match the true one to near machine precision,
    across ITM/ATM/OTM strikes, both option types, and low/typical/high
    volatility regimes -- not just one convenient case."""
    price = _bs_price(100.0, moneyness, 0.05, true_vol, 0.75, option_type)
    result = calibrate_implied_volatility(100.0, moneyness, 0.05, 0.75, option_type, price)
    assert result.implied_volatility == pytest.approx(true_vol, abs=1e-8)
    assert abs(result.price_error) < 1e-8


def test_price_above_upper_arbitrage_bound_rejected() -> None:
    with pytest.raises(CalibrationError):
        calibrate_implied_volatility(100.0, 105.0, 0.05, 0.75, "call", market_price=1000.0)


def test_price_below_lower_arbitrage_bound_rejected() -> None:
    # A call struck far in the money must be worth at least its discounted
    # intrinsic value; quoting less than that has no rationalizing vol.
    with pytest.raises(CalibrationError):
        calibrate_implied_volatility(100.0, 10.0, 0.05, 1.0, "call", market_price=1.0)


def test_rejects_non_positive_spot_or_price() -> None:
    with pytest.raises(ValueError):
        calibrate_implied_volatility(0.0, 100.0, 0.05, 1.0, "call", market_price=5.0)
    with pytest.raises(ValueError):
        calibrate_implied_volatility(100.0, 100.0, 0.05, 1.0, "call", market_price=0.0)


def test_bracket_that_does_not_span_the_root_raises_calibration_error() -> None:
    """A price within the arbitrage bounds can still fail to bracket if the
    caller supplies a vol_lower/vol_upper window that doesn't actually
    contain the true implied volatility -- this must surface as
    CalibrationError, not an uncaught scipy ValueError."""
    price = _bs_price(100.0, 100.0, 0.05, 0.2, 1.0, "call")
    with pytest.raises(CalibrationError):
        calibrate_implied_volatility(
            100.0, 100.0, 0.05, 1.0, "call", price, vol_lower=5.0, vol_upper=6.0
        )


def test_rejects_inverted_vol_bracket() -> None:
    with pytest.raises(ValueError):
        calibrate_implied_volatility(
            100.0, 100.0, 0.05, 1.0, "call", market_price=5.0, vol_lower=1.0, vol_upper=0.5
        )


def test_flat_true_smile_recovers_a_constant_implied_volatility() -> None:
    quotes = [
        (float(k), _bs_price(100.0, float(k), 0.03, 0.22, 0.5, "call"))
        for k in (80, 90, 100, 110, 120)
    ]
    smile = calibrate_volatility_smile(100.0, 0.03, 0.5, "call", quotes)
    for point in smile:
        assert point.implied_volatility == pytest.approx(0.22, abs=1e-8)


def test_genuine_smile_shape_is_recovered_strike_by_strike() -> None:
    """Prices generated from a strike-dependent (non-flat) true volatility
    must calibrate back to that exact shape -- confirming the smile
    function actually captures cross-strike variation, not just a single
    flat case."""
    true_vols = {80.0: 0.30, 90.0: 0.25, 100.0: 0.20, 110.0: 0.24, 120.0: 0.28}
    quotes = [
        (strike, _bs_price(100.0, strike, 0.03, vol, 0.5, "call"))
        for strike, vol in true_vols.items()
    ]
    smile = calibrate_volatility_smile(100.0, 0.03, 0.5, "call", quotes)
    for point in smile:
        assert point.implied_volatility == pytest.approx(true_vols[point.strike], abs=1e-8)


def test_smile_rejects_empty_quotes() -> None:
    with pytest.raises(ValueError):
        calibrate_volatility_smile(100.0, 0.03, 0.5, "call", [])


def test_smile_propagates_a_single_bad_quote_as_calibration_error() -> None:
    quotes = [(100.0, 6.0), (105.0, 100000.0)]  # second quote violates arbitrage bounds
    with pytest.raises(CalibrationError):
        calibrate_volatility_smile(100.0, 0.03, 0.5, "call", quotes)


def test_near_expiry_still_calibrates_correctly() -> None:
    """A short-dated, near-the-money option (small but nonzero vega) should
    still calibrate precisely, not just comfortably long-dated ones."""
    price = _bs_price(100.0, 100.0, 0.05, 0.3, 1 / 365, "call")
    result = calibrate_implied_volatility(100.0, 100.0, 0.05, 1 / 365, "call", price)
    assert result.implied_volatility == pytest.approx(0.3, abs=1e-6)
