"""Mapping a policy-rate path into macro-conditioned market simulation.

This is a simplified, explicitly non-neural v0 of STOCHASTICA's Tier 3
("macro conditioned ... neural SDE with macroeconomic state and publishing
lag"): the market's drift over each macro sub-period is set directly from
that period's already-realized policy rate plus a fixed equity risk
premium, chained via stochastica.gbm.simulate_piecewise_drift_gbm_paths.
Causality (no leakage from a future policy decision into an earlier
period's returns) follows from `policy_rate_path` itself being built
causally (econosim.policy_rate.simulate_policy_rate_path) and from the
piecewise-drift simulator drawing its random shocks period by period in
chronological order; both properties are tested explicitly in this
repository's test suite, not merely asserted here.
"""

from __future__ import annotations

import numpy as np

from prometheus.stochastica.gbm import simulate_piecewise_drift_gbm_paths


def simulate_policy_rate_conditioned_market(
    s0: float,
    policy_rate_path: list[float],
    equity_risk_premium: float,
    volatility: float,
    dt: float,
    n_paths: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """`policy_rate_path[t]` is the rate already known at the start of
    macro period t and applies as that period's market drift (plus
    equity_risk_premium). The path must have at least 2 points: an initial
    rate plus at least one subsequent step. The final entry is the rate
    known at the end of the simulated horizon and is not itself used as a
    period's drift -- there is no period after it in this path."""
    if len(policy_rate_path) < 2:
        raise ValueError("policy_rate_path must have at least 2 points (>= 1 simulated period)")
    mu_path = [rate + equity_risk_premium for rate in policy_rate_path[:-1]]
    return simulate_piecewise_drift_gbm_paths(s0, mu_path, volatility, dt, n_paths, rng)
