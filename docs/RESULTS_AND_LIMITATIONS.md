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

**Follow-up (PR-177): patience=20 (the production default here) turned
out to genuinely undertrain this model too -- but the fix surfaced a
new, separate methodological pitfall worth disclosing on its own
terms.** A 5-seed sweep at `patience=60` found `hybrid_quantum`
reaching real, well-calibrated discrimination (ROC-AUC 0.86-0.92,
calibration slope 0.95-1.17) that beats every classical candidate in
4 of 5 seeds -- a genuine improvement, not an artifact, confirmed by
checking a second, independent diagnostic (AUC/calibration) rather
than trusting the Brier-based verdict alone. Seed 0, however, is a
real cautionary counter-example: its own "quantum_better" verdict (the
bootstrap CI genuinely excludes zero) coincides with ROC-AUC 0.479 --
worse than random ranking -- because `base_rate_probability` is
computed from the TRAIN set's positive rate (5.4%) while the TEST set's
own rate differs (8.0%); after 344 epochs the quantum model drifts
toward a near-constant output that happens to match the test set's
class balance better, without learning any real per-example signal. A
THIRD instance (after Finding 1 and Finding 7) of this project's
recurring lesson: a single scalar acceptance criterion can be gamed
without the model doing anything real, and a second, independent
diagnostic is what catches it. **Not promoted to the production
default** — raising `patience` would also raise this failure mode's
own frequency (1 of 5 seeds checked), and shipping a result measured
once, without further validation across more seeds/an AUC-aware
verdict, would repeat exactly the mistake Finding 1 already corrected
once. See `tests/unit/test_recessionnet_kaggle_run.py::
test_patience_60_reveals_both_real_signal_and_a_brier_score_blind_spot`.
Separately, the ORIGINAL (Kenneth-French-factor) RECESSIONNET dataset
behind Finding 1/2 was checked the same way at `patience=60`: no
Brier/AUC divergence appears (both classical and quantum candidates
show real AUC throughout, 0.73-0.87), and the result shifts mildly
TOWARD classical (0/5 quantum-favoring, 2/5 classical-favoring, 3/5
inconclusive, vs. 5/5 inconclusive at `patience=20`) — consistent
with, and not contradicting, Finding 1/2's existing verdict.

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

**Follow-up (PR-177): checked whether `patience=20` is simply
undertraining this model -- the opposite turned out to be true, which
matters because this finding depends on it.** `benchmark_report`'s
"held-out" evaluation set is the SAME validation set early stopping
selects on, so a better in-distribution log-score at higher patience
is partly expected, not necessarily a better model; the genuinely
untouched COVID window settles it. At `patience=60`: in-distribution
log-score improves (4.82 -> 3.92) but COVID-window degradation
EXPLODES (+5.58 -> +48.75) -- now worse than the GBM baseline's
+29.97, destroying the exact property this finding reports. The model
overfits the in-distribution set at the direct expense of real OOD
robustness. This is positive evidence FOR `patience=20` as a
deliberate, correct choice, not an oversight -- "train harder" was
the wrong instinct here, and checking (not assuming) is what caught
it. See `tests/unit/test_neural_sde_run.py::
test_more_patience_improves_in_distribution_score_but_destroys_ood_robustness`.

## Finding 6 (PR-153, revised PR-177): the classical grid solver wins today, but the crossover this motivates is real and measured, not assumed

**Revised honestly: the original 1D comparison used undertrained
neural solvers, and a direct check closed most of the accuracy gap
it reported.** `pde_solvers.benchmark.compute_cost_comparison`
originally trained the deep-BSDE net for 400 epochs and the PINN at
its default learning rate (3e-3); a multi-seed sweep found the former
genuinely undertrained (price error a consistent ~1.43–1.48 across 4
seeds, not noise) and the latter improvable at the SAME epoch budget
by raising the learning rate (changing epoch count is not a clean
test here — the PINN's cosine-annealing schedule is tied to
`n_epochs`, so more epochs means a different LR trajectory, not just
"the same schedule continued"). Both are now fixed in that function:
deep-BSDE trains for 1600 epochs (price error 1.45 -> 0.005, a ~300x
cut), and the PINN uses `learning_rate=1e-2` (mean error across 4
seeds 1.58 -> 0.53). **Updated real numbers**: the classical
Crank-Nicolson grid is still simultaneously faster (0.02s vs. 22s/54s)
**and** more accurate than either neural method in 1D — but the
accuracy gap to deep-BSDE specifically narrowed from ~580x to ~2x
(price error 0.0025 vs. 0.0049), no longer the lopsided "neural loses
on both axes" picture the original undertrained numbers suggested.
Grid cost still scales as `M^d` — 200, 40,000 and 8,000,000 nodes at
d = 1, 2, 3 respectively at this package's own resolution — while the
deep-BSDE solver's walltime stays ≈flat across the same dimensions,
the actual mechanism (unchanged by this revision) by which the
neural solver's cost could pay off at higher dimensions. **Limitation
(unchanged):** the d = 3 grid case is reported analytically (node
count), not actually run in this sandbox — see `pde_solvers.
benchmark.grid_node_count`'s own docstring for why. See
`pde_solvers.benchmark.compute_cost_comparison`'s own docstring for
the full sweep numbers, and `tests/unit/test_pde_deep_bsde.py`/
`test_pde_pinn.py` for the permanent regression tests locking in both
training-budget effects.

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

**Follow-up (PR-176): a second confound, found and tested directly
rather than assumed away.** `static_baseline_cvar` was passed into
training only as a precondition gate — it never appeared in the
training signal itself, which minimized mean terminal loss, not the
CVaR the policy is actually judged on. The same reward/metric-mismatch
failure mode this project already found once in MARL's reward design
(Finding 7, below). A CVaR-aligned reward (each path rewarded by its
own excess over that batch's empirical VaR threshold — the
Rockafellar-Uryasev CVaR estimator's differentiable half) combined
with a longer, still-modest training budget (400–800 vs. the original
40 epochs; the policy has 82 parameters, so this stays fast) narrows
the gap from ~2.5x the static baseline's CVaR down to ~1.04x–1.41x
across 8 seeds at 800 epochs — but does not close it: 0/8 seeds beat
the static baseline at either 400 or 800 epochs. **Honest result: a
real, substantial improvement, and the qualitative conclusion
(REINFORCE still loses) is unchanged** — now ruled out as an artifact
of either an undertrained policy or a misaligned reward, rather than
merely asserted to be "sample inefficiency." The corrected objective
(`reward_objective="cvar"`) and the larger epoch budget are now the
real, tested production defaults
(`orchestration.rl_hedge_run.RlHedgeRunConfig`); the original
mean-loss objective remains available
(`reward_objective="mean_loss"`), and is exactly what this file's own
pre-existing loss-to-baseline test below still exercises, so that
test's original claim stays intact and unchanged. See
`tests/unit/test_hedging_rl_agent.py::
test_cvar_reward_objective_beats_mean_loss_reward_given_the_same_training_budget`
for the permanent, re-runnable, paired comparison.

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
test-set outcomes (exact binomial test, p ≈ 1.7×10⁻⁴³).

**Follow-up (PR-176): the two confounds this limitation note itself
named were tested directly, not left as speculation.** (1) *Capacity
mismatch* — `InflationGRU` has 2,786 parameters against only 139
training examples, ~2.2x the classical-MLP/hybrid-quantum challengers'
~1,261–1,265. An 8-hidden-size x 10-seed sweep (80 real training runs)
found this does **not** explain the failure: raw calibration rejects
(p<0.05) in all 80 runs regardless of hidden size (226–2,786
parameters), and point MAE stays ~3.5 throughout — capacity-matching is
ruled out, not assumed irrelevant. (2) *Calibration head* —
`fit_variance_temperature` (a standard post-hoc variance/temperature
scaling, fit by NLL on the validation split only, applied to test)
raises observed coverage substantially (from 0%–48% raw to 57%–71%
after scaling, across seeds 0–9 at the production hidden_size=24) but
does **not** close the gap to the 90% nominal target in any of the 80
runs. The residual failure is consistent with the real mechanism
already named in this project's neural-SDE finding (RQ2/Finding
on `neural_sde`): the test split (2022+) is the real 2021–2022
inflation-surge regime, genuinely out-of-distribution relative to the
calmer period the model and its calibration were fit on — a regime
shift, not an undertrained or miscalibrated-by-accident model. Both
checks are now permanent, real tests
(`tests/unit/test_inflationcast_evaluation.py`'s
`fit_variance_temperature` tests;
`tests/unit/test_inflationcast_run.py::
test_gru_calibration_is_robustly_bad_but_post_hoc_scaling_robustly_helps`,
parametrized over 5 real seeds), not a one-off script result.
**Limitation:** still one dataset, one architecture family, and a
single post-hoc calibration method (variance temperature scaling); a
fundamentally different calibration approach (e.g. conformal
prediction) or a model trained to be regime-aware was not tried, and
that remains future work, not a claim made here.

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
