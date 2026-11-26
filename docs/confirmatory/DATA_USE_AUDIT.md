# Data-use audit for the confirmatory protocol

Done on 24 November 2026, before the freeze, to answer one question for each endpoint: **which of the data
and seeds the protocol calls "untouched" has this repository already read?** Method: reading the loaders and
studies, listing every committed data file with its last date, and searching the code for the literal seeds
the protocol reserves. It is a manual audit by the assistant that wrote the analysis code, not an independent
one, and a search for literals cannot see a seed computed at run time. The maintainer should confirm it.

## E1: the reserved seeds

The protocol reserves seeds `10000`-`10049`. A search of `src/`, `tests/`, `tools/` and `scripts/` for seeds
at or above 10,000 finds none outside `prometheus.confirmatory`; the largest literal seed anywhere is 123.
**Result: untouched.** (The eight old seeds 0-7 were used for the reproduction and the power note; they are
not reserved.)

## E2: CPI, and the finding that changes its label

| File | Series | Last month | Read by | Scored by |
| --- | --- | --- | --- | --- |
| `data_cache/kaggle_cpi_index_monthly.csv` | seasonally adjusted (FRED CPIAUCSL via Kaggle) | 2023-03 | `inflationcast_long_study` | months 2000-01 to 2023-01; 2023-02 and 2023-03 were loaded, not scored |
| `data_cache/us_cpi_monthly.csv` | **not** seasonally adjusted (BLS CUUR0000SA0) | 2026-10 (no value for 2025-10) | the INFLATIONCAST dataset builder | **its default test split starts 2022-01 and holds 56 months, so months through 2026-10 were scored** (the committed demo recording shows `n_test` 56) |

The second row is the finding. `inflationcast.data` builds an example for every month that has a CPI value,
and INFLATIONCAST's own benchmark scores persistence of the year-over-year rate against learned models on
the months from 2022-01 on. So the target values E2 would score for 2023-04 to 2026-10, in their
not-seasonally-adjusted form, were **read and scored by code in this repository**, persistence side
included. The base-effect rule itself was never run on them, and the seasonally adjusted values were never
loaded, but by the protocol's own definition ("no code, fit, tuning choice or test read them") these months
are **re-used, not untouched**.

**Consequence, applied in the protocol:** E2's analysis of 2023-04 to 2026-10 is labelled *re-used,
pre-specified* (exploratory); the only confirmatory E2 analysis is the prospective extension on months after
2026-10. BLS published no index for 2025-10, so a target month that needs that level is excluded (targets
2025-10 to 2026-11); the first usable extension month is therefore 2026-12.

**The locked file.** `confirmatory_data/cpi_sa_bls_2026-11-24.csv` (seasonally adjusted, BLS series
`CUSR0000SA0`, 2022-01 to 2026-10, one blank level for 2025-10) was fetched on 2026-11-24 by
`python -m prometheus.confirmatory fetch-cpi`, which prints only labels and digests. No code in this
repository has parsed its values; a test checks its digest and that nothing in `src/` refers to it.

**A disclosure.** While checking that the BLS API was reachable, the assistant printed the start of one
response and saw three seasonally adjusted index values (2026-08, 2026-09, 2026-10). They influenced no
choice, and they fall inside the window that is now labelled re-used, but they were seen.

## E3: S&P 500

| File | Last date | Note |
| --- | --- | --- |
| `data_cache/kaggle_sp500_spliced_daily_close.csv` | 2023-05-03 | the committed daily series E3 extends |
| `data_cache/kaggle_nasdaq_daily_close.csv` | 2023-05-03 | |
| `data_cache/ff3_monthly_snapshot.csv` | 2026-09 | **monthly** market, size and value factors, loaded by the Q-MACRO and RECESSIONNET studies |
| `data_cache/kaggle_term_spread_monthly.csv` | 2024-05 | monthly |
| `data_cache/treasury_yield_spread_monthly.csv` | 2023-12 | monthly |

A daily S&P 500 file after 2023-05-03 is now in the repository, locked and unread:
`confirmatory_data/sp500_gspc_kaggle_2026-11-26.csv` (digest in the protocol). The slicing script that wrote it read the
closing values to copy them; nothing printed them, and `tests/unit/test_confirmatory_lock.py` reads only its dates.
The daily exceedance counts E3 scores cannot be derived from monthly factor returns, so **the daily data is
untouched**. The monthly market factor, though, shows the broad path of the market through 2026-09, so the volatility
regime of the window is not unknown to the code's authors. That is a named weakness, not a defence.

**Where the new daily closes came from.** From the environment where the code was written, Yahoo Finance answers
401, FRED is unreachable and Stooq serves a JavaScript challenge, so the file was taken from Kaggle with a token the
maintainer pasted in the chat for that purpose (never written to disk). The assistant searched Kaggle by last update,
chose `paveljurke/s-and-p-500-gspc-historical-data` from its page metadata and file list, and recorded the SHA-256 in
the protocol; the analysis code verifies it. The maintainer did not name the dataset and may replace it before the
anchor.

## What each frozen model has already read

- **E1's policy** reads simulated paths only.
- **E2's two rules** have no fitted parameters.
- **E3's GARCH-FHS** is fitted once on returns before 2000; its filter conditions on every earlier return up to
  the previous day, which for the committed series means everything to 2023-05-03.

## Decisions this audit forced

1. E2's primary window is re-used (exploratory); only months after 2026-10 are confirmatory.
2. A month with no published index level is excluded, listed in the output, and repeated as a clearly labelled
   sensitivity with each isolated gap interpolated.
3. The maintainer picks the S&P source; the code does not guess.

The power note (`power_note.json`, from the old data only) adds a fourth: under the protocol's own 0.8 rule
only E1 can support a verdict; E2 and E3 are estimation-only unless the maintainer changes the plan.
