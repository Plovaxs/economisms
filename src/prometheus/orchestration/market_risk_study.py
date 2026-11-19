"""Real-return evaluation of the market-risk models on the S&P 500 (PR-199).

Until now every financial-risk module in this repository ran on SIMULATED returns
(GBM, Heston, jump-diffusion, a GARCH benchmark). This study scores one-day-ahead
Value-at-Risk and volatility forecasts on 93 years of REAL daily S&P 500 returns
(`data_ingestion.kaggle_sp500`, 23,322 returns, 1927-12 .. 2020-11), strictly
chronologically:

- train       returns dated before 2000-01-01   (fits every parameter)
- validation  2000-01 .. 2007-12                (early-stops the neural model, nothing else)
- test        2008-01 onward                    (3,2xx days: the financial crisis and COVID)

Models (each forecasts day t's volatility or quantile from returns up to t-1 only):

- `historical_250`    empirical quantile of the previous 250 returns, via the repository's
                      own `titan.risk_metrics.historical_var`
- `constant_normal`   normal with the training-window standard deviation
- `ewma_094`          RiskMetrics exponentially weighted variance, lambda 0.94
- `garch_normal`      GARCH(1,1) (`neural_sde.benchmark.fit_garch11`) with a normal quantile
- `garch_fhs`         the same GARCH with the empirical quantile of its standardised
                      TRAINING residuals (filtered historical simulation)
- `neural_normal`     a small MLP that maps six past-return features to log volatility,
                      trained by Gaussian negative log-likelihood and early-stopped on the
                      validation split (a neural GARCH)
- `neural_ensemble`   the neural model averaged over seeds in variance space

The "more data" axis is the length of the training history: every fitted model is trained
on the last 10 years, the last 30 years, or all of the pre-2000 history, so the study
measures whether 70 more years of returns help.

Backtests: exceedance rate, Kupiec's proportion-of-failures test, Christoffersen's
independence test and their conditional-coverage combination, at 99% and 97.5%; and the
QLIKE loss of the volatility forecast against the squared-return proxy, with a moving-block
bootstrap for paired differences. The GARCH fit caps alpha + beta at 0.98 (a
stationarity headroom of `fit_garch11`), which understates the near-unit persistence of
equity volatility -- a disclosed limitation, not a tuned choice.

A standalone research CLI: no network call, all data committed.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import torch
from scipy import stats
from scipy.special import xlogy
from torch import nn

from prometheus.data_ingestion.kaggle_sp500 import load_sp500_closes, log_returns
from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.neural_sde.benchmark import fit_garch11
from prometheus.titan.risk_metrics import historical_var, quantile_score

DATA_PATH = Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_sp500_daily_close.csv"
TRAIN_END = date(2000, 1, 1)
VALIDATION_END = date(2008, 1, 1)
HISTORY_STARTS: dict[str, date | None] = {
    "10y": date(1990, 1, 1),
    "30y": date(1970, 1, 1),
    "all": None,
}
ALPHAS = (0.99, 0.975)
HS_WINDOW = 250
EWMA_LAMBDA = 0.94
LOOKBACK = 66
BLOCK_LENGTH = 22
N_FEATURES = 6


# ------------------------------------------------------------------------------ statistics


def kupiec_pof(n_hits: int, n: int, p: float) -> tuple[float, float]:
    """Kupiec's proportion-of-failures likelihood-ratio statistic and its chi-square(1)
    p-value for `n_hits` exceedances in `n` days at nominal exceedance probability `p`."""
    if not 0 < p < 1 or not 0 <= n_hits <= n or n < 1:
        raise ValueError("need 0 < p < 1 and 0 <= n_hits <= n")
    observed = n_hits / n
    log_null = xlogy(n - n_hits, 1 - p) + xlogy(n_hits, p)
    log_alt = xlogy(n - n_hits, 1 - observed) + xlogy(n_hits, observed)
    lr = float(max(-2.0 * (log_null - log_alt), 0.0))
    return lr, float(stats.chi2.sf(lr, 1))


def christoffersen_independence(hits: np.ndarray) -> tuple[float, float]:
    """Christoffersen's likelihood-ratio test that exceedances are serially independent
    (first-order Markov alternative), chi-square(1). Returns (0, 1) when the sequence has
    no information (no exceedances, or only exceedances)."""
    h = np.asarray(hits, dtype=int)
    previous, current = h[:-1], h[1:]
    n00 = int(np.sum((previous == 0) & (current == 0)))
    n01 = int(np.sum((previous == 0) & (current == 1)))
    n10 = int(np.sum((previous == 1) & (current == 0)))
    n11 = int(np.sum((previous == 1) & (current == 1)))
    total = n00 + n01 + n10 + n11
    if n01 + n11 == 0 or n00 + n10 == 0 or total == 0:
        return 0.0, 1.0
    pi = (n01 + n11) / total
    pi01 = n01 / (n00 + n01) if n00 + n01 else 0.0
    pi11 = n11 / (n10 + n11) if n10 + n11 else 0.0
    log_null = xlogy(n00 + n10, 1 - pi) + xlogy(n01 + n11, pi)
    log_alt = xlogy(n00, 1 - pi01) + xlogy(n01, pi01) + xlogy(n10, 1 - pi11) + xlogy(n11, pi11)
    lr = float(max(-2.0 * (log_null - log_alt), 0.0))
    return lr, float(stats.chi2.sf(lr, 1))


def backtest_var(returns: np.ndarray, thresholds: np.ndarray, alpha: float) -> dict[str, float]:
    """`thresholds[t]` is the return level below which day t counts as an exceedance.
    `pinball_loss_bp` is RISK-09's quantile score (the strictly consistent loss for a
    quantile forecast, in basis points of return); `n_exceedances` etc. are RISK-08-style
    coverage diagnostics extended with the CONDITIONAL tests."""
    hits = (returns < thresholds).astype(int)
    n, n_hits = len(returns), int(hits.sum())
    p = 1.0 - alpha
    lr_pof, p_pof = kupiec_pof(n_hits, n, p)
    lr_ind, p_ind = christoffersen_independence(hits)
    return {
        "n_days": float(n),
        "n_exceedances": float(n_hits),
        "expected_exceedances": n * p,
        "exceedance_rate": n_hits / n,
        "kupiec_p": p_pof,
        "christoffersen_independence_p": p_ind,
        "conditional_coverage_p": float(stats.chi2.sf(lr_pof + lr_ind, 2)),
        "mean_var_pct": float(-np.mean(thresholds) * 100.0),
        "pinball_loss_bp": float(np.mean(quantile_score(-returns, -thresholds, alpha)) * 1e4),
    }


def qlike(returns: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Per-day QLIKE loss of a volatility forecast against the squared-return proxy."""
    variance = np.square(sigma)
    return np.log(variance) + np.square(returns) / variance


# ------------------------------------------------------------------------------ forecasters


def rolling_historical_thresholds(returns: np.ndarray, window: int, alpha: float) -> np.ndarray:
    """Threshold for day t from the `window` returns BEFORE day t (NaN until available)."""
    out = np.full(len(returns), np.nan)
    for t in range(window, len(returns)):
        out[t] = -historical_var(-returns[t - window : t], alpha)
    return out


def ewma_sigma(returns: np.ndarray, decay: float, initial_variance: float) -> np.ndarray:
    """One-step-ahead EWMA volatility: sigma_t uses returns up to t-1."""
    variance = np.empty(len(returns))
    current = initial_variance
    for t in range(len(returns)):
        variance[t] = current
        current = decay * current + (1.0 - decay) * returns[t] ** 2
    return np.sqrt(variance)


def trailing_features(returns: np.ndarray) -> np.ndarray:
    """Row t holds six features built from returns strictly BEFORE day t; rows with fewer
    than `LOOKBACK` past returns are NaN."""
    n = len(returns)
    absolute = np.abs(returns)
    cumulative = np.concatenate([[0.0], np.cumsum(absolute)])
    features = np.full((n, N_FEATURES), np.nan)
    for t in range(LOOKBACK, n):
        features[t, 0] = returns[t - 1]
        features[t, 1] = absolute[t - 1]
        for column, k in ((2, 5), (3, 22), (4, 66)):
            features[t, column] = (cumulative[t] - cumulative[t - k]) / k
        features[t, 5] = min(returns[t - 1], 0.0)
    return features


class NeuralVolatility:
    """A small MLP: standardised past-return features -> log volatility."""

    def __init__(
        self, base_log_sigma: float, mean: np.ndarray, scale: np.ndarray, seed: int
    ) -> None:
        torch.manual_seed(seed)
        self.base = base_log_sigma
        self.mean, self.scale = mean, scale
        self.net = nn.Sequential(
            nn.Linear(N_FEATURES, 16), nn.Tanh(), nn.Linear(16, 16), nn.Tanh(), nn.Linear(16, 1)
        )

    def _tensor(self, x: np.ndarray) -> torch.Tensor:
        return torch.tensor((x - self.mean) / self.scale, dtype=torch.float32)

    def log_sigma(self, x: np.ndarray) -> torch.Tensor:
        out: torch.Tensor = self.base + self.net(self._tensor(x)).squeeze(-1)
        return out

    def nll(self, x: np.ndarray, r: np.ndarray) -> torch.Tensor:
        log_sigma = self.log_sigma(x)
        returns = torch.tensor(r, dtype=torch.float32)
        return torch.mean(log_sigma + 0.5 * returns**2 * torch.exp(-2.0 * log_sigma))

    def sigma(self, x: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            return np.exp(self.log_sigma(x).numpy().astype(np.float64))


def train_neural_volatility(
    train_x: np.ndarray,
    train_r: np.ndarray,
    validation_x: np.ndarray,
    validation_r: np.ndarray,
    *,
    seed: int,
    max_epochs: int = 400,
    patience: int = 25,
) -> NeuralVolatility:
    """Full-batch Adam on the Gaussian negative log-likelihood; the validation split is
    used ONLY to choose the epoch (restoring the best weights)."""
    model = NeuralVolatility(
        float(np.log(train_r.std())), train_x.mean(axis=0), train_x.std(axis=0) + 1e-12, seed
    )
    optimiser = torch.optim.Adam(model.net.parameters(), lr=3e-3)
    best, best_state, stale = math.inf, copy.deepcopy(model.net.state_dict()), 0
    for _ in range(max_epochs):
        optimiser.zero_grad()
        model.nll(train_x, train_r).backward()  # type: ignore[no-untyped-call]
        optimiser.step()
        with torch.no_grad():
            validation_loss = float(model.nll(validation_x, validation_r))
        if validation_loss < best - 1e-7:
            best, best_state, stale = validation_loss, copy.deepcopy(model.net.state_dict()), 0
        else:
            stale += 1
            if stale >= patience:
                break
    model.net.load_state_dict(best_state)
    return model


# ------------------------------------------------------------------------------ the study


def run_study(
    path: Path = DATA_PATH,
    *,
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    max_epochs: int = 400,
    patience: int = 25,
    block_resamples: int = 2000,
) -> dict[str, Any]:
    dates, closes = load_sp500_closes(path)
    returns = log_returns(closes)
    return_dates = dates[1:]
    train_mask = np.array([d < TRAIN_END for d in return_dates])
    validation_mask = np.array([TRAIN_END <= d < VALIDATION_END for d in return_dates])
    test_mask = np.array([d >= VALIDATION_END for d in return_dates])
    test_returns = returns[test_mask]
    features = trailing_features(returns)
    z = {a: float(stats.norm.ppf(1.0 - a)) for a in ALPHAS}

    backtests: dict[str, Any] = {}
    volatility: dict[str, Any] = {}
    sigma_by_model: dict[str, np.ndarray] = {}

    def record(name: str, sigma: np.ndarray | None, thresholds: dict[float, np.ndarray]) -> None:
        backtests[name] = {
            f"alpha_{a}": backtest_var(test_returns, thresholds[a], a) for a in ALPHAS
        }
        if sigma is not None:
            sigma_by_model[name] = sigma
            volatility[name] = {"qlike_mean": float(np.mean(qlike(test_returns, sigma)))}

    hs = {a: rolling_historical_thresholds(returns, HS_WINDOW, a)[test_mask] for a in ALPHAS}
    record("historical_250", None, hs)
    ewma = ewma_sigma(returns, EWMA_LAMBDA, float(returns[train_mask].var()))[test_mask]
    record("ewma_094", ewma, {a: z[a] * ewma for a in ALPHAS})

    for label, start in HISTORY_STARTS.items():
        window = train_mask & np.array([start is None or d >= start for d in return_dates])
        train_r = returns[window]
        constant = np.full(int(test_mask.sum()), float(train_r.std()))
        record(f"constant_normal@{label}", constant, {a: z[a] * constant for a in ALPHAS})

        garch = fit_garch11(train_r)
        sigma_all = np.sqrt(garch.conditional_variances(returns))
        garch_sigma = sigma_all[test_mask]
        record(f"garch_normal@{label}", garch_sigma, {a: z[a] * garch_sigma for a in ALPHAS})
        standardised = (train_r - garch.mu) / sigma_all[window]
        record(
            f"garch_fhs@{label}",
            garch_sigma,
            {a: garch.mu + garch_sigma * float(np.quantile(standardised, 1.0 - a)) for a in ALPHAS},
        )

        usable = ~np.isnan(features[:, 0])
        train_idx = window & usable
        validation_idx = validation_mask & usable
        per_seed: list[np.ndarray] = []
        seed_rows: list[dict[str, Any]] = []
        for seed in seeds:
            model = train_neural_volatility(
                features[train_idx],
                returns[train_idx],
                features[validation_idx],
                returns[validation_idx],
                seed=seed,
                max_epochs=max_epochs,
                patience=patience,
            )
            sigma = model.sigma(features[test_mask])
            per_seed.append(sigma)
            seed_rows.append(
                {f"alpha_{a}": backtest_var(test_returns, z[a] * sigma, a) for a in ALPHAS}
                | {"qlike_mean": float(np.mean(qlike(test_returns, sigma)))}
            )
        backtests[f"neural_normal@{label}"] = {
            "per_seed": seed_rows,
            **{
                f"alpha_{a}": {
                    key: float(np.mean([row[f"alpha_{a}"][key] for row in seed_rows]))
                    for key in seed_rows[0][f"alpha_{a}"]
                }
                for a in ALPHAS
            },
        }
        volatility[f"neural_normal@{label}"] = {
            "qlike_mean": float(np.mean([row["qlike_mean"] for row in seed_rows])),
            "qlike_std_over_seeds": float(np.std([row["qlike_mean"] for row in seed_rows])),
        }
        ensemble = np.sqrt(np.mean(np.square(per_seed), axis=0))
        record(f"neural_ensemble@{label}", ensemble, {a: z[a] * ensemble for a in ALPHAS})

    rng = np.random.default_rng(0)
    pairs = {
        "neural_ensemble_vs_garch_all": ("neural_ensemble@all", "garch_normal@all"),
        "garch_all_vs_10y": ("garch_normal@all", "garch_normal@10y"),
        "neural_ensemble_all_vs_10y": ("neural_ensemble@all", "neural_ensemble@10y"),
    }
    comparisons: dict[str, Any] = {}
    for label, (first, second) in pairs.items():
        difference = qlike(test_returns, sigma_by_model[first]) - qlike(
            test_returns, sigma_by_model[second]
        )
        boot = moving_block_bootstrap(
            np.mean, difference, BLOCK_LENGTH, rng, n_resamples=block_resamples
        )
        verdict = (
            "first_has_lower_qlike"
            if boot.ci_high < 0
            else "first_has_higher_qlike"
            if boot.ci_low > 0
            else "inconclusive"
        )
        comparisons[label] = {
            "first": first,
            "second": second,
            "qlike_difference_first_minus_second": boot.point_estimate,
            "ci_low": boot.ci_low,
            "ci_high": boot.ci_high,
            "verdict": verdict,
        }

    losses = -test_returns
    return {
        "config": {
            "train_end_exclusive": TRAIN_END.isoformat(),
            "validation_end_exclusive": VALIDATION_END.isoformat(),
            "seeds": list(seeds),
            "history_windows": {
                k: (v.isoformat() if v else "all") for k, v in HISTORY_STARTS.items()
            },
            "alphas": list(ALPHAS),
            "block_length_days": BLOCK_LENGTH,
        },
        "data": {
            "n_returns": len(returns),
            "n_train": int(train_mask.sum()),
            "n_validation": int(validation_mask.sum()),
            "n_test": int(test_mask.sum()),
            "test_first_date": next(
                d for d, m in zip(return_dates, test_mask, strict=True) if m
            ).isoformat(),
            "test_last_date": return_dates[-1].isoformat(),
            "test_daily_std_pct": float(test_returns.std() * 100),
            "test_worst_day_pct": float(-losses.max() * 100),
            "train_excess_kurtosis": float(stats.kurtosis(returns[train_mask])),
        },
        "backtests": backtests,
        "volatility": volatility,
        "comparisons": comparisons,
        "caveats": [
            "One market, one 3,2xx-day test period dominated by two crises; a few exceedances "
            "move a rate by several tenths of a percent.",
            "QLIKE uses the squared return as the variance proxy, which is unbiased but noisy; "
            "paired differences use a 22-day moving-block bootstrap.",
            "The GARCH fit caps alpha + beta at 0.98, understating equity-volatility persistence.",
            "Price returns of an index (no dividends); close-to-close only, pre-1983 prices are "
            "closes without an intraday range.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--max-epochs", type=int, default=400)
    parser.add_argument("--patience", type=int, default=25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seeds < 1:
        parser.error("--seeds must be a positive integer")
    report = run_study(
        seeds=list(range(args.seeds)), max_epochs=args.max_epochs, patience=args.patience
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
