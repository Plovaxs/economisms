"""Model zoo, tranche 3: structural macro, portfolio decisions, production networks, causal
effects and
survival, each judged against an exact answer, a classical method or the plain alternative.

Written down BEFORE the numbers were produced (the commit that adds this file has no results file).

What I had looked at before writing this: one run of each component on development seeds
72950-72960,
to see that the code ran. It showed: the deep equilibrium net and value-function iteration about
equally
accurate in both economies; the long-only QP layer's gradient matching finite differences to eight
digits; the decision-focused predictor ahead of the two-stage one and both behind minimum variance
on a
validation window (2000-2012); the 3-layer graph network well ahead of the same-reach truncated
series
on a larger graph; double ML near the true effect while OLS was not; DeepIV behind plain OLS on a
curve
metric; and DeepSurv ahead of the linear Cox model. Some claims below are ones that smoke run made
look likely to fail. The 2013-2026 portfolio test window had not been looked at.

Decision rules (`modelzoo.verdicts`): a paired difference is SUPPORTED if its 95% interval lies
wholly on
the claimed side of zero, CONTRADICTED if wholly on the other, INCONCLUSIVE otherwise; a size
claim is
judged on the median. Portfolio comparisons use a 12-month moving-block bootstrap on the monthly
returns.

STRUCTURAL MACRO (5 seeds, 3,000 steps; `modelzoo.structural`):
  Z-M1  Closed-form economy: the deep equilibrium net's mean absolute error in the savings rate
  against
        the exact alpha*beta is at most 0.005 (contradicted above 0.02).
  Z-M2  Closed-form economy: the net's mean log10 Euler error is lower than value-function
  iteration's
        (200 capital points, 7 productivity states).
  Z-M3  General economy (gamma = 2, delta = 10%, no closed form): the same claim as Z-M2.

PORTFOLIO (5 seeds, three Fama-French factor portfolios, features and a shrunk 60-month covariance
known
at the start of each month; fitted on months to 1999-12; evaluated on 2013-01 to the end of the
data;
risk aversion 4 and 15 epochs fixed in advance; `modelzoo.portfolio`):
  Z-P1  Decision-focused learning has a higher out-of-sample Sharpe ratio than the two-stage
        (predict, then optimise) predictor.
  Z-P2  Decision-focused learning has a higher Sharpe ratio than the equal-weight portfolio.
  Z-P3  The minimum-variance portfolio, which forecasts no returns at all, has a higher Sharpe
  ratio than
        decision-focused learning. (My prior: yes.)
  Z-P4  The QP layer's gradient equals a finite-difference gradient to within 1e-5 on 20 random
  cases.

PRODUCTION NETWORK (5 seeds; train on 60 simulated networks of 30 sectors; test on 20 unseen
networks of
60 sectors; the networks are SIMULATED; `modelzoo.networks`):
  Z-G1  A 3-layer graph network has a lower relative error than the 3-term truncated series (the
  same
        reach) on the larger unseen networks.
  Z-G2  A 3-layer graph network has a lower relative error than the same network with the graph
  removed.
  Z-G3  Error does not grow with size: the ratio of the 60-sector error to the 30-sector error is
  at most
        2 (judged on the median over seeds).

CAUSAL AND SURVIVAL (simulated data with a known truth; `modelzoo.causal`):
  Z-C1  Double ML (n = 1,000, 2-fold cross-fitting, 20 replications) has a smaller absolute error
  in the
        effect theta = 0.5 than OLS.
  Z-C2  DeepIV (n = 2,000, 10 replications) recovers the nonlinear structural curve with a lower
  RMSE than
        linear two-stage least squares.
  Z-C3  DeepIV recovers it with a lower RMSE than OLS. (The smoke run made this look unlikely.)
  Z-S1  DeepSurv (10 replications, 1,500 training and 1,500 test subjects, 25% censoring) has a
  higher
        test concordance index than the linear Cox model.
  Z-S2  DeepSurv's concordance is within 0.03 of the true risk score's own (supported;
  contradicted if
        more than 0.06 below), judged on the median.

Everything about the portfolio uses real monthly data; everything about production networks, causal
effects and survival uses simulated data and says nothing about any real economy. Seeds
73000-73999 are
reserved for this study.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import torch

from prometheus.experiments.block_bootstrap import moving_block_bootstrap
from prometheus.modelzoo import causal as cz
from prometheus.modelzoo import networks as nw
from prometheus.modelzoo import portfolio as pf
from prometheus.modelzoo import structural as st
from prometheus.modelzoo.verdicts import summarise_difference, threshold_verdict

DATA = Path(__file__).resolve().parents[3] / "data_cache" / "ff3_monthly_snapshot.csv"
OUTPUT_DIR = Path(__file__).resolve().parents[3] / "docs" / "numerics"
RISK_AVERSION = 4.0
PORTFOLIO_EPOCHS = 15
TRAIN_END = 199912
TEST_START = 201301


def _sharpe_difference_ci(
    first: np.ndarray, second: np.ndarray, seed: int, resamples: int
) -> dict[str, Any]:
    """Sharpe(first) - Sharpe(second) with a 12-month moving-block-bootstrap interval."""
    index = np.arange(len(first), dtype=float)

    def metric(idx: np.ndarray) -> float:
        i = idx.astype(int)
        return pf.sharpe(first[i]) - pf.sharpe(second[i])

    boot = moving_block_bootstrap(
        metric, index, 12, np.random.default_rng(seed), n_resamples=resamples
    )
    if boot.ci_low > 0.0:
        verdict = "SUPPORTED"
    elif boot.ci_high < 0.0:
        verdict = "CONTRADICTED"
    else:
        verdict = "INCONCLUSIVE"
    return {
        "sharpe_first": pf.sharpe(first),
        "sharpe_second": pf.sharpe(second),
        "difference": boot.point_estimate,
        "ci_low": boot.ci_low,
        "ci_high": boot.ci_high,
        "verdict": verdict,
    }


def structural_study(
    seeds: tuple[int, ...] = tuple(range(73000, 73005)), *, steps: int = 3000
) -> dict[str, Any]:
    out: dict[str, Any] = {"seeds": list(seeds), "economies": {}}
    for name, economy in st.ECONOMIES.items():
        vfi = st.solve_vfi(economy)
        k, log_z = st.evaluation_states(economy, 800, 73100)
        vfi_error = st.mean_log10_euler_error(economy, vfi, k, log_z)
        rows = []
        for seed in seeds:
            fit = st.train_deq(economy, steps=steps, seed=seed)
            row: dict[str, Any] = {
                "seed": seed,
                "deq_log10_euler": st.mean_log10_euler_error(economy, fit.net, k, log_z),
                "deq_seconds": fit.seconds,
            }
            if name == "closed_form":
                exact = st.exact_savings_rate()
                row["deq_policy_error"] = float(
                    np.abs(st.policy_values(fit.net, k, log_z) - exact).mean()
                )
            rows.append(row)
        entry: dict[str, Any] = {
            "vfi_log10_euler": vfi_error,
            "rows": rows,
            "advantage_over_vfi": summarise_difference(
                [vfi_error - r["deq_log10_euler"] for r in rows]
            ),
        }
        if name == "closed_form":
            exact = st.exact_savings_rate()
            entry["vfi_policy_error"] = float(
                np.abs(st.policy_values(vfi, k, log_z) - exact).mean()
            )
            median = float(np.median([r["deq_policy_error"] for r in rows]))
            entry["median_policy_error"] = median
            entry["policy_verdict"] = threshold_verdict(median, 0.005, 0.02)
        out["economies"][name] = entry
    out["Z-M1"] = out["economies"]["closed_form"]["policy_verdict"]
    out["Z-M2"] = out["economies"]["closed_form"]["advantage_over_vfi"]
    out["Z-M3"] = out["economies"]["general"]["advantage_over_vfi"]
    return out


def portfolio_study(
    seeds: tuple[int, ...] = tuple(range(73200, 73205)),
    *,
    epochs: int = PORTFOLIO_EPOCHS,
    resamples: int = 2000,
    gradient_cases: int = 20,
) -> dict[str, Any]:
    data = pf.load_factor_data(str(DATA))
    rows = np.arange(60, len(data.months))
    train = rows[data.months[rows] <= TRAIN_END]
    test = rows[data.months[rows] >= TEST_START]
    weights: dict[str, list[np.ndarray]] = {"two_stage": [], "dfl": []}
    for seed in seeds:
        for name, focused in (("two_stage", False), ("dfl", True)):
            net = pf.fit_predictor(
                data,
                train,
                decision_focused=focused,
                risk_aversion=RISK_AVERSION,
                epochs=epochs,
                seed=seed,
            )
            weights[name].append(pf.predicted_weights(net, data, train, test, RISK_AVERSION))
    returns = {
        name: pf.strategy_returns(data, test, np.mean(w, axis=0)) for name, w in weights.items()
    }
    returns["min_variance"] = pf.strategy_returns(data, test, pf.min_variance_weights(data, test))
    returns["equal_weight"] = data.returns[test].mean(axis=1)
    # gradient check against finite differences
    rng = np.random.default_rng(73299)
    worst = 0.0
    for _ in range(gradient_cases):
        sample = rng.standard_normal((200, 3))
        cov = torch.as_tensor(np.cov(sample.T)[None] * 0.01 + 1e-4 * np.eye(3), dtype=torch.float64)
        mu = torch.tensor(rng.normal(0, 0.01, (1, 3)), dtype=torch.float64, requires_grad=True)
        probe = torch.as_tensor(rng.standard_normal((1, 3)), dtype=torch.float64)
        w = pf.long_only_weights(mu, cov, RISK_AVERSION)
        grad = torch.autograd.grad((w * probe).sum(), mu)[0].numpy()[0]
        for i in range(3):
            shifted = mu.detach().clone()
            shifted[0, i] += 1e-7
            w2 = pf.long_only_weights(shifted, cov, RISK_AVERSION)
            fd = float(((w2 - w) * probe).sum() / 1e-7)
            worst = max(worst, abs(fd - float(grad[i])))
    return {
        "seeds": list(seeds),
        "test_months": int(len(test)),
        "sharpe": {k: pf.sharpe(v) for k, v in returns.items()},
        "Z-P1": _sharpe_difference_ci(returns["dfl"], returns["two_stage"], 73290, resamples),
        "Z-P2": _sharpe_difference_ci(returns["dfl"], returns["equal_weight"], 73290, resamples),
        "Z-P3": _sharpe_difference_ci(returns["min_variance"], returns["dfl"], 73290, resamples),
        "Z-P4": "SUPPORTED" if worst < 1e-5 else "CONTRADICTED",
        "Z-P4_worst_gradient_difference": worst,
    }


def network_study(
    seeds: tuple[int, ...] = tuple(range(73300, 73305)),
    *,
    epochs: int = 40,
    train_graphs: int = 60,
    test_graphs: int = 20,
) -> dict[str, Any]:
    rows = []
    for seed in seeds:
        train = [nw.make_graph_batch(30, 16, seed=seed * 100 + i) for i in range(train_graphs)]
        small = [
            nw.make_graph_batch(30, 16, seed=seed * 100 + 5000 + i) for i in range(test_graphs)
        ]
        large = [
            nw.make_graph_batch(60, 16, seed=seed * 100 + 9000 + i) for i in range(test_graphs)
        ]
        gnn = nw.ShockGNN(layers=3)
        nw.train_gnn(gnn, train, epochs=epochs, seed=seed)
        blind = nw.ShockGNN(layers=3, use_graph=False)
        nw.train_gnn(blind, train, epochs=epochs, seed=seed)
        rows.append(
            {
                "seed": seed,
                "gnn_30": float(np.mean([nw.evaluate_gnn(gnn, g) for g in small])),
                "gnn_60": float(np.mean([nw.evaluate_gnn(gnn, g) for g in large])),
                "blind_60": float(np.mean([nw.evaluate_gnn(blind, g) for g in large])),
                "truncated3_60": float(np.mean([nw.evaluate_truncation(g, 3) for g in large])),
                "truncated12_60": float(np.mean([nw.evaluate_truncation(g, 12) for g in large])),
            }
        )

    def col(key: str) -> np.ndarray:
        return np.array([r[key] for r in rows])

    ratio = float(np.median(col("gnn_60") / col("gnn_30")))
    return {
        "seeds": list(seeds),
        "rows": rows,
        "Z-G1": summarise_difference(col("truncated3_60") - col("gnn_60")),
        "Z-G2": summarise_difference(col("blind_60") - col("gnn_60")),
        "Z-G3": threshold_verdict(ratio, 2.0, 4.0),
        "Z-G3_median_ratio": ratio,
    }


def causal_study(
    *,
    dml_replications: int = 20,
    iv_replications: int = 10,
    survival_replications: int = 10,
    dml_epochs: int = 40,
    iv_epochs: int = 400,
    survival_epochs: int = 300,
) -> dict[str, Any]:
    dml_rows = []
    for r in range(dml_replications):
        data = cz.make_partially_linear(1000, seed=73400 + r)
        dml_rows.append(
            {
                "ols_error": abs(cz.ols_effect(data) - cz.TRUE_THETA),
                "dml_error": abs(
                    cz.double_ml_effect(data, epochs=dml_epochs, seed=73450 + r) - cz.TRUE_THETA
                ),
            }
        )
    grid = np.linspace(-1.5, 1.5, 50)
    iv_rows = []
    for r in range(iv_replications):
        data_iv = cz.make_iv_data(2000, seed=73500 + r)
        net = cz.deep_iv_fit(data_iv, epochs=iv_epochs, seed=73550 + r)
        iv_rows.append(
            {
                "deepiv": cz.curve_rmse(cz.deep_iv_curve(net, grid), grid),
                "two_sls": cz.curve_rmse(cz.two_stage_least_squares_curve(data_iv, grid), grid),
                "ols": cz.curve_rmse(cz.ols_curve(data_iv, grid), grid),
            }
        )
    surv_rows = []
    for r in range(survival_replications):
        train = cz.make_survival(1500, seed=73600 + r)
        test = cz.make_survival(1500, seed=73650 + r)
        row: dict[str, float] = {"oracle": cz.concordance(test.true_risk, test.time, test.event)}
        for name, hidden in (("cox", 0), ("deepsurv", 32)):
            net = cz.fit_cox(train, hidden=hidden, epochs=survival_epochs, seed=73700 + r)
            row[name] = cz.concordance(cz.risk_scores(net, test.x), test.time, test.event)
        surv_rows.append(row)

    def c(rows: list[dict[str, float]], key: str) -> np.ndarray:
        return np.array([x[key] for x in rows])

    gap = float(np.median(c(surv_rows, "oracle") - c(surv_rows, "deepsurv")))
    return {
        "dml_rows": dml_rows,
        "iv_rows": iv_rows,
        "survival_rows": surv_rows,
        "Z-C1": summarise_difference(c(dml_rows, "ols_error") - c(dml_rows, "dml_error")),
        "Z-C2": summarise_difference(c(iv_rows, "two_sls") - c(iv_rows, "deepiv")),
        "Z-C3": summarise_difference(c(iv_rows, "ols") - c(iv_rows, "deepiv")),
        "Z-S1": summarise_difference(c(surv_rows, "deepsurv") - c(surv_rows, "cox")),
        "Z-S2": threshold_verdict(gap, 0.03, 0.06),
        "Z-S2_median_gap_to_oracle": gap,
    }


STUDIES: dict[str, Callable[[], dict[str, Any]]] = {
    "structural": structural_study,
    "portfolio": portfolio_study,
    "networks": network_study,
    "causal": causal_study,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Model zoo tranche 3 study")
    parser.add_argument("family", choices=sorted(STUDIES))
    parser.add_argument("--threads", type=int, default=3)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    start = time.perf_counter()
    result = STUDIES[args.family]()
    result["family"] = args.family
    result["wall_seconds"] = time.perf_counter() - start
    path = OUTPUT_DIR / f"modelzoo_macro_{args.family}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
