"""Heston (1993) European option pricing via the characteristic function
(PRI-04), extending the GBM-only VOLTERRA pricing ladder (Black-Scholes,
forwards, American binomial) to a genuinely stochastic-volatility model.

Uses the "little trap" branch-stable formulation (Albrecher, Mayer,
Schoutens & Tistaert, 2007, "The Little Heston Trap"; equivalently
Gatheral, 2006, "The Volatility Surface", sec 2.1): the ORIGINAL Heston
(1993) characteristic function has a complex-logarithm branch cut that a
naive implementation can land on, silently returning a wrong price for
certain (strike, maturity, parameter) combinations -- not an error, a
*wrong number*, which is why that paper exists. The branch-stable `g` used
here (`(b - d) / (b + d)`, not its reciprocal) avoids that discontinuity.

`heston_characteristic_function` is a function of a general COMPLEX
argument `u`, not just real u: the P1/P2 call-pricing decomposition below
evaluates it at `u - i` as well as at real u, reusing the identical
formula (no second, differently-parameterized characteristic function is
needed, unlike some expositions of Heston's own original P1/P2 split).

Cross-checked, not merely asserted correct, against four independent
things that do not require trusting this module's own derivation:
  - phi(0) == 1 and phi(-i) == S0*exp((r-q)*T) -- cheap algebraic
    identities any correct characteristic function must satisfy exactly.
  - Put-call parity (Call - Put == S0*exp(-qT) - K*exp(-rT)) -- a
    model-independent identity; puts are priced through it rather than a
    second, separately-derived P1'/P2' formula.
  - The degenerate limit (vol-of-vol -> 0, v0 == theta == sigma^2):
    Heston collapses to Black-Scholes, confirmed to converge to the
    existing closed-form `volterra.black_scholes` price.
  - Monte Carlo: the Fourier price falls within a few standard errors of
    simulating `stochastica.heston.simulate_heston_paths` (an
    independently-written module, not derived from this one) and
    averaging discounted terminal payoffs.

`params: HestonParams` supplies ONLY the variance-process shape
(kappa, theta, xi, rho, v0); its own `mu` field is NOT used here -- that
field is `simulate_heston_paths`' real/risk-neutral simulation drift, a
different concept from this module's pricing drift, which is always
`market.risk_free_rate - market.dividend_yield` (the standard
risk-neutral convention every other VOLTERRA pricer already uses).

Not covered: Heston model CALIBRATION (fitting kappa/theta/xi/rho/v0 to
observed market prices) is a separate, larger undertaking -- this module
only prices a European option under ALREADY-SPECIFIED parameters, the
reverse direction of `volterra.calibration`'s implied-volatility solve.
No FFT/COS multi-strike acceleration either: each call prices one strike
via two adaptive numerical integrals (fine for the use here, not for
pricing an entire options chain at once).

SDE-12 ("test solver behavior on extreme but admissible inputs... no
silent NaN, Inf or unbounded accepted paths") property-based testing
found a real `ZeroDivisionError` reachable at an admissible parameter
combination `HestonParams` does not reject: whenever `kappa == rho*xi`
exactly, `heston_characteristic_function(-1j, ...)` -- evaluated
directly both by `heston_risk_neutral_probabilities` (as the `phi_neg_i`
normalizing constant) and by this module's own identity test -- hits
`b == d == 0` simultaneously (at u=-i, `iu + u**2` is identically 0 for
ANY parameters, so `d = sqrt(b**2) = |b|`; when additionally `b == 0`
this makes BOTH `b+d` and `b-d` exactly 0, a genuine removable 0/0
singularity in the `g = (b-d)/(b+d)` formulation, not merely a precision
issue algebraic rearrangement of `g` can route around). Rather than a
fragile near-zero epsilon patch, `u == -1j` is special-cased to the
already-known, model-independent martingale identity phi(-i) =
E[S_T] = S0*exp((r-q)*T) -- exact for every parameter choice, not an
approximation, and already relied upon (this module's own docstring
above, and `heston_risk_neutral_probabilities`' normalization) as a
correctness check on the general formula at non-degenerate parameters.

The same property-based testing found three further SDE-12 issues, all
reachable at a long enough `maturity` (confirmed directly around
maturity=142-145) combined with an otherwise ordinary rate/kappa/xi/rho/v0:
  - The plain discount factors in `heston_call_price` and the put-parity
    branch of `heston_option_price` (`math.exp(-rate*maturity)`) overflow
    unconditionally, the same class of bug already fixed in
    `volterra.black_scholes` and `volterra.asian_options` -- fixed the
    same way, via `_guarded_exp`.
  - The phi(-i) identity shortcut above overflows for the same reason
    when `(risk_free_rate - dividend_yield) * maturity` itself is too
    large -- also routed through `_guarded_exp`.
  - Separately, and NOT fixable the same way: at a long enough maturity,
    the adaptive quadrature in `heston_risk_neutral_probabilities` probes
    large real `u` values where the "little trap" formula's own `c`/`cap_d`
    terms suffer catastrophic cancellation, overflowing `cmath.exp` or
    dividing by an exactly-zero `(1j*u*phi_neg_i)` -- even though the TRUE
    characteristic function satisfies |phi(u)| <= 1 for every real u (it
    is the characteristic function of a real-valued random variable), so
    the overflow is a pure numerical artifact of this formula's
    evaluation, not a genuinely unrepresentable mathematical answer. No
    closed-form bound on exactly which (kappa, xi, rho, v0, maturity)
    combinations trigger this was derived (unlike the exact bounds found
    for `barrier_options`/`merton_pricer`); instead, `OverflowError` and
    `ZeroDivisionError` escaping the quadrature are caught and converted
    to a clear, named `ValueError` rather than silently producing a wrong
    number or crashing with a cryptic exception from deep inside
    `scipy.integrate.quad` -- an FFT/COS-based evaluation (already noted
    above as out of this module's scope) would likely be more robust at
    such extreme maturities.
"""

from __future__ import annotations

import cmath
import math

import numpy as np
from scipy import integrate

from prometheus.stochastica.heston import HestonParams
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot

_LOWER_INTEGRATION_BOUND = 1e-10
_QUAD_SUBDIVISION_LIMIT = 200

_MAX_EXP_ARG = 700.0
"""Safely below float64's ~709.78 overflow threshold for math.exp --
same constant and rationale as `volterra.barrier_options._MAX_EXP_ARG`."""


def _guarded_exp(exponent: float, context: str) -> float:
    """math.exp(exponent), raising a clear ValueError instead of a
    cryptic OverflowError when it would overflow float64 (SDE-12)."""
    if exponent > _MAX_EXP_ARG:
        raise ValueError(
            f"{context} pushes an internal exponential term to exp({exponent:.1f}), "
            "beyond what float64 can represent -- this input combination has no "
            "computable answer under this closed form"
        )
    return math.exp(exponent)


def heston_characteristic_function(
    u: complex,
    s0: float,
    maturity: float,
    risk_free_rate: float,
    dividend_yield: float,
    params: HestonParams,
) -> complex:
    """phi(u) = E[exp(i*u*ln(S_T))] under the risk-neutral measure, for
    any complex `u`. See this module's own docstring for the branch-
    stable ("little trap") derivation."""
    kappa, theta, xi, rho, v0 = params.kappa, params.theta, params.xi, params.rho, params.v0
    if u == -1j:
        # See this module's docstring (SDE-12): the general formula below
        # has a genuine removable 0/0 singularity here whenever
        # kappa == rho*xi. This identity is exact for every parameter
        # choice, not just a workaround for that one coincidence.
        return s0 * _guarded_exp((risk_free_rate - dividend_yield) * maturity, "phi(-i)'s forward")
    iu = 1j * u
    b = kappa - rho * xi * iu
    d = cmath.sqrt(b**2 + xi**2 * (iu + u**2))
    g = (b - d) / (b + d)
    exp_dt = cmath.exp(-d * maturity)
    c = (kappa * theta / xi**2) * (
        (b - d) * maturity - 2 * cmath.log((1 - g * exp_dt) / (1 - g))
    )
    cap_d = ((b - d) / xi**2) * (1 - exp_dt) / (1 - g * exp_dt)
    drift = (risk_free_rate - dividend_yield) * maturity
    return cmath.exp(1j * u * (math.log(s0) + drift) + c + cap_d * v0)


def heston_risk_neutral_probabilities(
    s0: float,
    strike: float,
    maturity: float,
    risk_free_rate: float,
    dividend_yield: float,
    params: HestonParams,
) -> tuple[float, float]:
    """(P1, P2): Heston's own named decomposition of the call price,
    Call = S0*exp(-qT)*P1 - K*exp(-rT)*P2. P2 is the risk-neutral
    probability the option is exercised (Q(S_T > K)), so it must lie in
    [0, 1] -- checked directly in tests, not just inferred from a price
    looking reasonable."""
    log_k = math.log(strike)

    def integrand_p2(u: float) -> float:
        phi = heston_characteristic_function(
            u, s0, maturity, risk_free_rate, dividend_yield, params
        )
        value = cmath.exp(-1j * u * log_k) * phi / (1j * u)
        return float(value.real)

    def integrand_p1(u: float) -> float:
        phi_shifted = heston_characteristic_function(
            u - 1j, s0, maturity, risk_free_rate, dividend_yield, params
        )
        phi_neg_i = heston_characteristic_function(
            -1j, s0, maturity, risk_free_rate, dividend_yield, params
        )
        value = cmath.exp(-1j * u * log_k) * phi_shifted / (1j * u * phi_neg_i)
        return float(value.real)

    try:
        p2_integral, _ = integrate.quad(
            integrand_p2, _LOWER_INTEGRATION_BOUND, np.inf, limit=_QUAD_SUBDIVISION_LIMIT
        )
        p1_integral, _ = integrate.quad(
            integrand_p1, _LOWER_INTEGRATION_BOUND, np.inf, limit=_QUAD_SUBDIVISION_LIMIT
        )
    except (OverflowError, ZeroDivisionError) as exc:
        # See this module's docstring (SDE-12): the TRUE characteristic
        # function always satisfies |phi(u)| <= 1 for real u, so this is
        # a numerical artifact of evaluating the "little trap" formula at
        # the large real u the quadrature probes, not a genuinely
        # unrepresentable mathematical answer -- but no closed-form
        # bound on exactly which inputs trigger it was derived, so it is
        # surfaced as a clear rejection rather than guessed around.
        raise ValueError(
            f"kappa={params.kappa}, theta={params.theta}, xi={params.xi}, rho={params.rho}, "
            f"v0={params.v0} combined with maturity={maturity} make the Heston characteristic "
            f"function numerically unstable under this module's adaptive-quadrature evaluation "
            f"({type(exc).__name__}: {exc}) -- this input combination has no computable answer "
            "under this implementation"
        ) from exc
    return 0.5 + p1_integral / math.pi, 0.5 + p2_integral / math.pi


def heston_call_price(
    s0: float,
    strike: float,
    maturity: float,
    risk_free_rate: float,
    dividend_yield: float,
    params: HestonParams,
) -> float:
    if s0 <= 0:
        raise ValueError("s0 must be positive")
    if strike <= 0:
        raise ValueError("strike must be positive")
    if maturity <= 0:
        raise ValueError("maturity must be positive")
    p1, p2 = heston_risk_neutral_probabilities(
        s0, strike, maturity, risk_free_rate, dividend_yield, params
    )
    s0_leg = s0 * _guarded_exp(-dividend_yield * maturity, "the spot discount factor")
    strike_leg = strike * _guarded_exp(-risk_free_rate * maturity, "the strike discount factor")
    return s0_leg * p1 - strike_leg * p2


def heston_option_price(
    market: MarketSnapshot, option: EuropeanOption, params: HestonParams
) -> float:
    """`market.volatility` is NOT used -- the variance process comes from
    `params` instead; `market` is accepted (rather than raw floats) only
    for the same reason `volterra.forwards` accepts one despite not
    needing every field either: consistency with every other VOLTERRA
    pricer's call signature."""
    call = heston_call_price(
        market.spot,
        option.strike,
        option.maturity,
        market.risk_free_rate,
        market.dividend_yield,
        params,
    )
    if option.option_type == "call":
        return call
    # Put-call parity, not a second P1'/P2' derivation: Put = Call -
    # S*exp(-qT) + K*exp(-rT), a model-independent identity.
    forward_value = market.spot * _guarded_exp(
        -market.dividend_yield * option.maturity, "the spot discount factor"
    ) - option.strike * _guarded_exp(
        -market.risk_free_rate * option.maturity, "the strike discount factor"
    )
    return call - forward_value
