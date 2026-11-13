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

ECONOSIM (formerly PROMETHEUS) is a from-scratch research platform that
combines six subsystems behind one evidence discipline:

- **a multi-agent computational economy** — households, firms, banks and a
  government, wired to a real double-entry ledger, with point-in-time data
  access, deterministic shocks, a macro time engine, and an optional
  PPO-trained multi-agent reinforcement-learning policy benchmarked
  against the deterministic/calibrated baseline;
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
- **a real, authenticated research dashboard** — a separate ASGI
  service (`python -m prometheus.dashboard serve`) rendering live
  computed output from every subsystem above, with owner-scoped
  portfolio access and real HTTP authorization boundaries, not a mockup.

The project is built against two governing specifications — the original
[374-item master blueprint](./docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf)
and the [PROMETHEUS-X final-project addendum](./docs/PROMETHEUS_X_Final_Project_Integrated_Blueprint.md)
— and tracks its own progress against both, honestly, in public.

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
for anyone other than the account that owns them.

**The final-project deep-learning demo is a real webapp, not an Artifact.**
`python -m prometheus.dashboard serve` exposes `/dashboard/inflationcast`:
naive/linear/classical-MLP/hybrid-quantum/GRU CPI nowcasting candidates
benchmarked live against real BLS CPI-U and Kaggle macro data, with an
animated bar chart, an actual-vs-predicted line chart, and a real
calibration pass/fail indicator — every number computed from a live run,
not a canned export. See [FP-07](./CHECKLIST_STATUS.md) for the real
(and honestly negative) result.

**One unified React app now fronts every real engine.** `frontend/`
(Vite + React + TypeScript + Tailwind + Framer Motion + Recharts) covers
every dashboard view above plus a "Deep Learning Lab" section — submit a
real job for RECESSIONNET, Q-MACRO, INFLATIONCAST, the neural SDE, the
PDE solvers, multi-agent RL, or the REINFORCE hedging agent, and watch
it resolve through the real SQLite-backed job queue to a real rendered
chart. Run the whole stack — job worker, job API, dashboard, frontend —
with one command: `./run_dev.sh`. See
[frontend/README.md](./frontend/README.md) for details, and
[FP-19](./CHECKLIST_STATUS.md) for the real end-to-end job trace this
adds across all seven deep-learning subsystems.

**Two of this project's own named limitations were re-tested directly,
not left as speculation.** `InflationGRU`'s miscalibration survived an
8-hidden-size × 10-seed capacity-matching sweep (80 real runs) and a
new post-hoc variance-calibration step — narrowed substantially, not
closed, consistent with a genuine 2022+ inflation-surge regime shift
rather than an undertrained model. The REINFORCE hedging agent's loss
to its static baseline survived fixing a real reward/metric mismatch
(it was trained to minimize mean loss, not the CVaR it's judged on)
plus a 10–20× longer training budget — the gap narrowed from ~2.5× to
~1.04×–1.41× across 8 seeds, still a real loss. Both honest,
unchanged conclusions, now with the obvious confounds ruled out
instead of assumed away. See `docs/RESULTS_AND_LIMITATIONS.md`'s
Finding 8 and Finding 11 follow-ups.

**A real recession-predictor feature — the US Treasury yield-curve
spread — was added to RECESSIONNET and made things worse, not
better.** Rather than chase an arbitrary data-volume target (this
repository's entire real dataset is ~136KB; monthly macro data is
structurally small, not a big-data domain), a genuinely new, textbook-
motivated real feature (the 10Y-3M spread, Estrella-Mishkin) was
ingested from `home.treasury.gov` and directly ablated. Honest result:
ROC-AUC is consistently decent without it (0.68–0.86 across 5 seeds)
and erratic, usually worse, with it (0.36–0.82) — plausibly because an
already data-starved model gains one more dimension to fit. See
`docs/RESULTS_AND_LIMITATIONS.md`'s Finding 12.

**The same check was then run across the remaining five DL
subsystems, with mixed and genuinely interesting results.** The PDE
solvers' neural-vs-classical accuracy gap narrowed sharply (deep-BSDE
was undertrained by ~300x) once properly trained. MARL's co-learning
condition turned out robustly worse for the household on average, not
just less stable. But two checks confirmed a default was already
*correct*: the neural SDE's real OOD-robustness finding — its one
clearly positive result — collapses under more training (COVID
degradation +5.58 → +48.75), and RECESSIONNET's Kaggle dataset
revealed a genuine Brier-score-vs-ROC-AUC blind spot in 1 of 5 seeds
that a second diagnostic caught before it could pass as a win. See
`docs/RESULTS_AND_LIMITATIONS.md`'s Finding 3, 5, and 6 follow-ups.

**New here?** [docs/PORTFOLIO_DEMO.md](./docs/PORTFOLIO_DEMO.md) is a
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
