# Beyond Model Complexity: An Empirical Evaluation of Classical, Deep Learning, and Hybrid Quantum Models for Quantitative Economic and Financial Tasks

**FP-22**: "A final paper includes limitations and null/negative
experiments." This document is that paper. It is dated **2026-11-15**,
against commit `1bcd2fd` (the most recent commit as of this writing).

It makes no claim beyond what is already evidenced elsewhere in this
repository — every number below is drawn verbatim from
[`docs/FINAL_PROJECT_HYPOTHESES.md`](./FINAL_PROJECT_HYPOTHESES.md),
[`docs/RESEARCH_CONTRIBUTIONS.md`](./RESEARCH_CONTRIBUTIONS.md), and
[`docs/RESULTS_AND_LIMITATIONS.md`](./RESULTS_AND_LIMITATIONS.md), which
remain the full, continuously-updated primary record. This paper's job
is to assemble that evidence into one linear, self-contained account —
not to re-derive it, re-run it, or restate it with different numbers.
Where this paper and those documents ever disagree after a future edit
to either, the living documents are authoritative; this paper should be
corrected to match, the same discipline it asks of itself below.

## Abstract

Quantitative finance research code is routinely demonstrated on results
that cannot be independently re-derived. This project (ECONOSIM, formerly
PROMETHEUS) tests, on real data and under an enforced reproducibility
discipline, whether added model complexity — deep learning, hybrid
quantum-classical architectures, or both — measurably improves forecasting
or pricing accuracy over simpler, well-understood baselines on six
quantitative-economics tasks: recession classification, macro factor
regression, inflation nowcasting with uncertainty calibration, option
pricing via neural PDE/BSDE solvers, multi-agent reinforcement learning
in a simulated economy, and deep hedging via a REINFORCE policy. Five
falsifiable hypotheses (H1–H5) were frozen on 2026-11-11 against evidence
gathered through that date and are reported here without revision to
their wording or verdict; a sixth result (inflation nowcasting) and two
further post-freeze checks are reported alongside them, disclosed as
such. Across all of these, the more complex method winning was the
exception, not the rule: a hybrid quantum-classical classifier showed no
significant advantage over classical baselines on recession prediction
(3 independent tests, all bootstrap confidence intervals including
zero); a neural SDE did not beat simple baselines in-distribution but
degraded measurably less than a classical GBM baseline under a real
2020 shock; a REINFORCE hedging policy lost to a well-specified static
baseline even after a real implementation bug and a reward/metric
mismatch were found and fixed; naive persistence beat every learned
inflation-forecasting candidate, and the one calibration-aware candidate
was confidently miscalibrated (90% nominal coverage, ~11% observed,
p ≈ 1.7×10⁻⁴³). The one case where the more complex method's cost was
justified — a neural PDE/BSDE solver's wall-time scaling advantage over
a classical finite-difference grid at higher problem dimension — was
demonstrated by direct measurement, not assumed, and only after an
undertrained baseline in an earlier pass of this same experiment was
caught and corrected. Methodologically, two independent instances were
found, within this project itself, of a naive evaluation protocol
(fixed-epoch training; an unaudited reward function) silently producing
a false comparative conclusion that a more careful protocol reversed.
The project's main contribution is not any individual result but the
mechanism that makes these results trustworthy: a 374-item requirements
register machine-cross-referenced against named, currently-passing
tests, and a standing practice of publishing null and negative results
with the same visibility as positive ones.

## 1. Introduction

Quantitative finance research code is routinely demoed on results that
cannot be independently re-derived: a backtest with unstated leakage, a
headline number nobody can reproduce from the committed code, a claim of
model superiority that was never checked against a capacity-matched
baseline. This project's research problem is two-layered:

1. **The domain problem.** Do specific modeling choices — hybrid
   quantum-classical architectures, neural stochastic differential
   equations, neural PDE/BSDE solvers, reinforcement learning — measurably
   improve forecasting or pricing accuracy over simpler, well-understood
   baselines on real data, once the comparison controls for the things
   that are easy to get wrong (capacity mismatch, point-in-time data
   leakage, test-set-driven hyperparameter selection)?
2. **The infrastructure problem.** Can a research codebase be built so
   that "this works" is never asserted without a specific, reproducible,
   automated test backing it, at the scale of a 374-item requirements
   register, without the discipline quietly degrading into assertion as
   the codebase grows?

Problem (2) is not secondary to (1). Every finding below that reversed
or nulled an earlier claim (most notably §5.4) was only catchable
*because* the infrastructure existed to catch it — a fixed-epoch training
protocol silently favored a simpler model for several pull requests
before a diagnostic trace surfaced it.

This paper reports what was actually found testing problem (1), using
problem (2)'s own infrastructure as the standard of evidence for every
claim made. It deliberately does not reframe a null result as a tuning
problem, and it reports the methodological failures found along the way
as findings in their own right, not as errata.

## 2. Governing specifications and scope

This project is built against two documents that remain authoritative
for different parts of its scope:

- The original **374-item master blueprint**
  ([`docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf`](./PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf)),
  governing the broader engineering and deployment constraints, numerical
  finance and accounting standards, and project governance.
- The **PROMETHEUS-X final-project addendum**
  ([`docs/PROMETHEUS_X_Final_Project_Integrated_Blueprint.md`](./PROMETHEUS_X_Final_Project_Integrated_Blueprint.md)),
  a 24-item (FP-01–FP-24) addendum defining this specific academic
  final-project's scope: a frozen title and hypotheses, real data, a
  working demo, and — this document's own requirement, FP-22 — a final
  paper that includes limitations and null/negative experiments.

Neither document is treated as satisfied by its own text alone (FP-24).
[`CHECKLIST_STATUS.md`](../CHECKLIST_STATUS.md) is the living record of
exactly which of the 374 + 24 items are evidenced, by which test, as of
any given commit; as of the commit this paper cites, that is 351/374
blueprint items (93.9%) and the final-project addendum items individually
itemized in §6.

**Scope boundary, stated plainly:** nothing in this repository is
financial advice, a trading system, or infrastructure for live trading.
This project's own internal release gate
([`evidence/gate_report_r0.json`](../evidence/gate_report_r0.json)) is an
explicit, unchanged **NO-GO for production** — stated here, not just in
a disclaimer footer, because it is a result in its own right: a research
platform that is honest about not being production infrastructure.

## 3. System overview

Six subsystems sit behind one shared evidence discipline:

- **A multi-agent computational economy** — households, firms, banks and
  a government on a real double-entry ledger, with point-in-time data
  access, deterministic shocks, and a PPO-trained multi-agent
  reinforcement-learning policy benchmarked against a deterministic/
  calibrated baseline.
- **Classical and stochastic-volatility market models** — GBM, Heston,
  Merton jump-diffusion, and regime-switching, with Monte Carlo and
  closed-form pricers for European, American, barrier, and Asian
  options, plus a neural SDE trained on real macro data.
- **Neural PDE/BSDE option-pricing solvers** — a physics-informed neural
  network (PINN) and a deep backward-SDE (deep-BSDE) solver for the
  Black-Scholes PDE, benchmarked against a classical Crank-Nicolson grid
  and the closed-form price.
- **Institutional risk analytics** — Value-at-Risk, Expected Shortfall,
  factor exposure, stress testing, portfolio optimization, and
  covariance shrinkage.
- **Deep hedging and inflation nowcasting** — a CVaR-trained neural
  hedging policy, and a recurrent encoder (`InflationGRU`) producing a
  calibrated `(mean, log-variance)` inflation forecast, both benchmarked
  against classical baselines.
- **A real, authenticated research dashboard and unified web frontend**
  exposing every subsystem above as a live, pollable job, used as this
  project's real-webapp demo requirement rather than a static report.

All six reuse a shared point-in-time data layer (`econosim.pit`) that
raises rather than silently returning partial data when a feature is not
yet eligible as of a given decision date, and a shared manifest/evidence
format (`RunManifest`, `evidence_bundle`) carrying a seed, a source-tree
code hash, a data hash, and a model ID for every run.

## 4. Methodology

### 4.1 The evidence rule

A claim is "evidenced" in this project if and only if a specific, named,
currently-passing automated test in this repository exercises that exact
claim — not a docstring, not a design note, not a one-off manual check.
This rule is enforced structurally, not just by discipline: a 374-item
requirements register is machine-cross-referenced against the test suite
via `prometheus.evidence.requirements`
([`docs/implementation/blueprint_register.json`](./implementation/blueprint_register.json),
regenerated and diffed on every change), so a claim marked evidenced with
no corresponding test is, by this project's own stated definition, a bug
report rather than a debatable design opinion.

### 4.2 Point-in-time safety

Every real-data pipeline in this project enforces that a feature used to
make a decision at date *t* could actually have been observed by date
*t* — not merely that it has a timestamp before *t* in a static CSV.
`econosim.pit.build_feature_vector`/`require_eligible` raise a
`FutureDataError` and fail the *whole* request rather than silently
returning a feature vector missing just the one series that is not yet
eligible. This matters concretely for one of this paper's own findings:
RECESSIONNET's real NBER-chronology labels are tested specifically for
whether `as_of` queries would have leaked the Great Recession's label
before its real 2008 NBER announcement date — not merely whether the
code runs.

### 4.3 Matched-capacity, validation-selected comparison

Every classical-vs-deep-learning-vs-quantum comparison in this project
holds model capacity and training protocol as controlled variables, not
free parameters that can inflate one side of the comparison:

- Classical MLP and hybrid-quantum candidates are **parameter-matched**
  wherever they are compared.
- Model selection (early-stopping epoch) is chosen from a **validation
  split carved out of the training era**, never from the test set — and,
  as §5.4 and §6 report, this specific control was itself the subject of
  a methodological finding: an earlier fixed-epoch protocol had been
  silently favoring the lower-capacity model.
- Every comparison reports a **bootstrap confidence interval** on the
  quantum-vs-best-classical gap, not just a point estimate, so "no
  significant difference" is a testable claim rather than an eyeballed
  one.

### 4.4 Real data, disclosed substitutions

Every dataset used for a reported result is real, licensed, and
disclosed with its source, license, and any known scope limitation —
U.S. recession chronology and macro indicators (NBER, a Kaggle mirror of
real FRED series, Kenneth French's factor library), U.S. Treasury par
yields, and BLS CPI-U inflation. Where an authoritative host was
unreachable from this project's environment (FRED/ALFRED, confirmed by
repeated direct retry), the gap is recorded as an infrastructure
limitation (§6.7), not quietly worked around with synthetic data
presented as real.

### 4.5 Negative-result discipline

This project treats a null or reversed result as reportable evidence,
not as a defect to be hidden or re-run until it disappears. §5 and §6
report every such instance found, including the two independent
methodological failures (§5.4) that this project's own process caught
*before* a false conclusion could be published, and the one case
(§6.6, the Treasury yield-curve ablation) where a theoretically
well-motivated real feature was added, tested, and found to hurt rather
than help — reported as a finding in itself rather than quietly dropped.

## 5. Results: the five frozen hypotheses

Five falsifiable hypotheses (H1–H5) were frozen on 2026-11-11 against
commit `c7d50ea`, in
[`docs/FINAL_PROJECT_HYPOTHESES.md`](./FINAL_PROJECT_HYPOTHESES.md).
**Honest methodological note, repeated from that document**: this is a
*retrospective* freeze. H1–H5 were tested across PR-139 through PR-168
before the freeze document existed; freezing them afterward prevents
further drift as this paper is written, but it does not carry the same
evidentiary weight as hypotheses registered before any data was seen.
After the freeze date, the hypothesis wording and verdict do not change
in response to new results — only the evidence cited for them can, and
every such revision is disclosed explicitly (§5.3 is one such case).

### 5.1 H1 — Hybrid quantum-classical advantage on recession classification and factor regression

**Hypothesis.** A hybrid quantum-classical architecture will show a
statistically significant accuracy or calibration advantage over a
parameter-matched classical baseline on real recession-classification
and factor-regression tasks.

**Verdict: rejected.** Tested three independent ways:

- **RECESSIONNET** on real-NBER-chronology-labeled factor data: once
  training controlled for model capacity (validation-selected early
  stopping instead of a fixed epoch budget — itself the finding reported
  in §5.4), the hybrid-quantum classifier's advantage over logistic
  regression became statistically inconclusive in 4 of 5 seeds.
- **RECESSIONNET** on a second, independently-sourced real dataset (a
  Kaggle mirror of real FRED GDP/claims/Fed-funds/M2/NASDAQ series): the
  **base rate** — not any trained model — was the strongest classical
  candidate, with the quantum classifier showing no significant
  difference against it.
- **Q-MACRO**, forecasting real Kenneth French market-factor returns:
  AR(3), a parameter-matched classical MLP, and the hybrid-quantum
  regressor landed within a statistically indistinguishable band
  (MASE ≈ 0.62), all clearly ahead of naive persistence (MASE ≈ 0.89).

Every reported bootstrap confidence interval on the quantum-vs-classical
gap includes zero, in all three tests. This is reported as the actual
result of a specific, falsifiable comparison tested three independent
ways — not reframed as a tuning problem.

### 5.2 H2 — Neural SDE: in-distribution accuracy and out-of-distribution robustness

**Hypothesis.** A neural stochastic differential equation will both
match classical baselines (GBM, GARCH) in-distribution and degrade less
under a genuine out-of-distribution shock.

**Verdict: partially supported.** In-distribution, the neural SDE does
*not* beat simple baselines (validation log-score 4.82 vs. baselines'
≈4.0–4.1). Under the real 2020 COVID shock — the genuine sample-wide
extremum in both real GDP year-over-year growth and real unemployment-
claims growth, independently verified against the raw source data, not
assumed — the neural SDE's log-score degrades by **+5.58**, while a
constant-parameter GBM baseline degrades by **+29.97**. The neural SDE
is not a better unconditional model, but its regime-conditioning
provides real, measured robustness under a genuine distributional shift
that a non-conditioned classical model lacks: a concrete, falsifiable
distinction between "better on average" and "more robust under shock,"
demonstrated on one real historical event rather than a synthetic
stress scenario.

### 5.3 H3 — Neural PDE solvers: when does the computational cost pay off?

**Hypothesis.** A neural PDE solver (PINN / deep BSDE) earns its
additional computational cost over a classical finite-difference grid
once problem dimensionality is high enough.

**Verdict: supported, with the crossover measured rather than assumed.**
In one dimension, the classical Crank-Nicolson grid is simultaneously
faster (0.02s vs. 22s/54s) **and** more accurate than either neural
method — the grid wins outright at low dimension. But grid cost scales
as *M<sup>d</sup>* (200, 40,000, and 8,000,000 nodes at d = 1, 2, 3 at
this package's own resolution) while the deep-BSDE solver's wall time
stays approximately flat across the same dimensions — the actual
mechanism by which the comparison could tip in the neural solver's favor
at higher dimension, independent of any one accuracy number.

**Evidence revised 2026-11-13, per this project's own disclosure
rule — what changed and why:** the 1D accuracy comparison originally
cited an undertrained deep-BSDE baseline (400 epochs; a 4-seed sweep
found this a consistent, real undertraining effect, not noise). Fixing
it (1,600 epochs, plus a higher PINN learning rate at the same epoch
budget) cut deep-BSDE's price error by roughly 300×, narrowing the
grid's accuracy advantage over it from roughly 580× to roughly 2×. The
verdict is unchanged — the grid still wins outright in 1D on both speed
and accuracy, and the *M<sup>d</sup>*-vs-flat scaling mechanism is
untouched — only the specific accuracy-gap magnitude cited as evidence
changed, once an undertrained comparison was caught and corrected. This
project is one of the few small research codebases that actually
measures this crossover, rather than citing the textbook "curse of
dimensionality" justification without checking it — and this revision
is itself an instance of the same discipline applied to its own earlier
work.

### 5.4 H4 — Can naive methodology alone produce a false comparative conclusion?

**Hypothesis.** Naive fixed-epoch training and unaudited reward design
can each, independently, produce a false conclusion about model
comparison that a more careful evaluation reverses.

**Verdict: supported, twice, independently.** Two unrelated subsystems,
caught by this project's own process rather than by chance:

- **RECESSIONNET** (supervised learning): a diagnostic training-curve
  trace found the higher-capacity hybrid-quantum and classical-MLP
  candidates overfitting past epoch ~20–60 under an earlier fixed
  150/300-epoch budget, while logistic regression (far fewer parameters)
  never overfit in that range. The entire H1 comparison had been unfair
  until validation-selected early stopping was introduced — which
  **reversed** the previously reported conclusion that the quantum model
  was robustly better.
- **Multi-agent reinforcement learning** (`marl`): a direct numeric
  sweep, run *before* trusting any training result, caught a degenerate
  reward design: log-utility of consumption alone made "spend
  everything, every step" trivially optimal regardless of training
  quality. Adding a bequest-value term created a genuine interior
  optimum, after which PPO discovered a materially better, non-trivial
  time-varying policy.

Methodology — not just model architecture — measurably determined a
reported conclusion in both a supervised and a reinforcement-learning
setting, demonstrated here as two independent, real, caught-before-
publication instances rather than a single anecdote.

### 5.5 H5 — Deep hedging: does a REINFORCE policy beat a well-specified classical baseline?

**Hypothesis.** A REINFORCE-trained hedging policy will outperform a
well-specified classical delta/no-trade-band baseline within a modest
training budget.

**Verdict: rejected.** The policy loses to the static baseline. Two real
confounds were found and ruled out before this conclusion was accepted,
rather than being left as alternative explanations:

- An AI-assisted adversarial audit found and fixed a real implementation
  bug — `rsample()` was silently zeroing the policy's mean-head gradient
  — that predated this finding; re-verified post-fix, the same
  qualitative conclusion held, now for the genuine reason (sample-
  inefficient terminal-only REINFORCE) rather than a broken gradient.
- A second confound — training minimized mean terminal loss while the
  static baseline's own CVaR sat unused except as a precondition gate, a
  metric/objective mismatch — was found and fixed with a CVaR-aligned
  reward, combined with a 10–20× longer (still fast: 82 parameters)
  training budget. This narrowed the gap from roughly 2.5× the static
  baseline's CVaR to roughly 1.04×–1.41× across 8 seeds — still 0 of 8
  wins for the learned policy.

Consistent with H1 and H3: across the five frozen hypotheses, "the more
complex learned approach wins" was the exception (H3's deep-BSDE, and
only along one specific, measured axis — compute scaling, not 1D
accuracy), not the rule.

## 6. Results beyond the frozen set, limitations, and null/negative experiments

This section is this paper's direct response to FP-22's exact wording —
"includes limitations and null/negative experiments" — collecting every
disclosed negative result, scope cut, and known limitation in one place,
rather than leaving them scattered only in per-subsystem documentation.

### 6.1 A sixth result, not part of the frozen set: inflation nowcasting (INFLATIONCAST)

INFLATIONCAST was built and tested (PR-173) before the 2026-11-11 freeze
commit but was not included among H1–H5; it is reported here as a sixth,
unfrozen result, disclosed as such rather than folded into the frozen
set after the fact.

Naive persistence, linear regression, a parameter-matched classical MLP,
a hybrid-quantum regressor, and `InflationGRU` (a recurrent encoder
trained by Gaussian negative log-likelihood to produce a calibrated
`(mean, log-variance)` forecast — the only candidate across this
project's three forecasting tasks that attempts calibration at all) were
benchmarked on real BLS CPI-U year-over-year inflation and real Kaggle
macro predictors, behind the point-in-time mixed-frequency masking layer
described in §4.2, so no candidate can see a month's own not-yet-
published CPI figure.

**Finding: not supported, on either axis, reported honestly.**
*Accuracy:* naive persistence beat every learned candidate (MAE 0.31 vs.
1.77–3.59 percentage points) — CPI year-over-year is a highly persistent
series month to month, a well-known real property of this series, not
an artifact of this pipeline, so the "harder" models had no real signal
advantage to exploit on this task. *Calibration:* `InflationGRU`'s 90%
nominal predictive interval covered only ≈11% of real outcomes (an exact
binomial coverage test, p ≈ 1.7×10⁻⁴³) — confidently wrong, not merely
imprecise.

### 6.2 Null result: a real, well-motivated feature made a model worse

After the freeze, the real US Treasury 10-year/3-month yield-curve
spread — one of the most-studied real recession predictors in the
economics literature — was added to RECESSIONNET as a feature over the
real 1990–2023 overlap between the two existing data sources, and
directly ablated (same seeds, same train/validation/test split, with
and without the feature). **It did not help, and mostly hurt**: ROC-AUC
was consistently decent (0.68–0.86) without the feature, but erratic and
usually worse (0.36–0.82) with it, across the same 5 seeds, with 4 of 5
seeds degraded or unchanged. The plausible mechanism is disclosed rather
than left unexplained: an already data-starved model (a few hundred
monthly rows) gained one more input dimension to fit, which cost more
than the feature's genuine theoretical relevance was worth at this
sample size. This is reported as a negative result for a textbook,
well-motivated feature, not omitted because it failed to help.

### 6.3 A "train harder" pass found two defaults were already correct

A direct attempt to improve results on every deep-learning subsystem by
training longer (patience/epoch-count sweeps) found, honestly, that two
of the apparent "wins" were artifacts of undertraining in the wrong
direction:

- The neural SDE's one genuinely positive result (§5.2's COVID-shock
  robustness) **collapses under more training**: raising patience from
  20 to 60 improves the in-distribution score (the model's own selection
  metric) but makes COVID-window log-score degradation explode from
  +5.58 to +48.75 — worse than the GBM baseline, destroying the exact
  robustness property §5.2 reports. `patience=20` is confirmed a
  deliberate, correct choice, not an oversight that more training would
  have fixed.
- RECESSIONNET's Kaggle-dataset candidate, trained with `patience=60`
  instead of 20, reached genuine, well-calibrated discrimination
  (ROC-AUC 0.86–0.92) beating every classical candidate in 4 of 5
  seeds — but the 5th seed revealed a real Brier-score-vs-ROC-AUC
  divergence (ROC-AUC 0.479, worse than random, while still showing an
  apparently-improved Brier score by bootstrap CI) that a second,
  independent diagnostic caught before it could be mistaken for a clean
  win. Neither result was promoted to this project's production default
  on the strength of one favorable aggregate metric alone.

### 6.4 Scope cuts in the original 374-item blueprint, disclosed rather than hidden

Several final-project-addendum items remain explicitly **not verified**,
named here rather than left to be discovered by omission:

- **FP-08** (shared-vs-independent encoder ablation): no shared
  multi-task encoder exists in this repository; each forecasting task
  (RECESSIONNET, Q-MACRO, INFLATIONCAST) uses its own independent model,
  so the ablation this item asks for has no object to test.
- **FP-10** (CONTAGION-GNN): a graph neural network for interbank
  contagion does not exist; `titan.contagion`'s existing synthetic-bank-
  network primitive is a different, non-GNN approach to a related
  problem.
- **FP-13** (VOLTERRA-GEN): a conditional market-scenario generator does
  not exist.
- **FP-15** (POLICYLAB-RL): a dedicated policy-intervention RL
  laboratory does not exist, distinct from the multi-agent RL that does
  (§3; §5.4's second instance).
- **FP-16** (a single TITAN report carrying horizon, units, and cost
  together): an audit found this claim inaccurate as stated — every
  TITAN risk function returns a bare float or a report object missing at
  least one of horizon, units, or cost, individually. The gap is
  specific and disclosed, not glossed as "mostly done."

Each of FP-08/10/13/15 represents a full new subsystem the original
blueprint called for and this project's scope did not reach; they are
listed here as what this paper's title's claims do *not* cover, not
quietly folded into "future work" without specifics.

### 6.5 What five or six experiments do not establish

Five or six experiments on different tasks, datasets, and architectures
do not establish a universal law about quantum computing, deep learning,
or model complexity in general. "Complexity does not help" is reported
here as the pattern actually observed across these specific models,
datasets, and evaluation protocols — not as a claim that generalizes to
every neural or quantum architecture, every dataset, or every economic
task. Sample sizes throughout are small (a few hundred to a couple
thousand monthly rows for the macro work), named explicitly wherever a
finding above is reported.

### 6.6 Infrastructure limitations, not unwritten features

- **FRED/ALFRED ingestion** (the original blueprint's DAT-02/DAT-03)
  remains unbuilt because `fred.stlouisfed.org`/`alfred.stlouisfed.org`
  were confirmed unreachable from this project's environment by direct,
  repeated retry — general internet access is otherwise fine (e.g. the
  U.S. Treasury's own data API, used in §6.2, is reachable). This is an
  infrastructure gap, not a feature nobody got to.
- **No independent human review** of any claim in this repository has
  happened. "Evidenced" here means covered by a passing automated test
  — not peer-reviewed, not regulator-approved, not production-ready.
- **No live-trading execution path exists, and none is planned** — this
  is this project's core safety boundary, stated once already in §2 and
  repeated here because it bears directly on how every result above
  should be read: as research findings about model comparison, not as
  trading signals.

### 6.7 A recurring, independently-useful methodological lesson

Four separate real bugs in this repository — a dashboard ASGI-lifespan
crash, the REINFORCE gradient silently zeroed by `rsample()` vs.
`sample()` (§5.5), a recession-label boundary-month mismatch, and this
project's own advertised smoke test having gone stale — were each found
the same way: by independently re-deriving a result or actually
executing a path, rather than trusting that passing tests meant the
claim was true. Every one of them was invisible to this repository's own
existing test suite specifically because the tests shared the same blind
spot as the code they tested. The general lesson, offered here as a
transferable finding rather than a repository-specific anecdote: a test
suite can be large, green, and still share its production code's own
unstated assumptions — the fix is periodic independent re-derivation,
not more of the same kind of test.

## 7. Threats to validity

- **Retrospective hypothesis freezing (§5).** H1–H5 were frozen after
  the experiments that test them were already run. This prevents further
  drift but does not carry the evidentiary weight of a true prospective
  pre-registration; it is named here rather than implied away.
- **Single-maintainer, single-reviewer project.** No claim in this paper
  has been independently reviewed by anyone besides this project's own
  maintainer. The fastest way to check that is named explicitly in
  [`docs/RESEARCH_CONTRIBUTIONS.md`](./RESEARCH_CONTRIBUTIONS.md): open
  one cited test and confirm it tests what this paper claims.
- **Document-numbering inconsistency, found while writing this paper and
  fixed the same day (PR-180).** An earlier document in this repository,
  [`docs/PROBLEM_STATEMENT.md`](./PROBLEM_STATEMENT.md), had labeled a
  different, earlier set of three hypotheses H1–H3 (RECESSIONNET,
  Q-MACRO, and a Treasury-holiday-detection check), predating and
  distinct from the later, frozen H1–H5 set this paper follows as
  authoritative per
  [`docs/FINAL_PROJECT_HYPOTHESES.md`](./FINAL_PROJECT_HYPOTHESES.md)'s
  explicit freeze. The two label sets collided for several PRs with no
  functional consequence — the underlying tests and numbers in both
  documents were always independently correct, only the shared "H1–H3"
  label across two documents was a leftover naming collision — but it
  risked a reader conflating a frozen, citable hypothesis with that
  document's own earlier, narrower framing. Fixed by renaming that
  document's hypotheses to P1–P3, with an explicit note pointing to this
  paper for how the collision was found.
- **Small sample sizes**, stated per-finding in §6.5, limit how far any
  single verdict above should be generalized.

## 8. Conclusion

Across six quantitative-economics tasks tested under a shared,
enforced, matched-capacity evaluation protocol, added complexity — deep
learning, hybrid quantum-classical architectures, or both — did not
reliably improve on simpler classical baselines. The one case where
added complexity's cost was shown to pay off (§5.3) did so along a
specific, measured axis (compute scaling at higher problem dimension),
not a blanket accuracy win, and only after an undertrained comparison in
this project's own earlier work was caught and corrected. Two
independent instances (§5.4) showed that the evaluation protocol itself
— not just model architecture — can silently determine a reported
conclusion, and both were caught by this project's own process before
publication rather than by external review. A real, theoretically
well-motivated feature addition (§6.2) made a model worse, and a
deliberate attempt to improve results by training longer (§6.3) instead
confirmed that two existing defaults were already correct. None of this
is reported as a failure of the underlying research question — it is
the actual, falsifiable answer this project set out to get, obtained
under a discipline designed to make that answer trustworthy rather than
flattering. The project's lasting contribution is that discipline itself:
a 374-item requirements register machine-cross-referenced against named,
passing tests, and a standing practice of publishing every null and
negative result with the same visibility as a positive one. A reader
does not have to trust this paper's summary of that evidence — every
claim above cites a specific file and test in this repository, designed
to be falsified in minutes by anyone willing to run it.

## Reproducibility and further reading

- [`docs/FINAL_PROJECT_HYPOTHESES.md`](./FINAL_PROJECT_HYPOTHESES.md) —
  the frozen title, hypotheses, and one-line verdicts this paper expands.
- [`docs/RESEARCH_CONTRIBUTIONS.md`](./RESEARCH_CONTRIBUTIONS.md) — the
  full research-questions account, with every cited test named.
- [`docs/RESULTS_AND_LIMITATIONS.md`](./RESULTS_AND_LIMITATIONS.md) — 12
  numbered findings, each with its own re-runnable test and the PR that
  produced it.
- [`docs/PR_LEDGER.md`](./PR_LEDGER.md) — the complete, PR-by-PR build
  history behind every number in this paper.
- [`CHECKLIST_STATUS.md`](../CHECKLIST_STATUS.md) — the living,
  machine-cross-referenced record of which of the 374 + 24 blueprint
  items are evidenced, by which test, as of any given commit.
- [`docs/PORTFOLIO_DEMO.md`](./PORTFOLIO_DEMO.md) — a 10-minute guide to
  independently installing this repository and re-running its real test
  suite and smoke test from a clean checkout.
- [`README.md`](../README.md) — the project's own entry point, including
  how to start the real web application (`./run_dev.sh`) this paper's
  §3 refers to as the demo requirement.
