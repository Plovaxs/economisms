"""Merton (1976) jump-diffusion European option pricing in closed form
(extends PRI-01/PRI-04's pricing ladder to a second non-GBM model,
alongside Heston), via the classical Poisson-weighted Black-Scholes sum:

    C = sum_{n=0}^inf  q_n(lambda') * BS_call(S0, K, T, r_n, q, sigma_n)

    k        = E[Y] = exp(jump_mean + 0.5*jump_std^2) - 1   (compensator)
    lambda'  = jump_intensity * (1 + k)                     (NOT jump_intensity
                                                               itself -- see below)
    q_n      = Poisson(lambda' * T) pmf at n
    sigma_n  = sqrt(sigma^2 + n*jump_std^2 / T)
    r_n      = r - jump_intensity*k + n*ln(1 + k) / T

BS_call(..., r_n, q, sigma_n) is the ordinary dividend-adjusted Black-
Scholes formula (d1 uses r_n - q, the S0 leg discounts at q, the K leg
discounts at r_n); the continuous dividend yield q enters exactly where
it always does in Black-Scholes and nowhere else -- it does not interact
with the jump compensator k, which is a pure, dividend-independent
proportional-price-change expectation.

Conditional on exactly n jumps having occurred by T, ln(S_T) is EXACTLY
normal (the diffusion's own lognormal terminal distribution, convolved
with the sum of n iid jump log-sizes, itself exactly Normal(n*jump_mean,
n*jump_std^2)) -- so each term is an ordinary Black-Scholes price under
an n-dependent effective (r_n, sigma_n). The weight sequence is the
RISK-NEUTRAL-ADJUSTED intensity lambda' = jump_intensity*(1+k), not the
physical jump_intensity used by the simulator in
`stochastica.jump_diffusion` -- using the physical intensity here is a
real, easy-to-make error (it looks equally plausible from the formula's
shape) that was caught, before writing this module, by deriving the
closed form directly from first-principles conditional expectations
(getting the S0-term and the K-term's weights to come out identical
confirms lambda*(1+k) is the correct single shared weight) and by
checking BOTH candidates against an independently-coded, high-path-count
Monte Carlo simulation: the physical-intensity candidate was rejected
(off by ~40x its own Monte Carlo standard error at a representative
parameter set), the adjusted one was not.

Cross-checked the same way `volterra.heston_pricer` was: against the
zero-jump limit (Black-Scholes), against Monte Carlo simulation of the
INDEPENDENTLY-written `stochastica.jump_diffusion` module, and against
put-call parity (puts are priced through parity applied to the call, not
a second derivation).

SDE-12 ("test solver behavior on extreme but admissible inputs... no
silent NaN, Inf or unbounded accepted paths") found two real, confirmed
crashes at jump parameter combinations `MertonJumpParams` itself does not
reject (it only checks positivity, not plausibility):

  - A very negative `jump_mean` drives the compensator k = exp(jump_mean
    + 0.5*jump_std^2) - 1 to underflow to exactly -1.0, making
    `math.log(1.0 + k)` a domain error (1+k == 0.0) inside the per-term
    loop.
  - A large `jump_std` drives k to an astronomically large (but still
    finite) value; `adjusted_intensity` and `r_n` inherit that magnitude,
    and `math.exp(-r_n * maturity)` eventually overflows.

Both are caught upfront in `merton_call_price`, before entering the
per-term loop, with a clear `ValueError` naming which check failed,
rather than letting a cryptic `OverflowError` or domain-error
`ValueError` escape from deep inside the loop. A third guard caps
`poisson_mean` itself: without it, a large-`jump_std` case can drive
`_poisson_term_count` to request an uncomputable number of loop
iterations (confirmed directly: jump_std=10 at otherwise ordinary
parameters pushes `poisson_mean` past 1e21) long before the per-term
`exp` overflow would even be reached.

SDE-12 property-based testing (wide-range, not just the two cases
above) found a FOURTH, independent overflow path that survives all
three guards: `r_n = r - jump_intensity*k + n*ln(1+k)/T` can already be
hugely negative at n=0 (`r_0 = r - jump_intensity*k`) purely because
`jump_intensity*k` is large, even when `k` itself is finite and
`poisson_mean` is well within `_MAX_POISSON_MEAN` (confirmed directly:
jump_intensity=1, jump_mean=0, jump_std=4, T=1 gives poisson_mean~2982,
comfortably under the cap, yet `r_0` ~ -2980, overflowing
`math.exp(-r_n*maturity)` at the very first term). Since `r_n` is affine
in `n`, its two endpoints (n=0 and n=n_terms-1) bound its range exactly,
so checking both upfront -- rather than guarding inside the loop --
catches every case cheaply.

VAL-11's property-based put-call-parity metamorphic test (not the
SDE-12 extreme-input probe above -- this is a perfectly ordinary,
non-extreme input) found a FIFTH, independent crash: `jump_intensity ==
0.0` (a valid "no jumps at all" parameter `MertonJumpParams` explicitly
permits) makes `poisson_mean` exactly `0.0`, and the per-term loop's
`n=1` iteration then computes `math.log(poisson_mean) ==
math.log(0.0)`, which Python's `math.log` raises on rather than
returning `-inf`. Mathematically, `poisson_mean == 0.0` means the
ENTIRE Poisson pmf's mass sits at `n=0` (every `n >= 1` term has exactly
zero weight), so the fix is to collapse the loop to its single `n=0`
term directly in that case, rather than guard the log call -- confirmed
to reduce EXACTLY (not approximately) to this module's own Black-Scholes
degenerate limit.
"""

from __future__ import annotations

import math

from scipy.stats import norm

from prometheus.stochastica.jump_diffusion import MertonJumpParams
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

_MAX_POISSON_MEAN = 1.0e5
"""Above this, `_poisson_term_count` would request an impractical (or
outright uncomputable, for a truly extreme input) number of loop
iterations -- confirmed directly: jump_std=10 at otherwise ordinary
jump_intensity/jump_mean pushes poisson_mean past 1e21. 1e5 is already a
generous ceiling (any realistic calibration has poisson_mean well under
10) and still finishes in well under a second."""

_MAX_EXP_ARG = 700.0
"""Safely below float64's ~709.78 overflow threshold for math.exp --
same constant and rationale as `volterra.barrier_options._MAX_EXP_ARG`."""


def _poisson_term_count(poisson_mean: float, min_terms: int = 50) -> int:
    """How many terms of the Poisson sum to keep: enough that the
    discarded tail (beyond mean + 10 standard deviations) is utterly
    negligible, even for a large lambda'*T this module has not been
    exercised at -- not a hardcoded guess sized only for "typical"
    parameters."""
    return max(min_terms, int(poisson_mean + 10.0 * math.sqrt(poisson_mean + 1.0)) + 20)


def merton_call_price(
    s0: float,
    strike: float,
    maturity: float,
    risk_free_rate: float,
    dividend_yield: float,
    params: MertonJumpParams,
) -> float:
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if strike <= 0:
        raise ValueError("strike must be positive")
    if maturity <= 0:
        raise ValueError("maturity must be positive")

    k = params.jump_compensator()
    if not math.isfinite(k) or 1.0 + k <= 0.0:
        raise ValueError(
            f"jump compensator k = exp(jump_mean + 0.5*jump_std^2) - 1 = {k} makes "
            "1 + k non-positive or non-finite, so log(1+k) is undefined -- "
            f"jump_mean={params.jump_mean} is too extreme for this closed form"
        )
    adjusted_intensity = params.jump_intensity * (1.0 + k)
    poisson_mean = adjusted_intensity * maturity
    if not math.isfinite(poisson_mean) or poisson_mean > _MAX_POISSON_MEAN:
        raise ValueError(
            f"adjusted Poisson mean jump_intensity*(1+k)*maturity = {poisson_mean} "
            f"exceeds the practical {_MAX_POISSON_MEAN:.0g} limit for summing this closed "
            f"form -- jump_intensity={params.jump_intensity}, jump_mean={params.jump_mean}, "
            f"jump_std={params.jump_std} is too extreme for this closed form"
        )
    # poisson_mean == 0.0 (jump_intensity == 0.0, a perfectly ordinary,
    # non-extreme "no jumps at all" parameter MertonJumpParams explicitly
    # allows) means ALL of the Poisson pmf's mass sits at n=0: every
    # n >= 1 term has exactly zero weight, so the sum degenerates to its
    # single n=0 term. _poisson_term_count's own `min_terms=50` floor
    # would otherwise still request 50 iterations, and the n=1 iteration
    # below computes math.log(poisson_mean) = math.log(0.0), which Python
    # raises on rather than returning -inf -- a real, previously-untested
    # crash on a mainstream input, not an extreme one (found by
    # VAL-11's property-based put-call-parity metamorphic test, not the
    # SDE-12 extreme-input probe, since jump_intensity=0 is not extreme).
    n_terms = 1 if poisson_mean == 0.0 else _poisson_term_count(poisson_mean)

    log_one_plus_k = math.log(1.0 + k)
    r_n0 = risk_free_rate - params.jump_intensity * k
    r_n_last = r_n0 + (n_terms - 1) * log_one_plus_k / maturity
    most_negative_r_n = min(r_n0, r_n_last)
    if -most_negative_r_n * maturity > _MAX_EXP_ARG:
        raise ValueError(
            f"risk_free_rate={risk_free_rate}, jump_intensity={params.jump_intensity}, "
            f"jump_mean={params.jump_mean} and jump_std={params.jump_std} combine to push "
            f"the per-term effective rate r_n as low as {most_negative_r_n}, beyond what "
            f"float64 can represent as a finite math.exp(-r_n*maturity) term "
            f"(overflows past ~{_MAX_EXP_ARG:.0f}) -- this input combination has no "
            "computable answer under this closed form"
        )

    total = 0.0
    log_weight = -poisson_mean  # running log(e^{-poisson_mean} * poisson_mean^n / n!)
    for n in range(n_terms):
        if n > 0:
            log_weight += math.log(poisson_mean) - math.log(n)
        weight = math.exp(log_weight)
        sigma_n = math.sqrt(params.sigma**2 + n * params.jump_std**2 / maturity)
        r_n = r_n0 + n * log_one_plus_k / maturity

        d1 = (
            math.log(s0 / strike) + (r_n - dividend_yield + 0.5 * sigma_n**2) * maturity
        ) / (sigma_n * math.sqrt(maturity))
        d2 = d1 - sigma_n * math.sqrt(maturity)
        bs_call = s0 * math.exp(-dividend_yield * maturity) * norm.cdf(
            d1
        ) - strike * math.exp(-r_n * maturity) * norm.cdf(d2)
        total += weight * bs_call

    return total


def merton_option_price(
    market: MarketSnapshot, option: EuropeanOption, params: MertonJumpParams
) -> float:
    """`market.volatility` is not used -- the diffusion volatility comes
    from `params.sigma` instead, the same deliberate convention
    `volterra.heston_pricer.heston_option_price` already uses."""
    call = merton_call_price(
        market.spot,
        option.strike,
        option.maturity,
        market.risk_free_rate,
        market.dividend_yield,
        params,
    )
    if option.option_type == "call":
        return call
    forward_value = market.spot * math.exp(
        -market.dividend_yield * option.maturity
    ) - option.strike * math.exp(-market.risk_free_rate * option.maturity)
    return call - forward_value
