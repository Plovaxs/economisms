# PR-018 local validation — 2026-11-02

Scope: bounded integer-tick wage/goods discovery, budget-limited orders,
exact pro-rata quantities, physical production/inventory, atomic market
settlement, deterministic payment rounding and ledger safeguards. This is
local work pending commit and independent review.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 52 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 558 passed in 18.59 seconds; 97% line coverage |
| `git diff --check` | Passed |

The local runtime used Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1 and
PyTorch 2.15.0+cpu. No remote CI or independent review is claimed.
Reference and replay observed the same package source digest:

```text
f583a6dd3cd2865fe4df68bca1ae315eb302a5abce63db49b3f330be2d94cf7e
```

## Reference scenario

```bash
.venv/bin/python -m prometheus.orchestration.economy_run \
  --output evidence/economy_price_reference.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/economy_price_reference.json --output evidence/economy_price_replay.json
```

The recorded scenario has one firm, two households and twelve monthly
steps. Explicit opening injections are 200,000 minor USD for the firm and
100,000 per household, totaling 400,000. No later cash injections occur.
The nominal payroll target is 18,000 per month, capped by available firm
cash. Household consumption budgets use realized wages and cash, with
propensity one in the reference. Labor and goods quantities are divisible.

Household labor supply rises linearly above a 500-cent reservation wage
at 1/50 hour per extra cent, capped at 12 hours. The firm's labor demand is
limited by its nominal budget and a 24-hour quantity cap. Goods supply is
linear above a 25-cent reference price and capped by physical inventory.
Demand is capped by household budgets and quantity limits. These monotone
rules permit deterministic bisection over integer price ticks.

Productivity is initially 10 goods per labor hour and halves at step 4.
Unsold goods carry forward. Optional seeded productivity noise defaults to
zero; any negative noise factor is explicitly clipped and recorded.
The default search allows 32 quote evaluations and records an exact
quantity tolerance of 1/1,000,000.

| Step | Wage, minor USD/hour | Goods price, minor USD/unit | Inventory after sales, approximately | Firm cash, minor USD |
|------|----------------------|-----------------------------|--------------------------------------|----------------------|
| 1 | 966 | 108 | 20.335404 | 199928 |
| 3 | 966 | 108 | 61.006211 | 199784 |
| 4 | 966 | 117 | 0.327759 | 199784 |
| 5 | 966 | 193 | 0.231212 | 199784 |
| 8 | 966 | 193 | 0 | 199772 |
| 12 | 966 | 193 | 0 | 199696 |

All quantities and rounding residuals in JSON are exact numerator/
denominator pairs; this table alone rounds inventory for readability.
The reference's selected wage/goods quotes are tick-limited. Their
nonzero excess-demand residuals are retained; valid accounting does not
establish exact equilibrium at every tick.

## Settlement and ledger fixes

Each market validates the complete participant/funding plan and posts one
balanced batch. Largest-remainder allocation distributes the integer floor
of total nominal market value among households, with deterministic ID-based
tie resolution. Aggregate nominal rounding remainder is non-negative and
less than one minor unit per market. Every paid amount has exactly matching
counterpart postings, so total cash is conserved without floating-cent drift.

The older fixed-quote helpers retain their per-household floor rounding
and posting sequence. They now validate all expected funds/participant
failures before paying the first household. Regression tests force a later
unfunded buyer and an aggregate payroll that would previously have partially
settled. NaN/Infinity, boolean quantities and aggregate float overflow are
also rejected.

Ledger now checks every posting's account currency before any balance
changes and refuses further postings on a corrupted ledger. Invalid sides
are rejected. Duplicate transaction IDs cannot be reused, rejected attempts
do not consume generated IDs, and automatic IDs avoid explicit-ID collisions.
Economic-state balance maps are copied into read-only views, preventing
mutation through either the snapshot or an aliased input dictionary.

Atomicity covers one market batch. A macro step can contain multiple
markets; a later failure halts without rolling back earlier batches.
Such a run is marked invalid, retains completed steps, and omits a valid
final inventory claim. Unresolved search limits halt by default; optional
approximate rationing retains the `iteration_limit` status.

## Exact arithmetic and negative-path evidence

Configured property tests exercise 100 goods-settlement examples, 100
payroll examples and 75 bisection examples. They check exact cash/equity
and quantity conservation, buyer budgets, aggregate wage limits and
rounding bounds. Bisection is compared with an exhaustive 30-price grid.
Unit fixtures also use an independently solved continuous root and a
half-cent root whose integer-tick residual cannot vanish.

Integration tests reconcile each household and firm payment, cumulative
production/sales/inventory and total cash/equity. They verify future-shock
causality, seeded noise replay, explicit noise clipping, zero-fund
rationing, savings-induced funding exhaustion, corrupted-ledger failure,
bounded search and exact rational JSON replay. Generic replay tests now
exercise the economy payload's corruption and fabricated-result handling.

## Actual artifact replay and compatibility

The complete reference and recomputation both produced:

```text
cdfccc07e4f1a73f9c98951c7bf726a425d79a93efb1b919e1e7b0724b70a7cb
```

Replay returned 0, `matches=true`, with no runtime changes. A separate JSON
read-back reconciled all twelve steps and twenty-four market transactions:
each batch's debits equal credits, transaction IDs are unique, all rounding
remainders are below one minor unit, aggregate cash/equity stays 400,000,
and physical inventory exactly matches cumulative production minus sales.

The original full financial monthly scenario was also rerun:

```bash
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/multi_step_reference.json --output evidence/multi_step_replay_pr018.json
```

It returned 0 and reproduced its original result hash:

```text
3525187c1dad682736baf4a10a6d0904832679499caf89d941053d87e920b80e
```

The original artifact predates runtime metadata; replay correctly reports
that absence. Its reference and previous replay remain preserved.

## Limits

Physical inventory has no monetary ledger valuation. Payroll targets,
budget demand and supply slopes are specified behavioral rules, not
estimated preferences, profit maximization or general equilibrium.
No multi-firm settlement, banking, joint monetary-policy transmission or
financial hedge integration is added by this runner. R0 remains NO-GO,
and the wider blueprint remains incomplete and unverified.
