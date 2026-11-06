import math
from datetime import date

import pytest

from prometheus.volterra.forwards import forward_contract_value, forward_price
from prometheus.volterra.instruments import ForwardContract
from prometheus.volterra.market import MarketSnapshot


def _snapshot(**overrides: float) -> MarketSnapshot:
    defaults = dict(
        as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2, dividend_yield=0.02
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)  # type: ignore[arg-type]


def test_forward_price_rejects_non_positive_maturity() -> None:
    with pytest.raises(ValueError):
        forward_price(_snapshot(), 0.0)


def test_forward_price_matches_cost_of_carry_formula() -> None:
    market = _snapshot()
    maturity = 1.5
    expected = market.spot * math.exp((market.risk_free_rate - market.dividend_yield) * maturity)
    assert forward_price(market, maturity) == pytest.approx(expected)


def test_a_freshly_entered_contract_is_worth_exactly_zero() -> None:
    """By construction, the forward price IS the delivery price that
    makes a brand new contract worth zero -- the defining property of a
    fair forward price, checked directly rather than assumed."""
    market = _snapshot()
    maturity = 0.75
    fair_delivery_price = forward_price(market, maturity)
    contract = ForwardContract(fair_delivery_price, maturity)
    assert forward_contract_value(market, contract) == pytest.approx(0.0, abs=1e-9)


def test_contract_value_matches_the_equivalent_f_minus_k_formulation() -> None:
    """Two different, independently-derivable formulas for the same
    no-arbitrage value must agree: V = S*exp(-qT) - K*exp(-rT), and
    V = (F_now - K) * exp(-rT) where F_now = S*exp((r-q)T)."""
    market = _snapshot()
    contract = ForwardContract(90.0, 1.0)

    direct = forward_contract_value(market, contract)
    via_forward_price = (forward_price(market, contract.maturity) - contract.delivery_price) * (
        math.exp(-market.risk_free_rate * contract.maturity)
    )

    assert direct == pytest.approx(via_forward_price, abs=1e-10)


def test_higher_delivery_price_strictly_reduces_a_long_contracts_value() -> None:
    market = _snapshot()
    cheap = ForwardContract(80.0, 1.0)
    expensive = ForwardContract(120.0, 1.0)
    assert forward_contract_value(market, cheap) > forward_contract_value(market, expensive)


def test_forward_contract_rejects_non_positive_delivery_price() -> None:
    with pytest.raises(ValueError):
        ForwardContract(0.0, 1.0)


def test_forward_contract_rejects_non_positive_maturity() -> None:
    with pytest.raises(ValueError):
        ForwardContract(100.0, 0.0)


def test_forward_contract_rejects_nan_and_inf_fields() -> None:
    """VAL-13 ("perform NaN/Inf injection and solver fail-closed
    tests... no invalid output promoted or silently cached")."""
    with pytest.raises(ValueError, match="finite"):
        ForwardContract(float("nan"), 1.0)
    with pytest.raises(ValueError, match="finite"):
        ForwardContract(100.0, float("inf"))
