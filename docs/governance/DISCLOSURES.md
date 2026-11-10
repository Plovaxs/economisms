# Conflicts of interest, intended audience, and research ethics

GOV-06 (conflicts of interest/intended audience) and GOV-07 (research
ethics/simulation limitations) — both short, honest statements rather
than long policy documents, because the real facts here are simple.

## Conflicts of interest (GOV-06)

**None disclosed, because none exist to disclose.** This is a non-
commercial, single-maintainer research repository (`CONTRIBUTING.md`).
No party has a financial interest in any result this repository
produces being favorable, published, or suppressed. If that ever
changes (a commercial interest, a funding relationship, a dependency
on a specific finding), this section must be updated before the change
takes effect, not after.

## Intended audience (GOV-06)

Software engineers and quantitative researchers evaluating this
project's methodology, test discipline, or specific findings — not
investors, not retail traders, not anyone seeking financial advice.
See [README.md § Status & disclaimers](../../README.md#status--disclaimers).

## Research ethics and simulation limitations (GOV-07)

- This project simulates synthetic and real historical economic/
  market data for methodological research. It does not collect,
  process, or publish data about identifiable individuals (confirmed
  by `evidence.security_scan.pii_scan`, see
  `docs/DATA_PROCESSING_INVENTORY.md`).
- No result in this repository has been used, or is intended to be
  used, to make a real investment, lending, or policy decision.
- Every negative, null, or unflattering finding this project's own
  comparisons have produced is published, not filtered — see
  `docs/RESULTS_AND_LIMITATIONS.md`, which exists specifically to
  prevent only-favorable-results publication bias.
- Simulated/synthetic results are never presented as empirical fact
  about the real world without the word "synthetic"/"simulated"
  attached — enforced by `evidence.export`'s AUD-08 disclaimer/
  source_tag convention on every exported bundle.

**Honest status**: the statement above is real and accurate as of this
writing. **It has not been independently approved** by anyone besides
the project maintainer — GOV-07 is marked partial for that reason, the
same pattern as every other single-maintainer-repository governance
item in this checklist.
