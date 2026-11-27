"""Model zoo, tranche 2: do modern deep forecasters beat a ridge regression on 340 months of CPI?

Written down BEFORE the numbers were produced (the commit that adds this file has no results file).

The task is Finding 18's: nowcast the year-over-year CPI inflation rate by forecasting next month's
growth `MoM_t` and converting with the exact identity `YoY_t = I_{t-1} (1 + MoM_t) / I_{t-12} -
1`. The
data, the splits and the baselines are the ones of `orchestration.inflationcast_long_study`
(committed
Kaggle CPI-U levels and macro series, no network): fit on target months 1962-01 to 1989-12, validate
1990-1999 (early stopping and nothing else), test 2000-01 to 2023-01 (277 months). Each deep model
is
trained from five seeds and averaged in forecast space. The macro series begin in 1960, so every
model
here starts in 1962; that is the "1962" variant of Finding 18's neural model.

What I had looked at before writing this: Finding 18's numbers (a ridge on the last 12 growth rates
scored 0.212 against 0.226 for the best base-effect rule on the test months, and a small MLP did not
beat the ridge) and nothing else. Before any hypothesis below was judged I ran each new network
once on
development seeds 72900-72910 to see that it trains, looking only at the *validation* split, never
the
test months.

Models (`modelzoo.forecasting`): N-BEATS, N-HiTS, PatchTST, DeepAR, a reduced Temporal Fusion
Transformer (TFT-lite), a diagonal state-space network (S4D) and its input-dependent variant
(Mamba-lite). Baselines: `ridge_own` (ridge on the last 12 growth rates, penalty chosen on the
validation split), `mlp_own` (Finding 18's small MLP on the same inputs) and `base_mean12`
(forecast the
12-month mean growth).

A comparison is a paired difference of absolute YoY errors with a 12-month moving-block-bootstrap
95%
interval: SUPPORTED if the interval lies on the claimed side of zero, CONTRADICTED if wholly on the
other side, INCONCLUSIVE if it contains zero.

  Z-F1  The deep forecaster with the lowest *validation* error (chosen without looking at the test
        months) has a lower test error than `ridge_own`. (My prior, from Finding 18: it will not.)
  Z-F2  Each of N-BEATS, N-HiTS, PatchTST, S4D and Mamba-lite has a lower test error than `mlp_own`.
        All five comparisons must hold to support the claim; one contradiction contradicts it.
  Z-F3  TFT-lite with unemployment and the policy rate as extra channels has a lower test error than
        TFT-lite on the growth rate alone. (Finding 18, Q3: macro predictors did not help.)
  Z-F4  DeepAR's 80% predictive interval covers between 70% and 90% of the test months' realised
        growth. (Supported inside the band, contradicted outside it; there is no interval to
        bootstrap.)
  Z-F5  The validation-selected deep forecaster has a lower test error than `base_mean12`.
  Z-F6  Mamba-lite (input-dependent step) has a lower test error than S4D (fixed step).

Nothing here says how these architectures behave on the long, many-series datasets they were built
for.
It says what they do on one short monthly series, which is the situation this project is in. Seeds
72000-72999 are reserved for this study.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import torch

from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.modelzoo import forecasting as fc
from prometheus.orchestration.inflationcast_long_study import (
    RIDGE_PENALTIES,
    NowcastData,
    base_effect_forecast,
    build_nowcast_data,
    feature_matrix,
    fit_ridge,
    train_mom_network,
    yoy_from_mom,
)

SEEDS = tuple(range(72000, 72005))
OUTPUT = Path(__file__).resolve().parents[3] / "docs" / "numerics" / "modelzoo_forecast_study.json"
TRAIN_START = date(1962, 1, 31)
TRAIN_END = date(1989, 12, 31)
VALIDATION_END = date(1999, 12, 31)
TEST_END = date(2023, 1, 31)
BLOCK = 12
GAUSSIAN_80 = 1.2815515655446004


def windows(data: NowcastData, channels: str) -> np.ndarray:
    """(rows, 12, C): channel 0 is the growth history; `core` adds unemployment and the policy rate,
    whose window ends at the row's own month (known at the end of that month)."""
    if channels not in ("own", "core"):
        raise ValueError(f"unknown channel set {channels!r}")
    parts = [data.mom_history[:, :, None]]
    if channels == "core":
        n = len(data.months)
        for name in ("UNRATE", "FEDFUNDS"):
            series = data.macro[name]
            window = np.full((n, fc.WINDOW), np.nan)
            for k in range(fc.WINDOW):
                shift = fc.WINDOW - 1 - k
                window[shift:, k] = series[: n - shift]
            parts.append(window[:, :, None])
    return np.concatenate(parts, axis=2)


def split_masks(data: NowcastData, x: np.ndarray) -> dict[str, np.ndarray]:
    finite = np.isfinite(x).all(axis=(1, 2)) & np.isfinite(data.mom)
    return {
        "train": data.mask(TRAIN_START, TRAIN_END) & finite,
        "validation": data.mask(date(1990, 1, 1), VALIDATION_END) & finite,
        "test": data.mask(date(2000, 1, 1), TEST_END) & finite,
    }


def paired(first: np.ndarray, second: np.ndarray, seed: int, resamples: int) -> dict[str, Any]:
    """Mean of |e_first| - |e_second| with a block-bootstrap interval; negative favours `first`."""
    difference = np.abs(first) - np.abs(second)
    rng = np.random.default_rng(seed)
    boot = moving_block_bootstrap(np.mean, difference, BLOCK, rng, n_resamples=resamples)
    if boot.ci_high < 0.0:
        verdict = "SUPPORTED"
    elif boot.ci_low > 0.0:
        verdict = "CONTRADICTED"
    else:
        verdict = "INCONCLUSIVE"
    return {
        "mae_difference_first_minus_second": boot.point_estimate,
        "ci_low": boot.ci_low,
        "ci_high": boot.ci_high,
        "verdict": verdict,
    }


def _combine(verdicts: list[str]) -> str:
    if all(v == "SUPPORTED" for v in verdicts):
        return "SUPPORTED"
    if any(v == "CONTRADICTED" for v in verdicts):
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def gaussian_crps(mu: np.ndarray, sigma: np.ndarray, observed: np.ndarray) -> float:
    from scipy.stats import norm

    z = (observed - mu) / sigma
    crps = sigma * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))
    return float(np.mean(crps))


def run_study(
    seeds: tuple[int, ...] = SEEDS,
    *,
    max_epochs: int = 200,
    resamples: int = 2000,
    models: tuple[str, ...] = fc.FORECASTERS,
) -> dict[str, Any]:
    data = build_nowcast_data()
    x_own, x_core = windows(data, "own"), windows(data, "core")
    masks = split_masks(data, x_core)
    tr, va, te = masks["train"], masks["validation"], masks["test"]
    test_rows = np.flatnonzero(te)

    def error_of(mom_forecast: np.ndarray) -> np.ndarray:
        return np.asarray(yoy_from_mom(data, mom_forecast)[test_rows] - data.yoy[test_rows])

    def mae(mom_forecast: np.ndarray) -> float:
        return float(np.mean(np.abs(error_of(mom_forecast))))

    # baselines
    full = np.zeros(len(data.months))
    baselines: dict[str, np.ndarray] = {"base_mean12": base_effect_forecast(data, "base_mean12")}
    own_features = feature_matrix(data, "own")
    best_ridge, best_penalty, best_loss = None, None, np.inf
    for penalty in RIDGE_PENALTIES:
        ridge = fit_ridge(own_features[tr], data.mom[tr], penalty)
        loss = float(np.mean((ridge.predict(own_features[va]) - data.mom[va]) ** 2))
        if loss < best_loss:
            best_ridge, best_penalty, best_loss = ridge, penalty, loss
    if best_ridge is None:
        raise RuntimeError("no ridge penalty produced a finite validation loss")
    baselines["ridge_own"] = best_ridge.predict(own_features)
    mlp_runs = []
    for seed in seeds:
        net = train_mom_network(
            own_features[tr], data.mom[tr], own_features[va], data.mom[va], seed=seed
        )
        mlp_runs.append(net.predict(own_features))
    baselines["mlp_own"] = np.mean(mlp_runs, axis=0)

    # standardisation from the training months only
    y_mean, y_std = float(data.mom[tr].mean()), float(data.mom[tr].std())

    def standardise(x: np.ndarray) -> np.ndarray:
        mean = x[tr].mean(axis=(0, 1), keepdims=True)
        std = x[tr].std(axis=(0, 1), keepdims=True) + 1e-9
        return np.asarray((x - mean) / std)

    inputs = {"own": standardise(x_own), "core": standardise(x_core)}
    forecasts: dict[str, np.ndarray] = {}
    validation_mae: dict[str, float] = {}
    detail: dict[str, Any] = {}
    gaussian: dict[str, np.ndarray] = {}
    variants = [(name, "own") for name in models] + [("tft_lite", "core")]
    for name, channels in variants:
        x = inputs[channels]
        runs, sigmas, epochs = [], [], []
        for seed in seeds:
            torch.manual_seed(seed)
            model = fc.build_forecaster(name, x.shape[2])
            report = fc.fit_forecaster(
                model,
                x[tr],
                (data.mom[tr] - y_mean) / y_std,
                x[va],
                (data.mom[va] - y_mean) / y_std,
                seed=seed,
                max_epochs=max_epochs,
            )
            epochs.append(report.epochs_run)
            runs.append(fc.forecast_point(model, np.nan_to_num(x)) * y_std + y_mean)
            if isinstance(model, fc.DeepAR):
                mu, sigma = fc.forecast_gaussian(model, np.nan_to_num(x))
                sigmas.append((mu * y_std + y_mean, sigma * y_std))
        label = name if channels == "own" else f"{name}_core"
        forecasts[label] = np.mean(runs, axis=0)
        validation_mae[label] = float(np.mean(np.abs(forecasts[label][va] - data.mom[va])))
        detail[label] = {"epochs_run": epochs}
        if sigmas:
            gaussian[label] = np.stack(
                [np.mean([s[0] for s in sigmas], axis=0), np.mean([s[1] for s in sigmas], axis=0)]
            )
    del full

    scores = {
        label: {"test_mae_yoy": mae(fc_), "validation_mae_mom": validation_mae.get(label)}
        for label, fc_ in {**baselines, **forecasts}.items()
    }
    deep = [m for m in forecasts if not m.endswith("_core")]
    chosen = min(deep, key=lambda m: validation_mae[m])
    rng_seed = 72900

    def compare(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
        return paired(error_of(a), error_of(b), rng_seed, resamples)

    z2 = {
        m: compare(forecasts[m], baselines["mlp_own"])
        for m in ("nbeats", "nhits", "patchtst", "s4d", "mamba_lite")
        if m in forecasts
    }
    coverage = None
    crps_deepar = crps_ridge = None
    z4 = "INCONCLUSIVE"
    if "deepar" in gaussian:
        mu, sigma = gaussian["deepar"]
        outcome = data.mom[te]
        inside = np.abs(outcome - mu[te]) <= GAUSSIAN_80 * sigma[te]
        coverage = float(inside.mean())
        z4 = "SUPPORTED" if 0.70 <= coverage <= 0.90 else "CONTRADICTED"
        crps_deepar = gaussian_crps(mu[te], sigma[te], outcome)
        resid_sd = float(np.std(data.mom[va] - baselines["ridge_own"][va]))
        crps_ridge = gaussian_crps(
            baselines["ridge_own"][te], np.full(int(te.sum()), resid_sd), outcome
        )
    return {
        "seeds": list(seeds),
        "test_months": int(te.sum()),
        "ridge_penalty": best_penalty,
        "scores": scores,
        "validation_selected": chosen,
        "Z-F1": compare(forecasts[chosen], baselines["ridge_own"]),
        "Z-F2": {"verdict": _combine([v["verdict"] for v in z2.values()]), "detail": z2},
        "Z-F3": compare(forecasts["tft_lite_core"], forecasts["tft_lite"])
        if "tft_lite" in forecasts
        else None,
        "Z-F4": {
            "verdict": z4,
            "coverage_80": coverage,
            "crps_deepar_gaussian": crps_deepar,
            "crps_ridge_gaussian": crps_ridge,
        },
        "Z-F5": compare(forecasts[chosen], baselines["base_mean12"]),
        "Z-F6": compare(forecasts["mamba_lite"], forecasts["s4d"])
        if "mamba_lite" in forecasts and "s4d" in forecasts
        else None,
        "training": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Model zoo tranche 2 study")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    start = time.perf_counter()
    result = run_study()
    result["wall_seconds"] = time.perf_counter() - start
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
