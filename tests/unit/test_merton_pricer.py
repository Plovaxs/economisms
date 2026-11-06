import math
from datetime import date

import numpy as np
import pytest
from scipy.stats import norm

from prometheus.stochastica.jump_diffusion import MertonJumpParams, simulate_jump_diffusion_paths
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.merton_pricer import merton_call_price, merton_option_price


def _market(**overrides: float) -> MarketSnapshot:
    defaults: dict = dict(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def _params(**overrides: float) -> MertonJumpParams:
    defaults: dict = dict(mu=0.03, sigma=0.2, jump_intensity=0.75, jump_mean=-0.1, jump_std=0.25)
    defaults.update(overrides)
    return MertonJumpParams(**defaults)


def test_jump_params_reject_invalid_fields() -> None:
    with pytest.raises(ValueError):
        MertonJumpParams(mu=0.0, sigma=0.0, jump_intensity=1.0, jump_mean=0.0, jump_std=0.1)
    with pytest.raises(ValueError):
        MertonJumpParams(mu=0.0, sigma=0.2, jump_intensity=-1.0, jump_mean=0.0, jump_std=0.1)
    with pytest.raises(ValueError):
        MertonJumpParams(mu=0.0, sigma=0.2, jump_intensity=1.0, jump_mean=0.0, jump_std=-0.1)


def test_jump_params_reject_nan_and_inf_fields() -> None:
    """VAL-13 ("perform NaN/Inf injection and solver fail-closed
    tests... no invalid output promoted or silently cached"): sigma's
    own `<= 0` check silently admits NaN (every comparison involving
    NaN is False), and jump_mean has no sign check at all to
    accidentally catch it either -- before `require_finite` was added,
    both passed through uncaught and propagated silently."""
    with pytest.raises(ValueError, match="finite"):
        MertonJumpParams(
            mu=0.0, sigma=float("nan"), jump_intensity=1.0, jump_mean=0.0, jump_std=0.1
        )
    with pytest.raises(ValueError, match="finite"):
        MertonJumpParams(
            mu=0.0, sigma=0.2, jump_intensity=1.0, jump_mean=float("inf"), jump_std=0.1
        )


def test_rejects_non_positive_s0_strike_or_maturity() -> None:
    p = _params()
    with pytest.raises(ValueError):
        merton_call_price(0.0, 100.0, 1.0, 0.03, 0.0, p)
    with pytest.raises(ValueError):
        merton_call_price(100.0, -1.0, 1.0, 0.03, 0.0, p)
    with pytest.raises(ValueError):
        merton_call_price(100.0, 100.0, 0.0, 0.03, 0.0, p)


def test_matches_a_from_scratch_second_computation_of_the_closed_form() -> None:
    """A completely independent, from-scratch re-implementation of the
    same formula (not calling production code at all, not even
    scipy.stats.norm from the same import), confirming this isn't a
    copy-paste bug reproducing itself identically in two places."""
    s0, k, t, r, q = 100.0, 100.0, 1.0, 0.03, 0.0
    p = _params()
    production = merton_call_price(s0, k, t, r, q, p)

    jump_k = math.exp(p.jump_mean + 0.5 * p.jump_std**2) - 1.0
    lam_prime = p.jump_intensity * (1 + jump_k)
    total = 0.0
    for n in range(80):
        weight = math.exp(-lam_prime * t) * (lam_prime * t) ** n / math.factorial(n)
        sigma_n = math.sqrt(p.sigma**2 + n * p.jump_std**2 / t)
        r_n = r - p.jump_intensity * jump_k + n * math.log(1 + jump_k) / t
        d1 = (math.log(s0 / k) + (r_n + 0.5 * sigma_n**2) * t) / (sigma_n * math.sqrt(t))
        d2 = d1 - sigma_n * math.sqrt(t)
        total += weight * (s0 * norm.cdf(d1) - k * math.exp(-r_n * t) * norm.cdf(d2))

    assert production == pytest.approx(total, abs=1e-9)


def test_using_the_physical_jump_intensity_as_the_poisson_weight_would_be_wrong() -> None:
    """Documents and guards against the real, easy-to-make error this
    module's own docstring describes: weighting the Poisson sum by the
    PHYSICAL jump_intensity instead of jump_intensity*(1+k) gives a
    materially different (and wrong) price, confirmed against Monte
    Carlo in test_matches_monte_carlo_simulation below. This test just
    pins the magnitude of the (large, not a rounding-level) discrepancy,
    so a future refactor that reintroduces the bug fails loudly here too."""
    s0, k, t, r, q = 100.0, 100.0, 1.0, 0.03, 0.0
    p = _params()
    correct = merton_call_price(s0, k, t, r, q, p)

    jump_k = math.exp(p.jump_mean + 0.5 * p.jump_std**2) - 1.0
    wrong_lambda = p.jump_intensity  # the bug: physical, not adjusted, intensity
    total = 0.0
    for n in range(80):
        weight = math.exp(-wrong_lambda * t) * (wrong_lambda * t) ** n / math.factorial(n)
        sigma_n = math.sqrt(p.sigma**2 + n * p.jump_std**2 / t)
        r_n = r - p.jump_intensity * jump_k + n * math.log(1 + jump_k) / t
        d1 = (math.log(s0 / k) + (r_n + 0.5 * sigma_n**2) * t) / (sigma_n * math.sqrt(t))
        d2 = d1 - sigma_n * math.sqrt(t)
        total += weight * (s0 * norm.cdf(d1) - k * math.exp(-r_n * t) * norm.cdf(d2))

    assert abs(correct - total) > 0.03  # far larger than any floating-point/quadrature slack


def test_converges_to_black_scholes_as_jump_intensity_vanishes() -> None:
    sigma = 0.2
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.0, volatility=sigma)
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    bs_price = black_scholes_price(market, option)

    p = _params(sigma=sigma, jump_intensity=1e-9, jump_mean=0.0, jump_std=1e-6)
    merton_price = merton_option_price(market, option, p)
    assert merton_price == pytest.approx(bs_price, abs=1e-4)


def test_converges_to_black_scholes_put_as_jump_intensity_vanishes_with_dividends() -> None:
    sigma = 0.25
    market = _market(spot=90.0, risk_free_rate=0.02, dividend_yield=0.015, volatility=sigma)
    option = EuropeanOption(strike=100.0, maturity=0.5, option_type="put")
    bs_price = black_scholes_price(market, option)

    p = _params(sigma=sigma, jump_intensity=1e-9, jump_mean=0.0, jump_std=1e-6)
    merton_price = merton_option_price(market, option, p)
    assert merton_price == pytest.approx(bs_price, abs=1e-4)


def test_matches_monte_carlo_simulation_of_the_independent_simulator() -> None:
    """Agreement with stochastica.jump_diffusion (an independently
    written SDE simulator, not derived from this closed-form module) is
    the strongest available check here, short of an external published
    reference table -- the same standard volterra.heston_pricer was held
    to."""
    p = _params()
    s0, t, r, q, k = 100.0, 1.0, 0.03, 0.0, 100.0
    closed_form_price = merton_call_price(s0, k, t, r, q, p)

    rng = np.random.default_rng(7)
    n_paths, n_steps = 2_000_000, 50
    paths = simulate_jump_diffusion_paths(s0, p, t, n_steps, n_paths, rng)
    terminal = paths[:, -1]
    payoffs = np.maximum(terminal - k, 0.0)
    mc_price = math.exp(-r * t) * payoffs.mean()
    mc_stderr = math.exp(-r * t) * payoffs.std(ddof=1) / math.sqrt(n_paths)

    assert abs(closed_form_price - mc_price) < 5 * mc_stderr


def test_put_call_parity_holds() -> None:
    p = _params()
    market = _market(spot=100.0, risk_free_rate=0.03, dividend_yield=0.01)
    call = merton_option_price(market, EuropeanOption(95.0, 0.75, "call"), p)
    put = merton_option_price(market, EuropeanOption(95.0, 0.75, "put"), p)
    forward_value = market.spot * math.exp(
        -market.dividend_yield * 0.75
    ) - 95.0 * math.exp(-market.risk_free_rate * 0.75)
    assert (call - put) == pytest.approx(forward_value, abs=1e-9)


def test_market_volatility_field_is_ignored_in_favor_of_params_sigma() -> None:
    p = _params()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    price_a = merton_option_price(_market(volatility=0.1), option, p)
    price_b = merton_option_price(_market(volatility=0.9), option, p)
    assert price_a == price_b


def test_price_increases_with_jump_intensity_for_negative_mean_jumps() -> None:
    """A basic economic sanity check: with downward-biased jumps (a
    'crash' model), more frequent jumps mean more downside variance, so a
    call option (which only pays on the upside) should become MORE, not
    less, valuable as jump-driven variance rises -- variance always helps
    a call, regardless of the direction of the jump's mean."""
    market = _market()
    option = EuropeanOption(strike=100.0, maturity=1.0, option_type="call")
    low_intensity = merton_option_price(market, option, _params(jump_intensity=0.1))
    high_intensity = merton_option_price(market, option, _params(jump_intensity=2.0))
    assert high_intensity > low_intensity


def test_simulator_rejects_invalid_inputs() -> None:
    p = _params()
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        simulate_jump_diffusion_paths(0.0, p, 1.0, 10, 100, rng)
    with pytest.raises(ValueError):
        simulate_jump_diffusion_paths(100.0, p, 0.0, 10, 100, rng)
    with pytest.raises(ValueError):
        simulate_jump_diffusion_paths(100.0, p, 1.0, 0, 100, rng)
    with pytest.raises(ValueError):
        simulate_jump_diffusion_paths(100.0, p, 1.0, 10, 0, rng)


def test_simulator_with_zero_jump_intensity_matches_pure_gbm_moments() -> None:
    """With jump_intensity == 0, the model IS plain GBM: the terminal mean
    must match the standard E[S_T] = S0*exp(mu*T) exactly (within Monte
    Carlo error), with no jump contribution at all."""
    mu, sigma = 0.05, 0.2
    p = MertonJumpParams(mu=mu, sigma=sigma, jump_intensity=0.0, jump_mean=0.0, jump_std=0.1)
    rng = np.random.default_rng(3)
    s0, t = 100.0, 1.0
    paths = simulate_jump_diffusion_paths(s0, p, t, 100, 500_000, rng)
    terminal = paths[:, -1]
    expected_mean = s0 * math.exp(mu * t)
    stderr = terminal.std(ddof=1) / math.sqrt(len(terminal))
    assert abs(terminal.mean() - expected_mean) < 4 * stderr


def test_jump_diffusion_paths_are_always_positive_and_finite() -> None:
    """FP-11 (ECONOSIM-X addendum): an explicit positivity/finiteness
    diagnostic for the jump-diffusion simulator specifically -- GBM and
    Heston already each have one of their own (`test_gbm.py`,
    `test_heston.py`), but jump-diffusion previously had only moment-
    matching tests, not this. GBM-style log-price simulation is positive
    by construction (price = exp(log_s)), but a large negative jump mean
    combined with a high jump intensity is exactly the kind of stress
    case that could in principle blow up a less careful implementation
    (e.g. overflow in exp() from an unbounded jump sum), so this is
    checked directly rather than assumed from the GBM analogy alone."""
    rng = np.random.default_rng(13)
    s0, t, n_steps, n_paths = 100.0, 2.0, 50, 200_000
    stress_params = MertonJumpParams(
        mu=0.03, sigma=0.5, jump_intensity=5.0, jump_mean=-0.6, jump_std=0.8
    )
    paths = simulate_jump_diffusion_paths(s0, stress_params, t, n_steps, n_paths, rng)
    assert np.all(np.isfinite(paths))
    assert np.all(paths > 0.0)


def test_extremely_negative_jump_mean_raises_a_clear_error_not_a_domain_crash() -> None:
    """SDE-12 regression guard: before this fix, jump_mean extreme enough
    to underflow the jump compensator k to exactly -1.0 caused
    `math.log(1.0 + k)` to raise a cryptic domain-error ValueError from
    deep inside the per-term loop, with no indication of what was
    actually wrong. The fixed, clear message is checked for instead."""
    p = _params(jump_mean=-50.0, jump_std=0.25)
    with pytest.raises(ValueError, match="compensator"):
        merton_call_price(100.0, 100.0, 1.0, 0.03, 0.0, p)


def test_extremely_large_jump_std_raises_a_clear_error_not_an_overflow_crash() -> None:
    """SDE-12 regression guard: before this fix, jump_std large enough to
    drive the adjusted Poisson mean past 1e21 caused an uncaught
    `OverflowError` from `math.exp` deep inside the per-term loop (and,
    before even reaching that, would have made `_poisson_term_count`
    request an uncomputable number of loop iterations)."""
    p = _params(jump_std=10.0)
    with pytest.raises(ValueError, match="Poisson mean"):
        merton_call_price(100.0, 100.0, 1.0, 0.03, 0.0, p)


def test_large_but_practical_jump_intensity_still_prices_without_error() -> None:
    """Confirms the new upfront checks do not accidentally reject inputs
    that were already known to work (SDE-12 should tighten validation,
    never silently narrow what the pricer actually supports)."""
    p = _params(jump_intensity=1000.0)
    price = merton_call_price(100.0, 100.0, 1.0, 0.03, 0.0, p)
    assert math.isfinite(price)
    assert price > 0.0


def test_large_jump_std_with_small_intensity_raises_a_clear_error_not_an_overflow_crash() -> None:
    """SDE-12 regression guard: a FOURTH, independent overflow path that
    survives the compensator and poisson-mean checks above -- r_0 =
    r - jump_intensity*k is already hugely negative at n=0 purely
    because jump_intensity*k is large, even though k itself is finite
    and poisson_mean (~2982 here) is comfortably under
    `_MAX_POISSON_MEAN`. Before this fix, `math.exp(-r_n*maturity)`
    overflowed at the very first loop iteration with no indication of
    why (see this module's own docstring, SDE-12)."""
    p = _params(jump_intensity=1.0, jump_mean=0.0, jump_std=4.0)
    with pytest.raises(ValueError, match="effective rate"):
        merton_call_price(1.0, 1.0, 1.0, 0.0, 0.0, p)


def test_zero_jump_intensity_matches_black_scholes_exactly_not_a_log_zero_crash() -> None:
    """VAL-11 regression guard (see this module's own docstring): a
    perfectly ordinary, non-extreme parameter (jump_intensity=0.0, "no
    jumps at all") used to crash with `math.log(0.0)` at the loop's n=1
    iteration, because poisson_mean's floor of min_terms=50 iterations
    still ran even though every n>=1 term has exactly zero weight.
    Fixed by collapsing to the single n=0 term; the result must now
    match Black-Scholes EXACTLY, not just approximately."""
    p = _params(jump_intensity=0.0, jump_mean=0.0, jump_std=0.0)
    price = merton_call_price(100.0, 100.0, 1.0, 0.05, 0.0, p)
    bs_price = black_scholes_price(
        MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.05, volatility=0.2),
        EuropeanOption(100.0, 1.0, "call"),
    )
    assert price == pytest.approx(bs_price, abs=1e-12)
