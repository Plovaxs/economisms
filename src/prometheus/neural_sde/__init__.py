"""Neural SDE subsystem (blueprint category NSD).

A neural SDE replaces a classical model's hand-specified drift/diffusion
functions (`stochastica.gbm`'s constant mu/sigma, `stochastica.heston`'s
CIR variance process) with small neural networks mu_theta(t, X_t, regime),
sigma_theta(t, X_t, regime), trained by maximum likelihood on real data
and integrated forward by Euler-Maruyama exactly like any other SDE in
`stochastica`. See `neural_sde.design` for the concrete design record
(state variables, units, constraints) NSD-01 asks for.

State variables are the real monthly `KAGGLE_NASDAQ_YOY`/`KAGGLE_GDP_YOY`
series already ingested by `data_ingestion.kaggle_macro` (PR-145) -- year-
over-year percent-change series, not price levels -- conditioned on
`KAGGLE_FEDFUNDS`/`KAGGLE_CLAIMS_YOY`/`KAGGLE_M2_YOY` as exogenous regime
features. See `neural_sde.model`'s docstring for why this means "price
positivity" (NSD-04's literal wording, written for a price-like state) is
honestly reinterpreted here as finiteness/boundedness, not a positivity
constraint that would be false of this project's own real data (real
`KAGGLE_GDP_YOY` reaches -7.69% in 2020-05 -- its single most negative
value in the entire 1981-2023 sample -- and real `KAGGLE_NASDAQ_YOY`
reaches -59.8% in 2001-03 -- see `neural_sde.ood`).
"""

from __future__ import annotations
