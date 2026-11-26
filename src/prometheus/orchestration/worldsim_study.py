"""What a volatile simulated world says about allocation, inequality, contagion and warnings.

`prometheus.worldsim` joins an economy (regimes, output gap, inflation, a Taylor-rule policy rate),
four asset returns, a household wealth distribution and a leveraged banking sector with interbank
contagion and fire sales. Its parameters are chosen to look like a plausible economy, not
estimated, so every result below is a statement about the simulator. Four questions and their
decision rule were written BEFORE any number below was computed, so a null result cannot be
reframed afterwards:

  W-A  In the `volatile` scenario, does any allocation rule (60/40, risk parity, minimum variance,
         volatility target) have a shallower maximum drawdown than equal weight? (paired across
         seeds)
  W-B  Do crises concentrate wealth? Is the top-decile wealth share at the end higher in `stressed`
         than in `calm`, under equal weight? (difference of means across independent seeds)
  W-C  Do bank fire sales amplify the banking crisis? In `stressed`, are more banks failed at the
         end with the fire-sale price impact on than with it off? (paired across seeds)
  W-D  Does the early-warning composite carry information? In `volatile`, is the AUC for "a crisis
         begins within six months" above 0.5? (bootstrap over seeds)

Decision rule: SUPPORTED if the whole interval lies on the predicted side of the null (zero, or 0.5
for the AUC), CONTRADICTED if wholly on the other side, INCONCLUSIVE otherwise. W-A tests four
rules and uses a Bonferroni-adjusted interval (1 - 0.05 / 4); the others use 95%. Whatever comes
out is reported.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.confirmatory.intervals import t_interval
from prometheus.worldsim import monitor
from prometheus.worldsim.allocation import RULES
from prometheus.worldsim.config import CRISIS, SCENARIOS, WorldConfig, scenario
from prometheus.worldsim.households import simulate_households
from prometheus.worldsim.world import WorldPath, simulate_world

N_SEEDS = 200
BONFERRONI = 1.0 - 0.05 / 4


def verdict(low: float, high: float, null: float = 0.0) -> str:
    if low > null:
        return "SUPPORTED"
    if high < null:
        return "CONTRADICTED"
    return "INCONCLUSIVE"


def max_drawdown_fraction(values: np.ndarray) -> float:
    return float(np.min(values / np.maximum.accumulate(values) - 1.0))


def _excess_kurtosis(x: np.ndarray) -> float:
    centred = x - x.mean()
    return float(np.mean(centred**4) / np.mean(centred**2) ** 2 - 3.0)


def _alert_hit_rates(path: WorldPath, alert: np.ndarray) -> tuple[int, int]:
    """(crisis onsets, onsets with an amber-or-red alert in the previous HORIZON months)."""
    onsets = [
        t
        for t in range(monitor.BURN_IN, path.n_months)
        if path.regime[t] == CRISIS and path.regime[t - 1] != CRISIS
    ]
    hits = sum(1 for t in onsets if np.any(alert[max(0, t - monitor.HORIZON) : t] >= 1))
    return len(onsets), hits


def run_scenario(config: WorldConfig, seeds: Sequence[int]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    scores: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    onsets = hits = 0
    amber_months = red_months = total_months = 0
    pooled_equity = []
    corr_calm: list[float] = []
    corr_crisis: list[float] = []
    for seed in seeds:
        path = simulate_world(config, seed)
        indicators = monitor.indicators(path)
        score, label = monitor.warning_samples(path, indicators.composite)
        scores.append(score)
        labels.append(label)
        n_on, n_hit = _alert_hit_rates(path, indicators.alert)
        onsets += n_on
        hits += n_hit
        defined = ~np.isnan(indicators.composite)
        total_months += int(defined.sum())
        amber_months += int((indicators.alert[defined] >= 1).sum())
        red_months += int((indicators.alert[defined] >= 2).sum())
        pooled_equity.append(path.asset_returns[:, 0])
        calm = path.regime != CRISIS
        if calm.sum() > 20:
            corr_calm.append(
                float(np.corrcoef(path.asset_returns[calm, 0], path.asset_returns[calm, 1])[0, 1])
            )
        if (~calm).sum() > 20:
            corr_crisis.append(
                float(np.corrcoef(path.asset_returns[~calm, 0], path.asset_returns[~calm, 1])[0, 1])
            )
        row: dict[str, Any] = {
            "seed": seed,
            "crisis_share": float((path.regime == CRISIS).mean()),
            "failed_banks": int(path.bank_failed[-1].sum()),
            "contagion_defaults": int(path.contagion_defaults.sum()),
            "fire_sale_volume": float(path.fire_sale_volume.sum()),
            "min_output_gap": float(path.output_gap.min()),
            "peak_unemployment": float(path.unemployment.max()),
            "peak_inflation": float(path.inflation.max()),
            "equity_max_drawdown": max_drawdown_fraction(
                np.cumprod(1.0 + path.asset_returns[:, 0])
            ),
            "rules": {},
        }
        for rule in RULES:
            result = simulate_households(path, rule, config.households, seed)
            years = (path.n_months - 1) / 12.0
            row["rules"][rule] = {
                "max_drawdown": max_drawdown_fraction(result.portfolio_value),
                "cagr": float(result.portfolio_value[-1] ** (1.0 / years) - 1.0),
                "gini_end": float(result.gini[-1]),
                "top10_end": float(result.top10_share[-1]),
                "bottom50_end": float(result.bottom50_share[-1]),
                "real_wealth_participants": result.final_real_wealth_participants,
                "real_wealth_others": result.final_real_wealth_others,
            }
        rows.append(row)
    pooled = np.concatenate(pooled_equity)
    return {
        "rows": rows,
        "scores": scores,
        "labels": labels,
        "alerts": {
            "crisis_onsets": onsets,
            "onsets_with_prior_alert": hits,
            "amber_or_red_share_of_months": amber_months / max(total_months, 1),
            "red_share_of_months": red_months / max(total_months, 1),
        },
        "stylised_facts": {
            "equity_volatility_annual": float(pooled.std() * math.sqrt(12.0)),
            "equity_excess_kurtosis": _excess_kurtosis(pooled),
            "equity_bond_correlation_outside_crisis": float(np.mean(corr_calm)),
            "equity_bond_correlation_in_crisis": float(np.mean(corr_crisis))
            if corr_crisis
            else None,
            "mean_crisis_share": float(np.mean([r["crisis_share"] for r in rows])),
            "mean_failed_banks": float(np.mean([r["failed_banks"] for r in rows])),
            "share_of_runs_with_a_bank_failure": float(
                np.mean([r["failed_banks"] > 0 for r in rows])
            ),
            "mean_min_output_gap": float(np.mean([r["min_output_gap"] for r in rows])),
            "mean_peak_unemployment": float(np.mean([r["peak_unemployment"] for r in rows])),
        },
    }


def _welch(a: np.ndarray, b: np.ndarray, confidence: float = 0.95) -> dict[str, float]:
    diff = float(a.mean() - b.mean())
    se = math.sqrt(float(a.var(ddof=1)) / a.size + float(b.var(ddof=1)) / b.size)
    z = 1.959964 if confidence == 0.95 else 2.5
    return {"estimate": diff, "low": diff - z * se, "high": diff + z * se, "confidence": confidence}


def _auc_interval(
    scores: list[np.ndarray], labels: list[np.ndarray], n_resamples: int = 500, seed: int = 7
) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    n = len(scores)
    point = monitor.auc(np.concatenate(scores), np.concatenate(labels))
    draws = []
    for _ in range(n_resamples):
        pick = rng.integers(0, n, size=n)
        draws.append(
            monitor.auc(
                np.concatenate([scores[i] for i in pick]), np.concatenate([labels[i] for i in pick])
            )
        )
    finite = [d for d in draws if not math.isnan(d)]
    low, high = np.quantile(finite, [0.025, 0.975]) if finite else (math.nan, math.nan)
    return {"estimate": point, "low": float(low), "high": float(high), "confidence": 0.95}


def run_study(n_seeds: int = N_SEEDS, n_months: int = 240) -> dict[str, Any]:
    seeds = list(range(n_seeds))
    configs = {name: replace(scenario(name), n_months=n_months) for name in SCENARIOS}
    results = {name: run_scenario(config, seeds) for name, config in configs.items()}

    def column(name: str, rule: str, key: str) -> np.ndarray:
        return np.array([r["rules"][rule][key] for r in results[name]["rows"]])

    # W-A: drawdown against equal weight, volatile scenario
    w_a: dict[str, Any] = {}
    for rule in RULES[1:]:
        gain = column("volatile", rule, "max_drawdown") - column(
            "volatile", "equal_weight", "max_drawdown"
        )
        cagr = column("volatile", rule, "cagr") - column("volatile", "equal_weight", "cagr")
        interval = t_interval(gain, BONFERRONI).as_dict()
        w_a[rule] = {
            "drawdown_gain_vs_equal_weight": interval,
            "median_drawdown": float(np.median(column("volatile", rule, "max_drawdown"))),
            "median_cagr": float(np.median(column("volatile", rule, "cagr"))),
            "cagr_difference_vs_equal_weight": t_interval(cagr, BONFERRONI).as_dict(),
            "verdict": verdict(interval["low"], interval["high"]),
        }
    w_a["equal_weight"] = {
        "median_drawdown": float(np.median(column("volatile", "equal_weight", "max_drawdown"))),
        "median_cagr": float(np.median(column("volatile", "equal_weight", "cagr"))),
    }

    # W-B: top-decile share, stressed minus calm
    w_b_interval = _welch(
        column("stressed", "equal_weight", "top10_end"), column("calm", "equal_weight", "top10_end")
    )

    # W-C: fire-sale ablation in the stressed scenario
    off = replace(configs["stressed"], market=replace(configs["stressed"].market, price_impact=0.0))
    ablation = run_scenario(off, seeds)
    failed_on = np.array([r["failed_banks"] for r in results["stressed"]["rows"]], dtype=float)
    failed_off = np.array([r["failed_banks"] for r in ablation["rows"]], dtype=float)
    w_c_interval = t_interval(failed_on - failed_off, 0.95).as_dict()

    # W-D: warning AUC
    auc_by_scenario = {
        name: _auc_interval(results[name]["scores"], results[name]["labels"]) for name in SCENARIOS
    }

    summary: dict[str, Any] = {}
    for name in SCENARIOS:
        per_rule: dict[str, Any] = {}
        for rule in RULES:
            per_rule[rule] = {
                "median_cagr": float(np.median(column(name, rule, "cagr"))),
                "median_max_drawdown": float(np.median(column(name, rule, "max_drawdown"))),
                "p5_max_drawdown": float(np.quantile(column(name, rule, "max_drawdown"), 0.05)),
                "mean_gini_end": float(column(name, rule, "gini_end").mean()),
                "mean_top10_end": float(column(name, rule, "top10_end").mean()),
                "mean_bottom50_end": float(column(name, rule, "bottom50_end").mean()),
            }
        summary[name] = {
            "stylised_facts": results[name]["stylised_facts"],
            "alerts": results[name]["alerts"],
            "rules": per_rule,
            "auc_crisis_within_6_months": auc_by_scenario[name],
        }

    return {
        "study": "worldsim_study (PR-223)",
        "n_seeds": n_seeds,
        "n_months": n_months,
        "scenarios": summary,
        "hypotheses": {
            "W-A_some_rule_has_shallower_drawdown_than_equal_weight_volatile": {
                "verdict": "SUPPORTED"
                if any(w_a[r]["verdict"] == "SUPPORTED" for r in RULES[1:])
                else "CONTRADICTED"
                if all(w_a[r]["verdict"] == "CONTRADICTED" for r in RULES[1:])
                else "INCONCLUSIVE",
                "by_rule": w_a,
            },
            "W-B_crises_concentrate_wealth_stressed_minus_calm_top10_share": {
                "interval": w_b_interval,
                "verdict": verdict(w_b_interval["low"], w_b_interval["high"]),
            },
            "W-C_fire_sales_amplify_bank_failures_stressed": {
                "mean_failed_banks_with_feedback": float(failed_on.mean()),
                "mean_failed_banks_without_feedback": float(failed_off.mean()),
                "difference_interval": w_c_interval,
                "verdict": verdict(w_c_interval["low"], w_c_interval["high"]),
            },
            "W-D_warning_composite_has_information_volatile": {
                "auc": auc_by_scenario["volatile"],
                "verdict": verdict(
                    auc_by_scenario["volatile"]["low"], auc_by_scenario["volatile"]["high"], 0.5
                ),
            },
        },
        "caveats": [
            "A simulation with chosen, not estimated, parameters: results describe the simulator.",
            "Households are price takers; one rule applies to every participating household.",
            "The crisis regime is an exogenous Markov chain; the warning composite can detect its "
            "precursors (slowdown, volatility, stressed banks) but not cause or avert a crisis.",
            "No taxes, fiscal policy, firms' balance sheets, foreign sector or bank bail-outs.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=N_SEEDS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seeds < 5:
        parser.error("--seeds must be at least 5")
    report = run_study(args.seeds)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
