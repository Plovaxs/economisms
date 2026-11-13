# ECONOSIM

**A research platform for computational economics, stochastic finance, and neural risk control.**

[![Tests](https://img.shields.io/badge/tests-3%2C014%20passing-brightgreen)](./docs/PR_LEDGER.md)
[![Lint & Types](https://img.shields.io/badge/ruff%20%2B%20mypy--strict-clean-brightgreen)](./CHECKLIST_STATUS.md)
[![Blueprint coverage](https://img.shields.io/badge/blueprint%20coverage-351%2F374%20(93.9%25)-blue)](./CHECKLIST_STATUS.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](./pyproject.toml)

> **Research and simulation only.** Nothing in this repository is financial
> advice, a trading system, or infrastructure for live trading. See
> [Status & disclaimers](#status--disclaimers).

---

## Overview

**Beyond Model Complexity: An Empirical Evaluation of Classical, Deep
Learning, and Hybrid Quantum Models for Quantitative Economic and
Financial Tasks.** ECONOSIM (formerly PROMETHEUS) is a from-scratch
research platform that puts that question to real data, with a hard
rule attached: nothing counts as a finding here unless a specific,
reproducible, currently-passing test produced it. It combines six
subsystems behind that one evidence discipline:

- **a multi-agent computational economy** — households, firms, banks and a
  government, wired to a real double-entry ledger, with point-in-time data
  access, deterministic shocks, a macro time engine, and a PPO-trained
  multi-agent reinforcement-learning policy benchmarked against the
  deterministic/calibrated baseline;
- **classical and stochastic-volatility market models** — GBM, Heston,
  Merton jump-diffusion, regime-switching, with Monte Carlo and
  closed-form pricers for European, American, barrier and Asian options,
  plus a neural SDE trained on real macro data and benchmarked against
  classical baselines with proper scoring rules and real-event OOD
  evaluation;
- **neural PDE/BSDE option-pricing solvers** — PINN and deep-BSDE
  solvers for the Black-Scholes PDE, benchmarked against the classical
  Crank-Nicolson grid and the closed-form price for accuracy, speed, and
  the dimensionality crossover where a grid stops being practical;
- **institutional risk analytics** — VaR, Expected Shortfall, factor
  exposure, stress testing, portfolio optimization and covariance
  shrinkage;
- **deep hedging and decision infrastructure** — a CVaR-trained neural
  hedging policy benchmarked against classical baselines, plus the audit,
  provenance, and model-lifecycle tooling needed to make any of the above
  trustworthy evidence rather than a demo; and
- **a real, authenticated research dashboard and a unified React
  frontend** — a separate ASGI service (`python -m prometheus.dashboard
  serve`) and a Vite + React + TypeScript app (`frontend/`) rendering
  live computed output from every subsystem above, with owner-scoped
  portfolio access and real HTTP authorization boundaries, not a mockup.
  `./run_dev.sh` starts the whole stack with one command; see
  [frontend/README.md](./frontend/README.md).

The project is built against two governing specifications — the original
[374-item master blueprint](./docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf)
and the [PROMETHEUS-X final-project addendum](./docs/PROMETHEUS_X_Final_Project_Integrated_Blueprint.md)
— and tracks its own progress against both, honestly, in public.

## Key findings

Five falsifiable hypotheses were frozen on 2026-11-11 against the
evidence gathered through that date — see
[docs/FINAL_PROJECT_HYPOTHESES.md](./docs/FINAL_PROJECT_HYPOTHESES.md)
for the full, retrospectively-frozen record and its own honest caveat
about what that means for evidentiary weight. After that date the
questions don't change; the evidence for or against them can, with
every revision disclosed. The pattern across all five, and across
the two newer, not-yet-frozen findings below: **the more complex
method winning was the exception, not the rule** — and the exceptions
that did appear were earned by ruling out confounds directly, not by
re-running until a result looked good.

| ID | Question | Verdict |
|---|---|---|
| **H1** | Does a hybrid quantum-classical model beat classical baselines on recession classification / factor regression? | **Rejected.** Tested 3 independent ways (2 real datasets, 2 task families); every bootstrap CI includes zero. |
| **H2** | Does a neural SDE beat classical baselines in-distribution, and degrade less under a real shock? | **Partially supported.** Not better in-distribution — but genuinely more robust under the real 2020 COVID shock (+5.58 vs. a GBM baseline's +29.97 log-score degradation). |
| **H3** | Does a neural PDE solver (PINN/deep-BSDE) earn its cost over a classical grid at high dimension? | **Supported**, crossover measured not assumed — revised 2026-11-13 once an undertrained baseline was caught and fixed (grid's accuracy edge over deep-BSDE: ~580x → ~2x; verdict unchanged). |
| **H4** | Can naive fixed-epoch training or an unaudited reward silently produce a false conclusion? | **Supported, twice**, independently (RECESSIONNET's early-stopping fix; MARL's reward-design fix). |
| **H5** | Does a REINFORCE hedging agent beat a well-specified static baseline? | **Rejected.** Still loses after fixing a real reward/metric mismatch and training 10–20x longer (gap narrowed ~2.5x → ~1.04–1.41x, still a loss). |

Two further checks, run after the freeze (disclosed as such, not
folded into H1–H5): a textbook recession predictor (the US Treasury
10Y-3M yield-curve spread) was added to RECESSIONNET as a real feature
and made things **worse**, not better (ROC-AUC 0.68–0.86 without it vs.
0.36–0.82 with it, across the same 5 seeds) — plausibly because an
already data-starved model gained one more dimension to fit. And a
"train harder" pass across all seven deep-learning subsystems found
two defaults were already *correct*: the neural SDE's one clearly
positive result (above) collapses under more training, and
RECESSIONNET's Kaggle dataset revealed a real Brier-score-vs-ROC-AUC
blind spot in 1 of 5 seeds that a second diagnostic caught before it
could pass as a win. See
[docs/RESULTS_AND_LIMITATIONS.md](./docs/RESULTS_AND_LIMITATIONS.md)
(12 numbered findings, each with its own re-runnable test) and
[docs/RESEARCH_CONTRIBUTIONS.md](./docs/RESEARCH_CONTRIBUTIONS.md) for
the full account behind every line above.

## The evidence discipline

**"Evidenced" means exactly one thing here: a passing automated test in
this repository links to that specific checklist item.** Not a design
document, not a docstring, not a plan — a test that runs today, cross-checked
against a closed-form, an independent numerical method, or real data
wherever one exists, with `ruff` and `mypy --strict` clean on every touched
module. Nothing is marked done on the strength of a specification alone,
and every PR states plainly what it does *not* cover.

| | |
|---|---|
| Blueprint items evidenced | **351 / 374** (93.9%) across 29 categories |
| Categories at 100% | API, AUD, CIQ, DOC, DRI, ECO, EXP, GOV, HDG, LCH, LED, MAR, MLO, NSD, OPS, OPT, PDE, PRI, REL, RISK, SDE, UIX, VAL |
| Test suite | **3,014 / 3,014** passing (Python; see `frontend/` for its own separate Vitest suite) |
| Lint & types | `ruff` clean, `mypy --strict` clean |
| Pull requests | 178, each independently verified |

For the full per-category breakdown, see [CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md).
For the detailed, PR-by-PR account of what was built and how each claim
was verified, see [docs/PR_LEDGER.md](./docs/PR_LEDGER.md).

**Live visual dashboards** (Claude Artifacts, kept in sync with each PR):
the [blueprint coverage dashboard](https://claude.ai/artifact/HChLfAPJQfvUasBbLP4fxj)
tracks this same 374-item checklist by category, and the
[simulation dashboard](https://claude.ai/artifact/Eit5ePvaZhWDgbSXSQhV5w)
charts real output from the economy, market-path, hedging and portfolio-risk
subsystems. Both must be shared from their Share menu before a link works
for anyone other than the account that owns them. **The deep-learning
demo itself is a real webapp, not an Artifact**: `/dashboard/inflationcast`
benchmarks five real CPI-nowcasting candidates live against real BLS/
Kaggle data, and the React frontend above submits a real job for any
of all seven deep-learning subsystems and renders the real result.

## New here?

[docs/PORTFOLIO_DEMO.md](./docs/PORTFOLIO_DEMO.md) is a
10-minute guide to running the real test suite, starting the real
research dashboard, and spot-checking a real finding yourself.
[docs/RESEARCH_CONTRIBUTIONS.md](./docs/RESEARCH_CONTRIBUTIONS.md)
states the actual research questions this project tested and what was
found — including the ones where the more complex approach lost.
[docs/FINAL_PROJECT_HYPOTHESES.md](./docs/FINAL_PROJECT_HYPOTHESES.md)
freezes a title and five falsifiable hypotheses against those same
findings, honestly disclosed as a retrospective freeze.

## Quickstart

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r requirements/bootstrap.txt
uv sync --locked --all-extras --group build
uv run --locked --all-extras pytest
uv run --locked --all-extras ruff check src tests tools
uv run --locked --all-extras mypy --strict src tools/reproducible_build.py
```

One-command smoke test — replays a recorded deterministic reference run and
checks the result hash, rather than waiting on the full suite:

```bash
uv run --locked --all-extras python -m prometheus.orchestration.replay \
  evidence/api_reference.json --require-integrity --output dist/reference-replay.json
```

Requires Python 3.11+. Core dependencies are `numpy`, `scipy` and `torch`;
optional extras add a local service layer (`uvicorn`, `jsonschema`),
encrypted local recovery (`cryptography`), and hybrid quantum-classical
ML (`pennylane`, `pennylane-lightning` — see
[`src/prometheus/quantum/`](./src/prometheus/quantum/)). See
[`pyproject.toml`](./pyproject.toml) for the full dependency and extras
list.

## Project structure

```
src/prometheus/
  core/            money, double-entry ledger, business-day calendar, RNG seed hierarchy
  econosim/        household/firm/bank/government agents, Economy wiring, point-in-time
                   macro data, macro time engine, central bank, market clearing,
                   step-hooks orchestration, data quality monitoring
  stochastica/     GBM, Heston, Merton jump-diffusion, regime-switching, historical calibration
  neural_sde/      drift/diffusion network trained on real macro data, proper scoring rules,
                   multi-seed/multi-solver sensitivity, real-event OOD evaluation, model card
  volterra/        Black-Scholes, Heston & Merton pricers, barrier/Asian/American options, Greeks
  pde_solvers/     classical finite-difference, PINN and deep BSDE solvers for the Black-Scholes
                   PDE (and a correlated multi-asset basket generalization), cross-checked against
                   closed-form/Monte Carlo and each other
  marl/            PPO-trained household/firm policies and rule-based bank/central-bank policies
                   over the real econosim ledger environment, with welfare, nonstationarity and
                   OOD-shock diagnostics
  titan/           VaR, Expected Shortfall, factor exposure, stress testing, portfolio optimization
  hedging/         delta/no-trade-band baselines, self-financing simulator, CVaR-trained MLP policy
  macrocore/       classical forecasting baselines (persistence/AR/VAR), rolling-origin backtests,
                   and a point-in-time-safe Q-MACRO regression benchmark (real Mkt-RF, h-months-ahead)
  recessionnet/    point-in-time-safe recession classification: real NBER labels, real factor
                   features, logistic/classical-MLP/hybrid-quantum model comparison
  quantum/         differentiable quantum circuit layer (PennyLane) and hybrid classifier/regressor
                   models shared by recessionnet and macrocore
  experiments/     bootstrap CIs, manifests, holdout splits, leakage diagnostics, benchmarks
  evidence/        model cards, gate reports, model registry, champion/challenger comparison
  service/         authenticated HTTP API, pricing/risk reports, deploy manifests
  dashboard/       authenticated research dashboard: economy/market/pricing/hedging/risk views,
                   experiment comparison, audit trail, provenance labels, reproducible exports
  jobs/            durable, bounded research-job queue and worker
  data_ingestion/  external data source connectors (point-in-time schema)
  orchestration/   demo, benchmark/study and replay runners
tests/
  unit/            one behavior per test, no hidden randomness
  property/        Hypothesis-based invariant and extreme-input testing
docs/
  PR_LEDGER.md     the full PR-by-PR evidence log
  implementation/  the machine-readable checklist register
```

## Status & disclaimers

- **This is research and simulation software.** It is not financial
  advice, not an investment product, and not permission or infrastructure
  for live trading. A separately gated, 12-item extension checklist (`EXT`)
  exists specifically for what real trading access would require, and it
  is deliberately untouched.
- **"NO-GO for production"** is this project's own, unchanged internal
  gate decision — see [`evidence/gate_report_r0.json`](./evidence/gate_report_r0.json).
  Nothing in this repository moves that needle, nor is it meant to yet.
- Remaining work is almost entirely governance/compliance/security
  controls that need real organizational authority this single-maintainer
  repository does not have — independent review, legal sign-off, a
  penetration test — plus two data-ingestion connectors (`DAT-02`/`DAT-03`)
  blocked on `stlouisfed.org` being unreachable from this environment, not
  on missing code. See [CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md) for
  exactly which items remain and why.
- No independent review of any claim in this repository has happened.
  "Evidenced" means covered by a passing automated test here, not
  peer-reviewed, regulator-approved, or production-ready.

## Contributing

This is presently a single-maintainer research repository. Issues and
discussion are welcome; the standing bar for any change is the same one
every PR here already meets: a passing test, `ruff`/`mypy --strict`
clean, and an honest, specific statement of what the change does and
does not cover. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full
workflow, [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md), and
[SECURITY.md](./SECURITY.md) for how to report a vulnerability.

## License

MIT — see [LICENSE](./LICENSE).
