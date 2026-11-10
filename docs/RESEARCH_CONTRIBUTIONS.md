# Research contributions

A single, consolidated statement of what this project actually set out
to test, what it found, and why that's a real contribution rather than
a demo — written for a reader deciding whether to spend ten minutes on
this repository (a professor, a researcher, a technical recruiter).
Every claim below cites the exact file/PR where it is backed by a real,
rerunnable test; nothing here is asserted without that.

## The central methodological contribution

Most small research codebases accumulate an unverifiable gap between
what their README claims and what their code actually does. This
project's real contribution is a mechanism that closes that gap
structurally rather than by discipline alone:

- A **374-item master checklist** (`docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf`),
  machine-cross-referenced against the repository's own test suite via
  `prometheus.evidence.requirements`
  (`docs/implementation/blueprint_register.json`, regenerated and
  diffed on every change — see `CONTRIBUTING.md`).
- A rule that an item counts as "evidenced" **only** when a specific,
  named, currently-passing test exercises the specific claim — not a
  docstring, not a design note. 326/374 items meet this bar today (see
  `README.md`'s live badge).
- A standing practice of publishing **negative and null results** with
  the same visibility as positive ones (`docs/RESULTS_AND_LIMITATIONS.md`),
  and of disclosing every substitution, approximation, or honest
  reinterpretation in the code and the record at the moment it happens
  (e.g. PR-146's FRED-for-Treasury.gov substitution; NSD-04's "price
  positivity" reinterpreted as boundedness for genuinely-negative
  growth-rate state variables).

This is the thing most worth evaluating independently: pick any
"evidenced" row in `CHECKLIST_STATUS.md`, open the cited test, and
confirm it actually tests what the row claims. That check is designed
to survive scrutiny.

## Research questions actually tested, and what was found

### RQ1 — Does a hybrid quantum-classical architecture improve financial time-series prediction over classical baselines of matched capacity?

Tested three times, on three different real datasets, across two
different task families (recession classification, factor regression):

- **RECESSIONNET** (PR-139/142/144/145): once training controlled for
  model capacity (validation-selected early stopping instead of a
  fixed epoch budget — itself a finding, see RQ4), the hybrid-quantum
  classifier's advantage over logistic regression became statistically
  inconclusive in 4 of 5 seeds; on a second, independently-sourced real
  dataset, the **base rate** — not any trained model — was the
  strongest classical candidate, with quantum showing no significant
  difference.
- **Q-MACRO** (PR-143): AR(3), a classical MLP, and the hybrid-quantum
  regressor landed within a statistically indistinguishable band
  (MASE ≈ 0.62), all clearly ahead of naive persistence (MASE ≈ 0.89).

**Finding: not supported.** A specific, falsifiable hypothesis was
tested three independent ways and did not hold up. This is reported as
the actual result, not reframed as a tuning problem.

### RQ2 — Can a neural stochastic differential equation outperform classical SDE models (GBM) and econometric baselines (GARCH) on real macro data, and does it degrade more gracefully under a genuine out-of-distribution shock?

**`neural_sde`** (PR-150): in-distribution, the neural SDE does *not*
beat simple baselines (validation log-score 4.82 vs. baselines'
≈4.0–4.1). Under the real 2020 COVID shock (the genuine sample-wide
extremum in both GDP YoY and Claims YoY, independently verified
against the raw CSV, not assumed), the neural SDE's log-score degrades
by +5.58 while a constant-parameter GBM baseline degrades by +29.97.

**Finding: partially supported, in a specific and interesting way.**
The neural SDE is not a better unconditional model, but its
regime-conditioning provides real, measured robustness under a genuine
distributional shift that a non-conditioned classical model lacks —
a concrete, falsifiable distinction between "better on average" and
"more robust under shock," demonstrated on one real historical event.

### RQ3 — For option pricing, when (if ever) does a neural PDE solver (PINN / deep BSDE) earn its computational cost over a classical finite-difference grid?

**`pde_solvers`** (PR-153): in 1D, the classical Crank-Nicolson grid is
simultaneously faster (0.013s vs. 9.3s/11.4s) **and** more accurate
than either neural method. But grid cost scales as `M^d` — 200,
40,000, and 8,000,000 nodes at d = 1, 2, 3 at this package's own
resolution — while the deep BSDE solver's walltime stays ≈flat
(≈10–13s) across the same dimensions.

**Finding: supported, with the crossover demonstrated, not assumed.**
The textbook "curse of dimensionality" justification for neural PDE
solvers is a real, commonly-asserted claim; this project is one of the
few small repositories that actually measures the crossover rather
than citing the claim.

### RQ4 — Does naive fixed-epoch training produce a fair comparison between models of different capacity, and does reward/objective design silently determine an RL agent's apparent conclusion before any learning happens?

Two independent instances of the same underlying methodological
failure mode, caught by this project's own process, not by luck:

- **PR-142**: a diagnostic trace found RECESSIONNET's higher-capacity
  candidates overfitting past epoch ~20–60 under a fixed-epoch budget
  while logistic regression did not — the entire RQ1 comparison had
  been unfair until early-stopping was introduced, which **reversed**
  the previously reported conclusion.
- **`marl`** (PR-154): a direct numeric sweep caught a degenerate
  reward design (log-utility of consumption alone made "spend
  everything, every step" trivially optimal) *before* trusting any
  training result. Adding a bequest-value term created a genuine
  interior optimum, after which PPO discovered a materially better,
  non-trivial time-varying policy.

**Finding: yes to both halves.** Methodology, not just model
architecture, measurably determines a reported conclusion in both a
supervised and a reinforcement-learning setting — demonstrated as two
independent, real, caught-before-publication instances rather than a
single anecdote.

### RQ5 — Does a quickly-trained RL agent beat a well-specified classical baseline on a hedging task, under a controlled, honest comparison?

**`hedging.rl_agent`** (PR-158, corrected PR-162): a REINFORCE agent,
risk-bounded by construction and refusing to train without a passing
static baseline already in hand, is reported **losing** to the static
delta/no-trade-band baseline at its training budget — not tuned until
it won. An AI-assisted adversarial audit (PR-162) found and fixed a
real implementation bug (`rsample()` silently zeroing the policy's
mean-head gradient) that predated this finding; re-verified post-fix,
the same qualitative conclusion holds, now for the genuine reason
(sample-inefficient terminal-only REINFORCE) rather than a broken
gradient — see `CHECKLIST_STATUS.md`'s PR-162 entry for the full
before/after numbers.

**Finding: not supported, reported honestly.** Consistent with RQ1/RQ3:
across five independent subsystems this session, "the more complex
learned approach wins" was the exception (RQ3's deep BSDE, and only
along one specific, measured axis — compute scaling, not accuracy),
not the rule. A project that only reported the cases where the new
method won would be reporting marketing, not research; this one
doesn't.

## Why this is a genuine, if narrow, scientific contribution

Not because any single result is individually surprising to a
specialist — simple baselines beating undertrained learned models is
well-known. The contribution is methodological and reproducibility-
focused: every one of the five findings above is independently
rerunnable from this repository today, with the exact seed, exact
data, and exact test that produced it named in `CHECKLIST_STATUS.md`
and `docs/PR_LEDGER.md`. A reader does not have to trust the summary
above — they can falsify it in minutes by running the cited test.

## What this is not

Not a peer-reviewed publication, not a claim of statistical rigor
beyond what's stated (sample sizes are small — a few hundred to a
couple thousand monthly rows for the macro work — and this is named
explicitly wherever a finding is reported, see
`docs/RESULTS_AND_LIMITATIONS.md`), and not independently reviewed by
anyone besides the project maintainer (`docs/governance/ISSUE_AND_VALIDATION_POLICY.md`).
If you are the second reviewer this project doesn't yet have, the
fastest way to start is: open `docs/RESULTS_AND_LIMITATIONS.md`, pick
one finding, and try to reproduce it from the cited test alone.
