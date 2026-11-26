"""Impulse responses: how a one-off shock to one sector travels through all the others.

For each shock the same world (same seed, so the same random draws) is simulated with and without
the shock; the difference in a set of outcomes over the following `WINDOW` months, averaged over
seeds with a t interval, is the response. The matrix of shocks against outcomes is the evidence
that the sectors are connected: a cell whose interval excludes zero is a channel that works.
Running it on a world with the links off shows which cells depend on the feedback loops.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

from prometheus.confirmatory.intervals import t_interval
from prometheus.worldsim.config import Shock, WorldConfig
from prometheus.worldsim.world import WorldPath, simulate_world

WINDOW = 24
SHOCK_MONTH = 100
SHOCK_SIZES: dict[str, float] = {
    "equity_crash": 0.30,
    "rate_hike": 2.0,
    "fx_crash": 0.15,
    "bank_loss": 0.08,
    "sovereign_default": 0.0,
    "supply_shock": 2.0,
    "demand_shock": 0.05,
}
OUTCOMES: tuple[str, ...] = (
    "output_gap",
    "inflation",
    "unemployment",
    "policy_rate",
    "equity_return",
    "failed_banks",
    "public_debt",
    "exchange_rate",
    "consumption",
    "gini",
    "top10_share",
)


def outcomes(path: WorldPath, month: int = SHOCK_MONTH) -> np.ndarray:
    """Outcomes over the `WINDOW` months from `month`: changes for stocks, means for flows."""
    end = month + WINDOW
    window = slice(month, end)
    consumption = float(np.mean(path.consumption[window]))
    reference = float(np.mean(path.consumption[month - 6 : month]))
    return np.array(
        [
            float(np.mean(path.output_gap[window])),
            float(np.mean(path.inflation[window])),
            float(np.mean(path.unemployment[window])),
            float(np.mean(path.policy_rate[window])),
            float(np.sum(path.asset_returns[window, 0])),
            float(path.bank_failed[end].sum() - path.bank_failed[month - 1].sum()),
            float(path.debt_ratio[end] - path.debt_ratio[month - 1]),
            float(path.fx_level[end] - path.fx_level[month - 1]),
            0.0 if reference <= 0.0 else float(np.log(max(consumption, 1e-9) / reference)),
            float(path.gini[end] - path.gini[month - 1]),
            float(path.top10_share[end] - path.top10_share[month - 1]),
        ]
    )


def _task(args: tuple[WorldConfig, int, str]) -> np.ndarray:
    config, seed, kind = args
    base = outcomes(simulate_world(config, seed))
    shocked = outcomes(simulate_world(config, seed, [Shock(SHOCK_MONTH, kind, SHOCK_SIZES[kind])]))
    difference: np.ndarray = shocked - base
    return difference


def impulse_matrix(
    config: WorldConfig,
    seeds: Sequence[int],
    shocks: Sequence[str] = tuple(SHOCK_SIZES),
    workers: int = 1,
) -> dict[str, Any]:
    """{shock: {outcome: interval dict}} plus the share of cells whose interval excludes zero."""
    if config.n_months < SHOCK_MONTH + WINDOW + 1:
        raise ValueError("the world is too short for the impulse window")
    jobs = [(config, seed, kind) for kind in shocks for seed in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_task, jobs, chunksize=4))
    else:
        results = [_task(job) for job in jobs]
    n = len(seeds)
    matrix: dict[str, dict[str, Any]] = {}
    significant = cells = 0
    for index, kind in enumerate(shocks):
        block = np.vstack(results[index * n : (index + 1) * n])
        row: dict[str, Any] = {}
        for column, name in enumerate(OUTCOMES):
            sample = block[:, column]
            if np.allclose(sample, sample[0]) and sample[0] == 0.0:
                interval = {"estimate": 0.0, "low": 0.0, "high": 0.0, "confidence": 0.95}
                excludes = False
            else:
                interval = t_interval(sample, 0.95).as_dict()
                excludes = bool(interval["low"] > 0.0 or interval["high"] < 0.0)
            row[name] = {**interval, "excludes_zero": excludes}
            significant += int(excludes)
            cells += 1
        matrix[kind] = row
    return {
        "shock_month": SHOCK_MONTH,
        "window_months": WINDOW,
        "sizes": {kind: SHOCK_SIZES[kind] for kind in shocks},
        "matrix": matrix,
        "cells": cells,
        "cells_excluding_zero": significant,
        "share_excluding_zero": significant / cells,
    }
