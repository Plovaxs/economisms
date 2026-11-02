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
pip install -e ".[dev]"
pytest                      # 35 tests, should all pass
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
| PR-006 Risk reference | not started | P&L, historical VaR/ES, loss estimators |
| PR-007 Deep hedge v0 | not started | MLP hedging policy, cost-aware delta baseline |
| PR-008 First research benchmark | not started | held-out seeds, bootstrap CI, reproducer |
| PR-009 Macro-financial link | not started | policy-rate scenario into market conditional states |
| PR-010 Evidence export | not started | run manifest, model card, gate report |

## License

MIT — see [LICENSE](./LICENSE).
