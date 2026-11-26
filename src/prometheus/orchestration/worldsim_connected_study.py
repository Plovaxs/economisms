"""One interconnected economy: deposit insurance, sovereign default and rising inequality (PR-225).

Finding 26 left three things out and its sectors only talked one way. In the connected world they
all feed back on each other: households' consumption moves output, bank failures cost the state
(deposit insurance) and the rich (uninsured deposits), banks hold the state's bonds so a sovereign
default hits them, the state's taxes and transfers come from the households' own incomes, firm
distress raises unemployment, and the central bank can lean against leverage. Eight questions, each
with its prediction, were written BEFORE the final run; every comparison is paired on the same
random draws. 200 seeds of 240 months. Decision rule: SUPPORTED if the whole 95% interval lies on
the predicted side of zero, CONTRADICTED if wholly on the other, INCONCLUSIVE otherwise.

  C-A  Counting what failures cost the state (deposit insurance, output lost), does recapitalising
         end with LOWER public debt than doing nothing? (stressed; predicted: yes)
  C-B  Does connecting the sectors make the worst output gap worse than the same economy
         unconnected? (stressed; predicted: yes)
  C-C  Do banks' holdings of government bonds raise bank failures when the state is under stress,
         the doom loop? (sovereign stress; predicted: yes)
  C-D  Do the inequality forces make the Gini rise over 20 years? (rising inequality; predicted:
         yes)
  C-E  Do progressive income taxes plus a wealth tax lower the top-decile wealth share at the end?
         (rising inequality; predicted: yes)
  C-F  Does leaning the policy rate against firm leverage lower bank failures? (stressed;
         predicted: yes)
  C-G  Do uninsured deposit losses fall on the rich, so that full insurance leaves them with a
         larger share of wealth? (stressed; predicted: yes)
  C-H  Does the consumption-to-output link make the worst output gap worse? (stressed; predicted:
         yes)

Beyond the questions it reports the impulse-response matrix of seven shocks over eleven outcomes in
the connected world and in the unconnected one (the share of cells whose interval excludes zero is
the measure of how connected the system is), the calibration check and a sensitivity table.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from prometheus.orchestration.worldsim_extended_study import _paired
from prometheus.worldsim import impulse, sensitivity
from prometheus.worldsim.config import (
    CRISIS,
    WorldConfig,
    connected_scenario,
    full_scenario,
)
from prometheus.worldsim.world import simulate_world

N_SEEDS = 200
SENSITIVITY_PARAMETERS: tuple[str, ...] = (
    "banks.deposit_funding",
    "banks.loss_given_default",
    "links.demand_coupling",
    "links.haircut",
    "links.bank_sovereign_share",
    "links.insured_share",
    "links.firm_unemployment",
    "fiscal.multiplier",
    "fiscal.initial_debt",
    "firms.default_sensitivity",
)


def _row(args: tuple[WorldConfig, int]) -> dict[str, float]:
    config, seed = args
    path = simulate_world(config, seed)
    gdp = config.fiscal.gdp_scale
    first_default = int(np.argmax(path.sovereign_default)) if path.sovereign_default.any() else -1
    failing = np.where(path.bank_failed.any(axis=1))[0]
    default_first = float(
        first_default >= 0 and (failing.size == 0 or first_default < int(failing[0]))
    )
    return {
        "default_first": default_first,
        "failed_banks": float(path.bank_failed[-1].sum()),
        "min_output_gap": float(path.output_gap.min()),
        "peak_unemployment": float(path.unemployment.max()),
        "debt_end": float(path.debt_ratio[-1]),
        "debt_max": float(path.debt_ratio.max()),
        "defaulted": float(path.sovereign_default.any()),
        "insurance_cost_gdp": float(path.deposit_insurance_cost.sum() / gdp),
        "injection_gdp": float(path.injection.sum() / gdp),
        "crisis_share": float((path.regime == CRISIS).mean()),
        "gini_start": float(path.gini[0]),
        "gini_end": float(path.gini[-1]),
        "top10_start": float(path.top10_share[0]),
        "top10_end": float(path.top10_share[-1]),
    }


def run_arm(config: WorldConfig, seeds: Sequence[int], workers: int) -> dict[str, np.ndarray]:
    jobs = [(config, seed) for seed in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_row, jobs, chunksize=8))
    else:
        rows = [_row(job) for job in jobs]
    return {key: np.array([r[key] for r in rows]) for key in rows[0]}


def run_study(
    n_seeds: int = N_SEEDS,
    workers: int = 1,
    impulse_seeds: int = 60,
    sensitivity_seeds: int = 30,
) -> dict[str, Any]:
    seeds = list(range(n_seeds))
    stressed = connected_scenario("stressed_connected")
    sovereign = connected_scenario("sovereign_stress")
    inequality = connected_scenario("rising_inequality")
    taxed = replace(
        inequality,
        links=replace(inequality.links, tax_progressivity=0.3, wealth_tax_rate=0.01),
    )
    configs: dict[str, WorldConfig] = {
        "stressed_connected/none": stressed,
        "stressed_connected/recapitalise": connected_scenario(
            "stressed_connected", mode="recapitalise"
        ),
        "stressed_full (unconnected)": full_scenario("stressed_full"),
        "sovereign_stress": sovereign,
        "sovereign_stress, banks hold no government bonds": replace(
            sovereign, links=replace(sovereign.links, bank_sovereign_share=0.0)
        ),
        "rising_inequality": inequality,
        "rising_inequality, progressive and wealth taxes": taxed,
        "stressed_connected, leaning against leverage": replace(
            stressed, links=replace(stressed.links, financial_stability_phi=0.1)
        ),
        "stressed_connected, deposits fully insured": replace(
            stressed, links=replace(stressed.links, insured_share=1.0)
        ),
        "stressed_connected, no consumption link": replace(
            stressed, links=replace(stressed.links, demand_coupling=0.0)
        ),
        "volatile_connected": connected_scenario("volatile_connected"),
    }
    arms = {name: run_arm(config, seeds, workers) for name, config in configs.items()}

    base = arms["stressed_connected/none"]
    hypotheses = {
        "C-A_recapitalisation_ends_with_lower_public_debt_counting_failure_costs": _paired(
            base["debt_end"], arms["stressed_connected/recapitalise"]["debt_end"]
        ),
        "C-B_connecting_the_sectors_worsens_the_worst_output_gap": _paired(
            arms["stressed_full (unconnected)"]["min_output_gap"], base["min_output_gap"]
        ),
        "C-C_banks_holding_government_bonds_raise_failures_under_sovereign_stress": _paired(
            arms["sovereign_stress"]["failed_banks"],
            arms["sovereign_stress, banks hold no government bonds"]["failed_banks"],
        ),
        "C-D_inequality_forces_raise_the_gini": _paired(
            arms["rising_inequality"]["gini_end"], arms["rising_inequality"]["gini_start"]
        ),
        "C-E_progressive_and_wealth_taxes_lower_the_top_decile_share": _paired(
            arms["rising_inequality"]["top10_end"],
            arms["rising_inequality, progressive and wealth taxes"]["top10_end"],
        ),
        "C-F_leaning_against_leverage_lowers_bank_failures": _paired(
            base["failed_banks"],
            arms["stressed_connected, leaning against leverage"]["failed_banks"],
        ),
        "C-G_full_insurance_leaves_the_rich_with_a_larger_share": _paired(
            arms["stressed_connected, deposits fully insured"]["top10_end"], base["top10_end"]
        ),
        "C-H_the_consumption_link_worsens_the_worst_output_gap": _paired(
            arms["stressed_connected, no consumption link"]["min_output_gap"],
            base["min_output_gap"],
        ),
    }
    secondary = {
        "C-B_failed_banks_connected_minus_unconnected": _paired(
            base["failed_banks"], arms["stressed_full (unconnected)"]["failed_banks"]
        ),
        "C-D_top10_share_end_minus_start": _paired(
            arms["rising_inequality"]["top10_end"], arms["rising_inequality"]["top10_start"]
        ),
        "C-E_cost_worst_output_gap_taxed_minus_untaxed": _paired(
            arms["rising_inequality, progressive and wealth taxes"]["min_output_gap"],
            arms["rising_inequality"]["min_output_gap"],
        ),
        "C-A_failure_costs_in_gdp_none_minus_recapitalise": _paired(
            base["insurance_cost_gdp"] + base["injection_gdp"],
            arms["stressed_connected/recapitalise"]["insurance_cost_gdp"]
            + arms["stressed_connected/recapitalise"]["injection_gdp"],
        ),
    }
    summary = {
        name: {
            "mean_failed_banks": float(a["failed_banks"].mean()),
            "share_of_runs_with_failure": float((a["failed_banks"] > 0).mean()),
            "share_of_runs_with_sovereign_default": float(a["defaulted"].mean()),
            "share_of_defaults_before_any_bank_failure": float(
                float(a["default_first"].sum()) / max(float(a["defaulted"].sum()), 1.0)
            ),
            "mean_min_output_gap": float(a["min_output_gap"].mean()),
            "mean_peak_unemployment": float(a["peak_unemployment"].mean()),
            "mean_debt_end": float(a["debt_end"].mean()),
            "mean_deposit_insurance_cost_gdp": float(a["insurance_cost_gdp"].mean()),
            "mean_injection_gdp": float(a["injection_gdp"].mean()),
            "mean_gini_start": float(a["gini_start"].mean()),
            "mean_gini_end": float(a["gini_end"].mean()),
            "mean_top10_share_start": float(a["top10_start"].mean()),
            "mean_top10_share_end": float(a["top10_end"].mean()),
        }
        for name, a in arms.items()
    }
    shock_seeds = list(range(impulse_seeds))
    responses = {
        "connected": impulse.impulse_matrix(
            connected_scenario("volatile_connected"), shock_seeds, workers=workers
        ),
        "unconnected": impulse.impulse_matrix(
            full_scenario("volatile_full"), shock_seeds, workers=workers
        ),
    }
    return {
        "study": "worldsim_connected_study (PR-225)",
        "n_seeds": n_seeds,
        "arms": summary,
        "hypotheses": hypotheses,
        "secondary": secondary,
        "impulse_responses": responses,
        "sensitivity_sovereign_stress_25_percent_moves": sensitivity.tornado(
            sovereign, seeds[:sensitivity_seeds], SENSITIVITY_PARAMETERS, workers=workers
        ),
        "caveats": [
            "A simulation with chosen, not estimated, parameters: results describe the simulator.",
            "Households hold one fixed passive portfolio inside the world; the allocation-rule "
            "comparison of Finding 25 replays a finished world.",
            "The crisis regime is still an exogenous random switch; sovereign default, bank "
            "failure "
            "and inequality respond to it but do not cause it.",
            "Deposit insurance is paid from the budget at once, with no premiums, fund or "
            "resolution authority; the tax system is one rate with a progressivity exponent.",
            "Impulse responses are means over seeds of the difference between paired worlds; "
            "a cell that excludes zero is a working channel, not a real-economy elasticity.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--seeds", type=int, default=N_SEEDS)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.seeds < 4 or args.workers < 1:
        parser.error("--seeds must be at least 4 and --workers at least 1")
    report = run_study(args.seeds, args.workers)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
