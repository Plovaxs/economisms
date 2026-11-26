"""Stylised-fact targets: what the volatile scenario must look like to count as a plausible economy.

The ranges are broad, set from well-known features of developed-market data (equity volatility
around 15-20%, fat tails, a negative equity-bond correlation in crises, a handful of severe crises
per century of months, unemployment peaks around 6-9%). They are guard rails against the simulator
drifting into nonsense, not estimates and not a fit.
"""

from __future__ import annotations

from typing import Any

TARGETS: dict[str, tuple[float, float]] = {
    "equity_volatility_annual": (0.10, 0.22),
    "equity_excess_kurtosis": (1.5, 10.0),
    "equity_bond_correlation_in_crisis": (-0.70, -0.10),
    "equity_bond_correlation_outside_crisis": (-0.20, 0.30),
    "mean_crisis_share": (0.02, 0.08),
    "mean_min_output_gap": (-6.0, -2.0),
    "mean_peak_unemployment": (5.5, 9.0),
    "share_of_runs_with_a_bank_failure": (0.0, 0.10),
}


def check(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For every target: the value, the allowed range and whether it is inside."""
    result: dict[str, dict[str, Any]] = {}
    for name, (low, high) in TARGETS.items():
        value = facts.get(name)
        ok = value is not None and low <= float(value) <= high
        result[name] = {"value": value, "low": low, "high": high, "ok": bool(ok)}
    return result


def all_ok(facts: dict[str, Any]) -> bool:
    return all(row["ok"] for row in check(facts).values())
