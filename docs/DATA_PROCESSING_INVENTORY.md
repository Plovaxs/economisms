# Data processing inventory

PRV-02: classify personal, financial and confidential records; acceptance
— "data processing inventory and purposes documented." Every real series
this repository ingests, with its classification and purpose, derived
directly from [docs/DATA_DICTIONARY.md](./DATA_DICTIONARY.md) and each
connector's own `source_license` field — not a separate, hand-maintained
list that could drift.

## Classification key

- **Personal**: identifies or could identify a specific natural person.
- **Financial (individual)**: a specific person's or entity's private
  financial position (account balances, transaction history, holdings).
- **Confidential**: non-public, under a restriction on redistribution.
- **Public aggregate**: published macroeconomic/market statistics with no
  individual-level content.

## Inventory

| Series / dataset | Source | Classification | Purpose |
|---|---|---|---|
| U.S. Treasury CMT yields (`UST_*`) | FRED (public republication of U.S. Treasury data) | Public aggregate | Yield-curve research (DAT-04) |
| World Bank indicators | World Bank Open Data | Public aggregate | Macro research (DAT connectors) |
| Kenneth French factors (`FF3_*`) | Kenneth French Data Library | Public aggregate | Market-factor research (RECESSIONNET, Q-MACRO) |
| Kaggle US macro series (`KAGGLE_*`: GDP, claims, Fed funds, M2, NASDAQ) | Kaggle mirror of FRED series (ODbL-1.0) | Public aggregate | Recession classification, neural SDE training |
| NBER recession dates | Public NBER chronology | Public aggregate | Recession labels (RECESSIONNET) |
| Kaggle extended US macro-financial series (`KAGGLEX_*`: unemployment, seasonally adjusted CPI, bank credit, S&P 500 return/volatility, re-derived GDP/claims/Fed funds) | Kaggle mirror of FRED and Investing.com data (ODbL-1.0) | Public aggregate | Real-data feature expansion for recession classification (PR-198) |
| Kaggle US Treasury 10Y-3M term spread (`KAGGLE_TERM_SPREAD_10Y3M`) | Kaggle mirror of Treasury yields (CC BY-NC 4.0) | Public aggregate | Yield-curve recession feature from 1981 |
| Kaggle S&P 500 daily closes | Kaggle (Yahoo Finance ^GSPC; ODbL-1.0) | Public aggregate | Real-return evaluation of the financial-risk models (PR-199) |
| Kaggle Federal Reserve policy variables | Kaggle (Federal Reserve; CC0-1.0) | Public aggregate | Real-data policy-rule study (PR-200) |
| Kaggle S&P 500 daily closes continued to 2023-05 (Yahoo ^GSPC through 2020-11-04, then the Investing.com SPX500 series of the backbone dataset, rescaled at the join) | Kaggle (ODbL-1.0, both datasets) | Public aggregate | Longer out-of-time test of the market-risk models (PR-202) |
| Kaggle NASDAQ composite daily closes, 1980-2023 | Kaggle backbone dataset (Investing.com; ODbL-1.0) | Public aggregate | Second-market replication and pooled volatility training (PR-202) |

**No row above is Personal, Financial (individual), or Confidential.**
Every ingested series is a published, aggregate, government- or
institution-level macroeconomic/market statistic — none describes an
identifiable individual or a specific entity's private financial
position. This is confirmed, not merely asserted: `evidence.security_scan
.pii_scan` (PRV-03) scans this repository's real committed datasets
(`data_cache/`, `tests/fixtures/`) for common PII shapes (SSN, email,
phone number, credit-card-number-shaped sequences) and finds zero
matches — see `tests/unit/test_security_scan.py::test_this_repositorys_own_real_committed_datasets_have_no_pii_findings`.

## What this repository does NOT process

Real user accounts, real brokerage/portfolio holdings, real trading
activity, or any other individual-level financial or personal data — see
[README.md § Status & disclaimers](../README.md#status--disclaimers) and
[docs/THREAT_MODEL.md § Assets](./THREAT_MODEL.md#assets). If a future
change introduces any of these, this inventory must be updated before
that data is ingested, not after.

## Data-subject / deletion procedures (PRV-05)

Not applicable today, confirmed by the inventory above and the real
`pii_scan` check rather than assumed: there is no personal data in this
system for a deletion or data-subject-access request to act on. If that
changes, a real procedure is required before it does — this inventory
existing and being checked is the mechanism that would catch the change.

## External API/vendor contract security review (PRV-08)

Not applicable today, confirmed by the real source list above, not
assumed: every external source this repository actually calls (FRED,
World Bank Open Data, the Kenneth French Data Library) is a free,
public, no-authentication data republication — none is a paid API
vendor, none requires a contract, a processor agreement, or a
permissions grant of any kind. `docs/LICENSE_INVENTORY.md` already
records each one's real license terms. There is no vendor relationship
for "service data flows and processors/permissions approved" to apply
to. If a future change introduces a real paid API or SaaS dependency,
a real security/contract review is required before that integration
ships — this inventory existing and being checked (alongside
`docs/compliance/`) is the mechanism that would catch the change, the
same pattern PRV-05 above already uses.
