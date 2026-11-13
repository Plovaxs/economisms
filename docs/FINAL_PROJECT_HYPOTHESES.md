# Final project: frozen title and hypotheses

**FP-01**: "A final project title and hypotheses are frozen." This
document is that freeze, dated **2026-11-11**, against commit
`c7d50ea` (the most recent commit as of this writing). After this
date, the title and the five hypotheses below do not change in
response to results; only the evidence for or against them does. Any
later revision to this document must say so explicitly and name what
changed and why, the same discipline `CHECKLIST_STATUS.md` already
applies to every other claim in this repository.

**Honest methodological note**: this is a *retrospective* freeze, not
a prospective pre-registration. RQ1-RQ5 below were tested across
PR-139 through PR-168 before this document existed; freezing them now
prevents further drift as the final paper is written, but it does not
carry the same evidentiary weight as hypotheses registered before any
data was seen. This gap is named here rather than left implicit.

## Title

**Beyond Model Complexity: An Empirical Evaluation of Classical, Deep
Learning, and Hybrid Quantum Models for Quantitative Economic and
Financial Tasks**

## The five frozen hypotheses

Each hypothesis is stated as a falsifiable prediction, together with
its current status and the exact evidence behind that status. Source:
[docs/RESEARCH_CONTRIBUTIONS.md](./RESEARCH_CONTRIBUTIONS.md) and
[docs/RESULTS_AND_LIMITATIONS.md](./RESULTS_AND_LIMITATIONS.md), which
remain the full, detailed account; this document only freezes the
questions and states each verdict in one line.

**H1 (RECESSIONNET + Q-MACRO).** A hybrid quantum-classical
architecture will show a statistically significant accuracy or
calibration advantage over a parameter-matched classical baseline on
real recession-classification and factor-regression tasks.
**Verdict: rejected.** Tested three independent ways (two real
datasets for classification, one real dataset for regression); every
bootstrap confidence interval includes zero. See
`tests/unit/test_recessionnet_run.py::
test_multi_seed_summary_matches_the_real_observed_result_across_five_seeds`
for the committed, re-runnable multi-seed evidence (5/5 seeds
inconclusive as of this freeze).

**H2 (Neural SDE).** A neural stochastic differential equation will
both match classical baselines (GBM, GARCH) in-distribution and degrade
less under a genuine out-of-distribution shock. **Verdict: partially
supported.** The in-distribution half is rejected (the neural SDE does
not beat simple baselines there); the OOD-robustness half is supported
(real 2020 COVID-shock degradation: +5.58 for the neural SDE vs. +29.97
for a constant-volatility GBM baseline).

**H3 (PDE solvers).** A neural PDE solver (PINN / deep BSDE) earns its
additional computational cost over a classical finite-difference grid
once problem dimensionality is high enough. **Verdict: supported, with
the crossover measured rather than assumed.** The classical grid wins
outright in 1D (faster AND more accurate); grid cost scales as `M^d`
while the neural solvers' wall time does not, which is the actual
mechanism by which complexity could pay off in higher dimensions.
**Evidence revised 2026-11-13 (PR-177), per this document's own rule
above — what changed and why:** the 1D accuracy comparison originally
cited an undertrained deep-BSDE baseline (400 epochs; a 4-seed sweep
found this a consistent, real undertraining effect, not noise).
Fixing it (1600 epochs, plus a higher PINN learning rate at the same
epoch budget) cut deep-BSDE's price error by ~300x, narrowing the
grid's accuracy advantage over it from ~580x to ~2x. The verdict itself
is unchanged — the grid still wins outright in 1D on both speed and
accuracy, and the `M^d`-vs-flat scaling mechanism is untouched — only
the specific accuracy-gap magnitude cited as evidence changed. See
`docs/RESULTS_AND_LIMITATIONS.md`'s Finding 6 for the full numbers.

**H4 (methodology).** Naive fixed-epoch training and unaudited reward
design can each, independently, produce a false conclusion about model
comparison that a more careful evaluation reverses. **Verdict:
supported, twice, independently.** A fixed-epoch budget let
higher-capacity RECESSIONNET candidates overfit undetected (reversed by
validation-selected early stopping); an unaudited MAR reward let "spend
everything" look trivially optimal (caught by a direct numeric sweep
before training was trusted).

**H5 (deep hedging).** A REINFORCE-trained hedging policy will
outperform a well-specified classical delta/no-trade-band baseline
within a modest training budget. **Verdict: rejected.** The policy
loses to the static baseline; a real, independently found and fixed
implementation bug (`rsample()` silently zeroing the policy gradient)
was ruled out as the cause before this conclusion was accepted — see
`docs/RESULTS_AND_LIMITATIONS.md` Finding 8.

## What this title and hypothesis set does not claim

Five or six experiments on different tasks do not establish a
universal law. "Complexity does not help" is reported as the pattern
actually observed across these specific models, datasets, and
evaluation protocols — not as a claim that generalizes to every neural
or quantum architecture, every dataset, or every economic task. See
`docs/RESULTS_AND_LIMITATIONS.md`'s own limitation notes for each
finding's specific sample-size and scope caveats.
