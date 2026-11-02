# PROMETHEUS

Research platform for computational economics, stochastic finance and neural
risk control. **Research / simulation only — not financial advice, and not
permission or infrastructure for live trading.**

This repository implements a small, real, tested subset of the project's
[master specification](./docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf):
a 57-page design document covering a multi-agent computational economy
(ECONOSIM-X), neural stochastic market dynamics (STOCHASTICA), derivatives
pricing (VOLTERRA) and institutional risk analytics (TITAN), plus a
374-item engineering readiness checklist across 29 categories.

**That specification is a design document, not a status report.** Treat any
claim that its contents are "included" as a description of the PDF's table
of contents, not of working software. This README and
[CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md) are the actual, current,
test-backed status. Nothing below is claimed without a passing test behind
it.

## What exists today (v0.1)

A multi-sector, double-entry **stock-flow ledger** (`prometheus.core.ledger`)
plus three agent types built on it (`prometheus.econosim.agents`):

- `Money` — exact integer minor-unit currency values (no floating-point
  cent drift).
- `Ledger` — accounts tagged by sector (household / firm / bank / government
  / central bank) and type (asset / liability / equity); every state change
  goes through `Ledger.post()`, which validates a transaction's accounting
  identity **before** mutating any balance (fail closed), not after.
- `Household`, `Firm`, `Bank` — income, consumption, wages, loan
  origination, loan repayment and a bank leverage cap, each implemented as
  one balanced `Transaction`.
- `Economy` — thin wiring over the above plus an integrity check.

Every one of those behaviors is covered by a unit test, and the ledger's
core conservation property (no sector's books can go out of balance, and
total economy-wide equity equals exactly the sum of exogenous injections) is
checked by a Hypothesis property test over randomized action sequences —
see `tests/property/test_ledger_invariants.py`.

Plus a **macro time engine** (`prometheus.econosim.time_engine`):

- `BusinessDayCalendar` — weekend/holiday-aware date stepping.
- `SeedHierarchy` — deterministic, order-independent named RNG streams from
  one root seed, so replaying a simulation with the same seed reproduces
  every stream's draws regardless of what order they're first requested in.
- `PointInTimeStore` — macro observations keyed by both the period they
  describe and when they were published; `as_of(t)` enforces the strict
  `published_at <= t` inclusion rule, so a simulated step can never see a
  data revision before it actually existed (the concrete mitigation for
  R-03 in the risk register: lookahead leakage).
- `ShockGenerator` — deterministic exogenous shocks tagged with the step
  they arrive at, drawn from a seeded stream.
- `MacroTimeEngine` — steps the clock one calendar month at a time (snapped
  to the next business day), releasing only currently-eligible macro data
  and drawing that step's shocks, then re-checks the ledger's accounting
  identities and emits a content hash of the resulting state.

Plus physical-measure **stochastic market dynamics** (`prometheus.stochastica`),
not yet wired to the economy:

- `simulate_gbm_paths` — exact lognormal-transition GBM (no discretization
  bias to characterize), checked against closed-form terminal moments.
- `simulate_correlated_gbm_paths` — multi-asset GBM with correlated shocks.
- `simulate_heston_paths` — log-Euler price / full-truncation-Euler variance
  Heston, guaranteed non-negative variance by construction, checked against
  the CIR process's exact first moment.
- `correlated.validate_and_repair_covariance` — rejects a non-PSD covariance
  matrix outright, but repairs (with a warning) one that is PSD except for
  floating-point-sized negative eigenvalues.

Plus risk-neutral (Q) **derivatives pricing** (`prometheus.volterra`), also
not yet wired to the economy:

- `MarketSnapshot` — structurally requires `measure="Q"`; constructing one
  tagged `"P"` raises immediately, so a physical-measure calibration can't
  be fed into a pricing call by accident (SDE-09).
- `black_scholes_price` / `black_scholes_greeks` — the closed form plus
  delta/gamma/vega/theta/rho, matched against a central finite-difference
  of the same price function (an independent formula check, not an
  independent *pricer* check) and against put-call parity to floating-point
  precision.
- `monte_carlo_price_vanilla` — always simulates under Q (drift =
  risk-free rate minus dividend yield, never a physical `mu`), always
  returns a standard error alongside the price, and optionally applies a
  control variate (the discounted terminal spot, whose risk-neutral mean is
  known in closed form) — cuts the standard error by roughly 2-3x at the
  tested settings.

Plus institutional-style **risk metrics** (`prometheus.titan`), also not
yet wired to any position book:

- `historical_var` / `parametric_var` — empirical and Gaussian VaR, each
  declaring its convention (interpolation method / distributional
  assumption) explicitly rather than silently defaulting.
- `historical_expected_shortfall` — a tie/atom-safe quantile-integral
  estimator that operates on order statistics (so a run of tied loss values
  is handled correctly with no special-casing), checked against hand-worked
  discrete examples and against the exact Gaussian ES formula for a
  continuous reference.
- `max_drawdown` — peak-to-trough decline in a cumulative P&L/value series.
- `var_exception_coverage_test` — an exact two-sided binomial test of
  whether observed VaR breaches match the expected rate; confirmed to pass
  a correctly-calibrated model and flag (p < 1e-10) a badly miscalibrated
  one in testing.

Plus **deep hedging and stochastic control** (`prometheus.hedging`), the
first subsystem that uses PyTorch:

- `black_scholes_delta_hedge_ratios` / `apply_no_trade_band` — a causal
  (no-future-information) delta baseline and a cost-aware no-trade-band
  variant that cuts turnover by roughly 30% at a 0.1 band width in testing.
- `simulate_self_financing_hedge` — one shared, explicitly self-financing
  P&L simulator used for *every* policy, baseline and learned alike, so
  nothing can look better just by using a different accounting convention.
  Checked against an exact closed form (a zero-hedge naked short position)
  and against a brute-force manual recomputation.
- `HedgePolicyMLP` / `train_deep_hedge` — a small MLP trained to minimize
  CVaR of terminal loss plus a turnover penalty (Buehler et al., 2019),
  differentiating straight through a PyTorch rollout that mirrors the
  numpy simulator's accounting exactly. Training is deterministic given a
  seed and beats an untrained policy by roughly 10x CVaR in testing.
  **Not claimed**: that it beats delta hedging — it did, slightly, on one
  configuration explored during development, but the blueprint's own
  central hypothesis says such a result is not assumed in advance, so no
  test asserts it.

Plus a first **research benchmark** (`prometheus.experiments`):

- `paired_bootstrap_difference` — a percentile bootstrap CI for the
  difference between two policies evaluated on the *same* simulated paths.
  The pairing is load-bearing, not cosmetic: a planted constant per-path
  difference collapses to an exact-point CI in testing, which an unpaired
  bootstrap would not do.
- `RunManifest` / `compute_result_hash` — a reproducibility manifest whose
  result hash is a canonical, key-order-independent hash of the full
  per-seed results payload, confirmed identical across independent runs of
  the same config; `run_id`/`created_at` are wall-clock-derived and
  explicitly documented as *not* part of that reproducibility claim.
- `run_hedge_benchmark` — compares the delta baseline against a trained MLP
  policy across several independent held-out seeds, with a primary endpoint
  fixed in advance (`PRIMARY_ENDPOINT`). At the one configuration explored
  in development, the two were statistically indistinguishable (every
  seed's CI included zero) — an inconclusive result, and one the blueprint's
  own central hypothesis explicitly allows for. Every report also states,
  in plain text, exactly which axes of the blueprint's full factorial
  matrix it does *not* cover (only the hedge dimension is varied; no
  learned economy or neural-SDE market model exists yet).

Run `cat CHECKLIST_STATUS.md` for exactly which blueprint checklist IDs
(`ECO-*`, `LED-*`, `VAL-*`, ...) that evidence actually satisfies, and which
of their explicit acceptance conditions are *not yet* met.

## What does not exist yet

Everything else in the blueprint: the macro time engine and shocks, labor
and goods-market clearing, government/central-bank agents, multi-agent RL,
classical and neural stochastic market models, derivatives pricing, deep
hedging, portfolio risk and optimization, the service API, MLOps/CI/CD,
security controls, dashboards, and all governance/compliance process items.
The blueprint's own final verdict — **NO-GO for production** — stands
unchanged; nothing here moves that needle, nor is it meant to yet.

## Getting started

```bash
python3 -m venv .venv
source .venv/bin/activate
# torch is a heavy dependency; the CPU-only wheel installs much faster and
# smaller than letting pip resolve a CUDA build you likely don't need here.
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
pytest                      # 176 tests, should all pass (~14s, incl. MLP training)
ruff check src tests
mypy src
```

## Repository layout

```
src/prometheus/
  core/         money, ledger, business-day calendar, RNG seed hierarchy
  econosim/     household/firm/bank agents, Economy wiring, point-in-time
                macro data, deterministic shocks, macro time engine
  stochastica/  GBM, correlated multi-asset GBM, Heston path simulators
  volterra/     Black-Scholes pricing, Greeks, Monte Carlo + control variate
  titan/        VaR, Expected Shortfall, drawdown, VaR-exception coverage
  hedging/      BS delta / no-trade-band baselines, self-financing
                simulator, CVaR-trained MLP hedging policy (PyTorch)
  experiments/  paired bootstrap CI, reproducibility manifest, the
                delta-vs-MLP hedge benchmark
tests/
  unit/         one behavior per test, no randomness
  property/     Hypothesis-based invariant tests
```

This mirrors (a small slice of) the reference repository layout in section
18 of the master specification; subsystem directories named there
(`stochastica/`, `volterra/`, `titan/`, `api/`, ...) will be added as the
corresponding PRs land, not speculatively ahead of them.

## Roadmap (per the blueprint's own Appendix C prioritization)

The blueprint is explicit that the first priority is *"not building the
Transformer... making a constrained, correctly accounted toy economy and a
trustworthy valuation/risk baseline."* This repository follows that order:

| PR | Status | Scope |
|----|--------|-------|
| PR-001 Repository foundations | done | package, lint/type config, test harness |
| PR-002 Stock-flow ledger | done | double-entry journals, household/firm/bank, invariant tests |
| PR-003 Macro time engine | done | business-day calendar, seed hierarchy, point-in-time macro data, deterministic shocks |
| PR-004 Stochastic reference | done | GBM, correlated multi-asset GBM, Heston (full-truncation Euler) + numerical benchmarks |
| PR-005 Pricing reference | done | Black-Scholes, analytical + finite-difference Greeks, put-call parity, Monte Carlo + control variate |
| PR-006 Risk reference | done | historical/parametric VaR, tie-safe Expected Shortfall, drawdown, VaR-exception coverage test |
| PR-007 Deep hedge v0 | done | BS delta + no-trade-band baselines, self-financing simulator, CVaR-trained MLP policy |
| PR-008 First research benchmark | done | paired bootstrap CI, reproducibility manifest, multi-seed delta-vs-MLP comparison |
| PR-009 Macro-financial link | not started | policy-rate scenario into market conditional states |
| PR-010 Evidence export | not started | run manifest, model card, gate report |

## License

MIT — see [LICENSE](./LICENSE).
