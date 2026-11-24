# Confirmatory protocol (DRAFT, not frozen)

**Status: draft.** Nothing below binds the project, and nothing here may be cited as "pre-registered", until the
freeze checklist at the end is complete: the open items filled in, the analysis code written, a commit tagged, and
that tag anchored somewhere the maintainer cannot edit. Until then this is a plan.

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
5. **Outcome classes** for a paired effect `θ` (positive means the *baseline* is worse) with interval `[L, U]` and
   an equivalence margin `δ` fixed in advance: **better** if `L > 0`; **worse** if `U < 0`; **equivalent** if
   `-δ < L` and `U < δ`; otherwise **inconclusive**. An interval that contains zero is *not* evidence of equality.
6. **Margins are practical, not statistical.** Each `δ`, block length, seed and sample size below is a proposal the
   maintainer must confirm before the freeze; changing one afterwards is a deviation.

## Primary endpoints

### E1. Deep hedging against the static baseline (H5). Label: untouched (fresh simulated paths)

- **Question.** Does the REINFORCE hedging policy beat the delta / no-trade-band baseline on conditional value at
  risk of terminal hedging loss, on the same paths?
- **Frozen.** `rl_hedge` runner with its default configuration at the freeze commit (the CVaR reward and the epoch
  budget recorded there). The CVaR level is whatever that runner reports; record it in the freeze record.
- **Seeds.** 50 fresh seeds, `10000`-`10049`, none used by any earlier run in this repository.
- **Statistic.** Per seed, `r = CVaR(policy) / CVaR(baseline)` on common paths; `θ = -mean(log r)`, so positive
  favours the policy. Interval: across seeds (t interval at the level in rule 4).
- **Margin.** `δ = ln(1.05)`: a 5% CVaR difference is treated as no difference that matters.
- **Context (exploratory, Finding 8).** 8 seeds gave ratios of about 1.04 to 1.41, none below 1.

### E2. Inflation nowcast: base-effect rule against persistence (Finding 18). Label: untouched, then prospective

- **Question.** Does forecasting this month's price growth as the mean of the previous 12 months' growth give a
  smaller absolute error in the year-over-year rate than persisting the last year-over-year rate?
- **Frozen.** The two rules exactly as `orchestration.inflationcast_long_study` defines them. No learned model is
  involved, so nothing is fitted.
- **Data.** CPI-U all items, seasonally adjusted, for months **after** the last month in the committed snapshot
  (`data_cache/kaggle_cpi_index_monthly.csv`, last month 2023-04). The source is chosen and its checksum recorded
  before any model sees it.
- **Statistic.** `d_t = |e_persistence| - |e_rule|` in percentage points; `θ = mean(d_t)`; block length 3.
- **Margin.** `δ = 0.03` percentage points (about 10% of persistence's 0.326 pp test error in Finding 18).
- **Two analyses.** *Primary:* every untouched month available at the freeze. *Extension (prospective):* one
  re-analysis once 24 months have accrued after the freeze, each month's value captured on release day with its
  retrieval time and hash. These are reported separately and never pooled.
- **Known weakness.** Seasonally adjusted values are revised, so months taken from today's file are not the
  real-time values a forecaster would have had. Only the extension fixes that.
- **Context (exploratory).** On 277 test months the rule's error was 0.226 pp against 0.326 for persistence.

### E3. Value-at-risk coverage of GARCH with filtered historical simulation (Finding 15). Label: untouched, then prospective

- **Question.** Is the model that came closest in Finding 15 well calibrated on data it never saw?
- **Frozen.** GARCH(1,1) with filtered historical simulation, parameters estimated once on returns before 2000
  exactly as in Finding 15; the filter conditions on returns up to the previous day. At the freeze the maintainer
  confirms from the study's code that nothing is refitted during the test window.
- **Data.** Daily S&P 500 closes **after** the last day in the committed snapshot
  (`data_cache/kaggle_sp500_spliced_daily_close.csv`, last day 2023-05-03); source and checksum recorded first.
- **Statistics.** Exceedance counts at 99% and 97.5%; the conditional-coverage test at 5% as in Finding 15; the
  pinball-loss difference, 250-day historical simulation minus GARCH-FHS so that positive favours
  GARCH-FHS (paired, block length 20).
- **Reading.** "Consistent with coverage" only if the exact binomial interval for the exceedance rate contains the
  nominal rate *and* the conditional-coverage test does not reject; with about 9 expected exceedances at 99% over
  roughly 900 days, failing to reject is weak evidence, and the report says so.
- **Margin.** For the pinball difference, `δ = 0.2` basis points (about 5% of the 3.92 bp score in Finding 15).
- **Two analyses.** As E2: everything untouched at the freeze, then one prospective re-analysis after 750 further
  trading days.

## Pre-specified but re-used

### E4. Neural SDE under shocks (H2). Label: re-used; left open on purpose

H2 rests on a single shock (COVID). A fair test needs several shocks fixed before any result is seen, and a data-use
audit showing no event window influenced training, early stopping or any hyperparameter. That audit has not been
done, so the event list, windows and loss are **not** guessed here. They are filled in at the freeze, together with
the audit, or E4 is dropped from the confirmatory set. Per-event results are reported one by one, never pooled
into one universal score.

## Not testable now

- **H1 (hybrid quantum vs classical).** Recessions are rare and unplannable, so there is no fresh classification
  sample to wait for, and a fair equivalence test needs matched capacity and compute, which is a design task. It
  stays exploratory.
- **H3 (neural PDE solvers).** The claim is about a crossover in dimension; that is a matched-error benchmark
  (runtime, memory and error at d = 1, 2, 3 and beyond), not a hypothesis test on fresh data.
- **H4 (methodology).** A statement about how evaluation choices change conclusions; it was already shown twice
  (Findings 1 and 7) and is not a hypothesis about fresh data.

## Open items before the freeze

| Item | Status |
| --- | --- |
| Analysis code for E1-E3, run on old data first to show it works and reproduces Finding 8, 15 and 18 | not written |
| Power note per endpoint, from the retrospective paired differences (an endpoint with power below 0.8 is declared estimation-only up front) | not computed |
| Data-use audit: which windows each frozen model has already read | not done |
| Source and SHA-256 of the post-snapshot CPI and S&P 500 data | not chosen |
| Maintainer confirms every margin `δ`, block length, seed, sample size and date above | not done |
| E4 event list and audit, or E4 dropped | open |
| A collector that records each new CPI and price on release day, for the prospective extensions | not built |

## Freeze checklist (only the maintainer can do these)

1. Close every open item above and commit the analysis code.
2. Run the whole analysis once on old data to prove it works. Do not run it on any untouched data yet.
3. Fill in the freeze record below, commit, and push an annotated tag `protocol-v1`.
4. **Anchor the tag outside GitHub's editable history**: register this file on an independent registry (for
   example OSF), or archive a release in a service that issues a DOI. A commit date is set by its author and proves
   little on its own.
5. Only then load the untouched data and run E1-E3.

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
