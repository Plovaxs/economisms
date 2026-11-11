# Results, including negative findings, and known limits

This project's evidence discipline (README.md § The evidence discipline)
applies here too: this page reports what the comparisons in this
repository actually found, including every time a headline hypothesis did
**not** hold up, not just the results that look good. Every number below
has a corresponding test/run in this repository — see
[docs/PR_LEDGER.md](./PR_LEDGER.md) for the full PR-by-PR account each
summary is drawn from.

## The overall gate decision: NO-GO

[`evidence/gate_report_r0.json`](../evidence/gate_report_r0.json) is this
project's own, unchanged internal release gate decision: **NO-GO for
production.** Nothing in this repository is financial advice, a trading
system, or infrastructure for live trading (see
[README.md § Status & disclaimers](../README.md#status--disclaimers)). This
is the single most important "result" on this page, and it is stated here
precisely so it cannot be missed by skimming only the model-comparison
sections below.

## Finding 1 (PR-142): a fixed-epoch training budget had been silently favoring the simpler model

A diagnostic trace of RECESSIONNET's original fixed-epoch comparison
(PR-139) found the higher-capacity hybrid-quantum and classical-MLP
candidates (493 parameters) overfitting past epoch ~20-60, while 25-parameter
logistic regression did not — the comparison had been unfair the entire
time, not because of anything quantum-specific (no vanishing-gradient
plateau was observed; training loss fell smoothly the whole run), but
because nothing was controlling for capacity. Moving to validation-selected
early stopping **reversed the previously reported qualitative finding**:
real seed=0 result, quantum Brier score (~0.087) landed close to its best
classical challenger's (~0.083), and 4 of 5 seeds checked by hand were
statistically inconclusive rather than showing a robust quantum advantage.
**Limitation:** this is a small (few-hundred-to-low-thousands row) monthly
dataset; "inconclusive at 5 seeds" is an honest report of low statistical
power on this sample size, not evidence of equivalence.

## Finding 2 (PR-143): no classical/quantum regression gap either, once methodology was fixed from the start

Q-MACRO compared AR(3) (genuinely refit at every real test month, not
frozen), a classical MLP, and a hybrid quantum regressor for h-months-ahead
Mkt-RF prediction, using PR-142's early-stopping methodology from the
outset. Real result: all three learned/refit approaches landed within a
tight band (MAE ≈ 0.034, MASE ≈ 0.62), clearly ahead of naive persistence
(MASE ≈ 0.89) — but with **no significant difference among AR(3), MLP, and
the hybrid quantum model** across 5 seeds checked. The honest reading: the
hard part of this problem is beating persistence at all; once a model does
that, architecture (including "hybrid quantum") did not matter on this
data. **Limitation:** same small-sample caveat as Finding 1; this is not a
claim that no architecture could ever matter on a larger or different
dataset.

## Finding 3 (PR-145): on a second, independently-sourced real dataset, the simplest baseline won outright

RECESSIONNET re-run on real Kaggle-sourced U.S. GDP/claims/Fed-funds/M2/
NASDAQ data (a different real-data source than PR-139's original factor
data) found the **base rate** — not logistic regression, not either neural
candidate — was the strongest classical candidate on this dataset/split,
with quantum again showing no significant difference against it.
**Limitation:** a base rate winning is itself informative about how hard
(or how class-imbalanced) this particular prediction task is on this
particular dataset; it is reported here exactly because it's an
unflattering result for every model that took more effort to build, not
despite that.

## Finding 4 (PR-146): real market events used as correctness checks, not just backtests

The Treasury yield-curve connector's test suite deliberately checks the
ingested data against two real, independently verifiable historical
events rather than only internal consistency: the genuine 2-year/10-year
yield curve inversion on 2006-08-25 (4.86% vs 4.79%, preceding the 2008
recession) and the 3-month T-bill rate falling to exactly 0.00% during the
March 2020 COVID shock. A third real event (2020-04-10, Good Friday) is
used as a *discriminating* test case for the holiday-detection logic
specifically because it is a bond-market closure that is **not** a federal
holiday — proving the detection is derived from real data gaps rather than
copied from a wrong, generic federal-holiday list.

## Finding 5 (PR-150): a neural SDE is not a better average model, but is measurably more robust under a genuine shock

`neural_sde` does *not* beat simple GBM/GARCH baselines in distribution
(validation log-score 4.82 vs. baselines' ≈4.0–4.1 on real GDP YoY/
Claims YoY data). Under the real 2020 COVID shock — the genuine
sample-wide extremum in both series, independently verified against
the raw CSV rather than assumed — the neural SDE's log-score degrades
by +5.58 while a constant-parameter GBM baseline degrades by +29.97.
**Limitation:** one historical shock, not a distribution of shocks;
"more robust under this shock" is not a general robustness guarantee.

## Finding 6 (PR-153): the classical grid solver wins today, but the crossover this motivates is real and measured, not assumed

In 1D, the classical Crank-Nicolson grid is simultaneously faster
(0.013s vs. 9.3s/11.4s) **and** more accurate than either a PINN or a
deep-BSDE solver. But grid cost scales as `M^d` — 200, 40,000 and
8,000,000 nodes at d = 1, 2, 3 respectively at this package's own
resolution — while the deep-BSDE solver's walltime stays ≈flat
(≈10–13s) across the same dimensions. **Limitation:** the d = 3 grid
case is reported analytically (node count), not actually run in this
sandbox — see `pde_solvers.benchmark.grid_node_count`'s own docstring
for why.

## Finding 7 (PR-154): a degenerate reward silently determined an RL agent's "conclusion" before any training happened

A direct numeric sweep of the multi-agent economy's reward function,
done *before* trusting any training result, found that a bare
log-utility-of-consumption reward made "spend everything, every step"
trivially optimal — any apparent PPO "learning" would have been noise
dressed up as a finding. Adding a bequest-value term created a genuine
interior optimum, after which PPO discovered a materially better,
non-trivial time-varying policy. **Limitation:** one synthetic economy,
one reward family; this demonstrates the failure mode, not that every
RL reward design problem looks like this one.

## Finding 8 (PR-162): a one-line bug silently zeroed an RL policy's entire learning signal

An AI-assisted adversarial audit pass — explicitly not independent
human review — found that `hedging.rl_agent`'s REINFORCE policy used
`dist.rsample()` (the reparameterized, differentiable draw) instead of
`dist.sample()` (a detached draw) when computing the policy-gradient
log-probability. For a location-scale policy this is mathematically
fatal, not merely suboptimal: the reparameterized sample's own
dependence on the policy mean exactly cancels `log_prob`'s direct
dependence on it, so the gradient reaching the mean-producing layer was
IDENTICALLY zero (confirmed by direct measurement:
`mu_head.weight.grad.norm()` was exactly `0.0` before the fix, nonzero
after). Training ran without error and produced a normal-looking loss
curve the entire time. Fixed with a one-line change and a permanent
regression test that asserts the gradient directly, not just a
downstream metric. **Re-verified post-fix:** the already-published
conclusion (REINFORCE loses to the static baseline) is unchanged — now
true for the real reason (sample inefficiency) instead of a silent
broken gradient.

## Finding 9 (PR-168): an independent, separately-coded cross-check found a real boundary-month labeling bug

A second, independently-written implementation of RECESSIONNET's
train/test split and recession-label rules (never calling the
production functions it checks) disagreed with the real pipeline on 31
real target months. Root cause: `recessionnet.labels`' NBER chronology
table stores dates as the first day of a month, while the only real
caller queries with end-of-month dates; a raw date comparison silently
included every recession's PEAK month (documented as the last month of
*expansion*, should be excluded) and silently excluded every TROUGH
month (documented as the last month of *contraction*, should be
included). Invisible to every pre-existing unit test, because all of
them happened to query at first-of-month too — the identical "test
shares the production code's own blind spot" pattern as Finding 8 and
the ASGI dashboard-lifespan bug (`CHECKLIST_STATUS.md`'s PR-161 entry).
Fixed by comparing at (year, month) granularity; all 94
recessionnet-related tests still pass post-fix. **Limitation:** a
small, boundary-only mislabeling (31 of ~1,200 samples); no previously
reported qualitative conclusion in Findings 1–3 depended on these
specific boundary months.

## Finding 10 (PR-169): this project's own advertised "deterministic smoke test" had been silently broken

The one-command reproducibility check `README.md`/`CONTRIBUTING.md`/
`docs/PORTFOLIO_DEMO.md` all advertise — replay
`evidence/api_reference.json` and confirm an exact hash match — failed
outright when actually run, not merely drifted: `RunManifest` had
gained new fields since the committed file was last regenerated, and a
strict schema check rejected it. All 10 of this project's other
plain-named reference bundles had gone stale the identical way,
invisible to the other 2,819 tests in this repository because none of
them replay the actual committed files, only freshly-built ones. All
11 were regenerated from their own recorded configs; 5 recomputed to a
*different* result hash, confirmed to be legitimate drift from real,
already-disclosed `econosim` changes made across roughly 150 PRs since
these were first captured, not a live bug (the full suite passes
against current code, and the recomputation was independently confirmed
deterministic before any file was overwritten). **Limitation:** this is
a finding about this project's own reproducibility infrastructure, not
about any research result — it is reported here because "replays
exactly" is exactly the kind of claim this document exists to hold to
account, including when the claim is about the project itself.

## Finding 11 (PR-173): the simplest baseline won again, and the one calibrated candidate was badly miscalibrated

INFLATIONCAST (naive persistence, linear regression, a parameter-matched
classical MLP, a hybrid quantum regressor, and `InflationGRU` — a
recurrent encoder trained by Gaussian negative log-likelihood to
produce a calibrated `(mean, log-variance)` forecast, not just a point
estimate) was benchmarked on real BLS CPI-U year-over-year inflation
plus real Kaggle macro predictors, split strictly chronologically
(train < 2019, validation 2019–2021, test 2022+). Two real, honest
results: **naive persistence beat every learned candidate** on point
accuracy (MAE 0.31 vs. 1.77–3.59 for the learned models) — CPI
year-over-year is a highly persistent series month to month, a
well-documented real property, not an artifact of this pipeline or a
sign anything is broken; and **`InflationGRU`'s calibration failed
badly**: its nominal 90% predictive interval covered only ~11% of real
test-set outcomes (exact binomial test, p ≈ 1.7×10⁻⁴³). **Limitation:**
this is reported exactly as run — seed 0, the CLI's own default
splits — not re-run across seeds or architectures until a flattering
result appeared; a lower-capacity or differently-regularized
calibration head might do better, and that is future work, not a
claim made here.

## Known limitations that are not findings, just open scope

- **No independent human review of any claim in this repository has
  happened.** "Evidenced" means covered by a passing automated test here —
  not peer-reviewed, not regulator-approved, not production-ready. See
  `GOV`, `SEC`, and `LCH` categories in `CHECKLIST_STATUS.md` for exactly
  which sign-offs remain open and why they need real organizational
  authority this repository's source tree cannot itself provide.
- **No live-trading execution path exists, and none is planned**
  (`EXT` category, held at 0/12 by design) — this is this project's
  core safety boundary, not unfinished scope.
- **FRED/ALFRED ingestion (`DAT-02`/`DAT-03`) remains unbuilt** because
  `fred.stlouisfed.org`/`alfred.stlouisfed.org` are unreachable from
  this sandboxed environment, confirmed by direct repeated retry
  (general internet access is otherwise fine — e.g. Treasury's own data
  API is reachable) — an infrastructure gap, not an unwritten feature.
