"""A shock's transmission map: where it starts, how it travels and which links carry it.

Two measurements, both on the same seeds so every difference is paired:

- the response over time: the world is simulated with and without a one-off shock and the
  difference in each series is averaged over seeds (`response_paths`);
- the channel decomposition: for every feedback loop the world has, the same experiment is run
  again with that one loop switched off, and the part of the response that disappears is what the
  loop carries (`channel_effects`). The effect of a channel is the full response minus the response
  without it, with a t interval over seeds.

The map is a statement about the simulator's own wiring; it is not an estimate of how the real
economy transmits shocks.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from prometheus.confirmatory.intervals import t_interval
from prometheus.worldsim.config import CRISIS, SHOCK_KINDS, Shock, WorldConfig
from prometheus.worldsim.impulse import OUTCOMES, SHOCK_MONTH, SHOCK_SIZES, WINDOW, outcomes
from prometheus.worldsim.world import WorldPath, simulate_world

SECTORS: tuple[tuple[str, str], ...] = (
    ("markets", "Markets"),
    ("banks", "Banks"),
    ("households", "Households"),
    ("firms", "Firms"),
    ("government", "Government"),
    ("foreign", "Foreign sector"),
    ("central_bank", "Central bank"),
    ("economy", "Output and jobs"),
)
SECTOR_LABEL = dict(SECTORS)

SHOCK_ORIGIN: dict[str, str] = {
    "equity_crash": "markets",
    "rate_hike": "central_bank",
    "fx_crash": "foreign",
    "bank_loss": "banks",
    "sovereign_default": "government",
    "supply_shock": "economy",
    "demand_shock": "households",
}
SHOCK_LABEL: dict[str, str] = {
    "equity_crash": "Equity crash (all equity loses the size in one month)",
    "rate_hike": "Policy-rate hike (percentage points)",
    "fx_crash": "Currency crash (log fall in the exchange rate)",
    "bank_loss": "Bank loss (share of loans written off)",
    "sovereign_default": "Sovereign default (the state defaults at once)",
    "supply_shock": "Supply shock (inflation jump, percentage points)",
    "demand_shock": "Demand shock (share of household spending lost)",
}
OUTCOME_SECTOR: dict[str, str] = {
    "output_gap": "economy",
    "inflation": "central_bank",
    "unemployment": "economy",
    "policy_rate": "central_bank",
    "equity_return": "markets",
    "failed_banks": "banks",
    "public_debt": "government",
    "exchange_rate": "foreign",
    "consumption": "households",
    "gini": "households",
    "top10_share": "households",
}


@dataclass(frozen=True, slots=True)
class Channel:
    """One feedback loop: its name, the sector it leaves and the sector it enters, and how to
    switch it off in a config. `applies` says whether the config has the loop at all."""

    key: str
    label: str
    source: str
    target: str
    description: str
    switch_off: Callable[[WorldConfig], WorldConfig]
    applies: Callable[[WorldConfig], bool]


def _links(config: WorldConfig, **changes: Any) -> WorldConfig:
    return replace(config, links=replace(config.links, **changes))


CHANNELS: tuple[Channel, ...] = (
    Channel(
        "demand",
        "Household demand",
        "households",
        "economy",
        "What households spend, set against their income, moves output.",
        lambda c: _links(c, demand_coupling=0.0),
        lambda c: c.links.enabled,
    ),
    Channel(
        "depositor_losses",
        "Depositor losses and deposit insurance",
        "banks",
        "government",
        "A failed bank's deposits are lost: the insured part is paid by the state, the rest by "
        "households.",
        lambda c: _links(c, deposit_insurance=False),
        lambda c: c.links.enabled and c.fiscal.enabled,
    ),
    Channel(
        "bank_sovereign",
        "Banks' holdings of government bonds",
        "government",
        "banks",
        "Banks hold the state's bonds, so a sovereign default is a loss on their balance sheets.",
        lambda c: _links(c, bank_sovereign_share=0.0),
        lambda c: c.links.enabled and c.fiscal.enabled,
    ),
    Channel(
        "sovereign_default",
        "Sovereign default",
        "government",
        "economy",
        "High debt raises the chance of default, which hits the currency, spreads and output.",
        lambda c: _links(c, sovereign_default=False),
        lambda c: c.links.enabled and c.fiscal.enabled,
    ),
    Channel(
        "firm_distress",
        "Firm distress and jobs",
        "firms",
        "economy",
        "Leveraged firms that default push unemployment up.",
        lambda c: _links(c, firm_unemployment=0.0),
        lambda c: c.links.enabled and c.firms.enabled,
    ),
    Channel(
        "foreign",
        "Exchange rate and trade",
        "foreign",
        "economy",
        "A weaker currency raises inflation, helps exports and raises the cost of foreign-"
        "currency bank debt.",
        lambda c: replace(
            c,
            foreign=replace(
                c.foreign, inflation_pass_through=0.0, trade_effect=0.0, bank_fx_debt_share=0.0
            ),
        ),
        lambda c: c.foreign.enabled,
    ),
    Channel(
        "fire_sales",
        "Fire sales",
        "banks",
        "markets",
        "Banks under their capital trigger sell securities, which pushes equity prices down.",
        lambda c: replace(c, market=replace(c.market, price_impact=0.0)),
        lambda c: True,
    ),
    Channel(
        "credit_crunch",
        "Credit crunch",
        "banks",
        "economy",
        "Banks short of capital stop lending, which drags on output.",
        lambda c: replace(c, macro=replace(c.macro, credit_crunch_drag=0.0)),
        lambda c: True,
    ),
)

# The links that exist in the model but cannot be switched off one at a time (they are the
# structure, not a parameter): drawn as thin grey lines.
STRUCTURAL_EDGES: tuple[tuple[str, str, str], ...] = (
    ("markets", "banks", "mark-to-market on securities"),
    ("economy", "banks", "loan losses rise as output falls"),
    ("economy", "firms", "leverage builds in booms"),
    ("central_bank", "economy", "the policy rate moves output"),
    ("economy", "central_bank", "the Taylor rule reads output and inflation"),
    ("central_bank", "foreign", "interest-rate carry moves the currency"),
)

SERIES: tuple[str, ...] = (
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
)
MAX_SEEDS = 24
MIN_SEEDS = 3
PATH_BEFORE = 6
PATH_AFTER = 36


def shock_available(config: WorldConfig, kind: str) -> str | None:
    """Why `kind` would do nothing in `config`, or None if it can act."""
    if kind not in SHOCK_KINDS:
        raise ValueError(f"unknown shock {kind!r}; choose from {SHOCK_KINDS}")
    if kind == "sovereign_default" and not (config.links.enabled and config.fiscal.enabled):
        return "a sovereign default needs the government and the links (use a *_connected scenario)"
    if kind == "fx_crash" and not config.foreign.enabled:
        return "a currency crash needs the foreign sector (use a *_full or *_connected scenario)"
    if kind == "demand_shock" and not config.links.enabled:
        return "a demand shock needs the households inside the world (use a *_connected scenario)"
    return None


def series_of(path: WorldPath) -> dict[str, np.ndarray]:
    """Monthly series used for the time paths (stocks as levels, equity as the monthly return)."""
    return {
        "output_gap": path.output_gap,
        "inflation": path.inflation,
        "unemployment": path.unemployment,
        "policy_rate": path.policy_rate,
        "equity_return": 100.0 * path.asset_returns[:, 0],
        "failed_banks": path.bank_failed.sum(axis=1).astype(np.float64),
        "public_debt": 100.0 * path.debt_ratio,
        "exchange_rate": 100.0 * path.fx_level,
        "consumption": path.consumption,
        "gini": path.gini,
    }


def _run_pair(
    config: WorldConfig, seed: int, kind: str, size: float
) -> tuple[WorldPath, WorldPath]:
    base = simulate_world(config, seed)
    shocked = simulate_world(config, seed, [Shock(SHOCK_MONTH, kind, size)])
    return base, shocked


def response_paths(
    config: WorldConfig,
    kind: str,
    size: float,
    seeds: Sequence[int],
    pairs: list[tuple[WorldPath, WorldPath]] | None = None,
) -> dict[str, Any]:
    """Mean difference (shocked minus baseline) of each series from `PATH_BEFORE` months before the
    shock to `PATH_AFTER` months after, over seeds, plus the windowed outcomes with t intervals."""
    if config.n_months < SHOCK_MONTH + PATH_AFTER + 1:
        raise ValueError("the world is too short for the response window")
    window = slice(SHOCK_MONTH - PATH_BEFORE, SHOCK_MONTH + PATH_AFTER + 1)
    differences: dict[str, list[np.ndarray]] = {name: [] for name in SERIES}
    cells: list[np.ndarray] = []
    used_pairs = pairs if pairs is not None else _pairs(config, kind, size, seeds)
    for base, shocked in used_pairs:
        b, s = series_of(base), series_of(shocked)
        for name in SERIES:
            differences[name].append((s[name] - b[name])[window])
        cells.append(outcomes(shocked) - outcomes(base))
    months = list(range(-PATH_BEFORE, PATH_AFTER + 1))
    context = {
        "banks_failed_at_shock": float(
            np.mean([base.bank_failed[SHOCK_MONTH - 1].sum() for base, _ in used_pairs])
        ),
        "crisis_at_shock_share": float(
            np.mean([base.regime[SHOCK_MONTH] == CRISIS for base, _ in used_pairs])
        ),
    }
    mean_paths = {name: np.mean(rows, axis=0).tolist() for name, rows in differences.items()}
    block = np.vstack(cells)
    summary: dict[str, Any] = {}
    for column, name in enumerate(OUTCOMES):
        sample = block[:, column]
        if np.allclose(sample, 0.0):
            summary[name] = {
                "estimate": 0.0,
                "low": 0.0,
                "high": 0.0,
                "excludes_zero": False,
            }
        else:
            interval = t_interval(sample, 0.95).as_dict()
            summary[name] = {
                "estimate": interval["estimate"],
                "low": interval["low"],
                "high": interval["high"],
                "excludes_zero": bool(interval["low"] > 0.0 or interval["high"] < 0.0),
            }
    return {
        "months": months,
        "paths": mean_paths,
        "outcomes": summary,
        "window_months": WINDOW,
        "context": context,
    }


def channel_effects(
    config: WorldConfig,
    kind: str,
    size: float,
    seeds: Sequence[int],
    pairs: list[tuple[WorldPath, WorldPath]] | None = None,
) -> dict[str, Any]:
    """For each channel the config has: the windowed response of every outcome with the channel on
    minus the response with it off, as a t interval over paired seeds."""
    full_pairs = pairs if pairs is not None else _pairs(config, kind, size, seeds)
    full = np.vstack([outcomes(s) - outcomes(b) for b, s in full_pairs])
    result: dict[str, Any] = {}
    for channel in CHANNELS:
        if not channel.applies(config):
            continue
        reduced = channel.switch_off(config)
        without = np.vstack(
            [outcomes(s) - outcomes(b) for b, s in _pairs(reduced, kind, size, seeds)]
        )
        gap = full - without
        row: dict[str, Any] = {}
        for column, name in enumerate(OUTCOMES):
            sample = gap[:, column]
            if np.allclose(sample, 0.0):
                row[name] = {"estimate": 0.0, "low": 0.0, "high": 0.0, "excludes_zero": False}
                continue
            interval = t_interval(sample, 0.95).as_dict()
            row[name] = {
                "estimate": interval["estimate"],
                "low": interval["low"],
                "high": interval["high"],
                "excludes_zero": bool(interval["low"] > 0.0 or interval["high"] < 0.0),
            }
        result[channel.key] = row
    return result


def _pairs(
    config: WorldConfig, kind: str, size: float, seeds: Sequence[int]
) -> list[tuple[WorldPath, WorldPath]]:
    return [_run_pair(config, seed, kind, size) for seed in seeds]


def transmission_map(
    config: WorldConfig, kind: str, size: float | None, seeds: Sequence[int]
) -> dict[str, Any]:
    """Everything the page draws: origin, the response paths and the channel effects."""
    if not MIN_SEEDS <= len(seeds) <= MAX_SEEDS:
        raise ValueError(f"use between {MIN_SEEDS} and {MAX_SEEDS} seeds")
    reason = shock_available(config, kind)
    shock_size = SHOCK_SIZES[kind] if size is None else float(size)
    result: dict[str, Any] = {
        "scenario": config.name,
        "shock": kind,
        "size": shock_size,
        "origin": SHOCK_ORIGIN[kind],
        "seeds": len(seeds),
        "unavailable": reason,
        "channels": {},
        "response": None,
    }
    if reason is not None:
        return result
    pairs = _pairs(config, kind, shock_size, seeds)
    result["response"] = response_paths(config, kind, shock_size, seeds, pairs)
    effects = channel_effects(config, kind, shock_size, seeds, pairs)
    result["channels"] = {
        key: {
            "label": next(c.label for c in CHANNELS if c.key == key),
            "source": next(c.source for c in CHANNELS if c.key == key),
            "target": next(c.target for c in CHANNELS if c.key == key),
            "description": next(c.description for c in CHANNELS if c.key == key),
            "outcomes": row,
        }
        for key, row in effects.items()
    }
    return result
