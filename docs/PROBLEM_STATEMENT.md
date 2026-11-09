# Research problem statement and falsifiable hypotheses

## The problem

Quantitative finance research code is routinely demoed on results that
cannot be independently re-derived: a backtest with unstated leakage, a
headline number nobody can reproduce from the committed code, a claim of
model superiority that was never checked against a capacity-matched
baseline. ECONOSIM's actual research problem is two-layered:

1. **The domain problem**: do specific modeling choices (hybrid
   quantum-classical architectures, neural stochastic differential
   equations, specific training/stopping protocols) measurably improve
   forecasting or pricing accuracy over simpler, well-understood
   baselines, on real data, once the comparison controls for the things
   that are easy to get wrong (capacity mismatch, point-in-time leakage,
   test-set-driven hyperparameter selection)?
2. **The infrastructure problem**: can a research codebase be built so
   that "this works" is never asserted without a specific, reproducible,
   automated test backing it — i.e., can the evidence discipline itself
   (README.md § The evidence discipline) be maintained at scale across a
   374-item blueprint without quietly degrading into assertion?

Problem (2) is not secondary to (1): every finding in
[docs/RESULTS_AND_LIMITATIONS.md](./RESULTS_AND_LIMITATIONS.md) that
reversed or nulled an earlier claim (PR-142's early-stopping fix,
specifically) was only catchable *because* the discipline existed to catch
it.

## Falsifiable hypotheses actually tested in this repository

Stated before the fact in the sense that each is a specific, checkable
claim a result could have confirmed OR refuted — and in at least one case
below, did refute:

- **H1 (RECESSIONNET, PR-139/142/144/145)**: a hybrid quantum-classical
  classifier achieves a lower Brier score than capacity-matched classical
  baselines (logistic regression, classical MLP) on point-in-time-safe
  U.S. recession prediction, across multiple real data sources and
  multiple seeds.
  **Status: not supported.** Once training used validation-selected early
  stopping instead of a fixed epoch budget, the quantum candidate's
  advantage over its best classical challenger became statistically
  inconclusive in 4 of 5 seeds (PR-142), and on a second real dataset the
  base rate — not any trained model — was the strongest classical
  candidate, with quantum again showing no significant difference
  (PR-145).
- **H2 (Q-MACRO, PR-143)**: a hybrid quantum regressor achieves lower MAE/
  MASE than AR(3) and a classical MLP for h-months-ahead real-market-
  factor (Mkt-RF) prediction, using the same early-stopping methodology
  from the start.
  **Status: not supported** for the quantum-vs-classical half (no
  significant difference among AR(3)/MLP/quantum); **supported** for the
  weaker, still-real claim that all three beat naive persistence
  (MASE ≈ 0.62 vs ≈ 0.89).
- **H3 (DAT-04, PR-146)**: a derived-from-real-data-gaps holiday detector
  (rather than a hardcoded federal-holiday calendar) correctly
  distinguishes a genuine bond-market closure from an ordinary trading
  day, including the discriminating case of Good Friday — a bond-market
  holiday that is *not* a federal holiday, so a naive federal-calendar
  approach would get it wrong.
  **Status: supported** — verified against three real historical closure
  dates plus a real non-holiday negative control.

## What would falsify this project's own evidence claims

Any of the following, found in this repository, would mean the evidence
discipline has failed and should be treated as a bug report, not a
debatable design opinion:

- a checklist item marked evidenced with no corresponding passing test;
- a test that asserts "no exception raised" in place of a specific,
  checkable numeric claim;
- a claimed real-data result that is actually produced from synthetic or
  fabricated data without that substitution being disclosed in the code
  and in `CHECKLIST_STATUS.md`;
- a comparison between models of different capacity with no stated
  control for that difference (the exact mistake Finding 1 in
  [docs/RESULTS_AND_LIMITATIONS.md](./RESULTS_AND_LIMITATIONS.md) found
  and fixed).

## Non-goals

Explicitly out of scope, stated here so it doesn't need restating in every
other document: live trading, real order execution, investment advice,
custody of real funds, and any claim of regulatory or production
readiness. See [README.md § Status & disclaimers](../README.md#status--disclaimers)
and the separately gated, deliberately untouched `EXT` checklist category.
