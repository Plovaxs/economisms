"""Single-barrier European option pricing (PRI-08: "barrier option with
discretization correction"), via a from-scratch reflection-principle
derivation of the GBM survival density, plus the Broadie-Glasserman-Kou
(1997) continuity correction for discretely (rather than continuously)
monitored barriers.

Derivation (continuous monitoring). Under Q, ln(S_t/S0) = nu*t + sigma*W_t
with nu = r - q - 0.5*sigma^2. Writing X_t = ln(S_t/S0) and h =
ln(H/S0), the classical reflection principle for drifted Brownian motion
gives the sub-probability density of X_T conditional on the path never
crossing h:

  down barrier (survive means X_t > h for all t in [0,T]):
    f(x) = phi(x; nu*T, sigma^2*T) - exp(2*nu*h/sigma^2) * phi(x; 2h+nu*T, sigma^2*T),   x > h

  up barrier (survive means X_t < h for all t in [0,T]):
    f(x) = phi(x; nu*T, sigma^2*T) - exp(2*nu*h/sigma^2) * phi(x; 2h+nu*T, sigma^2*T),   x < h

(phi(.; mean, var) is the ordinary normal density.) The knock-out price is
then the discounted integral of the option payoff against this density;
the knock-in price is obtained via parity against the Black-Scholes
vanilla (in + out = vanilla), the same convention already used for puts in
`heston_pricer` and `merton_pricer`.

This was derived here from the reflection principle directly rather than
transcribed from a reference table (the classical Reiner-Rubinstein
closed form has ~8 case-dependent sub-formulas that are easy to
mis-transcribe from memory) and was verified, before being trusted,
against: an independent Brownian-bridge continuity-corrected Monte Carlo
(a genuinely different, non-closed-form method; the naive "check only at
discrete grid points" Monte Carlo is NOT independent evidence here --
it has its own O(1/sqrt(n_steps)) discretization bias, which is exactly
what the Brownian-bridge weighting removes), in-out parity, and the
H -> 0 / H -> S0 degenerate limits (recovering the vanilla price and zero,
respectively).

Discrete-monitoring correction. A real barrier is observed at discrete
times (e.g. daily closes), not continuously, so it is *less* likely to be
breached than a continuously-monitored barrier at the same level --
continuous monitoring catches excursions between observations that
discrete monitoring misses. The Broadie-Glasserman-Kou (1997) correction
compensates for this by repricing the CONTINUOUS formula at a shifted
barrier level moved away from the spot:

  H_adjusted = H * exp(+-beta * sigma * sqrt(T / n_observations))

with beta = -zeta(1/2) / sqrt(2*pi) ~ 0.582597 (Riemann zeta; confirmed
here via scipy.special.zeta(0.5)), sign + for an up barrier and - for a
down barrier (both move the barrier further from the spot). Verified
against Monte Carlo of the actual discretely-monitored process (checked
only at the n_observations sample times, which is by definition the exact
discrete-monitoring target -- no bridge correction needed for that
ground truth): across a grid of down/up, in/out, call/put, and strikes on
both sides of the barrier, the correction reduced pricing error by roughly
one to two orders of magnitude versus using the uncorrected continuous
formula directly, confirming both the sign and the magnitude of the shift.

Not covered: rebates (payment on knockout/failure to knock in), double
barriers, and barriers combined with American exercise. `market.mu` is
irrelevant here (it never appears); like `black_scholes_price` and the
other VOLTERRA pricers, only `market.risk_free_rate`, `market.dividend_yield`
and `market.volatility` drive the price.

SDE-12 ("test solver behavior on extreme but admissible inputs... no
silent NaN, Inf or unbounded accepted paths") found a real correctness
bug, not just a crash, in the integration-bound logic: the free integration
bound was built around log-return 0 ("the spot's own typical range"), but
the TRUE mean of ln(S_T/S0) is nu*maturity, not 0. Whenever |nu*maturity|
is not negligible next to the integration span -- at very small
volatility, where the span itself shrinks faster than the drift does --
the real probability mass sits entirely outside the integrated region and
`quad` silently integrates a window containing none of it, returning 0.0
with no error at all. Confirmed directly: at volatility=1e-8 with a down
barrier far below spot (which should never be reachable, so the price
should equal the vanilla price to high precision), the unfixed code
returned exactly 0.0 instead of ~2.9554. The fix centers the free bound on
nu*maturity instead of 0; re-verified against the same case (now matching
the vanilla price to 7 significant figures) and against the original
suite of in-out-parity/Monte-Carlo/degenerate-limit checks, all of which
still pass since realistic parameters always had span >> |nu*maturity| and
so were never affected by the mis-centering.

A second, genuinely different failure survives even the corrected
centering: at a large enough risk-free rate and maturity (e.g. r=10,
T=100), ln(forward price) itself exceeds roughly 700 -- the point beyond
which `math.exp` raises `OverflowError` in double precision -- so no
integration-bound choice can produce a finite, correct answer; the true
price is not representable in float64 at all. A third, independent
overflow path lives inside the reflected-image density's own weight term
(`exp(2*nu*barrier_log/sigma^2)`), triggered by a very negative rate
combined with small volatility, and does not depend on the integration
bounds at all. Rather than let a cryptic `OverflowError` escape from
deep inside `scipy.integrate.quad`, `barrier_call_or_put_price_continuous`
checks all of these upfront and raises a clear, explanatory `ValueError`
instead.

Fixing the centering bug exposed a FOURTH, independent, previously
dormant problem: `scipy.integrate.quad`'s adaptive algorithm is not told
that the payoff has a kink at `x = ln(strike/s0)` (a call/put payoff is
not differentiable there). Depending on exactly where the integration
bounds happen to fall relative to that kink, `quad` can silently converge
to a materially wrong value with a deceptively small reported error
estimate -- confirmed directly: at the H -> 0 degenerate limit, the
centered bounds [-5.99, 6.01] gave 9.4037 against an independently
computed (fine-grid Simpson's rule, 4,000,001 points, and `quad` with an
explicit `points=` hint) ground truth of 9.4134, a 0.1% error with no
warning at all. This was latent in the ORIGINAL (mis-centered) bounds
too -- it simply was not triggered by the specific cases exercised before
SDE-12's stress testing. The fix passes `points=[kink]` to `quad`
whenever the kink falls inside the integration range, which `quad` uses
to force a subdivision exactly there; re-verified against the Simpson's-
rule ground truth (matching to 10+ significant figures) and against the
full existing test suite (in-out parity, Monte Carlo, both degenerate
limits, Greeks), all still passing.

A FIFTH, independent overflow path survived all four fixes above and
was only found by re-running SDE-12's property suite with a fresh
Hypothesis seed: the discount-factor exponent `-risk_free_rate*maturity`
itself (used to discount the knock-out integral, and, separately, in
BOTH terms of the knock-in vanilla-parity closed form) was never checked
against `_MAX_EXP_ARG` at all -- only `upper` and the reflected-weight
exponent were. Confirmed directly: rate=-5.0, maturity=142.0 makes
`exp(-rate*maturity) = exp(710)` overflow, raising an uncaught
`OverflowError` (a) from `barrier_call_or_put_price_continuous`'s own
discounting of the knock-out integral, whenever `lower < upper` so that
branch actually runs, and (b), independently, from the knock-in vanilla
parity's `strike*exp(-risk_free_rate*maturity)` and
`s0*exp(-dividend_yield*maturity)` terms, which run whenever `knock ==
"in"` regardless of whether the knock-out branch above triggered at all
(including when it was skipped via the `lower >= upper` short-circuit,
since that branch deliberately avoids computing a discount factor it
does not need). Fixed by folding the discount exponent into the
knock-out branch's existing overflow check, and adding a second,
independent check of both the discount and dividend exponents right
before the knock-in vanilla parity computation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from scipy import integrate
from scipy.stats import norm

from prometheus.numerics import require_finite
from prometheus.volterra.instruments import OptionType
from prometheus.volterra.market import MarketSnapshot

BarrierDirection = Literal["down", "up"]
BarrierKnock = Literal["out", "in"]

_BGK_BETA = 0.5825971579390108  # -zeta(1/2) / sqrt(2*pi)
_INTEGRATION_STD_DEVS = 30.0
_MAX_EXP_ARG = 700.0
"""Safely below float64's exp() overflow threshold (~709.78), with
margin -- the point beyond which a log-return is not representable as a
finite price at all, not merely hard to integrate accurately."""


@dataclass(frozen=True, slots=True)
class BarrierOption:
    strike: float
    maturity: float
    option_type: OptionType
    barrier: float
    direction: BarrierDirection
    knock: BarrierKnock

    def __post_init__(self) -> None:
        require_finite(strike=self.strike, maturity=self.maturity, barrier=self.barrier)
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got {self.option_type!r}")
        if self.barrier <= 0:
            raise ValueError("barrier must be positive")
        if self.direction not in ("down", "up"):
            raise ValueError(f"direction must be 'down' or 'up', got {self.direction!r}")
        if self.knock not in ("out", "in"):
            raise ValueError(f"knock must be 'out' or 'in', got {self.knock!r}")


def _survival_density(
    x: float, maturity: float, nu: float, sigma: float, barrier_log: float
) -> float:
    """Unconditional sub-density of X_T = ln(S_T/S0) given the barrier was
    never crossed up to T -- valid on whichever side of barrier_log is the
    admissible (not-yet-crossed) region; callers restrict the integration
    domain accordingly, so this is not masked to zero here."""
    var = sigma**2 * maturity
    mean0 = nu * maturity
    g0 = norm.pdf(x, loc=mean0, scale=math.sqrt(var))
    g_reflected = norm.pdf(x, loc=mean0 + 2 * barrier_log, scale=math.sqrt(var))
    weight = math.exp(2 * nu * barrier_log / sigma**2)
    return g0 - weight * g_reflected


def barrier_call_or_put_price_continuous(
    s0: float,
    strike: float,
    barrier: float,
    maturity: float,
    risk_free_rate: float,
    dividend_yield: float,
    volatility: float,
    option_type: OptionType,
    direction: BarrierDirection,
    knock: BarrierKnock,
) -> float:
    """Continuously-monitored single-barrier price, no rebate."""
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if strike <= 0:
        raise ValueError("strike must be positive")
    if barrier <= 0:
        raise ValueError("barrier must be positive")
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    if direction == "down" and barrier >= s0:
        raise ValueError(f"down barrier {barrier} must be strictly below spot {s0}")
    if direction == "up" and barrier <= s0:
        raise ValueError(f"up barrier {barrier} must be strictly above spot {s0}")

    nu = risk_free_rate - dividend_yield - 0.5 * volatility**2
    barrier_log = math.log(barrier / s0)
    span = _INTEGRATION_STD_DEVS * volatility * math.sqrt(maturity)

    def payoff(x: float) -> float:
        s = s0 * math.exp(x)
        return max(s - strike, 0.0) if option_type == "call" else max(strike - s, 0.0)

    def integrand(x: float) -> float:
        return payoff(x) * _survival_density(x, maturity, nu, volatility, barrier_log)

    # The free bound must reach far enough past the barrier AND far enough
    # past where the probability mass actually sits -- which is centered
    # on nu*maturity (the true mean of ln(S_T/S0)), NOT on log-return 0.
    # Centering on 0 instead (an earlier version of this function did)
    # silently returns 0.0 whenever |nu*maturity| is not negligible next
    # to the integration span -- confirmed directly at volatility=1e-8,
    # where it returned 0.0 instead of matching the vanilla price to high
    # precision (see this module's own docstring).
    mean0 = nu * maturity
    if direction == "down":
        lower, upper = max(barrier_log, mean0 - span), mean0 + span
    else:
        lower, upper = mean0 - span, min(barrier_log, mean0 + span)

    # The drift-centered window [mean0-span, mean0+span] can fail to
    # overlap the survival region AT ALL (lower ends up > upper) when the
    # drift is extreme enough to point the real probability mass entirely
    # to the wrong side of the barrier -- confirmed directly with a large
    # negative rate and small volatility (down barrier). That means
    # survival is negligible (breach is all but certain): the knock-out
    # price is ~0, computed directly rather than via a degenerate or
    # inverted integration range.
    discount_exponent = -risk_free_rate * maturity
    dividend_exponent = -dividend_yield * maturity

    if lower >= upper:
        out_price = 0.0
    else:
        # A second, different failure survives correct centering: at a
        # large enough rate/maturity the TRUE price is not representable
        # in float64 at all (ln(forward price) itself exceeds exp()'s
        # overflow point) -- checking `upper` suffices since payoff's
        # exp(x) is increasing in x and upper is always the larger end.
        # A third, independent overflow path lives inside
        # `_survival_density`'s own reflected-image weight,
        # `exp(2*nu*barrier_log/volatility**2)`, which does not depend on
        # x at all and so is not fixed by any choice of integration
        # bounds -- confirmed directly with a very negative rate and
        # small volatility. A fifth overflow path (see this module's own
        # docstring) lives in the discount factor itself,
        # `exp(-risk_free_rate*maturity)`, used to discount the integral
        # below -- folded into the same upfront check. Only the POSITIVE
        # direction risks overflow (`math.exp` underflows harmlessly to
        # 0.0 for very negative arguments, which is mathematically
        # correct here, not an error); fail closed with a clear reason
        # for any of these three rather than let a cryptic OverflowError
        # escape from inside scipy.integrate.quad or math.exp.
        reflected_weight_exponent = 2 * nu * barrier_log / volatility**2
        if max(upper, reflected_weight_exponent, discount_exponent) > _MAX_EXP_ARG:
            raise ValueError(
                f"risk_free_rate={risk_free_rate}, dividend_yield={dividend_yield}, "
                f"volatility={volatility} and maturity={maturity} combine to push the "
                f"relevant log-return range to [{lower:.1f}, {upper:.1f}] (reflected-weight "
                f"exponent {reflected_weight_exponent:.1f}, discount exponent "
                f"{discount_exponent:.1f}), beyond what float64 can represent as a finite "
                f"price (exp() overflows past ~{_MAX_EXP_ARG:.0f}) -- this input combination "
                "has no computable answer under this closed form"
            )

        # The payoff has a kink at this point (not differentiable);
        # telling `quad` about it explicitly, rather than leaving its
        # adaptive subdivision to discover it on its own, is what
        # actually fixes the dormant wrong-answer bug the centering fix
        # above exposed (see this module's own docstring) -- confirmed
        # directly against an independent fine-grid Simpson's-rule
        # ground truth.
        kink = math.log(strike / s0)
        points = [kink] if lower < kink < upper else None

        out_price = math.exp(discount_exponent) * integrate.quad(
            integrand, lower, upper, limit=300, points=points
        )[0]

    if knock == "out":
        return out_price

    # The knock-in vanilla-parity closed form below uses the SAME
    # discount exponent, plus an independent dividend-yield exponent --
    # both overflow-checked again here since this branch runs whenever
    # knock == "in", independently of whichever path (including the
    # lower >= upper short-circuit, which deliberately never computes a
    # discount factor) out_price took above (see this module's own
    # docstring, fifth overflow path).
    if max(discount_exponent, dividend_exponent) > _MAX_EXP_ARG:
        raise ValueError(
            f"risk_free_rate={risk_free_rate}, dividend_yield={dividend_yield} and "
            f"maturity={maturity} push a discount or dividend exponent (discount "
            f"{discount_exponent:.1f}, dividend {dividend_exponent:.1f}) beyond what "
            f"float64 can represent (exp() overflows past ~{_MAX_EXP_ARG:.0f}) -- this "
            "knock-in vanilla-parity term has no computable answer under this closed form"
        )

    d1 = (
        math.log(s0 / strike) + (risk_free_rate - dividend_yield + 0.5 * volatility**2) * maturity
    ) / (volatility * math.sqrt(maturity))
    d2 = d1 - volatility * math.sqrt(maturity)
    if option_type == "call":
        vanilla = s0 * math.exp(-dividend_yield * maturity) * norm.cdf(d1) - strike * math.exp(
            -risk_free_rate * maturity
        ) * norm.cdf(d2)
    else:
        vanilla = strike * math.exp(-risk_free_rate * maturity) * norm.cdf(-d2) - s0 * math.exp(
            -dividend_yield * maturity
        ) * norm.cdf(-d1)
    return vanilla - out_price


def barrier_option_price(market: MarketSnapshot, option: BarrierOption) -> float:
    """`market.volatility` IS used here (unlike the Heston/Merton pricers):
    this model has no separate stochastic-volatility or jump parameter
    object, so the market snapshot's own volatility is the diffusion
    volatility, exactly as in `black_scholes_price`."""
    return barrier_call_or_put_price_continuous(
        market.spot,
        option.strike,
        option.barrier,
        option.maturity,
        market.risk_free_rate,
        market.dividend_yield,
        market.volatility,
        option.option_type,
        option.direction,
        option.knock,
    )


def broadie_glasserman_kou_adjusted_barrier(
    barrier: float,
    direction: BarrierDirection,
    volatility: float,
    maturity: float,
    n_observations: int,
) -> float:
    if barrier <= 0:
        raise ValueError("barrier must be positive")
    if n_observations < 1:
        raise ValueError("n_observations must be a positive integer")
    shift = _BGK_BETA * volatility * math.sqrt(maturity / n_observations)
    return barrier * math.exp(-shift) if direction == "down" else barrier * math.exp(shift)


def discretely_monitored_barrier_option_price(
    market: MarketSnapshot, option: BarrierOption, n_observations: int
) -> float:
    """Approximates the price of a barrier monitored only at
    `n_observations` equally-spaced times (not continuously) by applying
    the Broadie-Glasserman-Kou continuity correction to the barrier level
    and repricing with the continuous-monitoring formula."""
    adjusted_barrier = broadie_glasserman_kou_adjusted_barrier(
        option.barrier, option.direction, market.volatility, option.maturity, n_observations
    )
    adjusted_option = BarrierOption(
        strike=option.strike,
        maturity=option.maturity,
        option_type=option.option_type,
        barrier=adjusted_barrier,
        direction=option.direction,
        knock=option.knock,
    )
    return barrier_option_price(market, adjusted_option)
