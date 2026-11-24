"""Analysis code for the DRAFT confirmatory protocol (`docs/CONFIRMATORY_PROTOCOL.md`).

Three endpoints, each a pure function over the data or seeds it is given:

- `e1_hedging`   the REINFORCE hedging policy against the static delta / no-trade-band baseline,
                 scored on held-out simulated paths (Finding 8, hypothesis H5);
- `e2_inflation` the 12-month base-effect rule against persistence of the year-over-year rate
                 (Finding 18);
- `e3_var`       the coverage of GARCH with filtered historical simulation (Finding 15).

What this package is for: writing the analysis down, in code, before any untouched observation is
read, and showing that the code reproduces the numbers the findings already report on the OLD data
(`python -m prometheus.confirmatory reproduce`). It adds no model: every forecaster is the one the
original study uses, imported unchanged, and the tests compare the two.

What it deliberately does not do: fetch data (no network call), choose a data source, or decide the
margins. The margins, block lengths, seeds and sample sizes in each module are the protocol's
PROPOSALS; the maintainer confirms them at the freeze. The commands that would read untouched data
refuse to run until the protocol's freeze record is complete (`freeze.require_frozen`), so a
mistaken run cannot quietly use up the data the protocol is meant to protect.
"""
