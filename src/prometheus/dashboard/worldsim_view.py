"""The WORLDSIM live view: one simulated economy, month by month, rendered as a server-side page.

Everything on the page is computed on request from `prometheus.worldsim` with the scenario, seed
and allocation rule in the query string; nothing is canned. It is a SIMULATION with chosen
parameters and carries the repository's synthetic badge: it describes the simulator, not the real
economy.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from prometheus.dashboard.charts import line_chart
from prometheus.dashboard.html import escape, page, table
from prometheus.dashboard.provenance import synthetic_badge
from prometheus.worldsim import monitor
from prometheus.worldsim.allocation import RULES
from prometheus.worldsim.config import (
    EXTENDED_SCENARIOS,
    REGIMES,
    SCENARIOS,
    WorldConfig,
    full_scenario,
    scenario,
)
from prometheus.worldsim.households import simulate_households
from prometheus.worldsim.world import simulate_world

_ALERT_NAMES = ("green", "amber", "red")
_MODES = ("none", "liquidity", "recapitalise")


def _config(name: str, mode: str) -> WorldConfig:
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}")
    if name in EXTENDED_SCENARIOS:
        return full_scenario(name, mode=mode)  # type: ignore[arg-type]
    if name in SCENARIOS:
        return scenario(name)
    raise ValueError(f"scenario must be one of {SCENARIOS + EXTENDED_SCENARIOS}")


_STEP = 6


def _sampled(values: np.ndarray, step: int = _STEP) -> list[float]:
    return [float(v) for v in values[::step]]


def worldsim_as_json(
    *, name: str = "volatile", seed: int = 0, rule: str = "equal_weight", mode: str = "none"
) -> dict[str, Any]:
    config = _config(name, mode)
    if rule not in RULES:
        raise ValueError(f"rule must be one of {RULES}")
    path = simulate_world(config, seed)
    indicators = monitor.indicators(path)
    households = simulate_households(path, rule, config.households, seed)
    last = path.n_months - 1
    composite = indicators.composite[last]
    extensions: dict[str, float] = {}
    if config.fiscal.enabled:
        extensions["public_debt_ratio"] = float(path.debt_ratio[last])
        extensions["sovereign_spread"] = float(path.sovereign_spread[last])
    if config.firms.enabled:
        extensions["firm_leverage"] = float(path.firm_leverage[last])
    if config.foreign.enabled:
        extensions["fx_level_log"] = float(path.fx_level[last])
    return {
        "scenario": name,
        "bailout_mode": config.policy.mode,
        "extensions": extensions,
        "seed": seed,
        "rule": rule,
        "n_months": path.n_months,
        "synthetic": True,
        "final": {
            "regime": REGIMES[int(path.regime[last])],
            "output_gap": float(path.output_gap[last]),
            "inflation": float(path.inflation[last]),
            "policy_rate": float(path.policy_rate[last]),
            "unemployment": float(path.unemployment[last]),
            "failed_banks": int(path.bank_failed[last].sum()),
            "weakest_capital_ratio": float(indicators.min_capital_ratio[last]),
            "warning_composite": None if np.isnan(composite) else float(composite),
            "alert": _ALERT_NAMES[int(indicators.alert[last])],
            "gini": float(households.gini[last]),
            "top10_share": float(households.top10_share[last]),
            "bottom50_share": float(households.bottom50_share[last]),
        },
        "crisis_months": int((path.regime == 2).sum()),
        "red_alert_months": int((indicators.alert == 2).sum()),
        "new_bank_failures": int(path.new_failures.sum()),
        "contagion_defaults": int(path.contagion_defaults.sum()),
    }


def render_worldsim(
    *, name: str = "volatile", seed: int = 0, rule: str = "equal_weight", mode: str = "none"
) -> str:
    summary = worldsim_as_json(name=name, seed=seed, rule=rule, mode=mode)
    config = _config(name, mode)
    path = simulate_world(config, seed)
    indicators = monitor.indicators(path)
    households = simulate_households(path, rule, config.households, seed)
    labels = [str(i) for i in range(0, path.n_months, _STEP)]
    final = summary["final"]
    composite = final["warning_composite"]

    macro_chart = line_chart(
        labels,
        {
            "output gap (%)": _sampled(path.output_gap),
            "inflation (%)": _sampled(path.inflation),
            "policy rate (%)": _sampled(path.policy_rate),
        },
    )
    wealth_index = np.cumprod(1.0 + path.asset_returns[:, 0])
    market_chart = line_chart(
        labels,
        {
            "equity index": _sampled(wealth_index / wealth_index[0]),
            f"portfolio ({rule})": _sampled(households.portfolio_value),
        },
    )
    bank_chart = line_chart(
        labels,
        {
            "weakest bank capital ratio": _sampled(indicators.min_capital_ratio),
            "credit growth 12m": _sampled(indicators.credit_growth),
        },
    )
    inequality_chart = line_chart(
        labels,
        {
            "Gini": _sampled(households.gini),
            "top 10% share": _sampled(households.top10_share),
            "bottom 50% share": _sampled(households.bottom50_share),
        },
    )
    status_rows = [
        ["Regime now", escape(str(final["regime"]))],
        [
            "Output gap / inflation / policy rate",
            f"{final['output_gap']:.2f}% / {final['inflation']:.2f}% / {final['policy_rate']:.2f}%",
        ],
        ["Unemployment", f"{final['unemployment']:.1f}%"],
        ["Failed banks (of 10)", str(final["failed_banks"])],
        ["Weakest bank capital ratio", f"{final['weakest_capital_ratio']:.1%}"],
        [
            "Warning composite / alert",
            ("n/a" if composite is None else f"{composite:.2f}") + f" / {final['alert']}",
        ],
        [
            "Months in crisis / on red alert",
            f"{summary['crisis_months']} / {summary['red_alert_months']}",
        ],
        ["Contagion defaults (whole run)", str(summary["contagion_defaults"])],
        ["Bank rescue policy", escape(str(summary["bailout_mode"]))],
        *[[escape(k.replace("_", " ")), f"{v:.3f}"] for k, v in summary["extensions"].items()],
    ]
    body = (
        synthetic_badge() + f"<p>Scenario <code>{escape(name)}</code>, seed {seed}, "
        f"allocation rule <code>{escape(rule)}</code>, "
        f"{path.n_months} months. Try "
        "<code>?scenario=stressed&amp;seed=3&amp;rule=min_variance</code>. "
        "Parameters are chosen, not estimated: this describes the simulator, "
        "not the real economy.</p>"
        + "<h2>Economic monitoring</h2>"
        + table(["indicator", "value at the last month"], status_rows)
        + "<h2>Output gap, inflation and policy rate (every 6th month)</h2>"
        + macro_chart
        + "<h2>Markets and the allocation rule</h2>"
        + market_chart
        + "<h2>Banking system</h2>"
        + bank_chart
        + "<h2>Wealth distribution</h2>"
        + inequality_chart
    )
    return page("WORLDSIM", "WORLDSIM: a volatile simulated economy (synthetic)", body)
