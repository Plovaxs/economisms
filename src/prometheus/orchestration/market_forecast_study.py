"""Can anything forecast the S&P 500's daily return, and does a forecast earn money? (PR-222).

The repository forecasts volatility and tail risk (Findings 15, 17, 20) and inflation (Findings
18, 19), but never the level of the market. This study asks the plainest market-forecasting
question on 95 years of real daily S&P 500 returns (committed snapshot, 1927-12 to 2023-05-03, no
network call), strictly chronologically: train before 2000-01-01, validation 2000-2007 (tunes the
ridge penalty and early-stops the network, nothing else), test 2008-01-01 onward (the financial
crisis, COVID, the 2022 bear market).

The four questions and their decision rule were written BEFORE any number below was computed, so a
null result cannot be reframed afterwards:

  M-A Does any return forecast (AR(1), 12-month momentum, ridge on nine past-return features, a
       small neural network) have lower out-of-sample squared error than the expanding historical
       mean?
  M-B Does any of them call the direction of the day more often than "always up"?
  M-C Does volatility management (hold the fraction target_vol / GJR-GARCH forecast, capped at 1,
       cash earning zero, 5 bp per unit of turnover) give a higher Sharpe ratio than buy-and-hold?
  M-D Does going long only when a return forecast is positive (cash otherwise, same cost) give a
       higher Sharpe ratio than buy-and-hold?

Decision rule, for every comparison: a 22-day moving-block bootstrap of the paired mean
difference; SUPPORTED if the whole interval lies on the favourable side of zero, CONTRADICTED if
it lies wholly on the other side, INCONCLUSIVE if it contains zero. A question over the four
forecasting models (M-A, M-B, M-D) uses a Bonferroni-adjusted interval (1 - 0.05 / 4) and is
SUPPORTED if any model is. M-C is one comparison and uses 95%. The efficient-market reading is the
expected result for M-A, M-B and M-D; M-C is the one the literature says can be positive. Whatever
comes out is reported.

This is an EXPLORATORY study on data the repository has read before, not a confirmatory test: the
post-2023-05-03 data and the reserved seeds of the confirmatory protocol are neither read nor
used.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import torch

from prometheus.data_ingestion.kaggle_sp500 import load_sp500_closes, log_returns
from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.titan.garch_family import fit_garch_family

DATA_PATH = (
    Path(__file__).resolve().parents[3] / "data_cache" / "kaggle_sp500_spliced_daily_close.csv"
)
TRAIN_END = date(2000, 1, 1)
TEST_START = date(2008, 1, 1)
WARMUP = 252
BLOCK_LENGTH = 22
COST_PER_UNIT_TURNOVER = 0.0005
N_MODELS = 4
MODEL_NAMES: tuple[str, ...] = ("ar1", "momentum_12m", "ridge", "mlp")
FEATURE_NAMES: tuple[str, ...] = (
    "r_lag1",
    "r_lag2",
    "r_lag3",
    "r_lag4",
    "r_lag5",
    "mean_22d",
    "std_22d",
    "sum_252d",
    "mean_abs_5d",
)
RIDGE_GRID: tuple[float, ...] = (1.0, 10.0, 100.0, 1_000.0, 10_000.0)


def verdict(low: float, high: float) -> str:
    """The pre-written rule: wholly above zero is SUPPORTED, wholly below CONTRADICTED."""
    if low > 0.0:
        return "SUPPORTED"
    if high < 0.0:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def build_features(returns: np.ndarray) -> np.ndarray:
    """Row `i` holds the features for forecasting `returns[i]`; every one of them uses
    `returns[:i]` only. Rows before `WARMUP` are NaN."""
    n = returns.size
    features = np.full((n, len(FEATURE_NAMES)), np.nan)
    for i in range(WARMUP, n):
        past = returns[:i]
        features[i] = (
            past[-1],
            past[-2],
            past[-3],
            past[-4],
            past[-5],
            past[-22:].mean(),
            past[-22:].std(),
            past[-252:].sum(),
            np.abs(past[-5:]).mean(),
        )
    return features


def expanding_mean(returns: np.ndarray) -> np.ndarray:
    """Forecast of `returns[i]` = mean of `returns[:i]` (NaN at i = 0)."""
    cumulative = np.cumsum(returns)
    forecast = np.full(returns.size, np.nan)
    forecast[1:] = cumulative[:-1] / np.arange(1, returns.size)
    return forecast


def _ols(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(x.shape[0]), x])
    solution = np.linalg.lstsq(design, y, rcond=None)[0]
    return np.asarray(solution, dtype=np.float64)


def _predict_linear(coefficients: np.ndarray, x: np.ndarray) -> np.ndarray:
    return np.asarray(coefficients[0] + x @ coefficients[1:], dtype=np.float64)


def _ridge_fit(x: np.ndarray, y: np.ndarray, penalty: float) -> np.ndarray:
    x_mean = x.mean(axis=0)
    y_mean = float(y.mean())
    centred = x - x_mean
    gram = centred.T @ centred + penalty * np.eye(x.shape[1])
    weights = np.linalg.solve(gram, centred.T @ (y - y_mean))
    return np.concatenate([[y_mean - float(x_mean @ weights)], weights])


def _train_mlp(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    seed: int,
    max_epochs: int,
    patience: int = 30,
) -> torch.nn.Module:
    torch.manual_seed(seed)
    net = torch.nn.Sequential(
        torch.nn.Linear(x_train.shape[1], 16), torch.nn.ReLU(), torch.nn.Linear(16, 1)
    )
    optimiser = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
    xt = torch.tensor(x_train, dtype=torch.float32)
    yt = torch.tensor(y_train, dtype=torch.float32).unsqueeze(1)
    xv = torch.tensor(x_val, dtype=torch.float32)
    yv = torch.tensor(y_val, dtype=torch.float32).unsqueeze(1)
    best = float("inf")
    best_state = {k: v.clone() for k, v in net.state_dict().items()}
    stale = 0
    for _ in range(max_epochs):
        net.train()
        optimiser.zero_grad()
        loss = torch.mean((net(xt) - yt) ** 2)
        loss.backward()  # type: ignore[no-untyped-call]
        optimiser.step()
        net.eval()
        with torch.no_grad():
            val = float(torch.mean((net(xv) - yv) ** 2))
        if val < best - 1e-12:
            best = val
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                break
    net.load_state_dict(best_state)
    net.eval()
    return net


def _paired_interval(
    differences: np.ndarray, confidence: float, n_resamples: int, seed: int
) -> dict[str, float]:
    """Moving-block bootstrap of the mean of a paired per-day difference."""
    result = moving_block_bootstrap(
        lambda s: float(np.mean(s)),
        np.asarray(differences, dtype=np.float64),
        BLOCK_LENGTH,
        np.random.default_rng(seed),
        n_resamples=n_resamples,
        confidence=confidence,
    )
    return {
        "estimate": result.point_estimate,
        "low": result.ci_low,
        "high": result.ci_high,
        "confidence": confidence,
    }


def sharpe(daily_returns: np.ndarray) -> float:
    std = float(np.std(daily_returns))
    return 0.0 if std == 0.0 else float(np.mean(daily_returns) / std * np.sqrt(252.0))


def _max_drawdown_fraction(daily_returns: np.ndarray) -> float:
    wealth = np.cumprod(1.0 + daily_returns)
    return float(np.min(wealth / np.maximum.accumulate(wealth) - 1.0))


def _strategy_returns(weights: np.ndarray, simple_returns: np.ndarray) -> np.ndarray:
    """Weight chosen before the day, cash earns zero, a cost on each unit of turnover."""
    previous = np.concatenate([[weights[0]], weights[:-1]])
    return np.asarray(
        weights * simple_returns - COST_PER_UNIT_TURNOVER * np.abs(weights - previous),
        dtype=np.float64,
    )


def _strategy_summary(strategy: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    return {
        "sharpe": sharpe(strategy),
        "annual_return": float(np.mean(strategy) * 252.0),
        "annual_volatility": float(np.std(strategy) * np.sqrt(252.0)),
        "max_drawdown": _max_drawdown_fraction(strategy),
        "mean_weight": float(np.mean(weights)),
    }


def _sharpe_difference_interval(
    strategy: np.ndarray, benchmark: np.ndarray, confidence: float, n_resamples: int, seed: int
) -> dict[str, float]:
    index = np.arange(strategy.size, dtype=np.float64)
    result = moving_block_bootstrap(
        lambda s: sharpe(strategy[s.astype(int)]) - sharpe(benchmark[s.astype(int)]),
        index,
        BLOCK_LENGTH,
        np.random.default_rng(seed),
        n_resamples=n_resamples,
        confidence=confidence,
    )
    return {
        "estimate": result.point_estimate,
        "low": result.ci_low,
        "high": result.ci_high,
        "confidence": confidence,
    }


def run_study(
    dates: Sequence[date] | None = None,
    closes: np.ndarray | None = None,
    *,
    n_mlp_seeds: int = 5,
    max_epochs: int = 300,
    n_resamples: int = 2000,
) -> dict[str, Any]:
    if dates is None or closes is None:
        loaded_dates, loaded_closes = load_sp500_closes(DATA_PATH)
        dates, closes = loaded_dates, loaded_closes
    returns = log_returns(np.asarray(closes, dtype=np.float64))
    return_dates = list(dates)[1:]
    train = np.array([d < TRAIN_END for d in return_dates])
    test = np.array([d >= TEST_START for d in return_dates])
    validation = ~train & ~test
    usable = np.arange(returns.size) >= WARMUP
    train &= usable
    features = build_features(returns)

    # ---- forecasts of the daily log return, one array of length n per model
    forecasts: dict[str, np.ndarray] = {}
    lag1 = features[:, [0]]
    momentum = features[:, [7]]
    forecasts["ar1"] = np.full(returns.size, np.nan)
    forecasts["momentum_12m"] = np.full(returns.size, np.nan)
    ok = usable
    forecasts["ar1"][ok] = _predict_linear(_ols(lag1[train], returns[train]), lag1[ok])
    forecasts["momentum_12m"][ok] = _predict_linear(
        _ols(momentum[train], returns[train]), momentum[ok]
    )
    scale_mean = features[train].mean(axis=0)
    scale_std = features[train].std(axis=0)
    standardised = (features - scale_mean) / scale_std
    best_penalty, best_val = RIDGE_GRID[0], float("inf")
    for penalty in RIDGE_GRID:
        coefficients = _ridge_fit(standardised[train], returns[train], penalty)
        val_error = float(
            np.mean(
                (_predict_linear(coefficients, standardised[validation]) - returns[validation]) ** 2
            )
        )
        if val_error < best_val:
            best_penalty, best_val = penalty, val_error
    ridge_coefficients = _ridge_fit(standardised[train], returns[train], best_penalty)
    forecasts["ridge"] = np.full(returns.size, np.nan)
    forecasts["ridge"][ok] = _predict_linear(ridge_coefficients, standardised[ok])
    return_scale = float(returns[train].std())
    mlp_sum = np.zeros(int(ok.sum()))
    for seed in range(n_mlp_seeds):
        net = _train_mlp(
            standardised[train],
            returns[train] / return_scale,
            standardised[validation],
            returns[validation] / return_scale,
            seed,
            max_epochs,
        )
        with torch.no_grad():
            mlp_sum += (
                net(torch.tensor(standardised[ok], dtype=torch.float32)).squeeze(1).numpy()
                * return_scale
            )
    forecasts["mlp"] = np.full(returns.size, np.nan)
    forecasts["mlp"][ok] = mlp_sum / n_mlp_seeds

    benchmark = expanding_mean(returns)
    realised = returns[test]
    benchmark_error = (realised - benchmark[test]) ** 2
    always_up_hits = (realised > 0).astype(np.float64)
    bonferroni = 1.0 - 0.05 / N_MODELS

    accuracy: dict[str, Any] = {}
    for position, name in enumerate(MODEL_NAMES):
        forecast = forecasts[name][test]
        error = (realised - forecast) ** 2
        r2 = 1.0 - float(error.sum() / benchmark_error.sum())
        error_gain = _paired_interval(
            benchmark_error - error, bonferroni, n_resamples, 1000 + position
        )
        hits = (np.sign(forecast) == np.sign(realised)).astype(np.float64)
        hit_gain = _paired_interval(hits - always_up_hits, bonferroni, n_resamples, 2000 + position)
        accuracy[name] = {
            "oos_r2_vs_historical_mean": r2,
            "squared_error_gain": error_gain,
            "squared_error_verdict": verdict(error_gain["low"], error_gain["high"]),
            "hit_rate": float(hits.mean()),
            "hit_rate_always_up": float(always_up_hits.mean()),
            "hit_rate_gain": hit_gain,
            "hit_rate_verdict": verdict(hit_gain["low"], hit_gain["high"]),
        }

    # ---- asset management: what do the forecasts earn?
    simple = np.exp(returns) - 1.0
    simple_test = simple[test]
    buy_and_hold = simple_test
    bh_weights = np.ones(simple_test.size)
    gjr = fit_garch_family(returns[train], asymmetric=True)
    sigma_hat = np.sqrt(gjr.conditional_variances(returns))[test]
    target_sigma = float(returns[train].std())
    managed: dict[str, Any] = {}
    for cap in (1.0, 2.0):
        weights = np.clip(target_sigma / sigma_hat, 0.0, cap)
        strategy = _strategy_returns(weights, simple_test)
        managed[f"cap_{cap:g}"] = {
            **_strategy_summary(strategy, weights),
            "sharpe_difference_vs_buy_and_hold": _sharpe_difference_interval(
                strategy, buy_and_hold, 0.95, n_resamples, 3000 + int(cap)
            ),
        }
        managed[f"cap_{cap:g}"]["verdict"] = verdict(
            managed[f"cap_{cap:g}"]["sharpe_difference_vs_buy_and_hold"]["low"],
            managed[f"cap_{cap:g}"]["sharpe_difference_vs_buy_and_hold"]["high"],
        )
    timing: dict[str, Any] = {}
    for position, name in enumerate(MODEL_NAMES):
        weights = (forecasts[name][test] > 0.0).astype(np.float64)
        strategy = _strategy_returns(weights, simple_test)
        interval = _sharpe_difference_interval(
            strategy, buy_and_hold, bonferroni, n_resamples, 4000 + position
        )
        timing[name] = {
            **_strategy_summary(strategy, weights),
            "sharpe_difference_vs_buy_and_hold": interval,
            "verdict": verdict(interval["low"], interval["high"]),
        }

    def any_supported(table: dict[str, Any], key: str) -> str:
        verdicts = [row[key] for row in table.values()]
        if "SUPPORTED" in verdicts:
            return "SUPPORTED"
        return "CONTRADICTED" if all(v == "CONTRADICTED" for v in verdicts) else "INCONCLUSIVE"

    return {
        "study": "market_forecast_study (PR-222)",
        "data": {
            "n_returns": int(returns.size),
            "first_date": str(return_dates[0]),
            "last_date": str(return_dates[-1]),
            "n_train": int(train.sum()),
            "n_validation": int(validation.sum()),
            "n_test": int(test.sum()),
            "test_start": str(TEST_START),
        },
        "ridge_penalty_selected_on_validation": best_penalty,
        "buy_and_hold": _strategy_summary(buy_and_hold, bh_weights),
        "forecast_accuracy": accuracy,
        "volatility_managed": managed,
        "return_forecast_timing": timing,
        "hypotheses": {
            "M-A_any_forecast_beats_historical_mean": any_supported(
                accuracy, "squared_error_verdict"
            ),
            "M-B_any_forecast_beats_always_up_on_direction": any_supported(
                accuracy, "hit_rate_verdict"
            ),
            "M-C_volatility_management_beats_buy_and_hold": managed["cap_1"]["verdict"],
            "M-D_any_forecast_timing_beats_buy_and_hold": any_supported(timing, "verdict"),
        },
        "caveats": [
            "Exploratory, not confirmatory: the history was read before, and the confirmatory "
            "protocol's data and seeds are untouched by this study.",
            "Excess returns are not used: cash earns zero and the market return is the price "
            "return of the index, so Sharpe ratios are not comparable to published ones.",
            "Costs are a flat 5 bp per unit of turnover; no taxes, borrowing or slippage.",
            "Four models and four questions were tried; the bootstrap intervals for the "
            "four-model questions are Bonferroni-adjusted but the reading of the table is not.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_study()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
