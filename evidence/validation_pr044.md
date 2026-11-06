# PR-044 local validation — 2026-11-03

Scope: empirical macro/market-mixture CVaR, paired nested uncertainty,
terminal-loss provenance and explicit numerical failure handling. This
continues the existing worktree through PR-043; unrelated local work is
preserved. All changes remain local, uncommitted and not independently
reviewed. This is evidence of engineering progress, not production approval.

The user-supplied blueprint and repository copy are byte-identical:

```text
6745f7dd2b027378fbafbd9a870b84d86489932d2068fa10abf0d604ef3bac75
```

The PDF was read as design context. Its embedded deployment/review controls
are requirements to assess, not instructions granting approval or a claim
that implementing code establishes industrial readiness.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 78 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 1,116 passed in 32.34 seconds; 97% line coverage |
| `git diff --check` | Passed |
| Default mixture study and actual replay | Valid; exact result match; no runtime changes |
| Original rate-study replay | Exact historical result hash; source digest change reported |
| Independent exported-JSON readback | All 55,296 losses, 36 model/scenario/arm CVaR groups, cell/cube hashes, contrast points and six model-card metrics reconciled |

Runtime: Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1 and PyTorch 2.15.0+cpu.
Reference, replay and final local package source have the same digest:

```text
9f654830bdd298b9fcb36ac0e88dec3481e586033b39739aea1ec03c0d1664e4
```

## Reproduction and identity

```bash
.venv/bin/python -m prometheus.orchestration.mixture_study \
  --output evidence/mixture_study_reference.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/mixture_study_reference.json --output evidence/mixture_study_replay.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/rate_study_reference.json --output evidence/rate_study_replay_pr044.json
```

Mixture-study result hash:

```text
ccad649ce9a2d264f1c920a6fd0299ccfce78777cb62f53ca8e73c8725b38265
```

Embedded conditional-study and historical rate-study result hash:

```text
7b8b9f011062af41547716bc5fcb9944c248a6641e3770a3edfb3413c8f77960
```

Original artifacts are preserved. Full replay retrains both matched arms,
reconstructs all training/evaluation banks, regenerates terminal losses and
recomputes both risk estimands and all bootstrap diagnostics. No remote CI,
dependency lock, signed source identity or external immutable storage is
claimed.

## Estimand and design

The default reuses PR-021's six fitted models: three independent training
replicates with matched rate-aware/blind arms. Its four evaluation scenarios
each have three macro banks and 512 conditional market paths per bank.
Every cell evaluates delta, rate-blind and rate-aware holdings with shared
prices/costs/financing. Training and market generation are unchanged.

For each fitted policy, the new estimand first pools its 3x512 macro/market
losses, with equal bank and conditional-path weights, then computes CVaR.
Comparator-minus-aware CVaR differences are averaged across the three
training replicates. The primary comparator is the matched rate-blind arm;
delta is secondary. Different fitted models are never pooled into an
ensemble before CVaR. The original average conditional-CVaR difference is
retained as an auxiliary statistic.

A hand-worked fixture shows the distinction is material: two equal-weight
macro states with constant losses 0 and 10 give mixture CVaR 10 at alpha .5,
while their average conditional CVaR is 5. Against constant loss 8, the
mixture difference is +2 and the average conditional difference is -3.
A separate fixture prevents accidentally pooling different fitted policies.

The nested bootstrap samples training rows, macro banks and market indices
within each sampled bank occurrence. Every arm and training row shares the
same selected bank/path pairs. Repeated draws of a macro bank receive fresh
inner market resamples. Training-only, macro-only and market-only intervals
condition on other axes; they are not additive variance components.

The new comparison family has eight mixture scenario/contrast pairs.
Nominal family confidence .95 allocates .99375 confidence per interval;
1,000 nested resamples are used. Original conditional-risk intervals have
a separate family and do not choose the mixture endpoint or verdict.
The economic margin is zero. Overall primary direction requires all four
scenario intervals to clear that margin in the same direction.

## Default result

| Scenario | Blind-minus-aware mixture mean | Nominal 99.375% nested interval | Primary verdict |
|----------|-------------------------------|--------------------------------|-----------------|
| baseline | -.334208 | [-.848254, .204662] | inconclusive |
| delayed_publication | -.155616 | [-.750566, .599017] | inconclusive |
| no_payroll_channel | -.333199 | [-.848280, .205253] | inconclusive |
| severe_supply_shock | -.430780 | [-.926223, -.000074007] | comparator_better |

The overall primary result is **inconclusive**. The severe-shock upper
bound is extremely close to zero. With 1,000 resamples and this allocated
confidence, each nominal tail has only about 3.125 expected resamples;
the reported endpoint is sensitive to bootstrap quantile precision. It is
not treated as a robust feature-superiority result or a promotion criterion.
Three independent training/macro levels also limit coverage reliability.

| Scenario | Delta-minus-aware mixture mean | Nominal 99.375% nested interval |
|----------|--------------------------------|--------------------------------|
| baseline | 2.018711 | [1.181826, 2.673302] |
| delayed_publication | 1.582005 | [.505835, 2.334929] |
| no_payroll_channel | 2.016370 | [1.180695, 2.670742] |
| severe_supply_shock | 2.345636 | [1.534979, 2.940166] |

The secondary intervals favor the aware MLP over delta in this synthetic
experiment, while the matched primary control does not show a consistent
incremental rate-feature benefit. The mixture points differ from the
original conditional-risk means, which remain in the artifact for direct
comparison. No empirical or optimal-policy claim follows.

## Reliability and independent evidence

The study retains terminal-loss cubes with explicit `(training, macro bank,
conditional market path)` axes and canonical float64 little-endian hashes.
Every constituent loss vector is checked against its original cell hash.
The original conditional payload/hash, full recipes/traces and per-model
mixture metrics are retained. The loss observer receives read-only copies;
tests deliberately mutate those copies and verify the original report's
result remains identical.

Independent readback used a separate sorted, fractional-tail calculation
with `math.fsum` to reconcile all per-model mixture CVaRs, conditional cell
CVaRs and contrast means within 1e-10. All cube/cell fingerprints and model
card mixture metrics match. Reference/replay runtimes and package-source
digests match. Current evidence-table ID columns contain 90 distinct
blueprint IDs; repeated/partial entries remain distinct from acceptance.

Tests reconstruct nested draws through independent row/bank/path loops,
check tied/fractional tails and preserve planted constant paired shifts.
Increasing conditional path counts cannot erase uncertainty from training
or macro levels. Changing nested resample counts cannot change training,
market samples or original conditional results. Reversing declared axes
preserves the result hash.

Malformed shapes, non-finite inputs, invalid resampling controls and
overflowing risk calculations fail explicitly. Failed source experiments
yield no mixture inference/model cards and replay as invalid. The CLI
preserves an existing output when given an invalid recipe. Generic replay
tests cover mixture payload corruption, fabricated results after rehashing,
missing fields, runtime changes and source-preserving CLI behavior. Existing
monetary-operations replay tests also pass in the complete project suite.

## Remaining requirements

This is an equal-weight finite empirical mixture, not a calibrated estimate
of unconditional population macro/market tail risk. Macro probabilities and
behavioral coefficients are synthetic; nested-percentile finite-cluster
coverage is uncalibrated. This is not a serial block bootstrap and does not
claim EXP-09 acceptance. The source experiment's separate economic/hedge
books, fixed-volatility delta and limited learned features remain unchanged.

Operational security, signed/pinned deployment artifacts, independent model
review, model lifecycle controls and the blueprint's promotion gates remain
required before broader deployment. **R0 remains NO-GO**. No approval state
was changed and no industrial/production certification is claimed.
