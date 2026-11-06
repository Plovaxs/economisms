# ECONOSIM

**A research platform for computational economics, stochastic finance, and neural risk control.**

[![Tests](https://img.shields.io/badge/tests-2%2C022%20passing-brightgreen)](./docs/PR_LEDGER.md)
[![Lint & Types](https://img.shields.io/badge/ruff%20%2B%20mypy--strict-clean-brightgreen)](./CHECKLIST_STATUS.md)
[![Blueprint coverage](https://img.shields.io/badge/blueprint%20coverage-180%2F374%20(48.1%25)-blue)](./CHECKLIST_STATUS.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](./pyproject.toml)

> **Research and simulation only.** Nothing in this repository is financial
> advice, a trading system, or infrastructure for live trading. See
> [Status & disclaimers](#status--disclaimers).

---

## Overview

ECONOSIM (formerly PROMETHEUS) is a from-scratch research platform that
combines four subsystems behind one evidence discipline:

- **a multi-agent computational economy** — households, firms, banks and a
  government, wired to a real double-entry ledger, with point-in-time data
  access, deterministic shocks, and a macro time engine;
- **classical and stochastic-volatility market models** — GBM, Heston,
  Merton jump-diffusion, regime-switching, with Monte Carlo and
  closed-form pricers for European, American, barrier and Asian options;
- **institutional risk analytics** — VaR, Expected Shortfall, factor
  exposure, stress testing, portfolio optimization and covariance
  shrinkage; and
- **deep hedging and decision infrastructure** — a CVaR-trained neural
  hedging policy benchmarked against classical baselines, plus the audit,
  provenance, and model-lifecycle tooling needed to make any of the above
  trustworthy evidence rather than a demo.

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
| Blueprint items evidenced | **180 / 374** (48.1%) across 29 categories |
| Categories at 100% | API, ECO, LED, OPT, PRI, RISK, SDE |
| Test suite | **2,022 / 2,022** passing |
| Lint & types | `ruff` clean, `mypy --strict` clean |
| Pull requests | 109, each independently verified |

For the full per-category breakdown, see [CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md).
For the detailed, PR-by-PR account of what was built and how each claim
was verified, see [docs/PR_LEDGER.md](./docs/PR_LEDGER.md).

## Quickstart

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r requirements/bootstrap.txt
uv sync --locked --all-extras --group build
uv run --locked --all-extras pytest
uv run --locked --all-extras ruff check src tests tools
uv run --locked --all-extras mypy --strict src tools/reproducible_build.py
```

Requires Python 3.11+. Core dependencies are `numpy`, `scipy` and `torch`;
optional extras add a local service layer (`uvicorn`, `jsonschema`) and
encrypted local recovery (`cryptography`). See
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
  volterra/        Black-Scholes, Heston & Merton pricers, barrier/Asian/American options, Greeks
  titan/           VaR, Expected Shortfall, factor exposure, stress testing, portfolio optimization
  hedging/         delta/no-trade-band baselines, self-financing simulator, CVaR-trained MLP policy
  experiments/     bootstrap CIs, manifests, holdout splits, leakage diagnostics, benchmarks
  evidence/        model cards, gate reports, model registry, champion/challenger comparison
  service/         authenticated HTTP API, pricing/risk reports, deploy manifests
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
- Remaining work spans data ingestion pipelines, neural stochastic
  models, multi-agent reinforcement learning, a product-facing dashboard,
  and governance/compliance/security controls that need real
  organizational authority — independent review, legal sign-off, a
  penetration test, disaster-recovery drills — not just more code. See
  [CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md) for exactly which items
  remain and why.
- No independent review of any claim in this repository has happened.
  "Evidenced" means covered by a passing automated test here, not
  peer-reviewed, regulator-approved, or production-ready.

## Contributing

This is presently a single-maintainer research repository. Issues and
discussion are welcome; the standing bar for any change is the same one
every PR here already meets: a passing test, `ruff`/`mypy --strict`
clean, and an honest, specific statement of what the change does and
does not cover.

## License

MIT — see [LICENSE](./LICENSE).
