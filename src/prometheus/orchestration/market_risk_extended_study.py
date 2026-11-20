"""A second market, a longer out-of-time test, asymmetric volatility and pooled training (PR-202).

PR-199 scored the market-risk models on 93 years of S&P 500 returns (to 2020-11) and found that
no model passes a conditional-coverage test at 99%, that GARCH with filtered historical
simulation comes closest, that the neural volatility model loses to GARCH but gains most from
more history, and it named the GARCH fit's persistence cap (0.98) as a limitation without
measuring it. This study asks the five questions that follow. They were written down BEFORE
any number below was computed, each with its decision rule, so that a null result cannot be
reframed afterwards:

  Q-A  Does leverage asymmetry help?  `gjr` has a lower mean QLIKE than the symmetric GARCH
       fitted by the SAME optimiser and cap (`garch_free`), on both markets.
  Q-B  Was the 0.98 persistence cap a handicap?  `garch_free` (cap 0.999) has a lower mean
       QLIKE than PR-199's `garch_normal` (cap 0.98).
  Q-C  Does any VaR model pass conditional coverage at 99% over the longer test window, on
       either market?
  Q-D  Does PR-199's pattern replicate on a second market and on days that did not exist when
       PR-199 was written (2020-11-05 .. 2023-05-03)?  (i) the neural model has a HIGHER QLIKE
       than GARCH; (ii) more history lowers the neural model's QLIKE by more than it lowers
       GARCH's.
  Q-E  Does training on BOTH markets help the neural volatility model on each one?

Decision rule for a paired QLIKE comparison (22-day moving-block bootstrap of the mean
difference, 95% interval): SUPPORTED if the interval lies on the predicted side of zero,
CONTRADICTED if it lies on the other side, INCONCLUSIVE if it contains zero. For Q-C: SUPPORTED
if some model's conditional-coverage p-value at 99% exceeds 0.05. Q-D(ii) compares point
estimates only (as PR-199 did). Whatever comes out is reported.

Data (committed snapshots, no network call):

- `sp500_extended`  1927-12-30 .. 2023-05-03: the Yahoo ^GSPC history of the PR-199 dataset
  through 2020-11-04, continued with the Investing.com SPX500 series of the backbone dataset,
  rescaled at the join. The two sources agree on the 10,305 days both contain (see the
  snapshot's `.meta.json`), which is what licenses splicing them.
- `nasdaq`          1980-03-18 .. 2023-05-03: the backbone dataset's NASDAQ composite.

Both are split exactly as in PR-199 (fit before 2000, validate 2000-2007, test from 2008), so
the S&P 500's test window grows from 3,2xx days to about 3,8xx, and every model is fitted on
data that ends in 1999.

New models: `garch_free` and `gjr` (`titan.garch_family`, persistence cap 0.999) each with a
normal quantile and a filtered-historical-simulation quantile; `neural_pooled`, the neural
volatility model trained on both markets' pre-2000 rows (history window `all` only).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.orchestration.market_risk_study import (
    ALPHAS,
    BLOCK_LENGTH,
    HISTORY_STARTS,
    MarketData,
    Scoreboard,
    evaluate_baseline_models,
    paired_qlike,
    prepare_market,
    qlike,
    train_neural_volatility,
)
from prometheus.titan.garch_family import fit_garch_family

DATA_DIR = Path(__file__).resolve().parents[3] / "data_cache"
MARKET_PATHS: dict[str, Path] = {
    "sp500_extended": DATA_DIR / "kaggle_sp500_spliced_daily_close.csv",
    "nasdaq": DATA_DIR / "kaggle_nasdaq_daily_close.csv",
}
EXTENSION_START = date(2020, 11, 5)
"""The first trading day PR-199's data did not contain."""
POOLED_WINDOW = "all"
EXTENSION_SPECS: dict[str, tuple[str, str, bool]] = {
    "Q-A_extension": ("gjr_normal@all", "garch_free_normal@all", True),
    "Q-D(i)_extension": ("neural_ensemble@all", "garch_normal@all", False),
}
"""Q-A and Q-D(i) repeated on the extension days alone (about 600 days)."""
EXPLORATORY_SPECS: dict[str, tuple[str, str]] = {
    "X-1_gjr_vs_pr199_garch": ("gjr_normal@all", "garch_normal@all"),
    "X-2_pooled_neural_vs_pr199_garch": ("neural_pooled_ensemble@all", "garch_normal@all"),
}
"""Questions that arose AFTER the first results; reported, not tested. With seven paired
intervals per market, a lone interval excluding zero is weak evidence."""


def verdict(ci_low: float, ci_high: float, *, predicted_negative: bool) -> str:
    """The pre-registered decision rule: where does the interval sit against zero?"""
    if ci_low > 0.0 and ci_high > 0.0:
        return "CONTRADICTED" if predicted_negative else "SUPPORTED"
    if ci_low < 0.0 and ci_high < 0.0:
        return "SUPPORTED" if predicted_negative else "CONTRADICTED"
    return "INCONCLUSIVE"


def _usable(data: MarketData) -> np.ndarray:
    return np.asarray(~np.isnan(data.features[:, 0]), dtype=bool)


def add_garch_family_models(data: MarketData, board: Scoreboard) -> None:
    """`garch_free` and `gjr`, each with a normal and an FHS quantile, per history window."""
    for label, start in HISTORY_STARTS.items():
        window = data.train_mask & np.array(
            [start is None or d >= start for d in data.return_dates]
        )
        train_returns = data.returns[window]
        for name, asymmetric in (("garch_free", False), ("gjr", True)):
            fit = fit_garch_family(train_returns, asymmetric=asymmetric)
            sigma_all = np.sqrt(fit.conditional_variances(data.returns))
            sigma = sigma_all[data.test_mask]
            board.record(f"{name}_normal@{label}", sigma, {a: board.z[a] * sigma for a in ALPHAS})
            standardised = (train_returns - fit.mu) / sigma_all[window]
            board.record(
                f"{name}_fhs@{label}",
                sigma,
                {a: fit.mu + sigma * float(np.quantile(standardised, 1.0 - a)) for a in ALPHAS},
            )
            board.parameters[f"{name}@{label}"] = {
                "mu": fit.mu,
                "omega": fit.omega,
                "alpha": fit.alpha,
                "gamma": fit.gamma,
                "beta": fit.beta,
                "persistence": fit.persistence,
            }


def pooled_neural_sigmas(
    markets: dict[str, MarketData],
    *,
    seeds: Sequence[int],
    max_epochs: int,
    patience: int,
) -> dict[str, list[np.ndarray]]:
    """Train ONE neural volatility model per seed on every market's pre-2000 rows (and
    validate on every market's 2000-2007 rows), then predict each market's test window."""
    start = HISTORY_STARTS[POOLED_WINDOW]
    train_x: list[np.ndarray] = []
    train_r: list[np.ndarray] = []
    validation_x: list[np.ndarray] = []
    validation_r: list[np.ndarray] = []
    for data in markets.values():
        usable = _usable(data)
        window = data.train_mask & np.array(
            [start is None or d >= start for d in data.return_dates]
        )
        train_x.append(data.features[window & usable])
        train_r.append(data.returns[window & usable])
        validation_x.append(data.features[data.validation_mask & usable])
        validation_r.append(data.returns[data.validation_mask & usable])
    pooled_train_x = np.vstack(train_x)
    pooled_train_r = np.concatenate(train_r)
    pooled_validation_x = np.vstack(validation_x)
    pooled_validation_r = np.concatenate(validation_r)
    out: dict[str, list[np.ndarray]] = {name: [] for name in markets}
    for seed in seeds:
        model = train_neural_volatility(
            pooled_train_x,
            pooled_train_r,
            pooled_validation_x,
            pooled_validation_r,
            seed=seed,
            max_epochs=max_epochs,
            patience=patience,
        )
        for name, data in markets.items():
            out[name].append(model.sigma(data.features[data.test_mask]))
    return out


def extension_scores(data: MarketData, board: Scoreboard) -> dict[str, Any]:
    """Every model's score on the days PR-199 never saw. About 600 days is too few to test
    coverage (six expected exceedances at 99%), so this reports counts and QLIKE only."""
    test_dates = [d for d, m in zip(data.return_dates, data.test_mask, strict=True) if m]
    window = extension_window(data)
    returns = data.test_returns[window]
    out: dict[str, Any] = {"n_days": int(window.sum()), "first_date": None, "models": {}}
    if window.any():
        out["first_date"] = next(d for d in test_dates if d >= EXTENSION_START).isoformat()
    for name, sigma in board.sigma_by_model.items():
        row: dict[str, float] = {"qlike_mean": float(np.mean(qlike(returns, sigma[window])))}
        for alpha in ALPHAS:
            threshold = board.thresholds_by_model[name][alpha][window]
            row[f"exceedances_{alpha}"] = float(np.sum(returns < threshold))
        out["models"][name] = row
    return out


def extension_window(data: MarketData) -> np.ndarray:
    """Boolean mask over the TEST axis: the days PR-199's data did not contain."""
    test_dates = [d for d, m in zip(data.return_dates, data.test_mask, strict=True) if m]
    return np.array([d >= EXTENSION_START for d in test_dates])


def _comparison(
    board: Scoreboard,
    first: str,
    second: str,
    rng: np.random.Generator,
    resamples: int,
    *,
    predicted_negative: bool,
    window: np.ndarray | None = None,
) -> dict[str, Any]:
    keep = np.ones(board.data.test_returns.size, dtype=bool) if window is None else window
    result = {
        "first": first,
        "second": second,
        "n_days": int(keep.sum()),
        **paired_qlike(
            board.data.test_returns[keep],
            board.sigma_by_model[first][keep],
            board.sigma_by_model[second][keep],
            rng,
            resamples,
        ),
    }
    result["prediction"] = (
        "first_has_lower_qlike" if predicted_negative else "first_has_higher_qlike"
    )
    result["preregistered_verdict"] = verdict(
        result["ci_low"], result["ci_high"], predicted_negative=predicted_negative
    )
    return result


def history_gain(board: Scoreboard, model: str) -> float:
    """Mean QLIKE with the last 10 years minus mean QLIKE with all history: positive when
    more history lowers the loss."""
    return float(board.volatility[f"{model}@10y"]["qlike_mean"]) - float(
        board.volatility[f"{model}@all"]["qlike_mean"]
    )


def run_extended_study(
    paths: dict[str, Path] | None = None,
    *,
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    max_epochs: int = 400,
    patience: int = 25,
    block_resamples: int = 2000,
) -> dict[str, Any]:
    paths = MARKET_PATHS if paths is None else paths
    markets = {name: prepare_market(path, name) for name, path in paths.items()}
    boards: dict[str, Scoreboard] = {}
    neural_by_window: dict[str, dict[str, list[np.ndarray]]] = {}
    for name, data in markets.items():
        board = Scoreboard(data)
        neural_by_window[name] = evaluate_baseline_models(
            data,
            board,
            seeds=seeds,
            max_epochs=max_epochs,
            patience=patience,
            history_starts=HISTORY_STARTS,
        )
        add_garch_family_models(data, board)
        boards[name] = board

    pooled = pooled_neural_sigmas(markets, seeds=seeds, max_epochs=max_epochs, patience=patience)
    for name, board in boards.items():
        board.record_per_seed(f"neural_pooled@{POOLED_WINDOW}", pooled[name])
        ensemble = np.sqrt(np.mean(np.square(pooled[name]), axis=0))
        board.record(
            f"neural_pooled_ensemble@{POOLED_WINDOW}",
            ensemble,
            {a: board.z[a] * ensemble for a in ALPHAS},
        )

    rng = np.random.default_rng(0)
    # A separate stream, so the pre-registered intervals do not move when extras are added.
    extra_rng = np.random.default_rng(1)
    comparisons: dict[str, dict[str, Any]] = {}
    hypotheses: dict[str, dict[str, Any]] = {key: {} for key in ("Q-A", "Q-B", "Q-C", "Q-D", "Q-E")}
    for name, board in boards.items():
        specs = {
            "Q-A": ("gjr_normal@all", "garch_free_normal@all", True),
            "Q-B": ("garch_free_normal@all", "garch_normal@all", True),
            "Q-D(i)": ("neural_ensemble@all", "garch_normal@all", False),
            "Q-E": ("neural_pooled_ensemble@all", "neural_ensemble@all", True),
        }
        per_market: dict[str, Any] = {}
        for label, (first, second, predicted_negative) in specs.items():
            per_market[label] = _comparison(
                board, first, second, rng, block_resamples, predicted_negative=predicted_negative
            )
        window = extension_window(board.data)
        for label, (first, second, predicted_negative) in EXTENSION_SPECS.items():
            per_market[label] = _comparison(
                board,
                first,
                second,
                extra_rng,
                block_resamples,
                predicted_negative=predicted_negative,
                window=window,
            )
        for label, (first, second) in EXPLORATORY_SPECS.items():
            per_market[label] = {
                **_comparison(
                    board,
                    first,
                    second,
                    extra_rng,
                    block_resamples,
                    predicted_negative=True,
                ),
                "status": "EXPLORATORY: not one of the five pre-registered questions",
            }
            del per_market[label]["prediction"], per_market[label]["preregistered_verdict"]
        comparisons[name] = per_market
        for label in ("Q-A", "Q-B", "Q-E"):
            hypotheses[label][name] = per_market[label]["preregistered_verdict"]
        hypotheses["Q-D"][name] = {
            "neural_loses_to_garch": per_market["Q-D(i)"]["preregistered_verdict"],
            "neural_loses_to_garch_on_extension_days": per_market["Q-D(i)_extension"][
                "preregistered_verdict"
            ],
            "neural_gain_from_history": history_gain(board, "neural_ensemble"),
            "garch_gain_from_history": history_gain(board, "garch_normal"),
            "neural_gains_more": history_gain(board, "neural_ensemble")
            > history_gain(board, "garch_normal"),
        }
        # Only forecasts with ONE threshold series are tested for coverage; the per-seed neural
        # rows hold means of p-values, which are not p-values.
        passing = {
            alpha: {
                model: board.backtests[model][f"alpha_{alpha}"]["conditional_coverage_p"]
                for model in board.thresholds_by_model
                if board.backtests[model][f"alpha_{alpha}"]["conditional_coverage_p"] > 0.05
            }
            for alpha in ALPHAS
        }
        closest = max(
            board.thresholds_by_model,
            key=lambda model: board.backtests[model]["alpha_0.99"]["conditional_coverage_p"],
        )
        hypotheses["Q-C"][name] = {
            "closest_at_99": {
                "model": closest,
                "conditional_coverage_p": board.backtests[closest]["alpha_0.99"][
                    "conditional_coverage_p"
                ],
                "n_exceedances": board.backtests[closest]["alpha_0.99"]["n_exceedances"],
                "expected_exceedances": board.backtests[closest]["alpha_0.99"][
                    "expected_exceedances"
                ],
            },
            "verdict": "SUPPORTED" if passing[0.99] else "CONTRADICTED",
            "models_passing_at_99": dict(sorted(passing[0.99].items())),
            "models_passing_at_97.5": dict(sorted(passing[0.975].items())),
        }

    return {
        "config": {
            "seeds": list(seeds),
            "alphas": list(ALPHAS),
            "block_length_days": BLOCK_LENGTH,
            "extension_start": EXTENSION_START.isoformat(),
            "history_windows": {
                k: (v.isoformat() if v else "all") for k, v in HISTORY_STARTS.items()
            },
            "pooled_window": POOLED_WINDOW,
        },
        "markets": {
            name: {
                "data": board.data_summary(),
                "backtests": board.backtests,
                "volatility": board.volatility,
                "garch_family_parameters": board.parameters,
                "extension": extension_scores(board.data, board),
                "comparisons": comparisons[name],
            }
            for name, board in boards.items()
        },
        "hypotheses": hypotheses,
        "caveats": [
            "Two equity indices, one fit window (before 2000) and one test window (from 2008) "
            "dominated by two crises: a few exceedances move a rate by several tenths of a "
            "percent.",
            "The extension (about 600 days) is too short to test coverage; only QLIKE and counts "
            "are reported for it.",
            "The S&P 500 series is spliced from two vendors at 2020-11-04; they agree on the "
            "10,305 days both contain, but the continuation is not the original source.",
            "QLIKE uses the squared return as the variance proxy, which is unbiased but noisy; "
            "paired differences use a 22-day moving-block bootstrap.",
            "NASDAQ has only 20 years of pre-2000 data, so its 'all history' window is 1980-1999.",
            "Price returns of an index (no dividends), close-to-close.",
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
    report = run_extended_study(
        seeds=list(range(args.seeds)), max_epochs=args.max_epochs, patience=args.patience
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
