import math
from datetime import date

import pytest

from prometheus.stochastica.heston import HestonParams
from prometheus.stochastica.jump_diffusion import MertonJumpParams
from prometheus.volterra.heston_greeks import heston_finite_difference_greeks
from prometheus.volterra.identifiability import (
    heston_parameter_elasticities,
    merton_parameter_elasticities,
)
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _heston_params(**overrides: float) -> HestonParams:
    defaults: dict = dict(mu=0.03, kappa=1.5, theta=0.04, xi=0.3, rho=-0.6, v0=0.04)
    defaults.update(overrides)
    return HestonParams(**defaults)


def _merton_params(**overrides: float) -> MertonJumpParams:
    defaults: dict = dict(mu=0.03, sigma=0.2, jump_intensity=0.75, jump_mean=-0.1, jump_std=0.25)
    defaults.update(overrides)
    return MertonJumpParams(**defaults)


def test_v0_elasticity_matches_heston_vega_exactly() -> None:
    """Cross-check against this project's pre-existing, independently-
    verified Greeks (SDE-11's module docstring): v0's elasticity,
    un-normalized back to a raw partial derivative, must equal
    `heston_finite_difference_greeks`' own vega (both are d(price)/d(v0)
    computed via the same bump-and-reprice idea)."""
    market = _market()
    option = EuropeanOption(100.0, 1.0, "call")
    params = _heston_params()
    elasticities = heston_parameter_elasticities(market, option, params)

    from prometheus.volterra.heston_pricer import heston_call_price

    base_price = heston_call_price(
        market.spot, option.strike, option.maturity, market.risk_free_rate, 0.0, params
    )
    implied_vega = elasticities["v0"] * base_price / params.v0
    vega = heston_finite_difference_greeks(market, option, params).vega
    assert implied_vega == pytest.approx(vega, rel=1e-6)


@pytest.mark.parametrize("maturity", [0.1, 1.0, 10.0])
def test_kappa_and_rho_are_the_least_identifiable_heston_parameters(maturity: float) -> None:
    """Regression guard for the genuine, data-driven finding in this
    module's docstring: at a representative ATM parameter set, kappa
    and rho are consistently the two smallest-magnitude elasticities
    among Heston's five parameters, across short/medium/long maturity --
    the price of a single vanilla call is relatively insensitive to the
    variance mean-reversion speed and the spot-variance correlation."""
    market = _market()
    option = EuropeanOption(100.0, maturity, "call")
    params = _heston_params()
    elasticities = heston_parameter_elasticities(market, option, params)

    weak = {abs(elasticities["kappa"]), abs(elasticities["rho"])}
    strong = {abs(elasticities["theta"]), abs(elasticities["xi"]), abs(elasticities["v0"])}
    assert max(weak) < min(strong)


def test_all_heston_elasticities_are_finite() -> None:
    market = _market()
    option = EuropeanOption(100.0, 1.0, "call")
    params = _heston_params()
    elasticities = heston_parameter_elasticities(market, option, params)
    assert set(elasticities) == {"kappa", "theta", "xi", "rho", "v0"}
    assert all(math.isfinite(v) for v in elasticities.values())


@pytest.mark.parametrize("maturity", [0.1, 1.0, 5.0])
def test_jump_mean_is_the_least_identifiable_merton_parameter(maturity: float) -> None:
    """Regression guard for the genuine, data-driven finding in this
    module's docstring: at a representative parameter set, jump_mean is
    consistently the smallest-magnitude elasticity among Merton's four
    parameters, across short/medium/long maturity -- analogous to
    Heston's kappa/rho finding above, a different model's own weakly
    identifiable parameter."""
    market = _market()
    option = EuropeanOption(100.0, maturity, "call")
    params = _merton_params()
    elasticities = merton_parameter_elasticities(market, option, params)
    assert set(elasticities) == {"sigma", "jump_intensity", "jump_mean", "jump_std"}
    assert all(math.isfinite(v) for v in elasticities.values())
    weakest = min(elasticities, key=lambda name: abs(elasticities[name]))
    assert weakest == "jump_mean"


def test_elasticity_raises_a_clear_error_at_exactly_zero_parameter_value() -> None:
    market = _market()
    option = EuropeanOption(100.0, 1.0, "call")
    params = _heston_params(rho=0.0)
    with pytest.raises(ValueError, match="undefined"):
        heston_parameter_elasticities(market, option, params)

    params2 = _merton_params(jump_mean=0.0)
    with pytest.raises(ValueError, match="undefined"):
        merton_parameter_elasticities(market, option, params2)
