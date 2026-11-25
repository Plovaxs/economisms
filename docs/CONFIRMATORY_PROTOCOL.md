# Confirmatory protocol (DRAFT, not frozen)

**Status: draft.** Nothing below binds the project, and nothing here may be cited as "pre-registered", until the
freeze checklist at the end is complete: the open items filled in, a commit tagged, and that tag anchored somewhere
the maintainer cannot edit. Until then this is a plan. The analysis code now exists and is described under "The
analysis code"; the data-use audit is [confirmatory/DATA_USE_AUDIT.md](./confirmatory/DATA_USE_AUDIT.md) and the
power note is [confirmatory/power_note.json](./confirmatory/power_note.json). The plan around them does not yet
bind anyone.

**Why it exists.** [FINAL_PROJECT_HYPOTHESES.md](./FINAL_PROJECT_HYPOTHESES.md) is a *retrospective* freeze: the five
hypotheses were tested before that document existed, so every verdict in
[RESULTS_AND_LIMITATIONS.md](./RESULTS_AND_LIMITATIONS.md) is exploratory evidence. This protocol says, before any
fresh outcome is read, what will be tested on data and seeds the project has never used, how, and what result would
count for or against each claim.

**What it cannot be, even when frozen.** A single maintainer registering their own plan, with AI assistance, is
stronger than a retrospective freeze and weaker than an independent registry or an external replication. It does
not make any finding true; it limits how much the analysis can bend toward the result.

## Evidence labels

Every claim made from this protocol carries exactly one label.

| Label | Meaning |
| --- | --- |
| **Prospective** | The observations did not exist when the protocol was frozen. |
| **Untouched** | The observations exist, but no code, fit, tuning choice or test in this repository read them before the freeze. People (including the maintainer) may know what happened in that period; that is a named weakness, not a defence. |
| **Re-used** | Historical data this repository has already read. Anything on it is exploratory, however carefully pre-specified. |

## Rules for every endpoint

1. **Frozen pipeline.** The model, its configuration and the baseline are the code at the freeze commit, identified
   by that commit and the runner's recipe hash. Nothing is refit, retuned or reselected on the endpoint's data.
2. **One analysis per endpoint**, on a stated date or sample size, with no interim looks. A bug found later is fixed
   in the deviation log below with the before/after numbers, and the endpoint is reported both ways.
3. **Everything is reported**, including nulls and reversals. A negative result is a result.
4. **Intervals.** Three primary endpoints, so each is reported with a two-sided `1 - 0.05/3` (98.33%) interval
   (Bonferroni). Paired differences use a moving-block bootstrap, 10,000 resamples, seed fixed in advance.
5. **Outcome classes** for a paired effect `θ` (positive means the frozen model beats its baseline) with interval
   `[L, U]` and an equivalence margin `δ` fixed in advance, checked in this order: **equivalent** if `-δ < L` and
   `U < δ` (a real but negligible difference counts as equivalent); otherwise **better** if `L > 0`; otherwise
   **worse** if `U < 0`; otherwise **inconclusive**. An interval that contains zero is *not* evidence of equality.
6. **Margins are practical, not statistical.** Each `δ`, block length, seed and sample size below is a proposal the
   maintainer must confirm before the freeze; changing one afterwards is a deviation.

## Primary endpoints

### E1. Deep hedging against the static baseline (H5). Label: untouched (fresh simulated paths)

- **Question.** Does the REINFORCE hedging policy beat the delta / no-trade-band baseline on conditional value at
  risk (95%) of terminal hedging loss, on the same paths?
- **Frozen.** The `rl_hedge` runner with its default configuration at the freeze commit, one training run per seed
  on that seed's 2,000 simulated paths; its recipe hash goes in the freeze record.
- **Seeds.** 50 fresh seeds, `10000`-`10049`, none used by any earlier run in this repository. The analysis code
  refuses to run them until the freeze record below is complete.
- **Statistic.** Scored on **held-out** paths, which Finding 8 did not do: 20,000 fresh paths per seed from a generator
  independent of the training one, the policy acting deterministically (its mean action), both hedges on the same
  paths. `r = CVaR(policy) / CVaR(baseline)`; `θ = -mean(log r)` over seeds, so positive favours the policy;
  interval: t interval across the 50 independent training runs.
- **Margin.** `δ = ln(1.05)`: a 5% CVaR difference is treated as no difference that matters.
- **Why not Finding 8's number.** Finding 8 compares the policy's last-epoch *sampled* (exploring) rollout with the
  baseline on the *training* paths: the two biases point in opposite directions, so the result stands, but it is not
  the cleanest comparison. The code reports that number too (`in_sample_ratio`), so the old finding stays reproducible.
- **Power (old data, 80% target).** The spread of `θ` over the eight old seeds is 0.051. With 50 seeds the endpoint
  reaches "better" 99% of the time if the policy is truly 5% better, and can detect an improvement of about 2.4%
  (`θ` = 0.024) with 80% power: **adequate, it can support a verdict.** Planning numbers that assume the new seeds
  behave like the old ones.
- **Context (exploratory).** The held-out ratios on the eight old seeds were seen while the code was written, after
  `δ` was proposed; they are in "The analysis code" below and are not evidence for this endpoint.

### E2. Inflation nowcast: base-effect rule against persistence (Finding 18). Label: re-used (2023-04 to 2026-10); prospective after

- **Question.** Does forecasting this month's price growth as the mean of the previous 12 months' growth give a
  smaller absolute error in the year-over-year rate than persisting the last year-over-year rate?
- **Frozen.** The two rules exactly as `orchestration.inflationcast_long_study` defines them (`base_mean12` and the
  previous year-over-year rate). No learned model is involved, so nothing is fitted.
- **Why the label is not "untouched".** The data-use audit found that INFLATIONCAST scores persistence on the
  not-seasonally-adjusted CPI for every month from 2022-01 to 2026-10 (`data_cache/us_cpi_monthly.csv`, 56 test
  months), so the months a seasonally adjusted series would add after 2023-03 were already read and scored by code
  in this repository. The base-effect rule was never run on them, but they are **re-used**. Anything on them is
  exploratory; the only confirmatory E2 analysis is the prospective extension.
- **Data.** One single-vintage series, `confirmatory_data/cpi_sa_bls_2026-11-24.csv` (BLS `CUSR0000SA0`, seasonally
  adjusted, 2022-01 to 2026-10, SHA-256 `236a14d4b6ac86d721feb9533e324ab2a411ec8dfcee0edbf15da4de13874951`), scored
  on its own: it is **not** joined to the committed Kaggle series, because seasonally adjusted indexes are revised
  and a join would put a revision artefact into the first scored month; the output reports how far the two differ on
  the months they share. No value was read when it was fetched. **BLS published no index for 2025-10**, so a target
  month that needs that level (targets 2025-10 to 2026-11) is excluded and listed, and the endpoint is repeated as a
  clearly labelled sensitivity with the gap interpolated.
- **Statistic.** `d_t = |e_persistence| - |e_rule|` in percentage points; `θ = mean(d_t)`; block length 3 (about
  `n^(1/3)` for the months expected); blocks of 6 and 12 are reported as sensitivity, never decisive.
- **Margin.** `δ = 0.03` percentage points (about 10% of persistence's 0.326 pp test error in Finding 18).
- **Two analyses.** *Re-used window* (exploratory): 2023-04 to 2026-10, 30 usable months after the gap. *Extension
  (prospective, the confirmatory one):* one analysis once 24 usable months have accrued after 2026-10 (the first
  usable month is 2026-12, because the gap also removes 2026-11), each month's value captured on release day with its
  retrieval time and hash. Never pooled.
- **Power (old data, 80% target).** The old paired differences have mean 0.100 pp and spread 0.236 pp. With 30
  months the endpoint reaches "better" 59% of the time if the true effect is the old 0.100 (24 months: 52%), and
  needs a true effect of about 0.15 pp for 80%: **estimation-only under the 0.8 rule.** It can report a size and an
  interval; it cannot support a verdict.
- **Known weakness.** Seasonally adjusted values are revised, so months taken from today's file are not the
  real-time values a forecaster would have had. Only the extension fixes that.
- **Context (exploratory).** On 277 test months the rule's error was 0.226 pp against 0.326 for persistence.

### E3. Value-at-risk coverage of GARCH with filtered historical simulation (Finding 15). Label: untouched, then prospective

- **Question.** Is the model that came closest in Finding 15 well calibrated on data it never saw?
- **Frozen.** GARCH(1,1) with filtered historical simulation, parameters estimated once on returns before 2000
  exactly as in Finding 15; the filter conditions on returns up to the previous day. The code reproduces the study's
  own forecaster and a test compares the two number for number, so nothing is refitted on the scored days.
- **Data.** Daily S&P 500 closes **after** the last day in the committed snapshot
  (`data_cache/kaggle_sp500_spliced_daily_close.csv`, last day 2023-05-03): the first untouched day is 2023-05-04. A
  new `date,close` CSV is hashed against a SHA-256 stated in advance and may not overlap the committed series.
  **No source is chosen**: Yahoo, FRED and Stooq are not reachable from the environment that wrote the code and
  Kaggle needs the maintainer's token, so the maintainer downloads the file and records its checksum. No daily
  return after 2023-05-03 is in the repository (monthly factor returns to 2026-09 are, see the audit).
- **Primary claim (99% VaR).** "Consistent with coverage" only if the exact binomial interval for the exceedance rate
  contains 1% *and* the conditional-coverage test does not reject at the Bonferroni level `0.05/3`. With about 9
  expected exceedances over roughly 900 days, failing to reject is weak evidence, and the report prints the interval
  rather than a verdict alone.
- **Secondary.** The same at 97.5%; and the paired pinball-loss difference (250-day historical simulation minus
  GARCH-FHS, so positive favours GARCH-FHS), block length 22 (the study's own), margins `δ = 0.2` bp at 99% and
  `0.4` bp at 97.5% (about 5% of GARCH-FHS's 3.92 and 8.22 bp in Finding 15).
- **Two analyses.** As E2: everything untouched at the freeze, then one prospective re-analysis after 750 further
  trading days.
- **Power (exact, 98.33% interval).** The false-alarm rate is 1.1% over 880 days (below the 1.7% allowed). If the
  model's true exceedance rate is Finding 15's 1.48%, the interval excludes 1% only 11% of the time (10% over 750
  days); at 2% it is 49%, at 3% 97%. **Estimation-only for a modest miscalibration:** it can detect gross failure
  (about 3% or worse), not a 1.5% rate, and "consistent with coverage" over a few hundred days says little.

## Pre-specified but re-used

### E4. Neural SDE under shocks (H2). Label: re-used; pre-specified; estimation only

Designed and approved by the maintainer on 25 November 2026; code in `confirmatory/e4_shocks.py`.

- **Why it cannot be confirmatory.** Every shock in the committed macro grid (1981-12 to 2023-01) was read by code:
  2001 and 2008 sat inside the training data of the model Finding 5 reports, and COVID's window also decided
  `patience=20` (Finding 5's follow-up kept it after seeing the window), so COVID is flagged
  *selection-contaminated*. No shock after 2023-01 is in the data.
- **Question.** Per shock, does the neural SDE's log-score degrade less than a constant-parameter GBM's?
- **Events, fixed now:** the 2001 recession (decision times 2001-03-31 to 2001-11-30), the 2007-2009 crisis
  (2007-12-31 to 2009-06-30), both from the NBER dates already in `recessionnet/labels.py`, and COVID in
  Finding 5's own window (2020-02-29 to 2020-06-30).
- **Method.** Per event, train only on transitions decided strictly before it (80/20 chronological split, early
  stopping on the validation part, `patience` fixed at 20 and never tuned, 300 epochs at most); fit a GBM on the
  same training part; score both without retuning on the event window. Statistic: degradation = event log score
  minus in-distribution (validation) log score; `advantage = GBM degradation - neural degradation`, positive
  favouring the neural SDE.
- **Seeds.** 20000-20009, reserved for the frozen run (the guard refuses them until the freeze). Exploratory runs
  use seeds 0-9.
- **Inference.** None across events: three events cannot support an interval, and seeds measure only training
  noise. Reported event by event with the spread over seeds; never pooled into one score; outside the Bonferroni
  family.
- **Exploratory dry run (seeds 0-9, `confirmatory/e4_exploratory_seeds0-9.json`).** The neural SDE degraded
  *less* than the GBM in 0 of 10 seeds for 2001 (median advantage -0.81), 4 of 10 for 2008 (-0.69) and 4 of 10
  for COVID (-2.29, range -25.8 to +19.5). Seed 0 reproduces Finding 5's +6.99 against +26.45 exactly; most other
  seeds do not: **the "more robust under COVID" half of H2 is not stable across seeds.**

## Not testable now

- **H1 (hybrid quantum vs classical).** Recessions are rare and unplannable, so there is no fresh classification
  sample to wait for, and a fair equivalence test needs matched capacity and compute, which is a design task. It
  stays exploratory.
- **H3 (neural PDE solvers).** The claim is about a crossover in dimension; that is a matched-error benchmark
  (runtime, memory and error at d = 1, 2, 3 and beyond), not a hypothesis test on fresh data. The grid half of that
  benchmark now exists (`docs/RESULTS_AND_LIMITATIONS.md` Finding 19); the neural half, at matched error, does not.
- **H4 (methodology).** A statement about how evaluation choices change conclusions; it was already shown twice
  (Findings 1 and 7) and is not a hypothesis about fresh data.

## The analysis code

`src/prometheus/confirmatory/`, no network call, no model added: each forecaster is the original study's, imported
unchanged or reproduced line for line and compared with it by a test.

```
python -m prometheus.confirmatory reproduce            # old data and seeds 0-7 only; no freeze needed
python -m prometheus.confirmatory fetch-cpi --start-year 2022 --end-year 2026 --out FILE   # prints no value
python -m prometheus.confirmatory power --lock-meta FILE.meta.json --output power.json     # old data only
python -m prometheus.confirmatory e1 --seeds 10000-10049
python -m prometheus.confirmatory e4 --seeds 20000-20009
python -m prometheus.confirmatory e2 --series cpi.csv --series-sha256 <hex> --scored-from 2023-04-30
python -m prometheus.confirmatory e3 --new px.csv  --new-sha256 <hex> --scored-from 2023-05-04
```

`e1`, `e2` and `e3` refuse to run (before reading the data file or training anything) until the freeze record below has
every field filled in. The guard stops an accident, not a deliberate bypass: it reads a table the maintainer edits.

**What `reproduce` showed on the old data (24 November 2026).** 14 documented numbers compared, all matching (a 15th and 16th, Finding 5's COVID degradations for seed 0, were added with E4 and also match):

| Endpoint | Old finding | The new code gave |
| --- | --- | --- |
| E2 | Finding 18: 277 months; error 0.326 pp (persistence), 0.226 (rule); difference -0.100, 95% interval [-0.136, -0.068] | identical to three decimals, from the same bootstrap seed |
| E3 | Finding 15: 3,235 test days; GARCH-FHS 48 exceedances at 99%, pinball 3.92 and 8.22 bp; 250-day historical 56 exceedances, 5.63 and 10.40 bp | identical |
| E1 | Finding 8: 1.04x-1.41x the baseline's CVaR over 8 seeds; 0 of 8 beat it | 1.04-1.41 over the two budgets together; 0 of 8 at either budget |

Two things came out of it. First, Finding 8's range was attributed to "800 epochs", but it belongs to the two
budgets together: at 400 epochs the eight seeds gave 1.08x-1.41x, at 800 epochs 1.04x-1.19x (the text of the finding
is corrected). Second, the new held-out statistic on the same eight seeds gave ratios of 1.03-1.20 at 400 epochs
and 1.00-1.14 at 800, none below 1: exploratory, because those seeds are old, and not a prediction for E1.

A test also caught a real defect while this was written: a month written as `2023-13` was read as January.

## Open items before the freeze

| Item | Status |
| --- | --- |
| Analysis code for E1-E3, shown to reproduce Findings 8, 15 and 18 on old data | **done** (see above) |
| A guard that keeps untouched data and the reserved seeds unread until frozen | **done** |
| Power note per endpoint (an endpoint with power below 0.8 is declared estimation-only up front) | **done**: E1 adequate; E2 and E3 estimation-only (`confirmatory/power_note.json`) |
| Data-use audit: which windows each frozen model has already read | **done by the assistant** (`confirmatory/DATA_USE_AUDIT.md`); it changed E2's label; the maintainer accepted it on 25 November 2026 without an independent check |
| Source and SHA-256 of the post-snapshot CPI data | **done**: BLS `CUSR0000SA0`, locked in `confirmatory_data/`, digest above (a one-month gap, 2025-10) |
| Source and SHA-256 of the post-snapshot S&P 500 data | **not chosen**: only the maintainer can (Kaggle token or another download) |
| Decide the family: with E2 and E3 estimation-only, keep all three in the Bonferroni family (the code's default, conservative) or give only E1 a verdict and 95% intervals | **open**; if the maintainer does not choose, the code's default (all three, Bonferroni `0.05/3`) applies and is recorded in the freeze record |
| Maintainer confirms every margin `δ`, block length, seed, sample size and date above | **confirmed on 25 November 2026**, accepting the proposals as written (the maintainer did not change any, and did not independently re-derive them); changing one after the freeze is a deviation |
| E4 event list and audit, or E4 dropped | **designed and approved 25 Nov 2026** (code, tests, exploratory dry run on seeds 0-9); the frozen run on seeds 20000-20009 waits for the freeze |
| A collector that records each new CPI and price on release day, for the prospective extension | not built |

## Disclosures made before the freeze

- The assistant saw three seasonally adjusted CPI values (2026-08, 2026-09, 2026-10) when it printed the start of
  a BLS response to check that the API was reachable. They are inside the window labelled re-used.
- The held-out hedging ratios on the eight old seeds were seen while the code was written, after `δ` was proposed.
- INFLATIONCAST's use of the 2023-2026 not-seasonally-adjusted CPI (see E2) was found by the data-use audit, after
  E2 had first been labelled "untouched" in an earlier draft of this file.

## Freeze checklist (only the maintainer can do these)

1. Close every open item above and commit the result.
2. Run `python -m prometheus.confirmatory reproduce` once more on the freeze commit and keep its output.
3. Fill in the freeze record below, commit, and push an annotated tag `protocol-v1`.
4. **Anchor the tag outside GitHub's editable history**: register this file on an independent registry (for
   example OSF), or archive a release in a service that issues a DOI. A commit date is set by its author and proves
   little on its own.
5. Only then load the untouched data and run E1-E3 (the e1, e2 and e3 commands refuse to run until step 3 is done).

## Freeze record

| Field | Value |
| --- | --- |
| Freeze date | not frozen |
| Freeze commit | not frozen |
| Recipe hash, `rl_hedge` | not frozen |
| External anchor (registry or DOI) | none |

## Deviation log

| Date | What changed | Why | Effect on the result |
| --- | --- | --- | --- |
| none | | | |
