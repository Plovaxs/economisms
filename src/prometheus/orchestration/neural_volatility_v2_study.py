"""Can the neural volatility model be trained to beat GARCH? A tuned, anchored version (PR-215).

Findings 15 and 17 report that the project's neural volatility model (a 6-feature, 16-unit MLP,
never tuned) loses to GARCH on QLIKE and that no VaR model passes conditional coverage. This
study asks whether that is a property of neural volatility models or of THIS untuned one. The
three questions and their decision rule were written down BEFORE any number below was computed,
so that a null result cannot be reframed afterwards:

  V-A  Does the selected tuned model have a lower test QLIKE than Finding 17's pooled neural model
       (`neural_pooled_ensemble@all`), on each of the two markets?
  V-B  Does it have a lower test QLIKE than GJR-GARCH (`gjr_normal@all`, the strongest classical
       volatility forecast of Finding 17), on each market?
  V-C  Does ANY tuned-model VaR (normal or filtered-historical-simulation quantile) pass the
       conditional-coverage test at 99% on either market?

Decision rule for a paired QLIKE comparison (22-day moving-block bootstrap, 95% interval): SUPPORTED
if the interval lies below zero, CONTRADICTED if above, INCONCLUSIVE if it contains zero. V-C:
SUPPORTED if some model's conditional-coverage p-value at 99% exceeds 0.05. Whatever comes out is
reported.

What was changed, and how it was chosen. Sixteen configurations -- every combination of

  * ``anchor``        ``constant`` (the original: log-volatility = log of the training std plus the
                      network) or ``gjr`` (log-volatility = log of the GJR-GARCH conditional
                      volatility fitted on the same market's training rows, plus a network whose
                      output layer starts at ZERO, so training begins exactly at the GJR forecast
                      and can only move away from it where the data say so);
  * ``features``      the original 6 trailing features, or those plus four longer-memory ones
                      (log EWMA volatility at decay 0.94 and 0.985, the 250-day mean absolute
                      return, the largest absolute return of the last 22 days);
  * ``hidden``        16 or 32 units per layer;
  * ``weight_decay``  0 or 1e-3 --

are each trained (5 seeds, both markets pooled, as Finding 17's Q-E found best) and ranked by the
mean QLIKE of the seed-ensemble on the VALIDATION window (2000-2007) alone. The test window
(2008 onward) is read only for the one selected configuration, plus the original-style
configuration (the grid's own reference) so the comparison is like for like. Nothing is selected on
the test window, but that window was already seen in Findings 15 and 17: this is a model-selection
study with a clean selection rule, not an untouched-data confirmation.

Data: the committed snapshots of Finding 17 (no network call). Every feature at row t uses returns
strictly before day t (a leak test checks it), and every model is fitted on data ending in 1999.
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from scipy import stats
from torch import nn

from prometheus.orchestration.market_risk_extended_study import (
    MARKET_PATHS,
    POOLED_WINDOW,
    pooled_neural_sigmas,
    verdict,
)
from prometheus.orchestration.market_risk_study import (
    ALPHAS,
    EWMA_LAMBDA,
    HISTORY_STARTS,
    MarketData,
    backtest_var,
    ewma_sigma,
    paired_qlike,
    prepare_market,
    qlike,
    trailing_features,
)
from prometheus.titan.garch_family import fit_garch_family

BASE_FEATURES = 6
EXTENDED_FEATURES = 10
LONG_LOOKBACK = 250
SLOW_EWMA = 0.985
RECENT_WINDOW = 22

ANCHORS = ("constant", "gjr")
FEATURE_SETS = ("base", "extended")
HIDDEN_WIDTHS = (16, 32)
WEIGHT_DECAYS = (0.0, 1e-3)


@dataclass(frozen=True)
class Config:
    anchor: str
    features: str
    hidden: int
    weight_decay: float

    @property
    def name(self) -> str:
        return f"{self.anchor}/{self.features}/h{self.hidden}/wd{self.weight_decay:g}"


def config_grid() -> list[Config]:
    """The sixteen candidates, in a fixed order (a tie in validation loss goes to the earlier one,
    i.e. the simpler: constant anchor, base features, narrower, undecayed)."""
    return [
        Config(a, f, h, w)
        for a, f, h, w in itertools.product(ANCHORS, FEATURE_SETS, HIDDEN_WIDTHS, WEIGHT_DECAYS)
    ]


def extended_features(returns: np.ndarray) -> np.ndarray:
    """Ten columns for every day t, each built from returns strictly BEFORE day t; rows with fewer
    than `LONG_LOOKBACK` past returns are NaN. Columns 0-5 are `trailing_features`."""
    n = len(returns)
    out = np.full((n, EXTENDED_FEATURES), np.nan)
    out[:, :BASE_FEATURES] = trailing_features(returns)
    # The EWMAs start from the variance of the first LONG_LOOKBACK returns, all of which precede
    # the first usable row (t = LONG_LOOKBACK), so no row's feature depends on a later return.
    initial = float(np.var(returns[:LONG_LOOKBACK]))
    fast = np.log(ewma_sigma(returns, EWMA_LAMBDA, initial))
    slow = np.log(ewma_sigma(returns, SLOW_EWMA, initial))
    absolute = np.abs(returns)
    cumulative = np.concatenate([[0.0], np.cumsum(absolute)])
    for t in range(LONG_LOOKBACK, n):
        out[t, 6] = fast[t]
        out[t, 7] = slow[t]
        out[t, 8] = (cumulative[t] - cumulative[t - LONG_LOOKBACK]) / LONG_LOOKBACK
        out[t, 9] = absolute[t - RECENT_WINDOW : t].max()
    return out


class AnchoredVolatility:
    """log sigma_t = anchor_t + network(standardised features_t).

    With ``zero_init`` the network's output layer starts at zero, so the untrained model IS its
    anchor: for the GJR anchor that is exactly the GJR forecast."""

    def __init__(
        self,
        n_features: int,
        hidden: int,
        mean: np.ndarray,
        scale: np.ndarray,
        seed: int,
        *,
        zero_init: bool,
    ) -> None:
        torch.manual_seed(seed)
        self.mean, self.scale = mean, scale
        self.net = nn.Sequential(
            nn.Linear(n_features, hidden),
            nn.Tanh(),
            nn.Linear(hidden, hidden),
            nn.Tanh(),
            nn.Linear(hidden, 1),
        )
        if zero_init:
            last = self.net[-1]
            if not isinstance(last, nn.Linear):  # pragma: no cover - built three lines above
                raise TypeError("the output layer must be linear")
            nn.init.zeros_(last.weight)
            nn.init.zeros_(last.bias)

    def _tensor(self, x: np.ndarray) -> torch.Tensor:
        return torch.tensor((x - self.mean) / self.scale, dtype=torch.float32)

    def log_sigma(self, x: np.ndarray, anchor: np.ndarray) -> torch.Tensor:
        correction: torch.Tensor = self.net(self._tensor(x)).squeeze(-1)
        return torch.tensor(anchor, dtype=torch.float32) + correction

    def nll(self, x: np.ndarray, anchor: np.ndarray, r: np.ndarray) -> torch.Tensor:
        log_sigma = self.log_sigma(x, anchor)
        returns = torch.tensor(r, dtype=torch.float32)
        return torch.mean(log_sigma + 0.5 * returns**2 * torch.exp(-2.0 * log_sigma))

    def sigma(self, x: np.ndarray, anchor: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            return np.asarray(
                np.exp(self.log_sigma(x, anchor).numpy().astype(np.float64)), dtype=np.float64
            )


@dataclass(frozen=True)
class Block:
    """Rows of one market in one chronological window: features, returns and the anchor."""

    x: np.ndarray
    r: np.ndarray
    anchor: np.ndarray


def train_anchored(
    train: Block,
    validation: Block,
    *,
    hidden: int,
    weight_decay: float,
    zero_init: bool,
    seed: int,
    max_epochs: int,
    patience: int,
) -> AnchoredVolatility:
    """Full-batch Adam on the Gaussian negative log-likelihood; the validation split chooses the
    epoch (best weights restored) and nothing else."""
    model = AnchoredVolatility(
        train.x.shape[1],
        hidden,
        train.x.mean(axis=0),
        train.x.std(axis=0) + 1e-12,
        seed,
        zero_init=zero_init,
    )
    optimiser = torch.optim.Adam(model.net.parameters(), lr=3e-3, weight_decay=weight_decay)
    best, best_state, stale = math.inf, copy.deepcopy(model.net.state_dict()), 0
    for _ in range(max_epochs):
        optimiser.zero_grad()
        model.nll(train.x, train.anchor, train.r).backward()  # type: ignore[no-untyped-call]
        optimiser.step()
        with torch.no_grad():
            validation_loss = float(model.nll(validation.x, validation.anchor, validation.r))
        if validation_loss < best - 1e-7:
            best, best_state, stale = validation_loss, copy.deepcopy(model.net.state_dict()), 0
        else:
            stale += 1
            if stale >= patience:
                break
    model.net.load_state_dict(best_state)
    return model


@dataclass(frozen=True)
class MarketBlocks:
    """One market cut into train / validation / test blocks, for one feature set and anchor."""

    train: Block
    validation: Block
    test: Block


def _anchor_log_sigma(data: MarketData, kind: str) -> tuple[np.ndarray, float]:
    """Per-day anchor log volatility over ALL days, and the GJR persistence (0 for a constant)."""
    train_returns = data.returns[data.train_mask]
    if kind == "gjr":
        fit = fit_garch_family(train_returns, asymmetric=True)
        return 0.5 * np.log(fit.conditional_variances(data.returns)), float(fit.persistence)
    return np.full(len(data.returns), math.log(float(train_returns.std()))), 0.0


def build_blocks(data: MarketData, config: Config) -> MarketBlocks:
    every = extended_features(data.returns)
    features = every if config.features == "extended" else every[:, :BASE_FEATURES]
    # ONE usable-row rule for every feature set, so the sets are trained on the same days.
    usable = ~np.isnan(every[:, -1])
    anchor, _ = _anchor_log_sigma(data, config.anchor)

    def block(mask: np.ndarray) -> Block:
        keep = mask & usable
        return Block(features[keep], data.returns[keep], anchor[keep])

    return MarketBlocks(block(data.train_mask), block(data.validation_mask), block(data.test_mask))


def pool(blocks: Sequence[Block]) -> Block:
    return Block(
        np.vstack([b.x for b in blocks]),
        np.concatenate([b.r for b in blocks]),
        np.concatenate([b.anchor for b in blocks]),
    )


def ensemble_sigma(per_seed: Sequence[np.ndarray]) -> np.ndarray:
    """Seed-ensemble in variance space (as Findings 15 and 17)."""
    return np.asarray(np.sqrt(np.mean(np.square(per_seed), axis=0)), dtype=np.float64)


@dataclass(frozen=True)
class Trained:
    """One configuration trained on both markets' pooled rows, for every seed."""

    config: Config
    validation_qlike: dict[str, float]
    pooled_validation_qlike: float
    sigma: dict[str, dict[str, np.ndarray]]
    """sigma[market][window] -> seed-ensemble sigma over that market's rows of the window."""


def train_configuration(
    markets: dict[str, MarketData],
    config: Config,
    *,
    seeds: Sequence[int],
    max_epochs: int,
    patience: int,
) -> Trained:
    blocks = {name: build_blocks(data, config) for name, data in markets.items()}
    train = pool([b.train for b in blocks.values()])
    validation = pool([b.validation for b in blocks.values()])
    per_seed: dict[str, dict[str, list[np.ndarray]]] = {
        name: {"train": [], "validation": [], "test": []} for name in markets
    }
    for seed in seeds:
        model = train_anchored(
            train,
            validation,
            hidden=config.hidden,
            weight_decay=config.weight_decay,
            zero_init=config.anchor == "gjr",
            seed=seed,
            max_epochs=max_epochs,
            patience=patience,
        )
        for name, b in blocks.items():
            for window, block in (
                ("train", b.train),
                ("validation", b.validation),
                ("test", b.test),
            ):
                per_seed[name][window].append(model.sigma(block.x, block.anchor))
    sigma = {
        name: {w: ensemble_sigma(s) for w, s in windows.items()}
        for name, windows in per_seed.items()
    }
    validation_qlike = {
        name: float(np.mean(qlike(blocks[name].validation.r, sigma[name]["validation"])))
        for name in markets
    }
    pooled = float(
        np.mean(
            np.concatenate([qlike(blocks[n].validation.r, sigma[n]["validation"]) for n in markets])
        )
    )
    return Trained(config, validation_qlike, pooled, sigma)


def select(candidates: Sequence[Trained]) -> Trained:
    """The lowest pooled validation QLIKE; `min` keeps the first of equals, i.e. the simplest."""
    return min(candidates, key=lambda t: t.pooled_validation_qlike)


def fhs_thresholds(
    train_r: np.ndarray, train_sigma: np.ndarray, test_sigma: np.ndarray
) -> dict[float, np.ndarray]:
    """Empirical quantile of the standardised TRAINING residuals, times the test sigma."""
    standardised = train_r / train_sigma
    return {a: float(np.quantile(standardised, 1.0 - a)) * test_sigma for a in ALPHAS}


def score_var(returns: np.ndarray, thresholds: dict[float, np.ndarray]) -> dict[str, Any]:
    return {f"alpha_{a}": backtest_var(returns, thresholds[a], a) for a in ALPHAS}


def run_study(
    paths: dict[str, Path] | None = None,
    *,
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
    max_epochs: int = 400,
    patience: int = 25,
    block_resamples: int = 2000,
    grid: Sequence[Config] | None = None,
) -> dict[str, Any]:
    paths = MARKET_PATHS if paths is None else paths
    markets = {name: prepare_market(path, name) for name, path in paths.items()}
    grid = config_grid() if grid is None else list(grid)

    candidates = [
        train_configuration(markets, c, seeds=seeds, max_epochs=max_epochs, patience=patience)
        for c in grid
    ]
    chosen = select(candidates)
    reference = next((t for t in candidates if t.config == grid[0]), candidates[0])

    # The classical baselines and Finding 17's pooled neural model, as that study computed them.
    pooled_v1 = pooled_neural_sigmas(markets, seeds=seeds, max_epochs=max_epochs, patience=patience)
    start = HISTORY_STARTS[POOLED_WINDOW]
    rng = np.random.default_rng(0)
    per_market: dict[str, Any] = {}
    hypotheses: dict[str, dict[str, Any]] = {"V-A": {}, "V-B": {}, "V-C": {}}
    for name, data in markets.items():
        blocks = build_blocks(data, chosen.config)
        test_r = blocks.test.r
        usable_test = _usable_test_mask(data)
        window = data.train_mask & np.array(
            [start is None or d >= start for d in data.return_dates]
        )
        fit_gjr = fit_garch_family(data.returns[window], asymmetric=True)
        gjr_all = np.sqrt(fit_gjr.conditional_variances(data.returns))
        gjr_test = gjr_all[data.test_mask & _usable_all(data)]
        v1 = ensemble_sigma(pooled_v1[name])
        v1_test = v1[usable_test]
        sigma_v2 = chosen.sigma[name]["test"]

        comparisons: dict[str, Any] = {}
        for label, first, second in (
            ("V-A", sigma_v2, v1_test),
            ("V-B", sigma_v2, gjr_test),
        ):
            result = paired_qlike(test_r, first, second, rng, block_resamples)
            result["preregistered_verdict"] = verdict(
                result["ci_low"], result["ci_high"], predicted_negative=True
            )
            comparisons[label] = result
            hypotheses[label][name] = result["preregistered_verdict"]
        z = {a: float(stats.norm.ppf(1.0 - a)) for a in ALPHAS}
        train_r = blocks.train.r
        models = {
            "tuned_normal": {a: z[a] * sigma_v2 for a in ALPHAS},
            "tuned_fhs": fhs_thresholds(train_r, chosen.sigma[name]["train"], sigma_v2),
            "gjr_normal": {a: z[a] * gjr_test for a in ALPHAS},
        }
        backtests = {m: score_var(test_r, th) for m, th in models.items()}
        passing = [
            m
            for m, row in backtests.items()
            if m.startswith("tuned") and row["alpha_0.99"]["conditional_coverage_p"] > 0.05
        ]
        hypotheses["V-C"][name] = {
            "verdict": "SUPPORTED" if passing else "CONTRADICTED",
            "passing": passing,
        }
        per_market[name] = {
            "n_test_days": int(test_r.size),
            "test_qlike_mean": {
                "tuned": float(np.mean(qlike(test_r, sigma_v2))),
                "finding17_pooled_neural": float(np.mean(qlike(test_r, v1_test))),
                "gjr_normal@all": float(np.mean(qlike(test_r, gjr_test))),
                "grid_reference": float(np.mean(qlike(test_r, reference.sigma[name]["test"]))),
            },
            "comparisons": comparisons,
            "backtests": backtests,
        }

    return {
        "config": {
            "seeds": list(seeds),
            "max_epochs": max_epochs,
            "patience": patience,
            "alphas": list(ALPHAS),
            "grid_size": len(grid),
            "selected": asdict(chosen.config),
            "selection_rule": "lowest pooled QLIKE of the seed-ensemble on 2000-2007; "
            "ties go to the earlier (simpler) configuration",
        },
        "grid": [
            {
                "config": t.config.name,
                "pooled_validation_qlike": t.pooled_validation_qlike,
                "validation_qlike": t.validation_qlike,
            }
            for t in sorted(candidates, key=lambda t: t.pooled_validation_qlike)
        ],
        "markets": per_market,
        "hypotheses": hypotheses,
        "caveats": [
            "The test window (2008 onward) was already seen in Findings 15 and 17: nothing here is "
            "selected on it, but this is a model-selection study, not an untouched confirmation.",
            "Two equity indices and one test window dominated by two crises; coverage tests are "
            "asymptotic and a few exceedances move a rate by several tenths of a percent.",
            "Sixteen configurations were compared on one validation decade; the winner's margin "
            "over the runner-up is reported so a near-tie is visible.",
            "QLIKE uses the squared return as its variance proxy; paired differences use a "
            "22-day moving-block bootstrap.",
        ],
    }


def _usable_all(data: MarketData) -> np.ndarray:
    return np.asarray(~np.isnan(extended_features(data.returns)[:, -1]), dtype=bool)


def _usable_test_mask(data: MarketData) -> np.ndarray:
    """Mask over the FULL return axis, restricted to test days: the same rows as `Block.test`."""
    mask = np.asarray(data.test_mask & _usable_all(data), dtype=bool)
    return np.asarray(mask[data.test_mask], dtype=bool)


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
