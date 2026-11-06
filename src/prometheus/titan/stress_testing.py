"""Deterministic stress scenario testing (RISK-10, OPT-11): apply a named,
specified shock -- either to a set of common factors (composed with
`titan.factor_model`'s betas) or directly to asset returns -- to a
portfolio's weights, and report the resulting loss.

Sign convention, shared with `titan.risk_metrics`: a *loss* is positive
when money is lost. A stress scenario's "shock" is expressed in RETURN
space (the move a factor or an asset's return takes under the scenario);
the portfolio's stressed loss is the negative of its resulting return.

This is scenario-specified, not scenario-discovered: no historical crisis
is hard-coded here, and no scenario is calibrated from real market data --
callers supply their own `StressScenario` definitions (synthetic,
historical-return-derived, or regulatory). `historical_scenario_losses`
is the one exception that touches real data shape: given any historical
(or simulated) returns matrix, it replays every row as its own scenario
against today's weights, which is the standard "stress = reapply a past
period's realized moves to the current book" technique -- still with no
built-in opinion about which period is a "crisis."

`run_stress_tests` composes scenario results with an externally supplied
VaR threshold (e.g. from `titan.risk_metrics.historical_var`) to flag
whether any scenario's loss exceeds the model's own VaR estimate -- the
classic "stress test breaches VaR" red flag, reported here rather than
silently left for the caller to notice.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class StressScenario:
    """Exactly one of `factor_shocks` or `asset_return_shocks` must be
    supplied: a factor-shock scenario is composed with a factor model's
    betas (see `stress_scenario_loss_from_factor_shock`); an asset-shock
    scenario applies directly to portfolio weights."""

    name: str
    factor_shocks: np.ndarray | None = None
    asset_return_shocks: np.ndarray | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("scenario name must be non-empty text")
        if (self.factor_shocks is None) == (self.asset_return_shocks is None):
            raise ValueError(
                "exactly one of factor_shocks or asset_return_shocks must be provided"
            )


def stress_scenario_loss_from_factor_shock(
    weights: np.ndarray, betas: np.ndarray, factor_shocks: np.ndarray
) -> float:
    """Loss under a factor-space shock: exposure = weights @ betas, and the
    portfolio's stressed return is exposure . factor_shocks (idiosyncratic
    risk is not represented in a deterministic shock scenario -- it has no
    realized value to assign, unlike the variance decomposition in
    `titan.factor_model.decompose_portfolio_variance`)."""
    weights = np.asarray(weights, dtype=float)
    betas = np.asarray(betas, dtype=float)
    factor_shocks = np.asarray(factor_shocks, dtype=float)
    n_assets, n_factors = betas.shape
    if weights.shape != (n_assets,):
        raise ValueError(f"weights must have shape ({n_assets},), got {weights.shape}")
    if factor_shocks.shape != (n_factors,):
        raise ValueError(f"factor_shocks must have shape ({n_factors},), got {factor_shocks.shape}")
    exposure = weights @ betas
    stressed_return = float(exposure @ factor_shocks)
    return -stressed_return


def stress_scenario_factor_attribution(
    weights: np.ndarray, betas: np.ndarray, factor_shocks: np.ndarray
) -> np.ndarray:
    """Per-factor loss contribution under a factor-space shock scenario:
    `contributions[f] = -(exposure[f] * factor_shocks[f])`, which sums
    exactly to `stress_scenario_loss_from_factor_shock`'s total (the
    exposure . factor_shocks dot product is linear, so it splits term by
    term with no approximation, unlike the Euler risk-contribution formula
    `titan.factor_model` uses for variance)."""
    weights = np.asarray(weights, dtype=float)
    betas = np.asarray(betas, dtype=float)
    factor_shocks = np.asarray(factor_shocks, dtype=float)
    n_assets, n_factors = betas.shape
    if weights.shape != (n_assets,):
        raise ValueError(f"weights must have shape ({n_assets},), got {weights.shape}")
    if factor_shocks.shape != (n_factors,):
        raise ValueError(f"factor_shocks must have shape ({n_factors},), got {factor_shocks.shape}")
    exposure = weights @ betas
    contributions: np.ndarray = -(exposure * factor_shocks)
    return contributions


def stress_scenario_loss_from_asset_shock(
    weights: np.ndarray, asset_return_shocks: np.ndarray
) -> float:
    """Loss under a direct per-asset return shock."""
    weights = np.asarray(weights, dtype=float)
    asset_return_shocks = np.asarray(asset_return_shocks, dtype=float)
    if weights.shape != asset_return_shocks.shape:
        raise ValueError(
            f"weights and asset_return_shocks must have the same shape, "
            f"got {weights.shape} and {asset_return_shocks.shape}"
        )
    return -float(weights @ asset_return_shocks)


def historical_scenario_losses(returns: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Replay every row of a historical (or simulated) returns matrix as
    its own asset-shock scenario against today's `weights`: the standard
    "reapply a past period's realized moves to the current book"
    technique. Returns one loss per row, in the same positive-loss-on-money-lost
    convention as `titan.risk_metrics` -- feed the result directly to
    `historical_var`/`historical_expected_shortfall` for a stress-implied
    VaR/ES estimate."""
    returns = np.asarray(returns, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if returns.ndim != 2:
        raise ValueError("returns must be 2-D (n_scenarios, n_assets)")
    n_assets = returns.shape[1]
    if weights.shape != (n_assets,):
        raise ValueError(f"weights must have shape ({n_assets},), got {weights.shape}")
    losses: np.ndarray = -(returns @ weights)
    return losses


def _scenario_loss(
    scenario: StressScenario, weights: np.ndarray, betas: np.ndarray | None
) -> float:
    if scenario.factor_shocks is not None:
        if betas is None:
            raise ValueError(
                f"scenario {scenario.name!r} is factor-based but no betas were supplied"
            )
        return stress_scenario_loss_from_factor_shock(weights, betas, scenario.factor_shocks)
    assert scenario.asset_return_shocks is not None  # enforced by StressScenario.__post_init__
    return stress_scenario_loss_from_asset_shock(weights, scenario.asset_return_shocks)


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    loss: float


@dataclass(frozen=True, slots=True)
class StressTestReport:
    scenario_results: tuple[ScenarioResult, ...]
    worst_case: ScenarioResult
    value_at_risk_threshold: float
    worst_case_exceeds_var: bool


def run_stress_tests(
    weights: np.ndarray,
    scenarios: list[StressScenario],
    betas: np.ndarray | None = None,
    value_at_risk_threshold: float = 0.0,
) -> StressTestReport:
    """Evaluate every scenario against one fixed set of portfolio
    `weights`, rank by loss, and flag whether the worst scenario's loss
    exceeds an externally supplied VaR threshold (e.g. from
    `titan.risk_metrics.historical_var`) -- the classic "stress test
    breaches VaR" check, reported rather than left for the caller to
    compute by hand."""
    if not scenarios:
        raise ValueError("at least one scenario is required")
    if value_at_risk_threshold < 0:
        raise ValueError("value_at_risk_threshold must be non-negative")
    results = tuple(
        ScenarioResult(scenario.name, _scenario_loss(scenario, weights, betas))
        for scenario in scenarios
    )
    worst_case = max(results, key=lambda result: result.loss)
    return StressTestReport(
        scenario_results=results,
        worst_case=worst_case,
        value_at_risk_threshold=value_at_risk_threshold,
        worst_case_exceeds_var=worst_case.loss > value_at_risk_threshold,
    )
