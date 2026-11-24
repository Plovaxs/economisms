"""Power notes for the confirmatory endpoints: how often would the stated rule reach "better"?

The protocol says an endpoint whose power is below 0.8 is declared estimation-only up front, so
the claim it can support is a size and an interval, not a verdict. These functions compute that
power, and the smallest effect each endpoint can reliably detect, from the RETROSPECTIVE data,
under one assumption they state out loud: the new sample behaves like the old one. They are
planning numbers, not predictions, and they use the old data (never the untouched data).

- E1 (one value per independent seed): simulate `n` seeds from a normal with the old spread,
  apply the endpoint's t interval and rule.
- E2 (a serially dependent monthly series): resample `n` months of the OLD paired differences in
  blocks, re-centre them on a chosen true effect, apply the endpoint's block-bootstrap interval
  and rule.
- E3 (exceedance counts): exact binomial arithmetic, no simulation.

Everything is seeded, so the committed power note can be reproduced.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy import stats

from prometheus.confirmatory.intervals import block_interval, classify_effect, t_interval

TARGET_POWER = 0.8


def _share(outcomes: Sequence[str], wanted: str = "better") -> float:
    return sum(o == wanted for o in outcomes) / len(outcomes)


def power_e1(
    sd: float,
    n_seeds: int,
    effects: Sequence[float],
    *,
    confidence: float,
    margin: float,
    n_sims: int = 4000,
    seed: int = 0,
) -> list[dict[str, float]]:
    """Share of simulated experiments the endpoint calls "better", for each true `theta`.

    `theta = -log(CVaR ratio)`, so an effect of 0.05 means the policy's CVaR is about 5% lower."""
    if sd <= 0.0 or n_seeds < 2:
        raise ValueError("need a positive spread and at least two seeds")
    rng = np.random.default_rng(seed)
    rows = []
    for effect in effects:
        outcomes = [
            classify_effect(t_interval(rng.normal(effect, sd, size=n_seeds), confidence), margin)
            for _ in range(n_sims)
        ]
        rows.append(
            {
                "true_theta": effect,
                "power_better": _share(outcomes, "better"),
                "share_equivalent": _share(outcomes, "equivalent"),
                "share_inconclusive": _share(outcomes, "inconclusive"),
            }
        )
    return rows


def power_e2(
    old_differences: np.ndarray,
    n_months: int,
    effects: Sequence[float],
    *,
    confidence: float,
    margin: float,
    block_length: int,
    n_sims: int = 300,
    n_resamples: int = 400,
    seed: int = 0,
) -> list[dict[str, float]]:
    """The same, for a monthly series: resample the old paired differences in blocks of the
    endpoint's own length, shift them so their mean is the chosen true effect, and score them with
    the endpoint's own interval and rule."""
    d = np.asarray(old_differences, dtype=np.float64)
    if d.ndim != 1 or d.size < 2 * block_length or n_months < block_length:
        raise ValueError("not enough old months to resample blocks from")
    centred = d - d.mean()
    rng = np.random.default_rng(seed)
    max_start = d.size - block_length + 1
    n_blocks = -(-n_months // block_length)
    rows = []
    for effect in effects:
        outcomes = []
        for sim in range(n_sims):
            starts = rng.integers(0, max_start, size=n_blocks)
            sample = np.concatenate([centred[s : s + block_length] for s in starts])[:n_months]
            interval = block_interval(
                sample + effect,
                block_length=block_length,
                confidence=confidence,
                n_resamples=n_resamples,
                seed=seed + sim,
            )
            outcomes.append(classify_effect(interval, margin))
        rows.append(
            {
                "true_theta": effect,
                "power_better": _share(outcomes, "better"),
                "share_equivalent": _share(outcomes, "equivalent"),
                "share_inconclusive": _share(outcomes, "inconclusive"),
            }
        )
    return rows


def power_e3(
    true_rates: Sequence[float], n_days: int, *, nominal: float, confidence: float
) -> list[dict[str, float]]:
    """Exact probability that the Clopper-Pearson interval for the exceedance rate EXCLUDES the
    nominal rate, when the model's true exceedance rate is `rate`. At `rate == nominal` this is the
    false-alarm rate, which should not exceed `1 - confidence`."""
    if n_days < 1:
        raise ValueError("need at least one day")
    counts = np.arange(n_days + 1)
    alpha = 1.0 - confidence
    low = np.where(
        counts == 0, 0.0, stats.beta.ppf(alpha / 2.0, np.maximum(counts, 1), n_days - counts + 1)
    )
    high = np.where(
        counts == n_days,
        1.0,
        stats.beta.ppf(1.0 - alpha / 2.0, counts + 1, np.maximum(n_days - counts, 1)),
    )
    excludes = (low > nominal) | (high < nominal)
    return [
        {
            "true_rate": rate,
            "n_days": n_days,
            "expected_exceedances": rate * n_days,
            "power_to_exclude_nominal": float(
                stats.binom.pmf(counts, n_days, rate)[excludes].sum()
            ),
        }
        for rate in true_rates
    ]


def smallest_effect(rows: Sequence[dict[str, float]], target: float = TARGET_POWER) -> float | None:
    """The smallest listed true effect whose power reaches `target`, or None if none does."""
    reaching = [r["true_theta"] for r in rows if r["power_better"] >= target]
    return min(reaching) if reaching else None


def verdict(power_at_reference: float) -> str:
    return (
        "adequate: the endpoint can support a verdict"
        if power_at_reference >= TARGET_POWER
        else "estimation-only: report a size and an interval, not a verdict"
    )


def analytic_e1_minimum_effect(
    sd: float, n_seeds: int, *, confidence: float, target: float = TARGET_POWER
) -> float:
    """Back-of-the-envelope smallest `theta` a t interval separates from zero with probability
    `target`: (t_confidence + t_target) * sd / sqrt(n). A cross-check on the simulation."""
    df = n_seeds - 1
    return float(
        (stats.t.ppf(0.5 + confidence / 2.0, df) + stats.t.ppf(target, df))
        * sd
        / math.sqrt(n_seeds)
    )


def old_e2_differences(report: dict[str, Any]) -> np.ndarray:
    """`|e_persistence| - |e_rule|` per month, from an `e2_inflation.analyse_window` report."""
    return np.array(
        [
            abs(row["persistence"] - row["yoy"]) - abs(row["base_effect"] - row["yoy"])
            for row in report["per_month"]
        ]
    )
