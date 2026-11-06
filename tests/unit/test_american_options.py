from datetime import date

import pytest

from prometheus.volterra.american_options import (
    american_binomial_price,
    binomial_tree_values,
    crr_parameters,
    european_binomial_price,
)
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import AmericanOption, EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _snapshot(**overrides: float) -> MarketSnapshot:
    defaults = dict(
        as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.25, dividend_yield=0.0
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)  # type: ignore[arg-type]


def test_american_option_rejects_non_positive_strike() -> None:
    with pytest.raises(ValueError):
        AmericanOption(0.0, 1.0, "call")


def test_american_option_rejects_non_positive_maturity() -> None:
    with pytest.raises(ValueError):
        AmericanOption(100.0, 0.0, "call")


def test_american_option_rejects_invalid_option_type() -> None:
    with pytest.raises(ValueError):
        AmericanOption(100.0, 1.0, "straddle")  # type: ignore[arg-type]


def test_american_option_rejects_nan_and_inf_fields() -> None:
    """VAL-13 ("perform NaN/Inf injection and solver fail-closed
    tests... no invalid output promoted or silently cached")."""
    with pytest.raises(ValueError, match="finite"):
        AmericanOption(float("nan"), 1.0, "call")
    with pytest.raises(ValueError, match="finite"):
        AmericanOption(100.0, float("inf"), "call")


def test_rejects_non_positive_n_steps() -> None:
    with pytest.raises(ValueError):
        european_binomial_price(_snapshot(), EuropeanOption(100.0, 1.0, "call"), 0)


def test_crr_parameters_rejects_non_positive_n_steps_directly() -> None:
    """crr_parameters is public (volterra.american_greeks calls it
    directly) and validates its own input independently of
    binomial_tree_values' separate stop_at_step guard -- confirmed by
    calling it on its own, not only through a pricing wrapper that would
    never actually reach this check."""
    with pytest.raises(ValueError):
        crr_parameters(_snapshot(), 1.0, 0)


def test_binomial_tree_values_rejects_an_out_of_range_stop_at_step() -> None:
    option = EuropeanOption(100.0, 1.0, "call")
    with pytest.raises(ValueError):
        binomial_tree_values(_snapshot(), option, 10, early_exercise=False, stop_at_step=10)


def test_rejects_an_ill_posed_tree_where_p_falls_outside_unit_interval() -> None:
    snapshot = _snapshot(risk_free_rate=5.0, volatility=0.01)
    with pytest.raises(ValueError):
        european_binomial_price(snapshot, EuropeanOption(100.0, 1.0, "call"), 1)


@pytest.mark.parametrize("option_type", ["call", "put"])
def test_european_binomial_price_converges_to_black_scholes(option_type: str) -> None:
    """The defining correctness check: as n_steps grows, the SAME tree
    algorithm (with early exercise disabled) must converge to the
    closed-form Black-Scholes price, which prices the identical
    risk-neutral dynamics exactly."""
    snapshot = _snapshot()
    option = EuropeanOption(100.0, 1.0, option_type)  # type: ignore[arg-type]
    exact = black_scholes_price(snapshot, option)

    errors = [abs(european_binomial_price(snapshot, option, n) - exact) for n in (50, 200, 800)]

    assert errors[0] > errors[1] > errors[2]  # error shrinks monotonically with more steps
    assert errors[-1] < 0.01


def test_american_call_equals_european_call_with_no_dividends() -> None:
    """Merton's classical result: it is never optimal to exercise an
    American call early on a non-dividend-paying asset. The two prices
    must match to tree-discretization precision, not merely satisfy an
    inequality -- this is an equality theorem, tested as one."""
    snapshot = _snapshot(dividend_yield=0.0)
    american = american_binomial_price(snapshot, AmericanOption(100.0, 1.0, "call"), 400)
    european = european_binomial_price(snapshot, EuropeanOption(100.0, 1.0, "call"), 400)
    assert american == pytest.approx(european, abs=1e-9)


def test_american_call_exceeds_european_call_when_dividends_make_early_exercise_valuable() -> None:
    snapshot = _snapshot(dividend_yield=0.08)
    american = american_binomial_price(snapshot, AmericanOption(100.0, 1.0, "call"), 400)
    european = european_binomial_price(snapshot, EuropeanOption(100.0, 1.0, "call"), 400)
    assert american > european


def test_american_put_never_cheaper_than_the_european_put() -> None:
    """The early-exercise premium of an American put is always >= 0,
    regardless of dividends -- unlike the call case, this holds even
    without dividends because the strike is a fixed cash amount."""
    snapshot = _snapshot(dividend_yield=0.0)
    american = american_binomial_price(snapshot, AmericanOption(100.0, 1.0, "put"), 400)
    european = european_binomial_price(snapshot, EuropeanOption(100.0, 1.0, "put"), 400)
    assert american >= european
    assert american > european  # strictly, for these parameters


def test_american_option_price_never_falls_below_immediate_exercise_value() -> None:
    """A deep in-the-money American put's price can never be less than
    its intrinsic (immediate-exercise) value -- the backward induction's
    own max(continuation, intrinsic) step guarantees this by
    construction, confirmed directly rather than merely trusted."""
    snapshot = _snapshot(spot=50.0)
    option = AmericanOption(100.0, 1.0, "put")
    price = american_binomial_price(snapshot, option, 200)
    intrinsic = option.strike - snapshot.spot
    assert price >= intrinsic - 1e-9


def test_deep_in_the_money_call_price_exceeds_its_intrinsic_value() -> None:
    """A deep ITM call still carries positive time value on top of its
    intrinsic value (unlike the deep ITM put case above, which can be
    pinned exactly to intrinsic value once early exercise dominates)."""
    snapshot = _snapshot(spot=100.0)
    option = AmericanOption(50.0, 1.0, "call")
    price = american_binomial_price(snapshot, option, 200)
    intrinsic = snapshot.spot - option.strike
    assert price > intrinsic
