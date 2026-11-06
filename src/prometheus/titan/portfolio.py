"""Portfolio optimization (section 08's TITAN table; OPT-01..OPT-12).

Three formulations, each returning an OptimizationResult that always names
its solver, success flag and termination message (OPT-09: "no infeasible
solution silently labeled optimal"):

  minimum_variance_portfolio           -- global minimum-variance, budget
                                           and box constraints only
  target_return_portfolio              -- Markowitz: minimize variance
                                           subject to a required expected
                                           return (OPT-01)
  cvar_optimal_portfolio               -- Rockafellar-Uryasev scenario CVaR
                                           minimization via linear
                                           programming (OPT-03)

All three accept a shared PortfolioConstraints (budget, per-asset box
bounds -- OPT-02: "max/min weight, leverage and short-sale controls") and
an optional turnover penalty relative to a prior portfolio (OPT-04).
PortfolioConstraints.max_weight_per_asset (OPT-06: "liquidity and
position-capacity constraints") tightens that uniform box bound per
asset, e.g. a participation-limit cap derived from each asset's own
liquidity; the effective bound is always the tighter of the uniform
max_weight and the per-asset cap, never the looser.

Mean-variance solves are cross-checked in tests against their closed-form
analytical solutions (the global minimum-variance portfolio
w* = Sigma^-1 1 / (1' Sigma^-1 1), and the two-fund target-return formula)
to machine precision when box constraints don't bind; the CVaR LP is cross-
checked against a brute-force grid search over a 2-asset case using
titan.risk_metrics.historical_expected_shortfall independently.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import LinearConstraint, linprog, minimize


@dataclass(frozen=True, slots=True)
class PortfolioConstraints:
    """`max_weight_per_asset` (OPT-06: "liquidity and position-capacity
    constraints") is a per-asset cap distinct from the uniform
    `max_weight` -- e.g. a liquidity-implied participation limit (no
    more than X% of an asset's own average daily volume), which is
    naturally different per asset, unlike the single shared `max_weight`
    every asset is otherwise bound by alike. When supplied, asset i's
    effective upper bound is min(max_weight, max_weight_per_asset[i]):
    the tighter of the two always applies, so a cap can only ever
    restrict further, never loosen, the uniform bound."""

    min_weight: float = 0.0
    max_weight: float = 1.0
    budget: float = 1.0
    max_weight_per_asset: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.min_weight > self.max_weight:
            raise ValueError("min_weight must be <= max_weight")
        if self.max_weight_per_asset is not None:
            caps = np.asarray(self.max_weight_per_asset, dtype=float)
            if caps.ndim != 1:
                raise ValueError("max_weight_per_asset must be a 1-D array")
            if np.any(caps < self.min_weight):
                raise ValueError("max_weight_per_asset entries must each be >= min_weight")


_DEFAULT_CONSTRAINTS = PortfolioConstraints()


def _per_asset_bounds(constraints: PortfolioConstraints, n: int) -> list[tuple[float, float]]:
    """The box bounds every optimizer below passes to `scipy.optimize`,
    folding the uniform `max_weight` and the optional per-asset
    `max_weight_per_asset` liquidity caps (OPT-06) into one list -- the
    tighter of the two applies to each asset."""
    if constraints.max_weight_per_asset is None:
        return [(constraints.min_weight, constraints.max_weight)] * n
    caps = np.asarray(constraints.max_weight_per_asset, dtype=float)
    if caps.shape != (n,):
        raise ValueError(
            f"max_weight_per_asset must have shape ({n},), got {caps.shape}"
        )
    return [(constraints.min_weight, min(constraints.max_weight, cap)) for cap in caps]


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """`success` is not an exception-on-failure: a caller may legitimately
    want to inspect a failed/infeasible solve's diagnostics (`.weights` is
    then the solver's last iterate, not a usable allocation). It is the
    caller's responsibility to check `.success` before using `.weights` --
    OPT-09's "no infeasible solution silently labeled optimal" is satisfied
    by always populating `solver`/`status_message` rather than by refusing
    to construct a failed result."""

    weights: np.ndarray
    objective_value: float
    solver: str
    success: bool
    status_message: str
    n_iterations: int


def _turnover_penalty_term(
    weights: np.ndarray, prior_weights: np.ndarray | None, turnover_penalty: float
) -> float:
    if prior_weights is None or turnover_penalty == 0.0:
        return 0.0
    return float(turnover_penalty * np.sum(np.abs(weights - prior_weights)))


def minimum_variance_portfolio(
    covariance: np.ndarray,
    constraints: PortfolioConstraints | None = None,
    prior_weights: np.ndarray | None = None,
    turnover_penalty: float = 0.0,
) -> OptimizationResult:
    constraints = constraints if constraints is not None else _DEFAULT_CONSTRAINTS
    covariance = np.asarray(covariance, dtype=float)
    n = covariance.shape[0]
    if covariance.shape != (n, n):
        raise ValueError("covariance must be a square matrix")
    if turnover_penalty < 0:
        raise ValueError("turnover_penalty must be non-negative")
    if turnover_penalty > 0 and prior_weights is None:
        raise ValueError("prior_weights is required when turnover_penalty > 0")

    x0 = np.full(n, constraints.budget / n)

    def objective(w: np.ndarray) -> float:
        variance = float(w @ covariance @ w)
        return variance + _turnover_penalty_term(w, prior_weights, turnover_penalty)

    def jac(w: np.ndarray) -> np.ndarray:
        result: np.ndarray = 2 * covariance @ w
        return result

    budget_constraint = LinearConstraint(np.ones(n), constraints.budget, constraints.budget)
    bounds = _per_asset_bounds(constraints, n)
    # the turnover penalty's abs() term is not smooth, so the analytic
    # quadratic jacobian is only valid (and only passed) when it is absent;
    # SLSQP falls back to its own finite-difference approximation otherwise
    use_analytic_jac = turnover_penalty == 0.0

    result = minimize(
        objective,
        x0,
        jac=jac if use_analytic_jac else None,
        constraints=[budget_constraint],
        bounds=bounds,
        method="SLSQP",
        options={"ftol": 1e-14, "maxiter": 500},
    )
    return OptimizationResult(
        weights=result.x,
        objective_value=float(result.fun),
        solver="SLSQP",
        success=bool(result.success),
        status_message=str(result.message),
        n_iterations=int(result.nit),
    )


def target_return_portfolio(
    expected_returns: np.ndarray,
    covariance: np.ndarray,
    target_return: float,
    constraints: PortfolioConstraints | None = None,
    prior_weights: np.ndarray | None = None,
    turnover_penalty: float = 0.0,
) -> OptimizationResult:
    """The classic Markowitz formulation: minimize portfolio variance
    (plus an optional turnover penalty) subject to a required expected
    return and the budget/box constraints (OPT-01)."""
    constraints = constraints if constraints is not None else _DEFAULT_CONSTRAINTS
    expected_returns = np.asarray(expected_returns, dtype=float)
    covariance = np.asarray(covariance, dtype=float)
    n = covariance.shape[0]
    if expected_returns.shape != (n,):
        raise ValueError("expected_returns must have shape (n_assets,)")
    if turnover_penalty < 0:
        raise ValueError("turnover_penalty must be non-negative")
    if turnover_penalty > 0 and prior_weights is None:
        raise ValueError("prior_weights is required when turnover_penalty > 0")

    x0 = np.full(n, constraints.budget / n)

    def objective(w: np.ndarray) -> float:
        variance = float(w @ covariance @ w)
        return variance + _turnover_penalty_term(w, prior_weights, turnover_penalty)

    budget_constraint = LinearConstraint(np.ones(n), constraints.budget, constraints.budget)
    return_constraint = LinearConstraint(expected_returns, target_return, target_return)
    bounds = _per_asset_bounds(constraints, n)

    result = minimize(
        objective,
        x0,
        constraints=[budget_constraint, return_constraint],
        bounds=bounds,
        method="SLSQP",
        options={"ftol": 1e-14, "maxiter": 500},
    )
    return OptimizationResult(
        weights=result.x,
        objective_value=float(result.fun),
        solver="SLSQP",
        success=bool(result.success),
        status_message=str(result.message),
        n_iterations=int(result.nit),
    )


@dataclass(frozen=True, slots=True)
class CVaROptimizationResult(OptimizationResult):
    value_at_risk: float


def cvar_optimal_portfolio(
    scenario_returns: np.ndarray,
    alpha: float,
    constraints: PortfolioConstraints | None = None,
    target_return: float | None = None,
) -> CVaROptimizationResult:
    """Rockafellar-Uryasev (2000) scenario-CVaR minimization, formulated as
    a linear program in (weights, VaR, per-scenario shortfall slacks):

        minimize   VaR + 1/((1-alpha)*S) * sum_s u_s
        subject to u_s >= -(w . r_s) - VaR   for every scenario s
                   u_s >= 0
                   sum(w) = budget
                   min_weight <= w_i <= max_weight
                   (optional) w . mean(r) >= target_return

    `scenario_returns` has shape (n_scenarios, n_assets); each row is one
    scenario's realized (not necessarily risk-neutral) asset returns.
    """
    constraints = constraints if constraints is not None else _DEFAULT_CONSTRAINTS
    scenario_returns = np.asarray(scenario_returns, dtype=float)
    if scenario_returns.ndim != 2:
        raise ValueError("scenario_returns must be 2-D (n_scenarios, n_assets)")
    n_scenarios, n_assets = scenario_returns.shape
    if n_scenarios < 1:
        raise ValueError("scenario_returns must have at least one scenario")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")

    n_vars = n_assets + 1 + n_scenarios  # [weights, VaR, u_1..u_S]
    cost = np.zeros(n_vars)
    cost[n_assets] = 1.0
    cost[n_assets + 1 :] = 1.0 / ((1.0 - alpha) * n_scenarios)

    # u_s + w.r_s + VaR >= 0  <=>  -w.r_s - VaR - u_s <= 0
    a_ub = np.zeros((n_scenarios, n_vars))
    a_ub[:, :n_assets] = -scenario_returns
    a_ub[:, n_assets] = -1.0
    a_ub[np.arange(n_scenarios), n_assets + 1 + np.arange(n_scenarios)] = -1.0
    b_ub = np.zeros(n_scenarios)

    a_eq = np.zeros((1, n_vars))
    a_eq[0, :n_assets] = 1.0
    b_eq = [constraints.budget]

    if target_return is not None:
        mean_returns = scenario_returns.mean(axis=0)
        target_row = np.zeros((1, n_vars))
        target_row[0, :n_assets] = -mean_returns
        a_ub = np.vstack([a_ub, target_row])
        b_ub = np.concatenate([b_ub, [-target_return]])

    bounds = (
        _per_asset_bounds(constraints, n_assets)
        + [(None, None)]
        + [(0.0, None)] * n_scenarios
    )

    result = linprog(
        cost, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs"
    )

    weights = result.x[:n_assets] if result.x is not None else np.full(n_assets, np.nan)
    value_at_risk = float(result.x[n_assets]) if result.x is not None else float("nan")
    objective_value = float(result.fun) if result.fun is not None else float("nan")
    n_iterations = int(result.nit) if result.nit is not None else -1
    return CVaROptimizationResult(
        weights=weights,
        objective_value=objective_value,
        solver="HiGHS (scipy.optimize.linprog)",
        success=bool(result.success),
        status_message=str(result.message),
        n_iterations=n_iterations,
        value_at_risk=value_at_risk,
    )
