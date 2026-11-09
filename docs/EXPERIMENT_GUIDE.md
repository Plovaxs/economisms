# Experiment guide: seed, split, and comparison protocol

This describes how a model comparison in this repository is actually run —
derived from the real modules in [`src/prometheus/experiments/`](../src/prometheus/experiments/)
and the real comparisons already committed (RECESSIONNET, Q-MACRO), not an
aspirational process nobody follows. If you're adding a new model
comparison, follow this; if you find a comparison in this repo that
deviates from it without saying why, that's a bug — open an issue.

## 1. Lock the splits before looking at results

Build an immutable [`HoldoutManifest`](../src/prometheus/experiments/holdout_manifest.py)
(EXP-04) from non-overlapping `DataSplit`s, each tagged `"train"`,
`"validation"`, or `"test"`. `build_holdout_manifest` rejects overlapping
date ranges outright — a date belongs to at most one regime, or the whole
point of locking cutoffs doesn't hold. Gaps between regimes (e.g. a
quarantine buffer around a cutoff) are fine; overlap is not. The resulting
`manifest_id` is a content hash over every split — two people who lock
bit-identical cutoffs get the identical id; changing one date changes it.

## 2. Select hyperparameters/stopping epoch on validation only, never test

[`EarlyStopper`](../src/prometheus/experiments/early_stopping.py) (MLO-06)
requires every call to `.step()` to declare which regime the reported
metric came from; a call reporting anything other than `"validation"`
raises `NonValidationRegimeError` immediately. This is enforced
structurally at the one choke point every stopping decision passes
through — not a convention callers are trusted to remember.

This exists because of a real, documented failure mode: a diagnostic run
of RECESSIONNET at a fixed epoch budget (PR-139) found the
higher-parameter-count hybrid-quantum and classical-MLP candidates
overfitting past epoch ~20-60 while logistic regression did not — a
fixed-epoch comparison is not fair once model capacity differs that much.
`train_classifier_with_early_stopping` (PR-142) fixed this by selecting
each model's own stopping epoch from a validation split carved out of the
*training* era, and Q-MACRO (PR-143) reused the identical methodology from
the start rather than repeating the mistake. See
[docs/RESULTS_AND_LIMITATIONS.md](./RESULTS_AND_LIMITATIONS.md) for what
that actually changed about the reported result.

## 3. Hash the feature pipeline, not just the raw data

[`compute_dataset_fingerprint`](../src/prometheus/experiments/dataset_fingerprint.py)
(DAT-12) hashes a normalized/transformed feature array together with the
name of the transformation that produced it. Two independent consumers
applying the same named transformation to the same raw data must get
bit-identical fingerprints — this is what "every model reproduces dataset
fingerprint exactly" (the acceptance criterion) actually checks, verified
against a real transformation (GBM price paths → log returns), not a
synthetic array.

## 4. Seed every stochastic step explicitly

Nothing in this codebase reads unseeded global RNG state for anything that
affects a reported result (see [CONTRIBUTING.md § Code style](../CONTRIBUTING.md#code-style)).
[`prometheus.core.seeds`](../src/prometheus/core/seeds.py) provides the
seed-hierarchy primitives shared across subsystems. A comparison across
multiple seeds (e.g. RECESSIONNET/Q-MACRO's 5-seed checks) exists
specifically so a single lucky/unlucky seed cannot be reported as "the"
result — report the distribution across seeds, not just seed 0.

## 5. Compare with a paired bootstrap, not a point estimate

[`experiments.bootstrap`](../src/prometheus/experiments/bootstrap.py) (EXP-07)
resamples **path indices once** per resample and applies the same indices
to every candidate being compared (a paired design), preserving whatever
dependence exists between a path's outcome under policy/model A and B — an
unpaired bootstrap that resampled each candidate's indices independently
would throw that dependence away and overstate the uncertainty. The
interval reported is the percentile method (sort the bootstrap
distribution of the difference, take the `alpha/2`/`1 - alpha/2`
quantiles) — the simplest standard choice, not a claim that it's the
tightest one for every statistic (BCa intervals can do better for skewed
statistics; this project uses the simpler, well-understood method and says
so rather than quietly picking the more flattering one).

## 6. State the comparison before running it, and report it regardless of outcome

EXP-07's own acceptance language is "pre-registered comparative benchmark
report" — the benchmark being run should be nameable before the numbers
come back, and the report should be published whether the new candidate
wins, loses, or ties. Every real comparison run in this repository so far
has reported a negative or null result as the actual finding at least once
— see [docs/RESULTS_AND_LIMITATIONS.md](./RESULTS_AND_LIMITATIONS.md). A
model comparison that only gets written up when the new approach wins is
not evidence, it's marketing.

## Worked examples already in this repository

- `prometheus.recessionnet` / `orchestration.recessionnet_run` —
  logistic / classical-MLP / hybrid-quantum recession classifiers, 1988-99
  train era, early-stopped on a carved-out validation split, scored on a
  genuinely held-out test era.
- `prometheus.macrocore` / `orchestration.qmacro_run` — AR(3) refit at
  every real test month (a classical baseline that is re-estimated, not
  frozen, so the comparison isn't tilted by staleness) vs. MLP vs. hybrid
  quantum regressor, same early-stopping/validation discipline.

Read either orchestration script end-to-end as the reference
implementation of this guide, rather than treating this document as the
only source of truth.
