"""Estimating WORLDSIM's parameters from real data instead of choosing them.

Three stages, each as simple as it can be and no simpler:

1. Direct estimates where a parameter maps cleanly onto data: a three-state Gaussian hidden Markov
   model of monthly S&P 500 returns gives the regime transition matrix and each regime's mean and
   volatility of equity returns; a regression of the quarterly change in unemployment on real GDP
   growth gives Okun's coefficient; sample means give the inflation target, the neutral real rate
   and the natural unemployment rate.
2. Indirect inference for the macro block (persistence, the Phillips slope, the Taylor rule, the
   size and shift of the output shocks): simulate the world, compute the same summary statistics
   on the simulation as on the data (`macro_moments`), and move the parameters until the two agree,
   weighting every statistic by the sampling error of its real value (a block bootstrap).
3. The same for the bank-lending parameters, against bank-credit growth.

Parameters with no usable data here (bond and real-asset returns, bank loss rates, the fiscal and
foreign-sector blocks, household wealth) keep their chosen values and are listed as such. This
module is pure NumPy and knows nothing about files; `orchestration.worldsim_calibration_study`
loads the data and runs the stages.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

from prometheus.worldsim.config import CRISIS, WorldConfig
from prometheus.worldsim.world import WorldPath

HP_LAMBDA_MONTHLY = 129_600.0
BURN_IN = 24

MACRO_MOMENTS: tuple[str, ...] = (
    "ugap_sd",
    "ugap_ar1",
    "ugap_skew",
    "dunemployment_sd",
    "infl_sd",
    "infl_ar1",
    "ff_sd",
    "ff_ar1",
    "taylor_rho",
    "taylor_inflation",
    "taylor_ugap",
    "phillips_ugap",
)
EQUITY_MOMENTS: tuple[str, ...] = ("eq_mean_ann", "eq_vol_ann", "eq_skew", "eq_exkurt")
CREDIT_MOMENTS: tuple[str, ...] = ("credit_mean", "credit_sd", "credit_corr_ugap")
UNTARGETED_MOMENTS: tuple[str, ...] = (
    "eq_abs_acf1",
    "eq_worst_month",
    "ugap_p95",
    "ugap_exkurt",
    "eq12_ugap_corr",
    "ff_change_sd",
    "infl_skew",
)


# --------------------------------------------------------------------------- hidden Markov model


@dataclass(frozen=True, slots=True)
class HmmFit:
    """A fitted Gaussian hidden Markov model, states sorted by volatility (low to high)."""

    mean: np.ndarray
    sigma: np.ndarray
    transition: np.ndarray
    log_likelihood: float
    share: np.ndarray  # share of months in each state, from the smoothed probabilities
    converged: bool


def _emission(x: np.ndarray, mean: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    z = (x[:, None] - mean[None, :]) / sigma[None, :]
    density: np.ndarray = np.exp(-0.5 * z * z) / (sigma[None, :] * np.sqrt(2.0 * np.pi))
    floored: np.ndarray = np.maximum(density, 1e-300)
    return floored


def _forward_backward(
    emission: np.ndarray, transition: np.ndarray, start: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    n, k = emission.shape
    alpha = np.zeros((n, k))
    scale = np.zeros(n)
    alpha[0] = start * emission[0]
    scale[0] = alpha[0].sum()
    alpha[0] /= scale[0]
    for t in range(1, n):
        alpha[t] = (alpha[t - 1] @ transition) * emission[t]
        scale[t] = alpha[t].sum()
        alpha[t] /= scale[t]
    beta = np.ones((n, k))
    for t in range(n - 2, -1, -1):
        beta[t] = transition @ (emission[t + 1] * beta[t + 1]) / scale[t + 1]
    gamma = alpha * beta
    gamma /= gamma.sum(axis=1, keepdims=True)
    xi = np.zeros((k, k))
    for t in range(n - 1):
        step = alpha[t][:, None] * transition * (emission[t + 1] * beta[t + 1])[None, :]
        xi += step / step.sum()
    return gamma, xi, float(np.log(scale).sum())


def fit_gaussian_hmm(
    x: np.ndarray,
    n_states: int = 3,
    *,
    n_starts: int = 12,
    iterations: int = 300,
    tolerance: float = 1e-8,
    seed: int = 0,
) -> HmmFit:
    """Maximum-likelihood fit by EM from several starts; the best log likelihood wins."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 1 or x.size < 60:
        raise ValueError("a hidden Markov fit needs a 1-D series of at least 60 observations")
    rng = np.random.default_rng(seed)
    best: HmmFit | None = None
    spread = float(np.std(x))
    for start in range(n_starts):
        scale = np.sort(spread * np.exp(rng.uniform(-0.7, 0.9, size=n_states)))
        mean = float(np.mean(x)) + rng.normal(0.0, 0.3 * spread, size=n_states) * (start > 0)
        mean_arr = np.asarray(mean, dtype=np.float64) * np.ones(n_states)
        sigma = scale.copy()
        stay = rng.uniform(0.80, 0.97, size=n_states)
        transition = np.full((n_states, n_states), 0.0)
        for i in range(n_states):
            transition[i] = (1.0 - stay[i]) / (n_states - 1)
            transition[i, i] = stay[i]
        initial = np.full(n_states, 1.0 / n_states)
        previous = -np.inf
        converged = False
        gamma = np.full((x.size, n_states), 1.0 / n_states)
        loglik = -np.inf
        for _ in range(iterations):
            gamma, xi, loglik = _forward_backward(
                _emission(x, mean_arr, sigma), transition, initial
            )
            weight = gamma.sum(axis=0)
            mean_arr = (gamma * x[:, None]).sum(axis=0) / weight
            variance = (gamma * (x[:, None] - mean_arr[None, :]) ** 2).sum(axis=0) / weight
            sigma = np.maximum(np.sqrt(variance), 1e-3)
            transition = xi / xi.sum(axis=1, keepdims=True)
            initial = gamma[0]
            if abs(loglik - previous) < tolerance:
                converged = True
                break
            previous = loglik
        order = np.argsort(sigma)
        candidate = HmmFit(
            mean=mean_arr[order],
            sigma=sigma[order],
            transition=transition[np.ix_(order, order)],
            log_likelihood=loglik,
            share=gamma.mean(axis=0)[order],
            converged=converged,
        )
        if best is None or candidate.log_likelihood > best.log_likelihood:
            best = candidate
    if best is None:
        raise ValueError("no start produced a fit")
    return best


# --------------------------------------------------------------------------- filters and moments


def hp_gap(series: np.ndarray, smoothing: float = HP_LAMBDA_MONTHLY) -> np.ndarray:
    """The cycle of a Hodrick-Prescott filter (the series minus its smooth trend)."""
    y = np.asarray(series, dtype=np.float64)
    n = y.size
    if n < 8:
        raise ValueError("the HP filter needs at least 8 observations")
    rows = sparse.diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(n - 2, n), format="csc")
    system = sparse.identity(n, format="csc") + smoothing * (rows.T @ rows)
    trend = np.asarray(spsolve(system.tocsc(), y), dtype=np.float64)
    gap: np.ndarray = y - trend
    return gap


def _ar1(x: np.ndarray) -> float:
    a, b = x[:-1] - x[:-1].mean(), x[1:] - x[1:].mean()
    return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))


def _skew(x: np.ndarray) -> float:
    d = x - x.mean()
    return float((d**3).mean() / (d**2).mean() ** 1.5)


def _excess_kurtosis(x: np.ndarray) -> float:
    d = x - x.mean()
    return float((d**4).mean() / (d**2).mean() ** 2 - 3.0)


def _ols(y: np.ndarray, columns: list[np.ndarray]) -> np.ndarray:
    design = np.column_stack([np.ones(y.size), *columns])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    return np.asarray(coefficients, dtype=np.float64)


def build_table(
    unemployment: np.ndarray,
    inflation_yoy: np.ndarray,
    fed_funds: np.ndarray,
    equity_returns: np.ndarray,
    credit_yoy: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """One row per month (from the 13th on, so every lag and twelve-month sum exists) holding what
    every moment needs. Bootstrapping rows keeps each month's current and lagged values together,
    which resampling the raw series in blocks would not at the seams."""
    u = np.asarray(unemployment, dtype=np.float64)
    pi = np.asarray(inflation_yoy, dtype=np.float64)
    ff = np.asarray(fed_funds, dtype=np.float64)
    r = np.asarray(equity_returns, dtype=np.float64)
    n = u.size
    if not (pi.size == ff.size == r.size == n):
        raise ValueError("every series must have the same number of months")
    gap = hp_gap(u)
    cumulative = np.cumsum(np.log1p(np.clip(r, -0.99, None)))
    twelve = np.full(n, np.nan)
    twelve[12:] = cumulative[12:] - cumulative[:-12]
    rows = slice(12, n)
    previous = slice(11, n - 1)
    credit = (
        np.full(n - 12, np.nan)
        if credit_yoy is None
        else np.asarray(credit_yoy, dtype=np.float64)[rows]
    )
    return {
        "gap": gap[rows],
        "gap_lag": gap[previous],
        "u": u[rows],
        "du": u[rows] - u[previous],
        "pi": pi[rows],
        "pi_lag": pi[previous],
        "ff": ff[rows],
        "ff_lag": ff[previous],
        "dff": ff[rows] - ff[previous],
        "r": r[rows],
        "r_lag": r[previous],
        "r12": twelve[rows],
        "credit": credit,
    }


def _take(table: dict[str, np.ndarray], index: np.ndarray | None) -> dict[str, np.ndarray]:
    return table if index is None else {k: v[index] for k, v in table.items()}


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def macro_moments(
    table: dict[str, np.ndarray], index: np.ndarray | None = None
) -> dict[str, float]:
    """The twelve macro statistics used for indirect inference. `ugap` is the HP cycle of
    unemployment; `taylor_*` are the coefficients of
    `ff_t = c + rho * ff_{t-1} + b_pi * inflation_t + b_u * ugap_t`; `phillips_ugap` is the
    coefficient on the lagged gap in `inflation_t = c + a * inflation_{t-1} + b * ugap_{t-1}`."""
    t = _take(table, index)
    taylor = _ols(t["ff"], [t["ff_lag"], t["pi"], t["gap"]])
    phillips = _ols(t["pi"], [t["pi_lag"], t["gap_lag"]])
    return {
        "ugap_sd": float(t["gap"].std()),
        "ugap_ar1": _corr(t["gap"], t["gap_lag"]),
        "ugap_skew": _skew(t["gap"]),
        "dunemployment_sd": float(t["du"].std()),
        "infl_sd": float(t["pi"].std()),
        "infl_ar1": _corr(t["pi"], t["pi_lag"]),
        "ff_sd": float(t["ff"].std()),
        "ff_ar1": _corr(t["ff"], t["ff_lag"]),
        "taylor_rho": float(taylor[1]),
        "taylor_inflation": float(taylor[2]),
        "taylor_ugap": float(taylor[3]),
        "phillips_ugap": float(phillips[2]),
    }


def equity_moments(
    table: dict[str, np.ndarray], index: np.ndarray | None = None
) -> dict[str, float]:
    r = _take(table, index)["r"]
    return {
        "eq_mean_ann": float(12.0 * r.mean()),
        "eq_vol_ann": float(np.sqrt(12.0) * r.std()),
        "eq_skew": _skew(r),
        "eq_exkurt": _excess_kurtosis(r),
    }


def credit_moments(
    table: dict[str, np.ndarray], index: np.ndarray | None = None
) -> dict[str, float]:
    t = _take(table, index)
    keep = np.isfinite(t["credit"])
    if keep.sum() < 24:
        raise ValueError("too few months with bank-credit data")
    c, gap = t["credit"][keep], t["gap"][keep]
    return {
        "credit_mean": float(c.mean()),
        "credit_sd": float(c.std()),
        "credit_corr_ugap": _corr(c, gap),
    }


def untargeted_moments(
    table: dict[str, np.ndarray], index: np.ndarray | None = None
) -> dict[str, float]:
    """Statistics no estimation stage was asked to match."""
    t = _take(table, index)
    absolute, lagged = np.abs(t["r"]), np.abs(t["r_lag"])
    return {
        "eq_abs_acf1": _corr(absolute, lagged),
        "eq_worst_month": float(t["r"].min()),
        "ugap_p95": float(np.percentile(t["gap"], 95)),
        "ugap_exkurt": _excess_kurtosis(t["gap"]),
        "eq12_ugap_corr": _corr(t["r12"], t["gap"]),
        "ff_change_sd": float(t["dff"].std()),
        "infl_skew": _skew(t["pi"]),
    }


def all_moments(table: dict[str, np.ndarray], index: np.ndarray | None = None) -> dict[str, float]:
    moments = macro_moments(table, index)
    moments.update(equity_moments(table, index))
    moments.update(untargeted_moments(table, index))
    try:
        moments.update(credit_moments(table, index))
    except ValueError:
        pass
    return moments


QUARTERLY_SMOOTHING = 1600.0


def quarterly_output_gap(annualised_growth: np.ndarray) -> np.ndarray:
    """The output gap (percent) from quarterly real GDP growth at annual rates: cumulate the growth
    into a log level and take the cycle of a Hodrick-Prescott filter (smoothing 1600)."""
    level = np.cumsum(np.asarray(annualised_growth, dtype=np.float64) / 4.0)
    return hp_gap(level, QUARTERLY_SMOOTHING)


def okun_gap_coefficient(unemployment_gap: np.ndarray, output_gap: np.ndarray) -> float:
    """Okun's coefficient in the model's own units (`unemployment = base - okun * output_gap`):
    minus the slope of the quarterly unemployment gap on the output gap."""
    slope = float(_ols(np.asarray(unemployment_gap), [np.asarray(output_gap)])[1])
    return -slope


def output_gap_sd(monthly_output_gap: np.ndarray) -> float:
    """Standard deviation of a simulated output gap seen the way the real one is: sampled once a
    quarter and passed through the same quarterly filter (the model's output has no trend, so its
    level is the gap itself)."""
    quarterly = np.asarray(monthly_output_gap, dtype=np.float64)[2::3]
    return float(hp_gap(quarterly, QUARTERLY_SMOOTHING).std())


def yoy_from_price_level(price_level: np.ndarray) -> np.ndarray:
    """Twelve-month inflation (percent) from a price-level index; the first 12 entries are NaN."""
    p = np.asarray(price_level, dtype=np.float64)
    out = np.full(p.size, np.nan)
    out[12:] = 100.0 * (p[12:] / p[:-12] - 1.0)
    return out


def credit_yoy_from_loans(total_loans: np.ndarray) -> np.ndarray:
    loans = np.asarray(total_loans, dtype=np.float64)
    out = np.full(loans.size, np.nan)
    out[12:] = 100.0 * (loans[12:] / np.maximum(loans[:-12], 1e-9) - 1.0)
    return out


def simulated_table(path: WorldPath, burn_in: int = BURN_IN) -> dict[str, np.ndarray]:
    """The table of one simulated path after discarding `burn_in` months (at least 12)."""
    start = max(burn_in, 12)
    return build_table(
        path.unemployment[start:],
        yoy_from_price_level(path.price_level)[start:],
        path.policy_rate[start:],
        path.asset_returns[start:, 0],
        credit_yoy_from_loans(path.total_loans)[start:],
    )


def simulated_moments(path: WorldPath, burn_in: int = BURN_IN) -> dict[str, float]:
    """Every moment above, computed on one simulated path."""
    moments = all_moments(simulated_table(path, burn_in))
    moments["ygap_sd"] = output_gap_sd(path.output_gap[max(burn_in, 12) :])
    return moments


def regime_shares(path: WorldPath) -> dict[str, float]:
    return {
        "slowdown": float(np.mean(path.regime == 1)),
        "crisis": float(np.mean(path.regime == CRISIS)),
    }


# --------------------------------------------------------------------------- bootstrap and distance


def block_bootstrap_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Indices of one moving-block resample of a series of length `n`."""
    starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
    index = (starts[:, None] + np.arange(block)[None, :]).ravel()
    return np.asarray(index[:n], dtype=np.int64)


def bootstrap_moments(
    table: dict[str, np.ndarray],
    *,
    replications: int = 200,
    block: int = 24,
    seed: int = 0,
) -> list[dict[str, float]]:
    """All moments on `replications` moving-block resamples of the table's rows; a failed
    resample (a singular regression, say) is skipped."""
    rng = np.random.default_rng(seed)
    n = int(next(iter(table.values())).size)
    results: list[dict[str, float]] = []
    for _ in range(replications):
        indices = block_bootstrap_indices(n, block, rng)
        try:
            value = all_moments(table, indices)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            continue
        if all(np.isfinite(v) for v in value.values()):
            results.append(value)
    return results


def standard_errors(replicates: list[dict[str, float]], names: tuple[str, ...]) -> dict[str, float]:
    return {
        name: max(float(np.std([row[name] for row in replicates], ddof=1)), 1e-9) for name in names
    }


def distance(
    simulated: Mapping[str, float],
    real: Mapping[str, float],
    se: Mapping[str, float],
    names: tuple[str, ...],
) -> float:
    """Sum of squared standardised gaps between simulated and real moments."""
    return float(sum(((simulated[n] - real[n]) / se[n]) ** 2 for n in names))


# --------------------------------------------------------------------------- applying estimates

OKUN_FLOOR = 0.05

MACRO_PARAMETERS: tuple[tuple[str, float, float], ...] = (
    ("output_persistence", 0.50, 0.995),
    ("inflation_persistence", 0.50, 0.995),
    ("phillips_slope", 0.0, 0.60),
    ("inflation_vol", 0.05, 1.50),
    ("taylor_phi_pi", 0.30, 3.50),
    ("taylor_phi_y", 0.0, 3.00),
    ("rate_smoothing", 0.50, 0.99),
    ("output_vol_scale", 0.30, 4.00),
    ("output_shift_scale", 0.0, 5.00),
)
CREDIT_PARAMETERS: tuple[tuple[str, float, float], ...] = (
    ("loan_growth_base", -0.002, 0.01),
    ("loan_growth_slope", 0.0, 0.02),
)


def apply_macro(config: WorldConfig, values: Mapping[str, float]) -> WorldConfig:
    """`config` with the macro-block parameters in `values` replaced (the two scales multiply the
    chosen regime vectors)."""
    macro = config.macro
    changes: dict[str, Any] = {}
    for name in (
        "output_persistence",
        "inflation_persistence",
        "phillips_slope",
        "inflation_vol",
        "taylor_phi_pi",
        "taylor_phi_y",
        "rate_smoothing",
    ):
        if name in values:
            changes[name] = float(values[name])
    if "output_vol_scale" in values:
        scale = float(values["output_vol_scale"])
        changes["regime_output_vol"] = tuple(v * scale for v in macro.regime_output_vol)
    if "output_shift_scale" in values:
        scale = float(values["output_shift_scale"])
        changes["regime_output_shift"] = tuple(v * scale for v in macro.regime_output_shift)
    return replace(config, macro=replace(macro, **changes))


def apply_credit(config: WorldConfig, values: Mapping[str, float]) -> WorldConfig:
    banks = replace(
        config.banks,
        loan_growth_base=float(values.get("loan_growth_base", config.banks.loan_growth_base)),
        loan_growth_slope=float(values.get("loan_growth_slope", config.banks.loan_growth_slope)),
    )
    return replace(config, banks=banks)


def apply_direct(
    config: WorldConfig,
    *,
    hmm: HmmFit,
    okun: float,
    base_unemployment: float,
    inflation_target: float,
    neutral_real_rate: float,
) -> WorldConfig:
    """The stage-1 estimates. The equity mean in each regime is the HMM's mean less the expected
    monthly contribution of the model's own entry jump (jump size over expected spell length), so
    the jump is not counted twice."""
    market = config.market
    mu = market.mu.copy()
    mu[:, 0] = hmm.mean
    sigma = market.sigma.copy()
    sigma[:, 0] = hmm.sigma
    stay = float(hmm.transition[CRISIS, CRISIS])
    spell = 1.0 / max(1.0 - stay, 1e-6)
    mu[CRISIS, 0] = hmm.mean[CRISIS] - market.crisis_jump[0] / spell
    return replace(
        config,
        transition=hmm.transition.copy(),
        market=replace(market, mu=mu, sigma=sigma),
        macro=replace(
            config.macro,
            inflation_target=float(inflation_target),
            neutral_real_rate=float(neutral_real_rate),
        ),
        households=replace(
            config.households,
            okun=float(max(okun, OKUN_FLOOR)),
            base_unemployment=float(base_unemployment),
        ),
    )


def okun_coefficient(delta_unemployment: np.ndarray, annualised_growth: np.ndarray) -> float:
    """Okun's coefficient in the model's units from a quarterly regression: the change in
    unemployment over a quarter on the deviation of annualised real GDP growth from its mean. The
    output gap moves by a quarter of that deviation, so the coefficient is minus four times the
    slope."""
    g = np.asarray(annualised_growth, dtype=np.float64)
    d = np.asarray(delta_unemployment, dtype=np.float64)
    slope = float(_ols(d, [g - g.mean()])[1])
    return float(-4.0 * slope)
