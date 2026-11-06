import math
from dataclasses import replace
from datetime import date

import pytest

from prometheus.volterra.american_greeks import american_binomial_greeks, tree_delta_gamma
from prometheus.volterra.american_options import american_binomial_price
from prometheus.volterra.black_scholes import black_scholes_greeks
from prometheus.volterra.instruments import AmericanOption, EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _snapshot(**overrides: float) -> MarketSnapshot:
    defaults = dict(
        as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.25, dividend_yield=0.0
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)  # type: ignore[arg-type]


def test_tree_delta_gamma_rejects_too_few_steps() -> None:
    with pytest.raises(ValueError):
        tree_delta_gamma(_snapshot(), AmericanOption(100.0, 1.0, "call"), 1)


def test_naive_spot_bumped_central_difference_gamma_does_not_converge() -> None:
    """The pathology this module's docstring warns about, demonstrated
    directly rather than merely asserted: with a small bump on the scale
    `greeks_fd.py` uses for the smooth Black-Scholes price, re-pricing a
    binomial tree at S+-bump and taking a central difference produces a
    gamma off by orders of magnitude -- confirming the naive approach is
    genuinely broken, not just theoretically suboptimal."""
    snapshot = _snapshot()
    option = AmericanOption(100.0, 1.0, "call")
    n_steps = 500
    small_bump = 1e-3

    price_mid = american_binomial_price(snapshot, option, n_steps)
    price_up = american_binomial_price(
        replace(snapshot, spot=snapshot.spot + small_bump), option, n_steps
    )
    price_down = american_binomial_price(
        replace(snapshot, spot=snapshot.spot - small_bump), option, n_steps
    )
    naive_gamma = (price_up - 2 * price_mid + price_down) / (small_bump**2)

    true_gamma = tree_delta_gamma(snapshot, option, n_steps)[1]
    assert abs(naive_gamma - true_gamma) > 10 * abs(true_gamma)


@pytest.mark.parametrize("n_steps", [100, 500, 2000])
def test_delta_gamma_converge_to_black_scholes_for_a_no_dividend_call(n_steps: int) -> None:
    """Since an American call with no dividends is worth EXACTLY the same
    as the European call (PR-038's theorem), its Greeks must converge to
    the same analytical Black-Scholes Greeks too."""
    snapshot = _snapshot(dividend_yield=0.0)
    option = AmericanOption(100.0, 1.0, "call")
    exact = black_scholes_greeks(snapshot, EuropeanOption(100.0, 1.0, "call"))

    delta, gamma = tree_delta_gamma(snapshot, option, n_steps)
    assert delta == pytest.approx(exact.delta, abs=0.01)
    assert gamma == pytest.approx(exact.gamma, abs=0.01)


def test_delta_gamma_error_shrinks_monotonically_with_more_steps() -> None:
    snapshot = _snapshot(dividend_yield=0.0)
    option = AmericanOption(100.0, 1.0, "call")
    exact = black_scholes_greeks(snapshot, EuropeanOption(100.0, 1.0, "call"))

    gamma_errors = [
        abs(tree_delta_gamma(snapshot, option, n)[1] - exact.gamma) for n in (100, 500, 2000)
    ]
    assert gamma_errors[0] > gamma_errors[1] > gamma_errors[2]


def test_full_greeks_converge_to_black_scholes_for_a_no_dividend_call() -> None:
    snapshot = _snapshot(dividend_yield=0.0)
    option = AmericanOption(100.0, 1.0, "call")
    exact = black_scholes_greeks(snapshot, EuropeanOption(100.0, 1.0, "call"))

    greeks = american_binomial_greeks(snapshot, option, 1000)

    assert greeks.delta == pytest.approx(exact.delta, abs=0.005)
    assert greeks.gamma == pytest.approx(exact.gamma, abs=0.005)
    assert greeks.vega == pytest.approx(exact.vega, abs=0.5)
    assert greeks.theta == pytest.approx(exact.theta, abs=0.1)
    assert greeks.rho == pytest.approx(exact.rho, abs=0.5)


def test_put_delta_is_negative_and_call_delta_is_positive() -> None:
    snapshot = _snapshot()
    call_delta, _ = tree_delta_gamma(snapshot, AmericanOption(100.0, 1.0, "call"), 500)
    put_delta, _ = tree_delta_gamma(snapshot, AmericanOption(100.0, 1.0, "put"), 500)
    assert call_delta > 0.0
    assert put_delta < 0.0


def test_gamma_is_positive_for_both_calls_and_puts() -> None:
    snapshot = _snapshot()
    _, call_gamma = tree_delta_gamma(snapshot, AmericanOption(100.0, 1.0, "call"), 500)
    _, put_gamma = tree_delta_gamma(snapshot, AmericanOption(100.0, 1.0, "put"), 500)
    assert call_gamma > 0.0
    assert put_gamma > 0.0


def test_dividends_make_early_exercise_detectable_in_the_greeks_too() -> None:
    """With dividends, the American call's price exceeds the European
    call's (PR-038); its vega should still be positive and finite, and
    computing the full Greeks bundle must not raise even when early
    exercise is genuinely active throughout the tree."""
    snapshot = _snapshot(dividend_yield=0.08)
    option = AmericanOption(100.0, 1.0, "call")
    greeks = american_binomial_greeks(snapshot, option, 500)
    assert greeks.vega > 0.0
    values = (greeks.delta, greeks.gamma, greeks.vega, greeks.theta, greeks.rho)
    assert all(math.isfinite(x) for x in values)
