"""WORLDSIM with the parameters estimated from real data (Finding 28), as constants.

These are the final estimates of `orchestration.worldsim_calibration_study` run with
`--output-gap-anchor` on every month of the real sample (1960-01 to 2023-01, equity from 1928-01);
`docs/numerics/worldsim_calibration_study_v2.json` holds the run and a test pins these constants to
it. Only what the data could speak to is replaced:

- the regime transition matrix and the equity mean and volatility in each regime (a three-state
  hidden Markov model of monthly S&P 500 returns);
- Okun's coefficient, the natural unemployment rate, the inflation target and the neutral real
  rate;
- the macro block (persistence, Phillips slope, Taylor rule, the size and shift of the output
  shocks) by indirect inference, and the two bank-lending growth parameters.

Everything else (bond and real-asset returns, bank balance sheets and loss rates, the firm, fiscal
and foreign blocks, the households) keeps the value that was chosen, which is stated, not hidden;
the `calibrated_banks` scenario adds the bank block estimated from FDIC data (Finding 29).
The regimes are the model's own: state 1 ("slowdown") is the HMM's middle state, which the data
puts in about two thirds of all months, so "slowdown" here is the ordinary state, not a recession.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from prometheus.worldsim.config import (
    BailoutMode,
    WorldConfig,
    connected,
    extended,
    scenario,
)

CALIBRATED_SCENARIOS = ("calibrated", "calibrated_full", "calibrated_connected", "calibrated_banks")

ESTIMATES: dict[str, Any] = {
    "transition": [
        [0.951089, 0.048911, 0.0],
        [0.015317, 0.972845, 0.011838],
        [0.0, 0.080014, 0.919986],
    ],
    "equity_mu": [0.011013768, 0.00779447597, -0.00836253816],
    "equity_sigma": [0.0229020711, 0.0436722313, 0.119388271],
    "macro": {
        "output_persistence": 0.854416519,
        "inflation_persistence": 0.978969281,
        "phillips_slope": 0.0106917238,
        "inflation_vol": 0.617288108,
        "taylor_phi_pi": 1.30567742,
        "taylor_phi_y": 0.414711946,
        "rate_smoothing": 0.951299644,
        "inflation_target": 3.76350205,
        "neutral_real_rate": 1.12355211,
    },
    "regime_output_vol": [0.494637517, 0.692492524, 1.18713004],
    "regime_output_shift": [0.0, -0.150410745, -1.20328596],
    "okun": 0.403939494,
    "base_unemployment": 5.95231176,
    "loan_growth_base": 0.00465120697,
    "loan_growth_slope": 0.000777849887,
}

BANK_ESTIMATES: dict[str, float] = {
    "loans": 60.762311515354355,
    "securities": 20.91880179198835,
    "cash": 8.318886692657301,
    "deposit_funding": 72.96043048887132,
    "net_interest_margin": 0.0007795010144510306,
    "base_default_rate": 0.0011160128179361836,
    "default_sensitivity": 0.07844668334308015,
    "payout_ratio": 0.9496832703752298,
    "loan_growth_base": 0.009994100324598736,
    "loan_growth_slope": 6.122338496231321e-06,
}
"""The bank block of the first run of Finding 29 (`docs/numerics/worldsim_bank_study.json`, the
final fit on the FDIC's 1985-2022 annual totals); a test pins these to the record. Three of them lie
at or next to a bound of the search (payout, base loan growth, its slope): the data did not pin
them, which the record and Finding 29 say. Revision 2 of that study, which changed the model's
structure, did worse and is not used."""


def calibrated_config() -> WorldConfig:
    """The `volatile` world with the estimated parameters (240 months, every extension off)."""
    base = scenario("volatile")
    e = ESTIMATES
    mu = base.market.mu.copy()
    mu[:, 0] = e["equity_mu"]
    sigma = base.market.sigma.copy()
    sigma[:, 0] = e["equity_sigma"]
    macro = replace(
        base.macro,
        **e["macro"],
        regime_output_vol=tuple(e["regime_output_vol"]),
        regime_output_shift=tuple(e["regime_output_shift"]),
    )
    return replace(
        base,
        name="calibrated",
        transition=np.array(e["transition"], dtype=np.float64),
        market=replace(base.market, mu=mu, sigma=sigma),
        macro=macro,
        households=replace(
            base.households, okun=e["okun"], base_unemployment=e["base_unemployment"]
        ),
        banks=replace(
            base.banks,
            loan_growth_base=e["loan_growth_base"],
            loan_growth_slope=e["loan_growth_slope"],
        ),
    )


def calibrated_banks_config() -> WorldConfig:
    """`calibrated_config` with the bank block estimated from FDIC data (Finding 29, first run):
    the opening balance sheet, the net interest margin, the default rate and its sensitivity, a
    dividend payout and the loan-growth parameters. Loss given default (0.5), the capital trigger,
    the fire-sale fraction, the securities' equity share and the interbank network keep their
    chosen values."""
    base = calibrated_config()
    changes: dict[str, Any] = dict(BANK_ESTIMATES)
    return replace(base, name="calibrated_banks", banks=replace(base.banks, **changes))


def calibrated_scenario(name: str, *, mode: BailoutMode = "none") -> WorldConfig:
    """`calibrated` (the plain world), `calibrated_full` (firms, government, foreign sector,
    unequal households), `calibrated_connected` (all of it with the feedback loops on) or
    `calibrated_banks` (the plain world with the bank block estimated from FDIC data).

    There is no full or connected version of `calibrated_banks` on purpose: with the extensions on,
    firm distress multiplies the banks' default rate, and banks with real-sized capital lose every
    bank in 88% of 20-year paths (33% with the chosen banks; see
    `docs/numerics/worldsim_bank_collapse.json`), a world no real banking system resembles."""
    base = calibrated_config()
    if name == "calibrated":
        return base
    if name == "calibrated_banks":
        return calibrated_banks_config()
    if name == "calibrated_full":
        return replace(extended(base, mode=mode), name="calibrated_full")
    if name == "calibrated_connected":
        return replace(connected(base, mode=mode), name="calibrated_connected")
    raise ValueError(f"unknown calibrated scenario {name!r}; choose from {CALIBRATED_SCENARIOS}")
