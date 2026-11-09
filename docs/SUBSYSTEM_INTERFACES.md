# Subsystem interfaces and simulation event-order spec

This indexes how the subsystems listed in
[README.md § Project structure](../README.md#project-structure) actually
hand data to each other — grounded in the real orchestration code, not an
aspirational architecture diagram. If you're wiring a new subsystem into
the simulation loop, read [`step_hooks.py`](../src/prometheus/econosim/step_hooks.py)
and its test (`tests/unit/test_time_engine_hooks.py`) end to end before
this document; this is an index into that code, not a replacement for it.

## The economy simulation step order (authoritative)

[`MacroTimeEngine.advance_step()`](../src/prometheus/econosim/time_engine.py)
calls up to five pluggable, strictly ordered hooks per step
([`econosim.step_hooks.StepHooks`](../src/prometheus/econosim/step_hooks.py)),
each receiving only a `StepContext` built from data already known as of
that step — a hook cannot peek at a later step's prices or shocks:

| Step | Hook | Receives | Computes |
|---|---|---|---|
| 1-2 | *(engine-internal)* | — | advances the step/date, releases eligible point-in-time macro observations (`econosim.pit`), draws scheduled shocks (`econosim.shocks`) |
| 3 | `compute_actions` | `StepContext` | agent decisions from observed state |
| 4 | `clear_and_settle` | `(context, actions)` | budget constraints, journal entries, market clearing |
| 5 | `simulate_financial_step` | `(context, settlement)` | draws physical-measure shocks, updates financial state |
| 6 | `value_and_hedge` | `(context, financial_step, settlement)` | risk-neutral valuation, hedge actions under cost |
| 7 | `compute_portfolio_risk` | `(context, valuation_and_hedge, financial_step)` | realized P&L, conditional losses, constraints/limits |

Each hook is optional (an unset hook is skipped; its `StepResult` slot
stays `None`); hook return types are intentionally `Any` — the engine
threads each result to the next hook and records it, but does not itself
interpret what a hook computes. `StepHooks` ships no opinion about what
steps 3-7 should actually compute — that is scenario-specific, same as the
original one-off `demo_run.py` pipeline this generalizes. `StepContext`
itself carries: `step` (int), `step_date` (date), `released` (the tuple of
`MacroObservation`s eligible as of this step — see
[docs/DATA_DICTIONARY.md](./DATA_DICTIONARY.md)), `shocks`, and the
`Economy` object.

## Why this ordering, specifically

Agent decisions (3) must precede market clearing (4), which must precede
the physical-measure financial-state update (5) — an agent cannot react to
a price its own order hasn't cleared yet, and clearing cannot be priced
off a shock that hasn't been drawn. Valuation/hedging (6) runs after the
financial state update because a hedge decision needs that step's realized
state, not a stale one. Portfolio risk (7) runs last because realized P&L
and conditional losses are only knowable once every other effect of the
step has been applied. This mirrors the specification's own section 02
"steps 3-7" numbering — the two numbering schemes are intentionally kept
identical so a reader can cross-reference the blueprint PDF directly
against this code.

## Cross-subsystem data flow (above the step loop)

```
data_ingestion/*  --(MacroObservation, point-in-time)-->  econosim.pit.PointInTimeStore
                                                                    |
                                                        econosim.time_engine (steps 1-7 above)
                                                                    |
                           +---------------------+---------------------+
                           |                     |                     |
                    stochastica/*          titan/ (risk)        evidence/* (model
                 (GBM/Heston/jump/        VaR, ES, factor         cards, gate
                  regime paths feed        exposure, stress        reports, provenance,
                  step 5/6)                testing on step         registry — wraps
                           |               6/7 output              every subsystem's
                    volterra/* (pricing          |                 output, not just
                     Black-Scholes/Heston/   hedging/* (CVaR-      one)
                     American/barrier/        trained MLP policy
                     Asian options, Greeks,    vs. classical
                     consumed by step 6)       baselines, step 6)
```

`macrocore/` and `recessionnet/` are **not** part of the step-loop above —
they are standalone point-in-time-safe forecasting benchmarks
(h-months-ahead Mkt-RF regression; recession classification) that consume
the same `econosim.pit` schema and `experiments/` protocol
(see [docs/EXPERIMENT_GUIDE.md](./EXPERIMENT_GUIDE.md)) but run outside
the agent-economy simulation entirely, via their own
`orchestration.qmacro_run` / `orchestration.recessionnet_run` CLIs.

`service/` wraps the above as an authenticated HTTP API over a durable
local job queue (`jobs/`) — see [docs/RESEARCH_API.md](./RESEARCH_API.md)
and [docs/DATA_DICTIONARY.md § service API wire schema](./DATA_DICTIONARY.md#the-service-api-wire-schema).
It submits recipes to the queue; it does not compute anything in a request
thread.

## Interfaces each subsystem actually exposes

Rather than restate every function signature here (which would drift from
the real code within one PR), each subsystem's own top-of-module docstring
is the authoritative interface description — this document only records
the **cross-subsystem contracts** that aren't obvious from reading one
module in isolation:

- `econosim.pit.MacroObservation` is the only schema that crosses from
  `data_ingestion/*` into the simulation/forecasting subsystems — nothing
  downstream accepts a raw connector response directly.
- `experiments.manifest.compute_result_hash` (a canonical-JSON SHA256) is
  the one hashing convention reused across `experiments.holdout_manifest`,
  `experiments.dataset_fingerprint`, `evidence.security_scan`, and
  `service.reports`' `market_snapshot_id` — a specific design decision to
  have exactly one tamper-evidence primitive rather than several
  independently-invented ones.
- `evidence.model_card.ModelCard` is the one artifact every trained model
  in this repository (RECESSIONNET, Q-MACRO, the hedging MLP policy) is
  expected to produce before being compared or deployed — see
  [docs/DATA_DICTIONARY.md § ModelCard](./DATA_DICTIONARY.md#modelcard--the-mandatory-model-documentation-record).
