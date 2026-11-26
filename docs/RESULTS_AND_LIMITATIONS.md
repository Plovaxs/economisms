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

## Finding 5 (PR-150, revised 2026-11-25): a neural SDE is not a better average model, and its "more robust under a shock" result is one training seed

**Revised 2026-11-25: the headline originally read "but is measurably more robust under a genuine shock". It is not
supported.** The +6.99 against +26.45 below is real for seed 0 and does not survive other seeds (the 10-seed update
below); H2's verdict was changed to "not supported" in `FINAL_PROJECT_HYPOTHESES.md`. The original paragraph is kept as
written so the change can be audited.

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

**Update, 2026-11-25 (an exploratory 10-seed check; this is what changed the verdict):** the +6.99 against +26.45
above is seed 0. Over seeds 0-9, the same event-window code gives a median COVID degradation of +28.73 for the neural
SDE against +26.45 for the GBM, and the neural SDE degraded less in only 4 of 10 seeds (advantage range -25.8 to
+19.5). In the 2001 recession it degraded less in 0 of 10 seeds, in 2008 in 4 of 10. So the "more robust under a
shock" half of H2 rests on a favourable seed and is not stable; H2 is now "not supported". Details: `docs/confirmatory/
e4_exploratory_seeds0-9.json` and the E4 section of `docs/CONFIRMATORY_PROTOCOL.md`.

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
across 8 seeds — but does not close it: 0/8 seeds beat the static
baseline at either 400 or 800 epochs. (Correction, 2026-11-24: this
sentence first attributed that range to 800 epochs alone. Re-running
the eight seeds with `python -m prometheus.confirmatory reproduce`
gives 1.08x–1.41x at 400 epochs and 1.04x–1.19x at 800, so the range
spans both budgets.) **Honest result: a
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

## Finding 19 (PR-212): the grid's cost wall is measured at d = 3 and 4, plain Monte Carlo does not have one, and Heston's full-truncation scheme converges strongly at 1/2 only when the Feller condition holds

Two audit items (M-04 dimension scaling, M-01's missing Heston half) were answered with measurements instead of
statements. Code: `pde_solvers/dimension_scaling.py`, `stochastica/convergence.py`
(`heston_strong_convergence_study`); data: `docs/numerics/dimension_scaling.json`.

**Dimension scaling.** The problem is a call on the geometric average of d independent lognormal assets (sigma 0.2,
T = 1, r = 5%, at the money), chosen because it has an exact price in every dimension (a lognormal average, so
Black-Scholes with forward `S0 exp((r - sigma^2/2)T + sigma^2 T/(2d))` and volatility `sigma/sqrt(d)`; checked against
the repository's own Black-Scholes at d = 1 and against a 600,000-path Monte Carlo at d = 2, 3, 5). The grid is a
tensor-product finite-difference grid in log-price, Crank-Nicolson with Rannacher start-up and one sparse LU
factorization; its error falls at second order in space (ratio 3.2-4.8 per halving, tested) and does not depend on
the width of the box. For an absolute error of 0.02 (about 0.3% of the price):

| d | grid nodes per axis | unknowns | grid error | grid time | factor storage | Monte Carlo paths | MC time |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 161 | 161 | 0.005 | 0.018 s | ~0 | 2,055,315 | 0.042 s |
| 2 | 81 | 6,561 | 0.0075 | 0.062 s | 4 MB | 1,005,217 | 0.040 s |
| 3 | 41 | 68,921 | 0.0166 | **28.9 s** | **1.3 GB** | 655,561 | 0.037 s |
| 4 | not reached (best 0.189 at 11 nodes) | 14,641 | 0.189 | 0.9 s | 87 MB | 505,719 | 0.034 s |

At d = 3 the cheapest grid that reaches the target already costs 29 seconds and 1.3 GB of factors; at d = 4 the
ladder stopped at 11 nodes per axis (14,641 unknowns) with an error ten times the target, and the next rungs were not
run: 150,000 nodes is the cap, because a direct factorization that size has taken tens of gigabytes. Monte Carlo, which
samples all d assets exactly, needs fewer paths as d grows here (the payoff gets smoother) and about 0.04 s at every d.
Fill-in, not node count, is what hurts: at roughly 6,600-6,900 unknowns the 3-D factors are more than twice the size
of the 2-D ones (tested).

**What this does and does not show.** It shows that the classical grid with a direct solver hits a wall between
d = 3 and d = 4, which is the mechanism Finding 6 argued for with node counts alone, now measured with runtime, memory
and error. It does not show a neural solver wins: none was run here, the repository's deep-BSDE and PINN numbers are
Finding 6's and were not repeated at matched error in d >= 2, and for a smooth European payoff plain Monte Carlo already
solves every d in this table in a few hundredths of a second. The comparison a neural method has to win is against that,
not only against a grid. ADI splitting and multigrid would move the grid's wall and were not tried. Memory is
`tracemalloc`'s peak for NumPy/SciPy arrays; the LU factors live inside SuperLU, so they are reported separately
(entries x 12 bytes). One machine, one run of the timings; the errors are deterministic and a test recomputes them.

**Heston strong convergence.** The log-Euler / full-truncation scheme was driven on a coarse grid by the sums of the
increments of one fine Brownian path and compared pathwise with the same scheme on a grid 8x finer than the finest tested
(steps 4, 8, 16, 32, 64 against 512; 16,000 paths). With the Feller condition satisfied (kappa 2, theta 0.04, xi 0.3,
ratio 1.78) the strong order is **0.51 for log-price and 0.61 for variance**; with it badly violated (kappa 0.5,
xi 1.0, ratio 0.04) it falls to **0.30 and 0.30** (spread over three seeds below 0.02). So the usual "strong order 1/2" statement holds in the regime where
variance cannot reach zero and fails in the regime calibrated equity parameters live in (the ratio is often below 1);
a finer time step helps less than it looks. The reference's own error biases the fitted order slightly low.

## Finding 20 (PR-215..217): tuning the models helped only where a strong classical model could be built in, and left the other two questions open

Asked to "train the models to be more accurate", this round tuned three of the project's learned models
under one rule: every choice is made on the validation window alone, the questions and their decision rule
are written in each module's docstring before any number was computed, and the test windows (already seen
in Findings 14, 17 and 18) are read only to score the selected model. Each study ships its output in
`docs/numerics/`. The deep-hedging and neural-SDE recipes were deliberately **not** touched in this round:
they are the pipelines of protocol experiments E1 and E4 (Finding 21 tunes them, with the maintainer's
permission and under the same rule).

**Neural volatility (PR-215, `orchestration.neural_volatility_v2_study`).** Sixteen configurations -- an
anchor (the old constant, or log of the GJR-GARCH volatility fitted on the same market's training rows with
the network's output layer starting at zero, so training begins exactly at GJR), six or ten features,
16 or 32 units, weight decay 0 or 1e-3 -- were trained on both markets pooled (5 seeds) and ranked by the
seed-ensemble's QLIKE on 2000-2007. The anchor dominates: every one of the eight GJR-anchored
configurations (pooled validation QLIKE -7.866 to -7.878) beats every constant-anchored one (-7.828 to
-7.839), and the longer-memory features add about 0.005 to 0.01 on top. The winner (GJR anchor, ten
features, 32 units, no decay) leads the runner-up by only 0.002, so the choice among the top four is not
resolved; the anchor choice is. On the test window it lowers the QLIKE of Finding 17's pooled neural model
by 0.0265 (95% interval [-0.0412, -0.0126]) on the S&P 500 and 0.0369 ([-0.0573, -0.0170]) on NASDAQ
(V-A supported on both). Against GJR-GARCH, the strongest classical forecast of Finding 17, it is
indistinguishable on the S&P 500 (-0.0043, [-0.0167, +0.0085]; V-B inconclusive) and better on NASDAQ
(-0.0197, [-0.0320, -0.0087]; V-B supported). **Coverage did not move**: no tuned VaR passes the
conditional-coverage test at 99% (V-C contradicted); its filtered-historical-simulation quantile is the
closest, with 53 exceedances on the S&P 500 (38.6 expected, p = 0.04) and 60 on NASDAQ (p = 0.006). So the
tuned model closes the gap to GARCH and, on one market, passes it, by starting from GJR and learning a
correction to it; it is not a model that found structure GARCH misses on the S&P 500. A look-ahead in this
study's own first draft -- the EWMA features started from the variance of the first 1,000 returns, so early
training rows saw later returns -- was caught by the leak test, fixed (the first 250 returns, all before
the first usable row) and the study rerun; no number moved by more than 0.0001.

**Inflation nowcast (PR-216, `orchestration.inflation_tuning_study`).** Twenty-four configurations (6, 12 or
24 lags; predicting MoM directly or as a residual on the 12-month mean; squared or absolute error; fit from
1962 or 1980), each with its ridge penalty, ranked by mean absolute YoY error on 1990-1999. The winner (12
lags, residual target, squared error, from 1980, penalty 100) leads the runner-up by 0.0015 over 120
months. Test MAE: 0.2084, against 0.2117 for Finding 18's ridge, 0.2259 for the base-effect rule and 0.3261
for persistence. Against Finding 18's ridge the difference is -0.0033 ([-0.0124, +0.0076]): **inconclusive**
(I-A). Against the base-effect rule it is -0.0174 ([-0.0256, -0.0093]), supported (I-B), but Finding 18
already established that the learned ridge beats it. Tuning bought about 1.5% over Finding 18's model, which
is inside the noise; the validation decade cannot rank these variants and the test window would not either.

**Recession classifier (PR-217, `orchestration.recession_calibration_study`).** Finding 14's logistic
regression ranks months well (ROC-AUC 0.86) but has a Brier score of 0.095 against the base rate's 0.079,
which reads as over-confidence. A two-parameter map `sigmoid(a * logit + b)` was fitted on out-of-fold
predictions inside the training months only (expanding window, three-year blocks from 1985, no block ever
scored by a model that saw its own labels; 192 months, 11 positive), so the validation and test months
played no part. It **did not help**: Brier 0.0986 against 0.0950 uncalibrated (+0.0036,
[-0.0101, +0.0199], R-A inconclusive) and against 0.0791 for the base rate (+0.0196, [-0.0164, +0.0687],
R-B inconclusive). The fitted map stretches (a is about 1.24, b about -0.75): on 1985-2000 the model was
under-confident, on 2008 onward over-confident, so the miscalibration is not a stable property a map can
remove. That fits the data: the test window holds two episodes (2008-09, and 2020, a shock no macro
history could signal), 14 positive months, and a 175-month Brier difference is a statement about those
two. The recession classifier's honest status is unchanged: it ranks, it does not give calibrated
probabilities that beat the base rate.

**What this does not show.** All three test windows were seen before; none of this is an untouched
confirmation. One feature family, one anchor, two markets, one country, two recession episodes. Sixteen,
twenty-four and a one-shot map were tried, so a lone interval excluding zero is weak evidence, and the
margins by which the winners were chosen are reported above so that near-ties are visible. Nothing here
changes the NO-GO decision, and nothing says which model to deploy. No data after 2023-05-03 or from a
reserved seed was read: new data was permitted, but none exists in the repository for the volatility
and inflation tests, and the protocol's untouched windows are worth more intact than spent on a tuning
run.

## Finding 21 (PR-218, PR-219): tuning the deep-hedging policy closed about half of its gap to the static baseline but did not beat it, and tuning the neural SDE made it better in ordinary months and worse in shocks

With the maintainer's permission, the two recipes that Finding 20 left alone were tuned **before** the
confirmatory freeze, each under the same rule: questions and a decision rule written in the module's docstring
first, selection on data that no confirmatory endpoint reads, and the claim carried by seeds or months that
selected nothing. No reserved seed (10000-10049, 20000-20009) and no data after 2023-05-03 was read.

**Deep hedging (PR-218, `orchestration.hedging_tuning_study`).** Thirty-six recipes (learning rate 0.003, 0.01 or
0.03; 400, 1,000 or 2,000 epochs; 16 or 64 units; initial exploration log-std 0 or -1) were each trained on eight
selection seeds (1000-1007) and ranked by the E1 statistic `theta = -log(CVaR95 policy / CVaR95 static)` on 20,000
held-out paths per seed. The baseline (band, delta, costs) was not touched: tuning it would be tuning the
opponent. The current recipe (0.01, 400 epochs) scored -0.081 on the selection seeds; the best, at the corner of
the grid (0.003, 2,000 epochs), -0.031, leading the runner-up by 0.012. On 16 fresh validation seeds
(3000-3015) the selected recipe had theta -0.039 ([-0.050, -0.027]) against -0.077 ([-0.111, -0.043]) for the
current one: **better than the current recipe** by +0.038 ([+0.003, +0.074]; H-A supported), and **still worse
than the static baseline** (theta below zero; H-B contradicted), about 4% more CVaR. Because the winner sat on the
grid's corner, a second round extended the grid toward smaller steps and longer training (12 recipes) and used 16
new validation seeds (4000-4015). Its winner (0.001, 4,000 epochs, 64 units) was not better than round 1's
(-0.002, [-0.015, +0.011]; H-C inconclusive), and round 1's recipe scored theta -0.021 ([-0.030, -0.013], about 2%
more CVaR than the baseline). The gain flattened, so round 1's cheaper recipe (0.003, 2,000 epochs, 16 units) was
adopted; that tie-break was applied after seeing round 2 and is disclosed as such. E1 now freezes this recipe;
the runner's defaults remain as the legacy recipe for Finding 8. **What it means for E1:** over 32 exploratory
seeds the tuned policy's theta averaged -0.030 with spread 0.021; if new seeds agree, E1 will report
"equivalent" (within the 5% margin), not "better". That is a smaller claim than "the policy beats the baseline",
and a more favourable label than the legacy recipe would have earned, because tuning moved the estimate toward
the margin; the protocol says so.

**Neural SDE (PR-219, `orchestration.neural_sde_tuning_study`).** The 36 recipes (learning rate, 16/32/64
units, 300 or 1,000 epochs, `patience` 20 or 50) were selected using transitions decided before 2001-03-31 only
(110 training, 28 early-stopping, 46 selection months; 47 later months for the check), so no shock window played
any part. The selected recipe (0.003, 16 units, `patience` 50) had a mean log score of 5.685 on the check months
against 5.863 for the current recipe and 5.888 for the constant GBM: a lower score than both (N-A: -0.178,
[-0.300, -0.028]; N-B: -0.203, [-0.346, -0.027]; both supported, with upper limits close to zero and 47 months).
The 300- and 1,000-epoch versions are identical because early stopping ends training first, which is why the
reported margin over the "runner-up" is 0. **The shock question went the other way.** Scored once afterwards on
E4's exploratory seeds 0-9 (estimation only, nothing selected on it), the neural SDE degraded less than the GBM in
0 of 10 seeds for 2001, 0 of 10 for 2008 and 1 of 10 for COVID (medians -0.46, -1.35 and -15.47), against 0, 4 and
4 of 10 for the old recipe. In absolute event-window scores, the tuned model beats the GBM in 6 of 10 seeds for 2001
(4.69 against 4.73) but not in 2008 (6.00 against 4.93) or COVID (45.85 against 30.57). A sharper model is rewarded in
ordinary months and punished harder when the world leaves them. So the claim "tuning made the neural SDE more
accurate" holds for ordinary months, and "more robust under shocks" holds for neither recipe. The maintainer decides
which recipe E4 freezes; the code currently uses the tuned one.

**What this does not show.** The deep-hedging simulator is one option, one geometric Brownian motion and one cost
rate; its seeds are exploratory, not a test of E1. The neural-SDE check has 47 months and three shocks. Thirty-six
recipes were compared in each study; the margins, the corner-of-the-grid caveat and the post-hoc tie-break are
stated above. Nothing here changes the NO-GO decision.

## Finding 22 (PR-220): giving the hedging policy the option's delta made it beat the static baseline in every validation seed, by about 1% of CVaR, which the protocol's own margin calls "equivalent"

Tuning the plain policy (Finding 21) closed about half of its gap to the static delta / no-trade-band baseline and
no more. One reason a plain policy loses is that it is not told the option's delta and must rediscover it, while the
baseline is handed it. At the maintainer's request a new **structure** was tried before the freeze
(`hedging.rl_agent.PolicyStructure = "delta_rebalance"`): the policy also sees the Black-Scholes delta and the gap to
it and outputs only the fraction of that gap to close, `ratio = holding + g * (delta - holding)`, `g = sigmoid(action)`.
Doing nothing and a full rebalance are both inside the family; so is the baseline's band rule. The ratio stays in
[0, 1] by construction. Three questions and their decision rules were written in the module's docstring before any
structured policy was trained (`orchestration.hedging_tuning_study`, round 3).

**Selection.** Twelve recipes (learning rate 0.003, 0.01, 0.03; 400 or 1,000 epochs; initial exploration log-std 0 or
-1; 16 units) on eight new seeds (5000-5007). The winner, learning rate 0.003, 400 epochs, log-std -1, led the
runner-up by 0.0008 in `theta`: the top ten recipes all sit between 0.0079 and 0.0120, so the choice among them is
mostly luck and the claim rests on the validation seeds. Only the two largest-step recipes failed to help (0.0009,
-0.0139).

**Validation (16 new seeds, 6000-6015, which selected nothing).** `theta = -log(CVaR95 policy / CVaR95 static)` on
20,000 held-out paths per seed, 95% t intervals:

| Policy | mean `theta` | interval | seeds above zero | CVaR vs baseline |
| --- | --- | --- | --- | --- |
| legacy plain (0.01, 400 epochs) | -0.0739 | [-0.1045, -0.0434] | 0 of 16 | +7.7% |
| plain, tuned (0.003, 2,000 epochs) | -0.0222 | [-0.0319, -0.0125] | 2 of 16 | +2.3% |
| **`delta_rebalance`** | **+0.0109** | **[0.0092, 0.0127]** | **16 of 16** | **-1.1%** |

H-A (beats the legacy default) SUPPORTED (+0.0849, [0.0540, 0.1158]); H-B (beats the static baseline) SUPPORTED;
H-C (beats the plain tuned policy) SUPPORTED (+0.0332, [0.0239, 0.0425]). Its spread over seeds is 0.0033, against
0.0182 for the plain tuned policy.

**What this means, and what it does not.**
- The policy now beats the baseline, consistently, but by about 1% of CVaR. The confirmatory protocol's margin is 5%,
  so E1 is expected to report **"equivalent"** (rule 5 checks it first), with an interval that excludes zero. The
  margin was fixed earlier and was not moved.
- The gain is a statement about the structure, not about learning to hedge from nothing: the policy is handed the
  true-volatility delta that the baseline uses, and a family that contains the baseline cannot do much worse than it.
  The claim shrinks from "a policy rediscovers hedging" to "a policy given the delta learns when to trade it".
- One option, one geometric Brownian motion, one cost rate; the volatility is the true one. Real markets give neither
  the volatility nor a stationary law. Selection used eight seeds; training ran single-threaded in workers, so the last
  digits can differ from the confirmatory run.
- The seeds are exploratory, not a test of E1. The frozen E1 run uses seeds 10000-10049, none read here.

## Finding 23 (PR-221): the confirmatory run, once, on frozen code and untouched data: E1 equivalent, E3 consistent with coverage, E2 better, E4 worse than the baseline in every event

The protocol ([CONFIRMATORY_PROTOCOL.md](./CONFIRMATORY_PROTOCOL.md)) was frozen on 2026-11-26 (tag `protocol-v1`, commit
`15add42`) and anchored on Zenodo, DOI [10.5281/zenodo.24557019](https://doi.org/10.5281/zenodo.24557019), before any of
the reserved seeds or the locked post-snapshot data were read. The four commands then ran once each, with the arguments
the protocol lists, and nothing was changed afterwards. Raw outputs: `docs/confirmatory/results/`. No endpoint was
re-run, re-tuned or dropped. The Bonferroni family is the three primary endpoints (0.05/3, intervals at 98.33%).

| Endpoint | Result | Reading under the pre-written rules |
| --- | --- | --- |
| **E1** deep hedging, seeds 10000-10049 | `theta` = +0.0107, [0.0098, 0.0116]; policy better in 50 of 50 seeds; median CVaR ratio 0.989 | **equivalent**: the whole interval lies inside the margin (+-0.0488) |
| **E3** GARCH-FHS VaR, 893 days from 2023-05-04 | 99%: 11 exceedances against 8.9 expected, Kupiec p = 0.50, conditional coverage p = 0.24, rate interval [0.52%, 2.43%] | **consistent with coverage**; 250-day historical simulation is not (15 exceedances, independence p = 0.001) |
| **E3** pinball difference (historical minus GARCH-FHS) | 99%: +0.68 bp [-0.31, 1.52]; 97.5%: +0.60 bp [-0.35, 1.42] | **inconclusive** at both levels |
| **E2** inflation, 30 months | base-effect rule MAE 0.114 pp against 0.232 pp for persistence; `theta` = +0.118 pp [0.040, 0.243] | **better** (margin 0.03 pp); blocks 6 and 12 agree; with the 13 missing months imputed (n = 43): +0.098 [0.033, 0.190], also better |
| **E4** neural SDE under shocks, seeds 20000-20009 | median advantage over the GBM: 2001 -0.40, 2008 -1.19, COVID -12.70 | **worse than the baseline in all three events** (neural degraded less in 0, 0 and 2 of 10 seeds) |

**What each result supports.**
- **E1.** The structured policy beats the static baseline in every seed, but by 1.1% of CVaR, and the protocol asked for
  more than 5% before calling it better. The honest statement is the one made before the run: a policy given the delta
  and the freedom to trade it is *statistically indistinguishable in practice* from the baseline, not better. The
  in-sample paths agree (49 of 50 seeds), so this is not a held-out artefact. The sign agrees with the validation seeds
  of Finding 22 (+0.0109); it is not a fresh surprise.
- **E3.** The coverage claim survives data the model never saw, over 893 trading days (2023-05-04 to 2026-11-23). With about 9 expected exceedances the test cannot tell a 1.5% rate from 1%
  (power note: 11%), so "consistent" means "not rejected", not "calibrated". It does not show GARCH-FHS is more
  accurate than the simple benchmark: the pinball intervals contain zero.
- **E2.** The base-effect rule's advantage re-appears in a window the earlier analysis had not seen
  (2023-04 to 2025-09), at about half the persistence rule's error. Thirteen months from 2025-10 are excluded because
  the October 2025 index level was never published; the imputed sensitivity analysis agrees. The vintage check against
  the committed series over 15 overlapping months differs by at most 0.097%. The label for this window is
  "re-used (estimation)", as the protocol says, so it is a replication of direction on a new stretch, not a clean
  confirmation: the rule was designed on earlier data and is not independent of it.
- **E4.** Not a confirmation of "more robust under shocks": the tuned recipe's neural SDE degrades more than a
  constant-parameter GBM in 2001 and 2008 in every seed, and in 8 of 10 seeds for COVID (2 seeds are better, up to
  +6.6, and the spread is large). This matches the exploratory tuned run (0, 0, 1 of 10). Three events, estimation
  only, never pooled.

**Not shown.** Nothing here changes the live-trading gate (NO-GO). E1's margin, E3's data source (chosen by the
assistant on the maintainer's instruction to use Kaggle, one Yahoo-derived series) and the choice of which recipe to
freeze were all decided before the run; any of them can be questioned. No independent replication exists, and the
analysis was written and run by the same author who froze it, which the Zenodo anchor makes checkable but does not
make independent. The second prospective analysis (750 further trading days for E3, further months for E2) is still
ahead.

## Finding 24 (PR-222): none of four return forecasts beat the historical mean on the S&P 500 test years, and three were worse; volatility management cut drawdown by a third but its Sharpe gain is not distinguishable from zero

The repository forecast volatility, tail risk and inflation, but never the market's return. `orchestration.market_forecast_study`
asks the plain question on 95 years of real daily S&P 500 returns (committed snapshot to 2023-05-03; train before 2000,
validation 2000-2007, test 2008 onward, 3,861 days). Four questions and the decision rule were written before the run
(M-A..M-D in the module's docstring). It is **exploratory**: the history was read before and the confirmatory protocol's
data and seeds are not touched. Output: `docs/numerics/market_forecast_study.json`.

| Forecast of the next daily return | out-of-sample R² vs the expanding mean | squared-error gain, 98.75% interval | direction hit rate (always-up: 54.0%) |
| --- | --- | --- | --- |
| AR(1) | -0.0054 | wholly below zero | 52.3%, wholly below |
| 12-month momentum | -0.0003 | contains zero | 53.8%, contains zero |
| ridge on nine past-return features | -0.0050 | wholly below zero | 52.6%, wholly below |
| small neural network (5 seeds) | -0.0057 | wholly below zero | 50.9%, wholly below |

- **M-A and M-B (can a model forecast the day?): not supported.** No forecast beat the historical mean, three were
  significantly worse, and none called direction better than "always up". Momentum is indistinguishable from the mean.
  This is the efficient-market reading, on data where the network had about 18,000 training days.
- **M-D (does going long only on positive forecasts earn more?): not supported.** Buy-and-hold had Sharpe 0.43
  (8.9% a year, 20.8% volatility, 53% worst drawdown); AR(1), ridge and the network timing rules had Sharpe -0.05, 0.05
  and -0.08, each significantly worse than buy-and-hold; momentum timing was 0.47 and indistinguishable (+0.05,
  [-0.22, 0.37]).
- **M-C (does managing by forecast volatility help?): inconclusive.** Holding `target_vol / GJR-GARCH forecast` (capped at 1,
  5 bp cost per unit of turnover) gave Sharpe 0.53 against 0.43 (+0.105, 95% interval [-0.06, 0.29]), volatility 14.6%
  against 20.8%, worst drawdown 35% against 53%, and annual return 7.7% against 8.9%. The drawdown and risk reduction are
  large; the Sharpe gain is not distinguishable from zero over one 15-year test path. Allowing leverage up to 2 did not
  change that (+0.08, [-0.16, 0.32]).

**What this does and does not say.** Forecasting the *level* of a liquid index from its own past is not where the value
lies here; the model that forecasts volatility (GARCH) earns its place by managing risk, as Findings 15 and 17 already
showed. Not shown: that no information forecasts returns (only past-return features were used), anything about other
markets or horizons (daily only), or that volatility management works out of sample on new data (one path, 3,861 days).
Cash earns zero and returns are index price returns, so the Sharpe ratios are not comparable to published ones.

## Finding 25 (PR-223): in a volatile simulated economy, minimum variance was the only allocation rule with shallower drawdowns, fire sales added about 40% more bank failures, and the early-warning composite barely warned

WORLDSIM (`prometheus.worldsim`) joins an economy (three regimes, output gap, inflation, a Taylor-rule policy
rate), four asset returns whose volatility and correlations change with the regime, 1,000 households with a
fat-tailed wealth distribution, ten leveraged banks linked by interbank loans (the repository's Eisenberg-Noe
clearing) whose fire sales feed back into equity prices, five allocation rules and an early-warning monitor.
**Its parameters are chosen to look like a plausible economy, not estimated; every statement below is about
the simulator.** Four questions and their rules were written before the final run
(`orchestration.worldsim_study`); 200 seeds of 240 months per scenario; output `docs/numerics/worldsim_study.json`.
A live page is at `/dashboard/worldsim`.

**Does it look like a volatile economy? (stylised facts, `volatile`)** Equity volatility 15.0% a year, excess
kurtosis 3.6, equity-bond correlation 0.05 outside crises and -0.37 in them, crises 3.9% of months, output gap
down to -3.9% at its worst on average, unemployment peaking at 6.5%. `stressed`: crises 9.1% of months, output gap
-9.1%, unemployment 9.1%, bank failures in 43.5% of runs (4.2 banks on average, when one goes several follow);
`volatile`: a bank fails in 1% of runs; `calm`: 0.5%.

| Question | Result |
| --- | --- |
| **W-A** shallower drawdown than equal weight (`volatile`, 98.75% intervals) | **minimum variance SUPPORTED**: +2.5 points of drawdown [0.9, 4.2] and +0.7 points of annual return. Risk parity inconclusive (+0.6 [-0.3, 1.5]). 60/40 and the volatility target were **worse** (-5.6 and -3.8 points) but earned +1.5 and +1.4 points a year more |
| **W-B** crises concentrate wealth (top-decile share, `stressed` minus `calm`) | **INCONCLUSIVE**: -0.7 points [-1.8, +0.3] |
| **W-C** fire sales amplify bank failures (`stressed`, with against without the price impact) | **SUPPORTED**: 4.2 against 3.0 failed banks, +1.2 [0.8, 1.6] |
| **W-D** the warning composite has information (`volatile`, AUC for "a crisis begins within 6 months") | **SUPPORTED but weak**: AUC 0.565 [0.535, 0.591] |

- **W-A is about risk level as much as rule.** Median drawdowns were -18.4% (equal weight), -23.5% (60/40), -18.5% (risk
  parity), -17.0% (minimum variance), -22.4% (volatility target); median annual returns 3.6%, 5.1%, 4.1%, 4.3%, 5.0%.
  Equal weight holds 25% cash, so the rules that hold more equity earn more and fall further. In `stressed`, minimum
  variance's median drawdown was -15.7% against -26.3% for equal weight, with the highest median return (4.0% against 1.9%).
- **W-D in plain words:** the composite fired amber or red in 1.2% of months and preceded only 17 of 395 crisis onsets
  (4%) in `volatile` (67 of 913, 7%, in `stressed`). The crisis is an exogenous random switch, so the best any monitor can
  do is read its precursors (slowdown, volatility, stressed banks); it reads them poorly at these thresholds.
- **W-B:** this model does not show crises raising the top share; wealthy households hold the risky assets and lose in
  crashes, the poor lose jobs but hold little. The Gini falls in every scenario (0.81 at the start, about 0.72 at the end)
  because the model has no force that concentrates wealth over time; real inequality has risen, so this is a model
  limitation, not a finding about the economy.

**How this was built, in order, because it matters.** A smoke run found that the first bank initialisation scaled
deposits with a random factor and left some banks insolvent on day one (one at -3.8% capital); a full study run made
before that was fixed gave bank results that were artefacts of it (for example, 58.5% of `stressed` runs with a bank failure) and was
discarded. After the fix, bank leverage (84% deposits, 86% in `stressed`, a 5% capital trigger) was set by looking at a few
smoke runs so that `volatile` has rare and `stressed` has frequent banking crises; that is a choice about the scenarios,
not an estimate, and the W-C and W-D magnitudes depend on it. The hypotheses and rules were written before the final run.

**Not shown:** anything about the real economy; firms' balance sheets, fiscal policy, a foreign sector, bail-outs and
taxes are absent; households are price takers and every participant holds the same portfolio; bank loan losses depend on the
output gap only. The gate decision is unchanged (NO-GO).

## Finding 26 (PR-224): adding firms, a government, a foreign sector and bail-outs to the simulated economy: recapitalisation ended bank failures but cost 17% of GDP, a counter-cyclical rule did more than any rescue, and a learned early-warning model did not beat the hand-made one

Finding 25 left four things out of WORLDSIM; they are now in (`config.full_scenario`, `volatile_full` and
`stressed_full`). **Firms**: one aggregate leverage ratio that builds in expansions and jumps in recessions,
raising the bank loan-loss rate (a Minsky cycle). **A government**: taxes, spending that rises when output
falls, debt dynamics (interest less inflation and growth), a sovereign spread above 90% debt and austerity
above 120%. **A foreign sector**: an exchange rate with a carry term, volatility that rises with the regime and a
risk-off depreciation when a crisis starts, imported inflation, an output effect, equity flight and bank debt
denominated in foreign currency (a currency mismatch). **Bail-outs**: none, liquidity support (central-bank
lending instead of fire sales) or recapitalisation (inject equity into banks under 3% capital up to 6%, paid by
the government, with a moral-hazard term that makes surviving banks lend faster). With every extension off the
world is exactly the one Finding 25 used (six seed-by-scenario pins in a test). Seven questions, each with its
prediction, were written before the final run (`orchestration.worldsim_extended_study`); 200 seeds of 240
months, every comparison paired on the same random draws; `docs/numerics/worldsim_extended_study.json`.

`stressed_full`, 200 seeds:

| Arm | failed banks (of 10) | runs with a failure | worst output gap | peak unemployment | public debt, end (start 0.80) |
| --- | --- | --- | --- | --- | --- |
| no rescue | 7.0 | 73.5% | -9.3% | 9.2% | 1.50 |
| liquidity support | 5.2 | 53.5% | -8.3% | 8.7% | 1.26 |
| **recapitalisation** | **0.0** | **0%** | -7.5% | 8.3% | 1.21 (cost 255, 17% of GDP) |
| no rescue, no counter-cyclical rule | 8.3 | 85.5% | -14.0% | 11.5% | 2.19 |
| no rescue, no foreign-currency bank debt | 6.3 | 64.0% | -9.0% | 9.0% | 1.44 |

| Question (prediction) | Result |
| --- | --- |
| **E-A** recapitalisation lowers failed banks (yes) | SUPPORTED, -7.0 banks [6.4, 7.7]. Nearly true by construction: an injection that restores capital prevents the failure it targets |
| **E-B** it raises public debt at the end (yes) | **CONTRADICTED**: debt is 0.29 of GDP *lower* [-0.34, -0.24], because the banking crisis and credit crunch it prevents cost more revenue than the injection |
| **E-C** a counter-cyclical rule raises the worst output gap (yes) | SUPPORTED, +4.7 points [4.4, 5.1]; debt also ends lower (1.50 against 2.19) through a debt-deflation spiral without it |
| **E-D** foreign-currency bank debt raises failures (yes) | SUPPORTED, +0.74 banks [0.32, 1.16] |
| **E-E** firm leverage raises failures, `volatile_full` (yes) | SUPPORTED, +0.58 banks [0.26, 0.90]: 7.5% of runs have a failure against 1.5% without firms (1.0% in Finding 25's world) |
| **E-F** a learned warning beats the composite out of sample (yes) | **INCONCLUSIVE**: AUC 0.553 against 0.531, difference +0.022 [-0.020, 0.061]; the ceiling, knowing the true regime, is 0.645 |
| **E-G** moral hazard raises the total injected (yes) | SUPPORTED, +13.9 [10.9, 17.0] on 255 (about 6%) |

**What to take from it.**
- **Rescue design matters less than macro policy here.** Recapitalisation removed every bank failure, but the
  counter-cyclical rule moved the worst output gap by 4.7 points against 1.8 for recapitalisation, and lowered
  debt. Both lean on assumptions: a fiscal multiplier of 0.8 (steady state, `impulse_scale`) and no cost to the
  state of a bank failure (no deposit insurance payout or resolution cost is modelled), which flatters "no rescue" on
  debt and understates E-B's sign. E-B and E-C are therefore statements about this model's channels, not
  about real fiscal arithmetic.
- **A learned warning model adds almost nothing.** The crisis is an exogenous random switch, so the best any
  indicator can do is read the slowdown regime that precedes it; even the oracle that knows the regime reaches 0.645.
  Nine indicators and 19,000 training months gave 0.553.
- **Sensitivity (25% moves, mean failed banks, `stressed_full`).** The results lean first on bank equity (25% more
  equity at the start: 5.1 fewer failed banks), then on the capital trigger (+2.1), loss given default (+2.0), the loan-default
  sensitivity to the output gap (+1.4) and firm default sensitivity (+0.6); the fire-sale price impact (+0.2) and the
  foreign-currency debt share (+0.2) matter little. Higher capital trigger raises failures here because more banks sell into a thin market.
- **Calibration.** All eight stylised-fact guard rails hold for `volatile` (equity volatility 15.0%, excess kurtosis
  3.5, equity-bond correlation -0.37 in crises, crises 4.0% of months, worst output gap -3.9, peak unemployment 6.5%,
  bank failure in 1% of runs). They are broad ranges, not a fit.
- **Inequality still falls** (Gini 0.82 at the start, 0.75 at the end of `volatile_full`; 0.72 in Finding 25's world):
  wealth-dependent saving and a return premium for the top decile slow the fall but do not stop it. A model of rising
  inequality needs forces this one does not have.

**How it was built.** The first leverage rule had no mean reversion and drifted to its bounds, which made
`volatile_full` fail 8.8 banks on average; it was redesigned (build in expansions, bump in recessions, revert) before
the final run, and scenario values such as the initial debt (0.80), the multiplier and the moral-hazard coefficient were
chosen, not estimated. Everything in the table comes from the one final run.

**Not shown:** anything about real economies. No sovereign default, deposit insurance, central-bank balance sheet,
bank resolution, trade partners or housing; every number depends on chosen parameters.

## Finding 27 (PR-225): closing the loops between households, banks, the state and the rest: the connected economy transmits shocks the unconnected one absorbs, a sovereign default is mostly a consequence of a banking crisis, and leaning against leverage backfired

Finding 26's sectors talked one way. In the **connected** world (`config.connected_scenario`,
`LinkParams`) they feed back on each other. Households (1,000, one fixed passive portfolio) are inside the world:
their consumption drives next month's output gap (the gap in the spending-to-income ratio, so growth does not
create a boom), their taxes (a flat rate with a progressivity exponent, and an optional wealth tax) and transfers
are the government's revenue and part of its spending, and an uninsured deposit loss in a bank failure falls on
the wealthiest fifth. **Deposit insurance** is paid by the state at once (80% of the depositor shortfall, using a
60% loan recovery). Banks hold the government's bonds (40% of their securities), so a **sovereign default**
(a hazard above 150% debt, a 30% haircut, a 24-month exclusion, a currency jump, a spread jump, an output shock)
hits them. Firm distress raises unemployment, and the central bank can **lean** against firm leverage. Inequality
forces (faster income growth and a higher return premium at the top) make a `rising_inequality` scenario. With the
links off the Finding 26 world is unchanged (eight pins in a test). Eight questions with predictions were written
before the final run (`orchestration.worldsim_connected_study`), 200 seeds, paired on the same draws;
`docs/numerics/worldsim_connected_study.json`.

| Question (prediction) | Result |
| --- | --- |
| **C-A** counting failure costs, recapitalisation ends with lower public debt than doing nothing (yes) | SUPPORTED, 0.062 of GDP lower [0.031, 0.093]. Direct outlays go the other way: the injection costs 17.3% of GDP, deposit insurance without it 3.8%. Recapitalising also cuts sovereign defaults from 51.5% to 34.5% of runs |
| **C-B** connecting the sectors worsens the worst output gap (yes) | SUPPORTED, 0.49 points worse [0.15, 0.84]; failed banks not different (-0.13 [-0.40, +0.14]) |
| **C-C** banks' holdings of government bonds raise failures under sovereign stress (yes) | **INCONCLUSIVE**: +0.10 banks [-0.04, +0.23] (2.25 against 2.15). Only 8% of defaults came before any bank failure: the state's trouble mostly follows the banks' |
| **C-D** the inequality forces raise the Gini (yes) | SUPPORTED, +0.029 [0.028, 0.030] (0.817 to 0.846); the top-decile share rises 6.4 points (0.73 to 0.79) |
| **C-E** progressive and wealth taxes lower the top-decile share (yes) | SUPPORTED, -1.7 points [1.7, 1.7], Gini 0.835 against 0.846; but the worst output gap is 0.40 points deeper and the state ends in surplus (debt -0.54: the proceeds are not spent) |
| **C-F** leaning against firm leverage lowers bank failures (yes) | **CONTRADICTED**: +0.15 failed banks [0.04, 0.26] and a worse worst gap (-10.07 against -9.80) |
| **C-G** full deposit insurance leaves the rich a larger share (yes) | SUPPORTED but trivial: +0.04 points [0.03, 0.05] |
| **C-H** the consumption link worsens the worst output gap (yes) | SUPPORTED, 0.51 points [0.21, 0.82]; 6.9 against 6.3 failed banks |

**Interconnection, measured.** The shock-by-outcome matrix (seven one-off shocks, eleven outcomes over 24 months,
60 paired seeds, `worldsim.impulse`): **55 of 77 cells (71%) have intervals that exclude zero in the connected
world, 18 of 77 (23%) in the unconnected one.** A 30% equity crash lowers output by 0.48 points, raises
unemployment by 0.28 points, cuts consumption and moves the public debt in the connected world; in the
unconnected world only equity returns move. A sovereign default lowers output by 2.3 points, raises unemployment
by 1.5 points and fails 1.2 more banks, and cuts the debt ratio by 0.27 (the haircut). An 8% loan loss to every bank
produced no significant response: bank capital absorbs it.

**What to take from it.**
- **Most of the amplification comes from the feedback through households and from bank leverage**, not from the
  sovereign. Sensitivity (`sovereign_stress`, 25% moves, mean failed banks): bank equity at the start -8.6 banks
  (more equity, fewer failures), initial public debt +7.3, loss given default +1.8, firm default sensitivity +1.4,
  the fiscal multiplier -1.1, the consumption link +1.0; banks' holdings of government bonds +0.3, the haircut
  +0.1 and the insured share 0.0.
- **Leaning against leverage backfired in this model** because a higher rate in a leveraged boom deepens the
  bust it was meant to soften; the result depends on the lean coefficient (0.1) and the weak link from the rate to
  leverage, and is not a statement about macroprudential policy.
- **Taxing the top lowers its share but the model keeps the money**: the state runs surplus and does not spend it,
  and demand from the rich falls, so the output cost is probably overstated and the debt effect is not a result.
- **Inequality rises only because forces were added**, the Gini by 3 points over 20 years and the top decile's share by 6.

**How it was built, in order.** The first version of the demand link used consumption growth, which cancelled a
one-month shock; the second used its level, which made the inequality scenario boom because top wealth grows; the
final one uses the spending-to-income ratio. Two scenarios were changed after a first full run: the first
`rising_inequality` had weaker forces and the Gini fell (-0.008, CONTRADICTED), so the forces were strengthened and the
question rerun on the new scenario; the first `sovereign_stress` started from a stressed economy where 97% of runs had
bank failures anyway, so the channel could not be seen, and it now starts from the volatile economy with 130% debt.
Those were choices about the scenarios, made after seeing a run, and the C-C and C-D results depend on them.

**Not shown:** anything about real economies. Parameters are chosen; the crisis is still an exogenous random switch;
deposit insurance has no premiums or fund; one tax rate with a progressivity exponent; no housing, no sovereign
rating or market access beyond a spread, no central-bank balance sheet.

## Finding 28 (PR-226..228): estimating the simulated economy's parameters from real data instead of choosing them: the first attempt did worse than the chosen parameters out of sample, a revision that tied the output gap to real GDP did not, and the claim that connecting the sectors makes shocks travel survived both

Findings 25 to 27 used parameters chosen to look plausible. This finding replaces the ones that real data can speak to
and asks whether that helps. Data (all in `data_cache/`, Kaggle sources already used elsewhere): S&P 500 monthly price
returns 1928-2023; monthly US unemployment, CPI inflation, the federal funds rate and bank credit 1960-2023; quarterly
real GDP growth 1954-2016. Method (`worldsim.real_calibration`, `orchestration.worldsim_calibration_study`):

1. **Direct estimates.** A three-state Gaussian hidden Markov model of monthly equity returns gives the regime
   transition matrix and each regime's mean and volatility of equity returns (the mean in the worst regime is reduced by
   the model's own entry jump divided by the expected spell, so the jump is not counted twice); sample means give the
   inflation target, the neutral real rate and the natural unemployment rate; Okun's coefficient is estimated as
   described below.
2. **Indirect inference** for the macro block (nine parameters: persistence of output and inflation, the Phillips
   slope, inflation volatility, the Taylor rule's two coefficients and smoothing, and a scale on the size and on the
   shift of the output shocks). Twelve statistics of the real data (the unemployment gap's volatility, persistence and
   skew, the monthly change in unemployment, the volatility and persistence of inflation and of the policy rate, the
   coefficients of a Taylor-rule and a Phillips-curve regression) are matched by simulation, each weighted by the
   standard error of the real value from a 200-replication block bootstrap; Nelder-Mead from three starts.
3. **Bank lending**: the two loan-growth parameters against bank-credit growth.

Bond and real-asset returns, bank balance sheets and loss rates, the firm, fiscal, foreign and household blocks have
no data here and keep their chosen values (`design.not_calibrated` in the result files).

**Pre-written hypotheses (written into the script before the first run).** **K-A**: on the held-out months 2000-2023
(estimation used 1960-1999 only) the calibrated world is closer to the data than the chosen `volatile` world, in the
sum of squared standardised gaps over 19 statistics (SUPPORTED if the 95% interval of the paired difference over real
bootstraps is above zero). **K-B**: of seven statistics no stage targeted, at least five of the calibrated world's values
lie inside the real 95% interval (SUPPORTED; at most two is CONTRADICTED). **K-C**: in the calibrated connected world the
share of shock-by-outcome cells with an interval excluding zero exceeds that of the same world with the links off by
at least 0.20.

### First run (output gap not anchored): K-A CONTRADICTED

| Hypothesis | Result |
| --- | --- |
| **K-A** held-out distance, chosen 478.5, calibrated 1,267.2 | **CONTRADICTED**: the calibrated world was farther by 789 [725, 954]; closer on 6 of 19 statistics |
| **K-B** untargeted statistics | **INCONCLUSIVE**: 4 of 7 inside |
| **K-C** connected 78% of cells (60 of 77) against 36% (28) with the links off | SUPPORTED |

The diagnosis: nothing in the data fixed the **size of the model's output gap**. Okun's coefficient came from a
regression of the quarterly change in unemployment on annualised GDP growth, which is attenuated (0.24, against the
textbook 0.4 to 0.5), so the unemployment statistics could be matched with an output gap several times too large: in
the first calibrated world, over paths as long as the sample, the output gap has a standard deviation of 4.3 points and an
average minimum of -19.3 (the chosen world: 0.9 and -3.7). One parameter ended at its bound, the credit statistics were not matched
(simulated credit growth -28% a year against +7%), and a robustness run at the estimation length (770 months, not the
240 of every scenario) made public debt run away in three of forty paths of the links-off world and failed (a mistake in
the script, fixed; both runs now use 240 months). The first run's result is kept as it was
(`docs/numerics/worldsim_calibration_study.json`).

### Revision 2 (written after reading the first run, before the second): anchor the output gap

The real output gap is the Hodrick-Prescott cycle (smoothing 1600) of cumulated quarterly real GDP growth; Okun's
coefficient is the slope of the unemployment gap on it (0.37 on 1954-1999, 0.40 on 1954-2016), and the standard
deviation of the gap (1.62 and 1.53 points) becomes a thirteenth targeted statistic. The hypotheses were asked again
with the same rules (K-A2, K-B2, K-C2) with one more, **K-S**: the calibrated world's output gap has a standard deviation
between 1 and 4 points in both the plain and the connected world, no path fails numerically, and no macro parameter
sits at a bound.

| Hypothesis | Result (`docs/numerics/worldsim_calibration_study_v2.json`) |
| --- | --- |
| **K-A2** held-out distance, chosen 485.2, calibrated 382.6 | **INCONCLUSIVE**: calibrated closer by 103 but the interval is [-17, 133]; closer on only 7 of 20 statistics |
| **K-B2** untargeted statistics | **SUPPORTED**: 6 of 7 inside (volatility clustering, recession depth, the tail of the unemployment gap, equity/unemployment co-movement, rate-change volatility, inflation skew; the worst month, -22% against -17%, is outside). The chosen world has 5 of 7 |
| **K-C2** connected 74% of cells (57 of 77) against 27% (21) with the links off; the chosen world 75% against 26% | **SUPPORTED** (the calibrated world's worst output gap: connected minus plain +0.11 [-0.28, +0.49]) |
| **K-S** output gap sd 2.0 (plain) and 2.1 (connected) at 240 months; 2.2 and 2.8 at the sample length; no failed paths; no parameter at a bound | **SUPPORTED** |

**What the numbers say.**
- The estimated parameters (the shipped `calibrated` scenarios, `worldsim.calibrated`) are an inflation target of
  3.8% and a neutral real rate of 1.1% (full sample), Okun 0.40, a natural unemployment rate of 5.95%, a Taylor rule
  with inflation coefficient 1.3 and output coefficient 0.41, strong interest-rate smoothing (0.95), persistent inflation (0.98),
  an output persistence of 0.85, and regimes of 95/97/92% persistence. In the in-sample fit the thirteen
  statistics are matched with a distance of 19.3; the informal over-identification statistic (4 degrees of freedom,
  5% critical value 9.5) therefore says the fit is not exact.
- **Out of sample the calibrated world is not clearly better.** Its point distance is smaller, but 212 of the 383 come from
  the three credit statistics, which no calibration matched (in the full-sample fit simulated credit growth is 0.2%
  a year against 7.1%: the model's capital-constrained banks stop lending, a block that was not estimated), and the monetary
  statistics move between 1960-1999 (Volcker, high rates) and 2000-2023 (zero lower bound). **Exploratory, after the
  fact, not a result of the pre-written test:** without the three credit statistics the distance is 171 against
  392 for the chosen world; without credit and the six monetary statistics it is 42.5 against 35.9, no better.
- **Three parameters are identified by the data and six are not.** Moving a parameter 20% either way raises the
  distance by more than 3.84 (a 5% chi-square) only for the persistence of output, the persistence of inflation and the
  rate smoothing; the Phillips slope, inflation volatility, the Taylor coefficients and the two shock scales are
  flat. One of three optimiser starts failed outright.
- **The finding of Finding 27 survives calibration.** With the links on, a clear majority of shock-by-outcome cells
  respond in a world built from data (74%) as in the chosen one (75%), and about a quarter do with them off
  (27% and 26%). That is a statement about the simulator's wiring, which calibration of the macro block does not change; it
  says nothing about the real economy.

**Not shown:** that the calibrated world is a good model of the US economy. The regimes are the model's own: the
hidden Markov model's middle state, which the data puts in 69% of months, is called "slowdown" and is the ordinary
state; the model's crisis state has about 10% of months against 12% of NBER recession months, and the two are not the same
thing. Standard errors of the targeted statistics ignore simulation noise (18 paths) and the over-identification
statistic (19.3 against a 5% critical value of 9.5 for 4 degrees of freedom) is informal; the unemployment-gap
kurtosis in 2020 dominates several real statistics. The held-out period is one 23-year history, with a different
monetary regime from the estimation sample. Credit growth is the model's weakest link to data.

**New tools.** `/dashboard/transmission` (and the desktop "Shock transmission" explorer) draw where a shock enters and which
feedback loops carry it, measured on paired seeds with and without each loop; `calibrated`, `calibrated_full` and
`calibrated_connected` are selectable everywhere a WORLDSIM scenario is.

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
- **The desktop application has only been driven headlessly.** Its window was rendered and exercised
  on Qt's `offscreen` platform (every page's screenshot reviewed, in both themes, and a real job run
  through it end to end), which is also all this project's CI can do: there is no display there. On
  the author's own X11 desktop it could not open at all until the system library `libxcb-cursor` was
  installed, which is exactly the kind of thing an offscreen test cannot reveal -- `econosim desktop`
  now says so instead of aborting. Windows and macOS are untested, and running jobs needs Linux (the
  isolated worker uses parent-death signalling and resource limits). The layout was reviewed only at
  960x600 (the enforced minimum), 1256x706 and 1500x993; below 800 px of height pages hide their
  explanatory text. No packaged binary exists, and building one would take on the LGPL's
  obligations for Qt (see `docs/LICENSE_INVENTORY.md`).
