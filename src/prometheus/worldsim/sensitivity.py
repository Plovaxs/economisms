"""One-at-a-time sensitivity of the world's outcomes to its parameters (a tornado table).

Each named parameter is moved down and up by a fixed factor with every random draw held fixed, so
the change in an outcome is caused by the parameter alone. The table says which assumptions the
results lean on, which is the honest companion to a simulation with chosen parameters.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from typing import Any

import numpy as np

from prometheus.worldsim.config import WorldConfig
from prometheus.worldsim.world import simulate_world

PARAMETERS: tuple[str, ...] = (
    "banks.loss_given_default",
    "banks.default_sensitivity",
    "banks.deposit_funding",
    "banks.capital_trigger",
    "banks.fire_sale_fraction",
    "market.price_impact",
    "macro.credit_crunch_drag",
    "macro.regime_output_vol",
    "foreign.bank_fx_debt_share",
    "firms.default_sensitivity",
)


def get_param(config: WorldConfig, dotted: str) -> Any:
    group, name = dotted.split(".")
    return getattr(getattr(config, group), name)


def set_param(config: WorldConfig, dotted: str, value: Any) -> WorldConfig:
    group, name = dotted.split(".")
    return replace(config, **{group: replace(getattr(config, group), **{name: value})})


def scaled(config: WorldConfig, dotted: str, factor: float) -> WorldConfig:
    """`config` with one parameter multiplied by `factor`. Deposit funding is scaled in its distance
    from 100 (leverage), not in its level, so a 10% change moves leverage by 10%."""
    current = get_param(config, dotted)
    if dotted == "banks.deposit_funding":
        return set_param(config, dotted, 100.0 - (100.0 - current) * factor)
    if isinstance(current, tuple):
        return set_param(config, dotted, tuple(v * factor for v in current))
    return set_param(config, dotted, current * factor)


def outcomes(config: WorldConfig, seeds: Sequence[int]) -> dict[str, float]:
    failed, ymin, crisis = [], [], []
    for seed in seeds:
        path = simulate_world(config, seed)
        failed.append(int(path.bank_failed[-1].sum()))
        ymin.append(float(path.output_gap.min()))
        crisis.append(float((path.regime == 2).mean()))
    return {
        "mean_failed_banks": float(np.mean(failed)),
        "share_of_runs_with_failure": float(np.mean(np.array(failed) > 0)),
        "mean_min_output_gap": float(np.mean(ymin)),
    }


def _task(args: tuple[WorldConfig, str, float, tuple[int, ...]]) -> dict[str, float]:
    config, dotted, factor, seeds = args
    return outcomes(scaled(config, dotted, factor), seeds)


def tornado(
    config: WorldConfig,
    seeds: Sequence[int],
    parameters: Sequence[str] = PARAMETERS,
    factor: float = 0.25,
    workers: int = 1,
) -> list[dict[str, Any]]:
    """Rows sorted by the swing in mean failed banks between the low and high setting."""
    seed_tuple = tuple(seeds)
    tasks = [
        (config, dotted, 1.0 + sign * factor, seed_tuple)
        for dotted in parameters
        for sign in (-1.0, 1.0)
    ]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_task, tasks))
    else:
        results = [_task(task) for task in tasks]
    rows = []
    for index, dotted in enumerate(parameters):
        low, high = results[2 * index], results[2 * index + 1]
        rows.append(
            {
                "parameter": dotted,
                "base_value": get_param(config, dotted),
                "low": low,
                "high": high,
                "swing_mean_failed_banks": high["mean_failed_banks"] - low["mean_failed_banks"],
                "swing_min_output_gap": high["mean_min_output_gap"] - low["mean_min_output_gap"],
            }
        )
    rows.sort(key=lambda r: -abs(r["swing_mean_failed_banks"]))
    return rows
