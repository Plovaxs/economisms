import math
from datetime import date

import numpy as np
import pytest

from prometheus.volterra.barrier_options import (
    BarrierOption,
    barrier_call_or_put_price_continuous,
    barrier_option_price,
    broadie_glasserman_kou_adjusted_barrier,
    discretely_monitored_barrier_option_price,
)
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.25)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _mc_bridge_price(
    market: MarketSnapshot, option: BarrierOption, n_steps: int, n_paths: int, rng
) -> tuple[float, float]:
    """A from-scratch, independently-written Brownian-bridge continuity-
    corrected Monte Carlo: weights each path by its per-step continuous-
    monitoring SURVIVAL PROBABILITY (computed from the Brownian-bridge
    crossing formula) instead of a hard discrete-grid check, so it
    converges to the continuous-monitoring price much faster than a naive
    discrete check would, and is not just the production code's own
    quadrature re-run with different variable names."""
    s0, sigma = market.spot, market.volatility
    r, q = market.risk_free_rate, market.dividend_yield
    maturity = option.maturity
    nu = r - q - 0.5 * sigma**2
    barrier_log = math.log(option.barrier / s0)
    dt = maturity / n_steps
    drift, scale, var_step = nu * dt, sigma * math.sqrt(dt), sigma**2 * dt

    x = np.zeros(n_paths)
    survival = np.ones(n_paths)
    for _ in range(n_steps):
        x_next = x + drift + scale * rng.standard_normal(n_paths)
        if option.direction == "down":
            dist_i, dist_next = x - barrier_log, x_next - barrier_log
        else:
            dist_i, dist_next = barrier_log - x, barrier_log - x_next
        both_safe = (dist_i > 0) & (dist_next > 0)
        p_cross = np.where(both_safe, np.exp(-2.0 * dist_i * dist_next / var_step), 1.0)
        survival *= 1.0 - p_cross
        x = x_next

    terminal = s0 * np.exp(x)
    if option.option_type == "call":
        payoff = np.maximum(terminal - option.strike, 0.0)
    else:
        payoff = np.maximum(option.strike - terminal, 0.0)
    weight = survival if option.knock == "out" else (1.0 - survival)
    discounted = math.exp(-r * maturity) * weight * payoff
    return float(discounted.mean()), float(discounted.std(ddof=1) / math.sqrt(n_paths))


def _barrier_option(**overrides: object) -> BarrierOption:
    defaults: dict = dict(
        strike=100.0, maturity=1.0, option_type="call", barrier=80.0, direction="down", knock="out"
    )
    defaults.update(overrides)
    return BarrierOption(**defaults)  # type: ignore[arg-type]


def test_barrier_option_rejects_invalid_fields() -> None:
    with pytest.raises(ValueError):
        _barrier_option(strike=-1.0)
    with pytest.raises(ValueError):
        _barrier_option(maturity=0.0)
    with pytest.raises(ValueError):
        _barrier_option(option_type="x")
    with pytest.raises(ValueError):
        _barrier_option(barrier=-5.0)
    with pytest.raises(ValueError):
        _barrier_option(direction="sideways")
    with pytest.raises(ValueError):
        _barrier_option(knock="through")


def test_barrier_option_rejects_nan_and_inf_fields() -> None:
    """VAL-13 ("perform NaN/Inf injection and solver fail-closed
    tests... no invalid output promoted or silently cached"): an
    ordinary `if strike <= 0: raise` silently admits NaN (every
    comparison involving NaN is False under IEEE754)."""
    with pytest.raises(ValueError, match="finite"):
        _barrier_option(strike=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        _barrier_option(barrier=float("inf"))


def test_continuous_pricer_rejects_non_positive_scalars() -> None:
    args = dict(
        s0=100.0,
        strike=100.0,
        barrier=80.0,
        maturity=1.0,
        risk_free_rate=0.03,
        dividend_yield=0.0,
        volatility=0.25,
        option_type="call",
        direction="down",
        knock="out",
    )
    for field, bad_value in [("s0", 0.0), ("strike", -1.0), ("barrier", 0.0), ("maturity", -1.0)]:
        bad_args = dict(args)
        bad_args[field] = bad_value
        with pytest.raises(ValueError):
            barrier_call_or_put_price_continuous(**bad_args)


def test_rejects_barrier_on_wrong_side_of_spot() -> None:
    market = _market(spot=100.0)
    down_but_above = BarrierOption(100.0, 1.0, "call", barrier=120.0, direction="down", knock="out")
    with pytest.raises(ValueError):
        barrier_option_price(market, down_but_above)
    up_but_below = BarrierOption(100.0, 1.0, "call", barrier=80.0, direction="up", knock="out")
    with pytest.raises(ValueError):
        barrier_option_price(market, up_but_below)


@pytest.mark.parametrize(
    "option_type,direction,strike,barrier",
    [
        ("call", "down", 100.0, 80.0),
        ("call", "down", 70.0, 80.0),
        ("call", "up", 100.0, 130.0),
        ("call", "up", 140.0, 130.0),
        ("put", "up", 100.0, 120.0),
        ("put", "down", 100.0, 80.0),
        ("put", "down", 120.0, 80.0),
    ],
)
def test_matches_independent_bridge_corrected_monte_carlo(
    option_type, direction, strike, barrier
) -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.01, volatility=0.3)
    rng = np.random.default_rng(123)
    for knock in ("out", "in"):
        option = BarrierOption(strike, 1.0, option_type, barrier, direction, knock)
        closed_form = barrier_option_price(market, option)
        mc_price, mc_se = _mc_bridge_price(market, option, n_steps=100, n_paths=300_000, rng=rng)
        assert abs(closed_form - mc_price) < 5 * mc_se + 1e-9


@pytest.mark.parametrize(
    "option_type,direction,strike,barrier",
    [("call", "down", 100.0, 85.0), ("put", "up", 95.0, 115.0)],
)
def test_in_out_parity_holds(option_type, direction, strike, barrier) -> None:
    market = _market(spot=100.0, risk_free_rate=0.02, dividend_yield=0.015, volatility=0.28)
    maturity = 0.8
    out_price = barrier_option_price(
        market, BarrierOption(strike, maturity, option_type, barrier, direction, "out")
    )
    in_price = barrier_option_price(
        market, BarrierOption(strike, maturity, option_type, barrier, direction, "in")
    )
    vanilla = black_scholes_price(market, EuropeanOption(strike, maturity, option_type))
    assert (out_price + in_price) == pytest.approx(vanilla, abs=1e-8)


def test_down_and_out_call_converges_to_vanilla_as_barrier_vanishes() -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=0.25)
    option = BarrierOption(100.0, 1.0, "call", barrier=1e-8, direction="down", knock="out")
    price = barrier_option_price(market, option)
    vanilla = black_scholes_price(market, EuropeanOption(100.0, 1.0, "call"))
    assert price == pytest.approx(vanilla, abs=1e-4)


def test_down_and_in_call_vanishes_as_barrier_vanishes() -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=0.25)
    option = BarrierOption(100.0, 1.0, "call", barrier=1e-8, direction="down", knock="in")
    price = barrier_option_price(market, option)
    assert price == pytest.approx(0.0, abs=1e-4)


def test_knock_out_option_is_worth_almost_nothing_when_barrier_at_spot() -> None:
    market = _market(spot=100.0)
    option = BarrierOption(100.0, 1.0, "call", barrier=99.999, direction="down", knock="out")
    price = barrier_option_price(market, option)
    assert price < 0.01


def test_up_and_out_call_is_worthless_when_strike_at_or_above_barrier() -> None:
    """If K >= H, any positive call payoff (S_T > K >= H) would require
    the continuous path to have already crossed H (by the intermediate
    value theorem), so the up-and-out call must be exactly zero."""
    market = _market(spot=100.0)
    option = BarrierOption(130.0, 1.0, "call", barrier=120.0, direction="up", knock="out")
    assert barrier_option_price(market, option) == pytest.approx(0.0, abs=1e-10)


def test_down_and_out_put_is_worthless_when_strike_at_or_below_barrier() -> None:
    market = _market(spot=100.0)
    option = BarrierOption(70.0, 1.0, "put", barrier=80.0, direction="down", knock="out")
    assert barrier_option_price(market, option) == pytest.approx(0.0, abs=1e-10)


def test_knock_out_price_never_exceeds_vanilla() -> None:
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=0.3)
    option = BarrierOption(100.0, 1.0, "call", barrier=85.0, direction="down", knock="out")
    out_price = barrier_option_price(market, option)
    vanilla = black_scholes_price(market, EuropeanOption(100.0, 1.0, "call"))
    assert 0.0 <= out_price <= vanilla


def test_broadie_glasserman_kou_shift_moves_barrier_away_from_spot() -> None:
    down_adj = broadie_glasserman_kou_adjusted_barrier(80.0, "down", 0.3, 1.0, 50)
    up_adj = broadie_glasserman_kou_adjusted_barrier(120.0, "up", 0.3, 1.0, 50)
    assert down_adj < 80.0
    assert up_adj > 120.0


def test_bgk_adjustment_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        broadie_glasserman_kou_adjusted_barrier(-1.0, "down", 0.3, 1.0, 50)
    with pytest.raises(ValueError):
        broadie_glasserman_kou_adjusted_barrier(80.0, "down", 0.3, 1.0, 0)


def test_discretization_correction_reduces_error_vs_naive_discrete_monitoring() -> None:
    """Pins the empirically-confirmed result that drove this module's
    design: pricing a genuinely discretely-monitored barrier with the
    continuity-corrected formula is far closer to a direct simulation of
    that discrete process than using the uncorrected continuous formula --
    not just a plausible story, but a regression guard on the actual
    magnitude of the improvement."""
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=0.3)
    option = BarrierOption(100.0, 1.0, "call", barrier=80.0, direction="down", knock="out")
    n_obs = 50

    uncorrected = barrier_option_price(market, option)
    corrected = discretely_monitored_barrier_option_price(market, option, n_obs)

    rng = np.random.default_rng(99)
    n_paths = 600_000
    dt = option.maturity / n_obs
    drift = (market.risk_free_rate - market.dividend_yield - 0.5 * market.volatility**2) * dt
    scale = market.volatility * math.sqrt(dt)
    log_s = np.full(n_paths, math.log(market.spot))
    breached = np.zeros(n_paths, dtype=bool)
    for _ in range(n_obs):
        log_s = log_s + drift + scale * rng.standard_normal(n_paths)
        breached |= np.exp(log_s) <= option.barrier
    terminal = np.exp(log_s)
    payoff = np.where(breached, 0.0, np.maximum(terminal - option.strike, 0.0))
    discounted = math.exp(-market.risk_free_rate * option.maturity) * payoff
    true_discrete_price = float(discounted.mean())

    err_uncorrected = abs(uncorrected - true_discrete_price)
    err_corrected = abs(corrected - true_discrete_price)
    assert err_corrected < err_uncorrected / 5.0


def test_discretely_monitored_price_rejects_invalid_observation_count() -> None:
    market = _market()
    option = BarrierOption(100.0, 1.0, "call", barrier=80.0, direction="down", knock="out")
    with pytest.raises(ValueError):
        discretely_monitored_barrier_option_price(market, option, 0)


def test_tiny_volatility_matches_vanilla_not_zero() -> None:
    """SDE-12 regression guard: before this fix, a down-and-out call at
    an unreachably-tiny volatility silently returned exactly 0.0 instead
    of matching the vanilla price (the barrier should essentially never
    be reached), with no error of any kind -- the integration bounds
    were centered on log-return 0 rather than on the true drift
    nu*maturity, so the entire probability mass fell outside the
    integrated window. Confirmed independently against a fine-grid
    Simpson's-rule ground truth before trusting this fix."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=1e-8)
    option = BarrierOption(100.0, 1.0, "call", barrier=80.0, direction="down", knock="out")
    vanilla = black_scholes_price(market, EuropeanOption(100.0, 1.0, "call"))
    price = barrier_option_price(market, option)
    assert price == pytest.approx(vanilla, rel=1e-6)
    assert price > 1.0  # the old bug's failure mode: silently exactly 0.0


def test_degenerate_h_to_zero_limit_matches_vanilla_to_high_precision() -> None:
    """A second SDE-12 regression guard, for the previously-dormant
    quadrature kink bug the centering fix exposed: at the H -> 0
    degenerate limit, `quad`'s adaptive subdivision (not told where the
    payoff's kink at ln(strike/s0) is) could silently converge to a value
    ~0.1% off from the correct one, with no error and a deceptively small
    reported quadrature error estimate. Fixed by passing `points=` to
    `quad`; this pins the fix to a much tighter tolerance than 0.1%."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=0.2)
    option = BarrierOption(100.0, 1.0, "call", barrier=1e-8, direction="down", knock="out")
    vanilla = black_scholes_price(market, EuropeanOption(100.0, 1.0, "call"))
    price = barrier_option_price(market, option)
    assert price == pytest.approx(vanilla, abs=1e-6)


def test_rejects_rate_and_maturity_combination_beyond_float_range() -> None:
    """A large enough rate/maturity pushes ln(forward price) past
    float64's exp() overflow point -- the true price is not
    representable at all, so this must raise a clear ValueError rather
    than let a cryptic OverflowError escape from inside
    scipy.integrate.quad."""
    market = _market(spot=100.0, risk_free_rate=10.0, volatility=0.2)
    option = BarrierOption(100.0, 100.0, "call", barrier=80.0, direction="down", knock="out")
    with pytest.raises(ValueError, match="represent"):
        barrier_option_price(market, option)


def test_rejects_negative_rate_and_long_maturity_overflowing_the_discount_factor() -> None:
    """A FIFTH overflow path (see this module's own docstring),
    independent of the integration-bound check above: rate=-5.0,
    maturity=142.0 overflows the discount factor exp(-rate*maturity) =
    exp(710) itself, inside the knock-out branch's own discounting --
    the exact Hypothesis-found counterexample that originally escaped
    as an uncaught OverflowError rather than this clean ValueError."""
    market = _market(spot=1.0, risk_free_rate=-5.0, volatility=1.0)
    option = BarrierOption(1.0, 142.0, "call", barrier=1.5, direction="up", knock="out")
    with pytest.raises(ValueError, match="represent"):
        barrier_option_price(market, option)


def test_rejects_negative_rate_and_long_maturity_overflowing_the_knock_in_parity() -> None:
    """The discount-factor overflow's second, independent manifestation:
    the knock-in vanilla-parity closed form's OWN discount factors
    overflow even when the knock-out branch itself never reaches the
    discounting line at all (this exact barrier/direction combination
    takes the `lower >= upper` short-circuit, so only the parity
    computation's own check -- not the knock-out branch's -- is what
    must catch this)."""
    market = _market(spot=1.0, risk_free_rate=-5.0, volatility=1.0)
    option = BarrierOption(1.0, 142.0, "call", barrier=0.5, direction="down", knock="in")
    with pytest.raises(ValueError, match="represent"):
        barrier_option_price(market, option)


def test_very_negative_rate_with_small_volatility_gives_a_near_certain_breach() -> None:
    """A very negative rate combined with small volatility drives the
    drift (nu*maturity) so far below the down barrier that the drift-
    centered probability window has NO overlap with the survival region
    at all -- breach is effectively certain, so the correct knock-out
    price is exactly 0.0, computed directly rather than via a degenerate
    (inverted) integration range or a confusing crash."""
    market = _market(spot=100.0, risk_free_rate=-10.0, volatility=0.01)
    option = BarrierOption(100.0, 1.0, "call", barrier=80.0, direction="down", knock="out")
    assert barrier_option_price(market, option) == 0.0

    in_option = BarrierOption(100.0, 1.0, "call", barrier=80.0, direction="down", knock="in")
    vanilla = black_scholes_price(market, EuropeanOption(100.0, 1.0, "call"))
    assert barrier_option_price(market, in_option) == pytest.approx(vanilla, rel=1e-9)


def test_huge_volatility_gives_a_tiny_finite_price_not_a_crash() -> None:
    """At volatility=50 (an absurd 5000% annualized vol), the barrier is
    essentially certain to be breached almost instantly, so the correct
    answer is a tiny but finite, non-negative price -- not a crash."""
    market = _market(spot=100.0, risk_free_rate=0.03, volatility=50.0)
    option = BarrierOption(100.0, 1.0, "call", barrier=80.0, direction="down", knock="out")
    price = barrier_option_price(market, option)
    assert math.isfinite(price)
    assert 0.0 <= price < 1.0
