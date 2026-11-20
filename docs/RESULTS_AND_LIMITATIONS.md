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

**Follow-up (PR-177, re-measured in PR-197 -- see Finding 13): patience=20
(the production default here) genuinely undertrains this model, but the fix
surfaced a methodological pitfall worth disclosing on its own terms.** A
5-seed sweep at `patience=60` finds `hybrid_quantum` reaching real
discrimination in every seed (ROC-AUC 0.76-0.88, calibration slope
0.23-1.18) and beating every classical candidate in 4 of 5 seeds (seed 0 is
`inconclusive`: its Brier score, 0.0955, is worse than the base rate's
0.0743) -- a genuine improvement, confirmed with a second, independent
diagnostic (AUC and calibration) rather than the Brier-based verdict alone.
**The original PR-177 write-up of this sweep described a sharper result that
did not survive a data correction.** On the PR-145 grid, whose GDP column
leaked each quarter's growth one to two months early, seed 0 produced a
"quantum_better" verdict (the bootstrap CI genuinely excluded zero) at
ROC-AUC 0.479 -- worse than random ranking -- which was read as the model
drifting toward a near-constant output that happened to match the test set's
class balance (8.0%) better than the TRAIN-derived base rate (5.4%). After
the look-ahead was removed that counter-example no longer reproduces, so
the "1 of 5 seeds" blind-spot frequency quoted before is not a property of
the method. What survives is the rule it taught: at the production default
(`patience=20`), seed 3 now produces an INVERTED ranking (ROC-AUC 0.252,
calibration slope -3.01) that is not certified as a win (verdict
`inconclusive`) but that a Brier comparison alone would not have flagged. A
single scalar acceptance criterion can mislead, and a second, independent
diagnostic is what exposes it -- the same lesson as Finding 1 and Finding 7.
**Not promoted to the production default**: seeds 0 and 3 show the model is
still unstable across seeds, and shipping a result without an AUC-aware
verdict would repeat the mistake Finding 1 already corrected once. See
`tests/unit/test_recessionnet_kaggle_run.py::
test_patience_60_shows_real_signal_in_every_seed_and_no_brier_only_win` and
`::test_default_patience_seed_3_inverted_ranking_is_never_certified_as_a_win`.
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
(validation log-score 4.83 vs. baselines' ≈4.0–4.1 on real GDP YoY/
Claims YoY data). Under the real 2020 COVID shock — the genuine
sample-wide extremum of unemployment-claims growth, independently
verified against the raw CSV rather than assumed — the neural SDE's
log-score degrades by +6.99 while a constant-parameter GBM baseline
degrades by +26.45. *(Re-measured in PR-197, Finding 13: the original
+5.58 vs. +29.97 was computed on a GDP series that leaked Q2-2020's
collapse into the window; GDP's own extremum is now correctly knowable
only after the window ends. The qualitative result is unchanged.)*
**Limitation:** one historical shock, not a distribution of shocks;
"more robust under this shock" is not a general robustness guarantee.

**Follow-up (PR-177): checked whether `patience=20` is simply
undertraining this model -- the opposite turned out to be true, which
matters because this finding depends on it.** `benchmark_report`'s
"held-out" evaluation set is the SAME validation set early stopping
selects on, so a better in-distribution log-score at higher patience
is partly expected, not necessarily a better model; the genuinely
untouched COVID window settles it. At `patience=60`: in-distribution
log-score improves (4.83 -> 3.91) but COVID-window degradation
EXPLODES (+6.99 -> +47.41) -- now worse than the GBM baseline's
+26.45, destroying the exact property this finding reports. The model
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
accuracy (MAE 0.31 vs. 1.88–3.58 for the learned models; 1.77–3.59 before
the PR-197 GDP correction) — CPI
year-over-year is a highly persistent series month to month, a
well-documented real property, not an artifact of this pipeline or a
sign anything is broken (PR-203 later showed persistence of the YoY rate to be a
weak baseline: a base-effect rule beats it by about a third, Finding 18); and **`InflationGRU`'s calibration failed
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

## Finding 12 (PR-178): a textbook recession predictor, added as a real feature, made things worse rather than better

Neither RECESSIONNET's original Kenneth French factors nor its Kaggle
macro snapshot include any direct measure of the yield curve, despite
a curve inversion (short rates above long rates) being one of the
most-studied real recession predictors in the macro-finance literature
(Estrella-Mishkin; the NY Fed's own published recession-probability
model uses exactly this 10Y-3M spread). New `data_ingestion.treasury_
yield_spread` ingests the real US Treasury 10-Year and 3-Month par
yields from `home.treasury.gov`'s own public CSV endpoint (US
government work, public domain; independently sanity-checked against
three well-known historical inversions: 2000-07 before the 2001
recession, 2007-01 before the Dec 2007 recession, and the
widely-reported August 2019 inversion before the Feb 2020 recession),
committed as a monthly snapshot. A real, disclosed constraint: this
source has no data before 1990 (confirmed by direct request), so the
combined dataset (`orchestration.recessionnet_yield_curve_run`) covers
only the real 1990-2023 overlap with the Kaggle snapshot, not its full
1981-2023 range — `recessionnet.dataset.build_monthly_series_matrix`
requires every feature to have a value for every month, with no
per-series masking the way `inflationcast.data` has.

**A direct, same-range, same-seed, same-patience ablation (spread
added vs. not, 5 seeds) found the spread does not help
`hybrid_quantum`, and mostly hurts.** Without it, ROC-AUC is
consistently decent across all 5 seeds (0.71–0.85); with it, ROC-AUC
becomes erratic and usually worse (0.35–0.83; 4 of 5 seeds lower, seed 2
higher). *Re-measured in PR-197 on the corrected GDP grid (Finding 13): the
original figures were 0.68–0.86 vs. 0.36–0.82, with 4 of 5 seeds favoring
classical WITH the spread and 1 of 5 without; on the corrected data 3 of 5
favor classical both with and without it, so the verdict counts no longer
differ -- the AUC degradation itself does not depend on the correction.*
**Limitation, stated plainly:**
this is plausibly an artifact of an already data-starved model (689
parameters against only 127 training examples in the truncated range)
getting one more input dimension to fit, not evidence that the yield
curve itself carries no signal — a feature that is this well-motivated
making things worse is itself the honest, informative result, not a
reason to drop it from this record. See
`tests/unit/test_recessionnet_yield_curve_run.py::
test_adding_the_yield_curve_spread_does_not_help_and_mostly_hurts` for
the permanent, re-runnable comparison. This is a deliberately
separate, narrower module from the pre-existing `data_ingestion.
treasury_yield_curve` (DAT-04/PR-146) connector — that one fetches 11
tenors live via FRED's `fredgraph.csv` with recorded day-count/holiday
conventions, and was unreachable from this environment both at its own
original implementation time and when independently reconfirmed here;
`home.treasury.gov` was independently confirmed reachable instead,
which is why this is a second connector rather than an extension of
that one.

## Finding 13 (PR-197): a point-in-time look-ahead in our own GDP column, found only by re-deriving the snapshot from raw data

While adding more real datasets, the PR-145 prep step -- a one-off script
that was described in prose but never committed -- was replaced by a
committed, tested builder (`data_ingestion.kaggle_build`). Re-deriving the five
columns of `data_cache/kaggle_us_macro_monthly.csv` from the raw Kaggle files
reproduced four of them **exactly** (claims, Fed funds, M2, NASDAQ: 494 of 494
months each) and **not the fifth**: 288 of 494 `GDP_YOY` cells differed. Each
quarter's growth had been forward-filled across the quarter's own months
*before* the 30-day publication lag was applied, so it appeared one to two
months before the quarter had ended or been released -- Q2-2020's -7.69%
showed on the 2020-05 row although the quarter ends on 2020-06-30 and BEA's
advance estimate came on 2020-07-30. Nothing in the point-in-time machinery
could catch it: every row had `published_at == observation_at` by construction,
so the data looked eligible by its own metadata. Only an independent
re-derivation did -- the same pattern as Finding 9.

The fix is in the data (GDP released once per quarter and held until the next
release; `python -m prometheus.data_ingestion.kaggle_build --verify-baseline`
re-audits all five columns against the committed file and now reports zero
mismatches), plus a structural regression test that makes the whole class
impossible to reintroduce silently: quarterly GDP may only change on the
Jan/Apr/Jul/Oct rows (`tests/unit/test_kaggle_build.py`).

**Measured effect**, same code and seeds, only the GDP column differing (the
pre-fix runs reproduce the previously documented figures to the digit, which is
what makes the comparison trustworthy):

| Finding | Before (look-ahead) | After (corrected) |
|---|---|---|
| 3: RECESSIONNET-Kaggle, default patience, hybrid-quantum ROC-AUC, seeds 0-4 | 0.77 / 0.86 / 0.83 / 0.87 / 0.88; 4 of 5 `quantum_better` | 0.77 / 0.86 / 0.84 / **0.25** / 0.88; 3 of 5 `quantum_better` |
| 3: same, `patience=60` | 0.48 / 0.86 / 0.92 / 0.87 / 0.88 (seed 0: a Brier-only "win") | 0.76 / 0.86 / 0.82 / 0.87 / 0.88; no Brier-only win |
| 3: 5-seed mean test ROC-AUC, hybrid-quantum, default patience | 0.842 | 0.721 (the logistic baseline stays at 0.82) |
| 5: neural SDE COVID-window degradation, neural vs. GBM | +5.58 vs. +29.97 | +6.99 vs. +26.45 |
| 5: same at `patience=60` | +48.75 | +47.41 |
| 12: spread ablation, hybrid-quantum ROC-AUC without / with | 0.68-0.86 / 0.36-0.82 | 0.71-0.85 / 0.35-0.83 |

What held: INFLATIONCAST (naive persistence still wins, MAE 0.31; the GRU's
calibration result is identical), the FP-08 encoder ablation (all six seed x
task verdicts identical), VOLTERRA-GEN (same verdict, model test NLL 12.49 ->
12.19) and the multi-horizon benchmark (the best classical candidate and the
sign of every bootstrap interval are unchanged in all nine target x horizon
cells). The qualitative verdicts of H1 and H2 are unchanged; the figures quoted
for them are updated, and the original numbers are kept in the places that
record history (`docs/PR_LEDGER.md`, the historical sections of
`CHECKLIST_STATUS.md`).

**What this does NOT claim.** Only the one column that visibly disagreed with a
release-aware derivation was corrected. The other lags (claims 7 days, M2 7
days, CPI 15 days, ...) are still fixed, documented assumptions, not fetched
release vintages -- ALFRED is unreachable from this environment -- and the GDP
and seasonally adjusted CPI levels are the latest-revised values as downloaded,
not as first published, so *revision* leakage is a remaining, undisclosed-until-
now limitation of every series here, not a solved one. The lesson is process,
not a number: a data file should be re-derivable by committed code before any
result built on it is trusted, and a prose description ("its own period's
month-end + this lag") that two readers can implement differently hid this bug
for the whole project.

## Finding 14 (PR-198): more history helped the simple classifier; more features did not

Asked to "train the models on more data", the first question is which kind of
*more*. This study separates the two on four feature sets that are all scored on
the **identical** 175 test months (decision months from 2008-01, 14 of them
positive), with the same early-stopping methodology (PR-142), the production
default `patience=20`, five seeds, and nothing tuned on the test months
(`orchestration.recessionnet_extended_study`, no network call, all data committed):

- `baseline_5` -- the five PR-145 features (GDP, claims, Fed funds, M2, NASDAQ), 1981-12 onward.
- `macro_5_short` -- five FRED-sourced features that reach back to the 1960s (GDP,
  claims, Fed funds, unemployment, seasonally adjusted CPI), restricted to the same 1981-12 window.
- `macro_5_long` -- the **same five features** over their full common history (1968-02
  onward): 6 recession episodes and 60 positive months to learn from instead of 3 and 12.
- `extended_11` -- `baseline_5` plus unemployment, seasonally adjusted CPI, bank credit,
  S&P 500 return and realised volatility, and the 10Y-3M term spread.

Test Brier score / ROC-AUC, mean of 5 seeds (lower Brier is better):

| feature set | base rate | logistic regression | matched MLP | hybrid quantum |
|---|---|---|---|---|
| `baseline_5` | 0.0743 / 0.50 | 0.1415 / 0.82 | 0.0749 / 0.68 | **0.0615** / 0.72 |
| `macro_5_short` | 0.0743 / 0.50 | 0.1466 / 0.78 | 0.0886 / 0.42 | 0.0900 / 0.70 |
| `macro_5_long` | 0.0791 / 0.50 | 0.0950 / 0.86 | 0.0891 / 0.65 | 0.0776 / 0.80 |
| `extended_11` | 0.0743 / 0.50 | 0.1494 / 0.80 | 0.0880 / 0.77 | 0.0674 / 0.87 |

**More history helps** (`macro_5_long` vs. `macro_5_short`, features held fixed): the
logistic regression's Brier score falls from 0.147 to 0.095 -- a paired difference of
-0.052, 95% moving-block-bootstrap interval [-0.122, -0.003] -- and its ROC-AUC rises
from 0.78 to 0.86. The hybrid-quantum model moves the same way (Brier 0.090 to 0.078,
AUC 0.70 to 0.80) but its interval includes zero. **More features do not** (`extended_11`
vs. `baseline_5`, history held fixed): no learned model's Brier score improves, the matched
MLP is significantly worse (+0.013, [+0.002, +0.030]), and the quantum model's Brier moves
from 0.062 to 0.067 while its AUC rises from 0.72 to 0.87 -- better ranking, worse
probabilities, the same Brier-versus-AUC tension as Finding 3, and consistent with Finding
12's earlier result for the yield-curve spread. Swapping M2/NASDAQ for unemployment/CPI on
the same window (`feature_swap_only`) significantly hurts the quantum model (+0.029,
[+0.003, +0.062]).

**What this does not show.** The best test Brier score in the whole study is still the
hybrid-quantum model on the original five features (0.0615 vs. the base rate's 0.0743), so
no configuration is a clear overall winner; the logistic regression never beats the base
rate by Brier in any configuration even at its best (0.095 vs. 0.079) -- it ranks well but
is over-confident. There are only 14 positive test months from two recession episodes
(2008-09 and 2020), twelve model x question intervals are reported without a multiplicity
correction, and the two levers are in tension in practice: the most informative new
features (S&P 500, term spread, M2) do not exist before 1980-81, so they cannot be combined
with the long history. Publication lags are fixed assumptions and GDP / seasonally adjusted
CPI are latest-revised values (Finding 13). The practical reading: if the goal is a more
accurate recession classifier, the lever with evidence is **more recessions to learn from**,
not more columns.

## Finding 15 (PR-199): on 93 years of real S&P 500 returns no VaR model survives 2008 and 2020; GARCH with filtered historical simulation comes closest, and the neural volatility model loses to GARCH but gains the most from more history

Until now every financial-risk module here ran on *simulated* returns. This study
(`orchestration.market_risk_study`, no network call, all data committed) scores one-day-ahead
Value-at-Risk and volatility forecasts on the real daily S&P 500 series from the Kaggle
dataset `henryhan117/sp-500-historical-data` (23,322 returns, 1927-12 to 2020-11), strictly
chronologically: parameters fit on returns before 2000, a validation window (2000-2007) that
only early-stops the neural model, and a 3,235-day test period from 2008-01 that contains
the financial crisis and COVID (worst day -12.77%). Every forecaster uses returns up to the
previous day only -- a leak test per forecaster changes a *future* return and checks no
earlier forecast moves. The models: a 250-day historical simulation, a constant-volatility
normal, RiskMetrics EWMA (lambda 0.94), GARCH(1,1) with a normal quantile and with
filtered historical simulation (the empirical quantile of its standardised training
residuals), and a small MLP trained by Gaussian likelihood to map six past-return features to
log volatility (a neural GARCH; 5 seeds, and a seed-averaged ensemble). The "more data" axis is
how much history each fitted model sees: the last 10 years, the last 30, or everything
before 2000 (70+ years).

**No model passes.** At 99% the test period should contain about 32 exceedances. Every one
of the 17 model-and-history variants is rejected by the conditional-coverage test at 5%, at
both 99% and 97.5%. The closest are GARCH-FHS on the full history (48 exceedances, 1.48%),
on 10 years (52) and the 250-day historical simulation (56, 1.73%); every normal-quantile
model produces 2.4% to 4.9% (79 to 159 exceedances), the fat-tail failure of a Gaussian
quantile that the training returns' excess kurtosis of 22 makes unsurprising. The
repository's strictly consistent quantile score (RISK-09's pinball loss, which ranks VaR
forecasts without leaning on exceedance counts) agrees: GARCH-FHS on the full history is
best at both levels (3.92 bp at 99%, 8.22 bp at 97.5%) against 5.63 / 10.40 for historical
simulation, 4.61 / 8.67 for EWMA, 4.74 / 8.84 for the neural ensemble and 7.10 / 11.59 for the
constant-volatility normal.

**The neural model loses to GARCH.** On the volatility forecast itself (QLIKE against the
squared-return proxy, lower is better) GARCH on the full history scores -8.2996 against
-8.2577 for the neural ensemble, a paired difference of +0.042 (95% moving-block-bootstrap
interval [+0.008, +0.086]); EWMA scores -8.2404 and a constant -7.593. The pattern of the
whole project holds once more: the more complex model does not win.

**But more history helps the neural model the most.** Trained on 10 years (about 2,500
days) the neural ensemble scores -8.137 and produces 105 exceedances at 99%; on everything
before 2000 it scores -8.258 and 79 -- a paired QLIKE difference of -0.120
([-0.252, -0.033]). GARCH benefits much less (-0.013, [-0.024, -0.004]; 93 to 87 normal
exceedances), and GARCH-FHS shows no monotonic pattern (52, 73 and 48 exceedances for 10, 30 and all
years; why was not investigated). The result is consistent with a small neural model being
data-hungry in a way a three-parameter model is not.

**What this does not show.** One market and one test period dominated by two crises: a few
exceedances move a rate by several tenths of a percent, and the coverage tests are
asymptotic. QLIKE uses the squared return as its variance proxy, which is unbiased but
noisy. The GARCH fit caps alpha + beta at 0.98 (a stationarity headroom in `fit_garch11`),
which looked like it understated the near-unit persistence of equity volatility -- PR-202 then
measured it, and loosening the cap made out-of-sample forecasts WORSE (Finding 17) -- and the neural model was given
only a normal quantile, so it is not compared with GARCH-FHS on equal terms. These are index
price returns (no dividends), close-to-close, and before 1983 the data are closes with no
intraday range. Nothing here concerns expected shortfall or a portfolio of assets, and
nothing here tells a risk manager which model to deploy -- only that none of these
unmodified models would have survived the two regime breaks in the test window.

## Finding 16 (PR-200): the simulator's own Taylor baseline does not describe the real Fed; interest-rate smoothing and momentum do, a neural rule adds nothing over a linear one, and more history helps

The policy simulator (`policylab`) trains a reinforcement-learning policy against a Taylor-rule
baseline on a *synthetic* economy. This study (`orchestration.policy_rate_study`, no network
call, all data committed) puts the same kind of rule in front of the Federal Reserve's own data
(Kaggle `federalreserve/interest-rates`: effective federal funds rate, unemployment, inflation)
and asks a modest question -- predict this month's effective rate from what was known at the
start of the month (the previous month's values, a one-month publication delay). Fit on
1958-1989, early-stop on 1990-1999, test on 2000-2017 (206 months, including the 2008 crisis and
the zero lower bound; errors are also reported on the 106 months before the lower bound, 2008-11).

**The simulator's default Taylor baseline is far from the real Fed.** `policylab.TaylorRuleBaseline`
with the simulator's own parameters (3% neutral rate, 2% target, 1.5 on inflation, 0.5 on the
output gap, the gap proxied from unemployment by Okun's law) has a pre-lower-bound RMSE of
1.45 percentage points at best (1.96 and 2.44 with shorter training windows for the
unemployment reference), against 0.23 for "the rate stays where it was" -- a paired squared-
error difference of +2.06 (95% moving-block-bootstrap interval [+0.94, +3.16]). That is a
statement about the *simulator's baseline*, not about Taylor's insight: it has no interest-rate
smoothing, and the real rate is dominated by it. Fitting the standard partial-adjustment rule
by least squares gives a persistence coefficient of 0.977 on the 1958-1989 sample, and a long-run
inflation response of 0.53 with an interval of [-6.7, +2.9] (9% of the resamples have a unit
root and no long-run response at all): the sample, which straddles the 1979 regime change,
cannot say whether the Taylor principle (a response above 1, the simulator assumes 1.5) holds.

**Smoothing and momentum, not non-linearity.** Persistence (RMSE 0.17 over the whole test
period, 0.23 before the lower bound) is hard to beat. The three-input partial-adjustment rule
does not beat it (+0.020, [-0.003, +0.041]); a linear rule that also sees the previous rate
change is better but not significantly (-0.011, [-0.033, +0.007]); a small MLP on the same six
inputs, early-stopped on validation and averaged over five seeds, is significantly better than
persistence (RMSE 0.157 / 0.196; paired difference -0.015, [-0.027, -0.005]) but **not**
better than the linear rule with the same inputs (-0.005, [-0.013, +0.008]). The gain
comes from the momentum feature, not from the neural network -- the same lesson as Finding 5
and Finding 15, and the reason the like-for-like linear baseline was added.

**More history helps.** With the last 10 years of the training window (1980-1989, the Volcker
disinflation) instead of all of it, the partial-adjustment rule's pre-lower-bound squared error
is 0.21 higher ([+0.11, +0.30]) and the six-input linear rule's 0.23 higher; the neural rule's is
0.011 higher ([+0.003, +0.019]).

**What this does not show.** One central bank and 206 test months with a regime break (the lower
bound) in the middle: every linear rule fails by construction after 2008-11, so the headline
numbers are the pre-lower-bound ones. The output gap is proxied by an assumed Okun coefficient,
inflation is the dataset's own measure, the dataset ends in 2017 and some columns are sparse,
and nothing here evaluates the RL policy itself -- only the rule it is compared against.

## Finding 17 (PR-202): leverage asymmetry improves volatility forecasts on two markets, a looser persistence cap does not, no VaR model passes conditional coverage through 2023, and pooling two markets' history closes most of the neural model's gap to GARCH

Finding 15 left four loose ends: one market, a persistence cap it named but never measured,
a neural model that gained most from more history, and a test window that ended in 2020. This
study (`orchestration.market_risk_extended_study`, no network call, all data committed) asks
five questions **written down before any number was computed** -- they are in the module's
docstring with their decision rule (a paired QLIKE difference is SUPPORTED if its 95%
moving-block-bootstrap interval lies on the predicted side of zero) -- and answers them on two
markets and a longer test window.

**Data.** The S&P 500 now runs to 2023-05-03: the PR-199 history (Yahoo ^GSPC, through
2020-11-04) continued with the SPX500 series of the Kaggle backbone dataset, rescaled at the join.
Splicing two vendors needs evidence that they agree, and they do on the 10,305 days both contain:
the median level gap is 0.002%, 99.9% of daily returns differ by under 10 basis points, and the
worst single-day disagreement is 1.0 percentage point (in 1981). The NASDAQ composite (1980-03-18
to 2023-05-03) comes from the same dataset. Everything is fitted before 2000 (S&P 500: 18,077
returns; NASDAQ: 5,003), validated on 2000-2007 and scored on the same 3,861 days from 2008-01-02
to 2023-05-03 (Finding 15 had 3,235 days ending in 2020-11); the last 626 days did not exist when
Finding 15 was written. Extending the series changed nothing before 2020-11: a test shows the same
returns, the same fit and the identical forecast on every day Finding 15 scored.

**Leverage asymmetry helps (Q-A: supported on both markets).** A GJR-GARCH(1,1) -- one extra
parameter that lets a negative return raise tomorrow's variance by more than a positive one --
has a lower mean QLIKE than the symmetric GARCH fitted by the *same* optimiser and persistence
cap: -0.0227 (95% interval [-0.0307, -0.0149]) on the S&P 500 and -0.0171 ([-0.0261, -0.0066])
on NASDAQ. The fitted leverage coefficients are 0.071 and 0.101. On the 626 unseen days alone the
S&P 500 result holds (-0.0223, [-0.0323, -0.0102]) and NASDAQ has the same sign with an interval
that includes zero (-0.0141, [-0.0286, +0.0059]). Exploratory, and labelled so in the report:
GJR also beats the GARCH of Finding 15 itself (-0.0139, [-0.0233, -0.0028] and -0.0146,
[-0.0239, -0.0036]).

**The looser persistence cap did not help (Q-B: contradicted).** Finding 15 called the 0.98 cap on
alpha + beta a limitation that "understates the near-unit persistence of equity volatility". The
pre-registered prediction was that removing it would lower the loss. It raised it, on both markets:
+0.0089 ([+0.0010, +0.0178]) on the S&P 500 and +0.0024 ([+0.0009, +0.0038]) on NASDAQ. On 70 years
of S&P 500 returns the free fit sits exactly on the new cap of 0.999 (alpha 0.091, beta 0.909): the
likelihood prefers near-integrated volatility, the one-day-ahead forecast does not. Why was not
investigated.

**Coverage still fails (Q-C: contradicted).** No model passes a conditional-coverage test at 99% or
at 97.5% on either market over the longer window. The closest at 99% is the S&P 500's
free-persistence GARCH with filtered historical simulation (53 exceedances against 38.6 expected,
conditional-coverage p = 0.011) and NASDAQ's GARCH-FHS on 30 years (59, p = 0.009); GJR-FHS has 57
(p = 0.004) and 70 (p < 0.001). The asymmetric model improves the volatility forecast but not the
calibration of the tail: the best quantile (pinball) loss at 99% is still GARCH-FHS (3.86 bp on
the S&P 500).

**Finding 15's pattern replicates in part (Q-D).** (i) The neural model has a higher QLIKE than
GARCH on both markets (+0.0364, [+0.0076, +0.0734]; +0.0612, [+0.0144, +0.1273]); on the 626
unseen days alone the sign is the same but the intervals include zero (+0.0083, [-0.0297, +0.0405];
+0.0118, [-0.0445, +0.0556]). (ii) More history helped the neural model far more than GARCH on the
S&P 500 (QLIKE improves by 0.100 against 0.011 going from 10 years to everything before 2000), as
in Finding 15. It does not replicate on NASDAQ, which has only 20 years before 2000: its 10-year
window did better for both models (neural 0.018, GARCH 0.012).

**Pooling helps the neural model (Q-E: supported on both markets).** One neural volatility model
trained on both markets' pre-2000 rows beats the single-market model on each: -0.0280
([-0.0560, -0.0086]) on the S&P 500 and -0.0586 ([-0.1139, -0.0221]) on NASDAQ. Against the GARCH of
Finding 15 the pooled model is no longer distinguishable (exploratory: +0.0084, [-0.0082, +0.0255]
and +0.0026, [-0.0166, +0.0240]), where the single-market model lost by +0.036 and +0.061. The model
that gained most from more history also gains from more markets.

**What this does not show.** Two equity indices, one fitting window and one test window dominated
by two crises. The 626-day extension is too short to test coverage (about six exceedances are
expected at 99%), so it is scored on QLIKE and counts only. There are seven paired intervals per
market -- five pre-registered, two exploratory and marked as such -- so a lone interval that
excludes zero is weak evidence. The S&P 500 joins two data vendors. QLIKE uses the squared return
as its variance proxy. The persistence result depends on this fitter and these samples and was not
explained, and the neural numbers vary with the training seed (five seeds, averaged in variance
space). Nothing here says which model to deploy.

## Finding 18 (PR-203): the inflation nowcast's own baseline was weak -- a base-effect rule cut the error by about a third, a learned model added little, and neither macro predictors nor more history helped

Finding 11 reported that naive persistence beat every learned INFLATIONCAST candidate, on a test
set of 13 months. This study (`orchestration.inflationcast_long_study`, no network call) gives the
question 277 test months and asks what the year-over-year rate hides. Writing `I_t` for the index
level, `YoY_t - YoY_{t-1}` is about `MoM_t - MoM_{t-12}`: because the month that drops out of the
window is already known, a year-over-year nowcast is a forecast of ONE unknown number, this
month's growth. Persistence of the YoY rate implicitly forecasts `MoM_t = MoM_{t-12}`. Every model
below forecasts `MoM_t` and converts it with the exact identity `YoY_t = I_{t-1}(1 + MoM_t)/I_{t-12} - 1`.
The nowcast is made at the end of month t, before month t's CPI is published, from index levels
through month t-1 (CPI-U seasonally adjusted, 1947-2023, Kaggle backbone dataset) and the grid's
macro-financial predictors on row t. Fit through 1989, validate 1990-1999 (it selects the ridge
penalty and early-stops the neural model, nothing else), test 2000-01 to 2023-01. Five questions
were **written down before any number was computed**, in the module's docstring.

**The base-effect rule beats persistence by about a third (Q1: supported).** Forecasting monthly
growth as its 12-month mean gives a mean absolute error of 0.226 percentage points against 0.326
for persistence: a paired difference of -0.100 (95% moving-block-bootstrap interval [-0.136,
-0.068]). Even the crudest rule, last month's growth, has 0.232 ([-0.140, -0.058] against
persistence). The benefit is largest when inflation moves: from 2020 on (37 months, reported not
tested) persistence has an error of 0.403 against 0.267 for last month's growth. This is not a
learned model; it is arithmetic the YoY rate hides, and it says Finding 11's baseline was the weak
one.

**A learned model adds a little (Q2: supported, narrowly).** A ridge regression on the last twelve
monthly growth rates (fit 1962-1989) scores 0.212 against 0.226 for the best rule: -0.0141
([-0.0287, -0.0006]), about 6%.

**Macro predictors did not help (Q3: inconclusive).** Adding unemployment and the policy rate
(level and 3-month change) moved the ridge by +0.0210 ([-0.0011, +0.0531]) and the neural model by
+0.0031 ([-0.0045, +0.0105]), both the wrong way. During 2020-2023 the ridge with macro inputs was
clearly worse (0.378 against 0.253 without them): a relationship fitted on 1960-1989 did not
survive the surge.

**More history did not help either (Q4: inconclusive, wrong direction).** The ridge fitted from
1949 against from 1980: +0.0088 ([-0.0005, +0.0186]); the neural model from 1962 against from 1980:
+0.0091 ([-0.0005, +0.0171]). Descriptively, the ridge from 1962 was significantly worse than from
1980 (+0.0125, [+0.0010, +0.0227]): the monthly inflation process before 1980 is a different regime
and dilutes the fit, so on this series more history is not more information.

**No variant is headlined.** The ten learned variants score between 0.199 and 0.233 on the test
months, every one at least 29% below persistence, but they differ by about 0.01 among themselves
and the validation decade cannot tell them apart (0.109 to 0.113): choosing the best on the test
months would be selection, so only the pre-registered comparisons are claimed.

**What this does not show.** One country and one price index, a test window that contains the 2008
collapse and the 2021-2022 surge, and 277 serially dependent errors (12-month blocks). The index
levels are the seasonally adjusted series as it stands today, not the real-time vintage (seasonal
factors are re-estimated for years after publication). The macro predictors sit on the grid's
fixed-lag point-in-time convention. The 2020-onward subperiod has 37 months. Nothing here is a forecast
of future inflation, and `INFLATIONCAST` itself is unchanged: the finding is about its baseline.

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
