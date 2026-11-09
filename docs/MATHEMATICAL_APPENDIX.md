# Mathematical notation and assumptions appendix

Every equation below is copied from the module that implements and tests
it, not re-derived here — if an equation and its implementation ever
disagree, trust the code and its test suite, and open an issue against
this document. This is a reference index, not a tutorial; each section
links to the source module, which carries the full derivation/assumption
discussion in its own docstring.

## Notation conventions used throughout

`S` (or `S_t`) — asset price; `r` — risk-free rate; `q` — continuous
dividend yield; `sigma` — volatility; `T`/`t` — maturity/time; `dW` —
Brownian increment. Greeks are reported **per unit of their input** (e.g.
vega = price change per 1.00 = 100 percentage points of vol, theta = price
change per 1.00 year) — never rescaled to "per 1% vol" or "per calendar
day" conventions; a caller rescales at the display layer if it wants that.

## Black-Scholes PDE and closed-form pricing

[`prometheus.volterra.black_scholes`](../src/prometheus/volterra/black_scholes.py):

```
V_t + 0.5*sigma^2*S^2*V_SS + (r-q)*S*V_S - r*V = 0
```

with the standard closed-form European solution. **Disclosed numerical
assumption**: a sufficiently negative `risk_free_rate` combined with a
long `maturity` can overflow `exp(-r*t)` directly (confirmed at
rate=-5, maturity=142), and a second, subtler input combination can
silently produce `inf * 0.0 = nan` (confirmed at rate=-4.90625,
maturity=144, strike=27) because the discount factor overflows to `inf`
exactly where the risk-neutral exercise probability has independently
underflowed to exactly `0.0`. The implementation evaluates the
probability term first and short-circuits to `0.0` there, both resolving
the `nan` case correctly on economic grounds (a probability that has
underflowed to exactly zero contributes nothing, however large the
nominal discounted notional) and avoiding the overflow.

## Geometric Brownian motion (GBM)

[`prometheus.stochastica.gbm`](../src/prometheus/stochastica/gbm.py):

```
dS/S = mu*dt + sigma*dW   =>   S_t = S_0 * exp((mu - 0.5*sigma^2)*t + sigma*W_t)
```

Paths are drawn from the **exact** lognormal transition density at each
step, not an Euler discretization of `S` — there is no time-discretization
bias to characterize for this model. **Disclosed floating-point
boundary**: strict positivity is a mathematical guarantee (`S_t` is an
exponential) but not a floating-point one at extreme inputs — a large
enough `sigma*sqrt(dt)` can underflow `np.exp` to exactly `0.0` (confirmed
at sigma=50), which is a representable, legitimate float and not treated
as a violation; a large enough **positive** drift over a long maturity is
the genuine violation direction (confirmed at mu=5, maturity=142) and is
rejected with a clear error rather than silently returned as `inf`.

## Heston stochastic volatility

[`prometheus.stochastica.heston`](../src/prometheus/stochastica/heston.py) /
[`prometheus.volterra.heston_pricer`](../src/prometheus/volterra/heston_pricer.py):

```
dS = mu*S*dt + sqrt(v)*S*dW_s
dv = kappa*(theta - v)*dt + xi*sqrt(v)*dW_v,   corr(dW_s, dW_v) = rho
```

Discretization: log-Euler on price (so `S` stays positive by construction)
combined with full-truncation Euler on variance (Lord, Koekkoek & van Dijk,
2010) — wherever `v` appears in a drift, diffusion, or square root it is
floored at zero first. This is a simple, well-known positivity-preserving
scheme, **not a claim of being the most accurate one available** (e.g.
Andersen's QE scheme is more accurate at large time steps); see the
Feller-ratio diagnostic in the source module for when this scheme's bias
is likely to matter. Independently re-verified in this session: fitted
weak-convergence order ≈ 0.91 against a closed-form reference price across
a 5-point step-halving sweep (theory predicts ≈ 1 for a log-Euler/
full-truncation scheme; the observed deviation at coarse `dt` is expected
and consistent with the scheme's own documented limitations, not a bug).

## Merton (1976) jump-diffusion

[`prometheus.stochastica.jump_diffusion`](../src/prometheus/stochastica/jump_diffusion.py):

```
dS/S = (mu - lambda*k) dt + sigma dW_t + d(sum of jumps)
```

Jumps arrive as a compound Poisson process with intensity `lambda`; each
jump multiplies price by `(1 + Y)` with `ln(1 + Y) ~ Normal(jump_mean,
jump_std^2)` i.i.d. `k = E[Y] = exp(jump_mean + 0.5*jump_std^2) - 1` is the
jump compensator, subtracted from the drift to keep `S` a martingale
(when `mu = r`) despite the jumps' nonzero expected log-return
contribution — the same role `-0.5*sigma^2` plays for the pure-diffusion
part. Terminal-time simulation is **exact**, not an Euler approximation:
given `N ~ Poisson(lambda*T)` jumps over the horizon, the sum of `N` i.i.d.
jump log-sizes is itself exactly `Normal(N*jump_mean, N*jump_std^2)`
(closed under convolution), so one Poisson draw plus one Normal draw per
path reproduces the exact terminal jump contribution with zero
time-stepping error.

## Regime-switching market model

[`prometheus.stochastica.regime_switching`](../src/prometheus/stochastica/regime_switching.py):
a discrete-time Markov chain over `n_regimes` states, each with its own
`(mu_i, sigma_i)`; the regime evolves by sampling from the current state's
row of `transition_matrix` each step, and log-price evolves by one
log-Euler GBM step using that regime's own parameters. Row-stochasticity
(`transition_matrix` rows sum to 1, every entry in `[0, 1]`) is enforced at
construction, not assumed. The stationary distribution `pi` (`pi @ P == pi`)
is found by the general eigenvector/null-space method (not a 2-state
closed form only), independently verified against: (1) the closed-form
2-state solution, (2) direct fixed-point substitution, (3) long-run
empirical regime-occupancy frequency from simulation.

## Ledger compounding (not a pricing model, but a tested real formula)

[`prometheus.core.ledger`](../src/prometheus/core/ledger.py) (LED-05):
interest accrual/amortization is hand-verified against exact compounding —
e.g. `1000.00 * 1.01^3 = 1030.301`, rounding to `1030.30` — over multiple
periods, in integer `Money` minor units throughout (see
[docs/DATA_DICTIONARY.md § Money](./DATA_DICTIONARY.md#money--ledger-currency-values)),
never floating-point cents.

## Options not yet covered by a closed-form or PDE/neural solver

American, barrier, and Asian options
([`prometheus.volterra.american_options`](../src/prometheus/volterra/american_options.py),
`barrier_options.py`, `asian_options.py`) are priced via Monte Carlo /
semi-analytic methods in this repository today — see
[`prometheus.volterra.monte_carlo`](../src/prometheus/volterra/monte_carlo.py).
A grid/PINN/deep-BSDE PDE solver subsystem is tracked separately under the
blueprint's `PDE` category; see `CHECKLIST_STATUS.md` for its current
status.
