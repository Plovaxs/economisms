"""UIX-07: "Implement experiment comparison with CI and negative results
-- No cherry-picked score-only presentations by default."

Every row below is a REAL, already-evidenced result copied from
`docs/RESULTS_AND_LIMITATIONS.md` (PR-142/143/150), not re-derived or
invented for this view -- each one names the PR it traces to, so a
reader can verify it against this repository's own ledger. Deliberately
includes every real "not significant" / "no significant difference"
finding alongside the ones with a clear winner: a view that only
rendered the flattering comparisons would itself BE the cherry-picking
this item exists to prevent. `render_experiment_comparison` always
prints the `verdict` field (never omits it for a null result) and
always prints the confidence interval alongside the point estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus.dashboard.html import page, table
from prometheus.dashboard.provenance import real_data_badge


@dataclass(frozen=True, slots=True)
class ExperimentComparisonRow:
    experiment: str
    metric_name: str
    champion_value: str
    challenger_value: str
    ci_or_spread: str
    verdict: str
    source_pr: str

    def __post_init__(self) -> None:
        for name, value in (
            ("experiment", self.experiment),
            ("verdict", self.verdict),
            ("source_pr", self.source_pr),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")


REAL_COMPARISON_LOG: tuple[ExperimentComparisonRow, ...] = (
    ExperimentComparisonRow(
        experiment="RECESSIONNET: logistic regression vs. hybrid-quantum classifier",
        metric_name="Brier score (lower is better)",
        champion_value="~0.083 (best classical challenger)",
        challenger_value="~0.087 (hybrid quantum, seed=0)",
        ci_or_spread="4 of 5 seeds statistically inconclusive",
        verdict="NOT SIGNIFICANT -- no robust quantum advantage found",
        source_pr="PR-142",
    ),
    ExperimentComparisonRow(
        experiment="Q-MACRO: AR(3)/classical-MLP vs. hybrid-quantum regressor",
        metric_name="MASE (lower is better)",
        champion_value="~0.62 (AR(3)/MLP, both beat persistence ~0.89)",
        challenger_value="~0.62 (hybrid quantum, within the same tight band)",
        ci_or_spread="no significant difference across 5 seeds checked",
        verdict="NOT SIGNIFICANT -- architecture did not matter once beating persistence",
        source_pr="PR-143",
    ),
    ExperimentComparisonRow(
        experiment="RECESSIONNET on real Kaggle-sourced macro data",
        metric_name="classification performance vs. base rate",
        champion_value="base rate (strongest classical candidate on this split)",
        challenger_value="hybrid quantum",
        ci_or_spread="no significant difference vs. base rate",
        verdict="NOT SIGNIFICANT -- base rate was the strongest candidate here",
        source_pr="PR-145",
    ),
    ExperimentComparisonRow(
        experiment="Neural SDE vs. GBM baseline, real 2020 COVID OOD window",
        metric_name="log-score degradation (lower is better)",
        champion_value="+29.97 (GBM baseline)",
        challenger_value="+5.58 (neural SDE)",
        ci_or_spread="single real historical OOD window, not a multi-seed CI",
        verdict="GENUINE IMPROVEMENT -- regime-conditioning measurably helped under a real shock",
        source_pr="PR-150",
    ),
)


def render_experiment_comparison(
    rows: tuple[ExperimentComparisonRow, ...] = REAL_COMPARISON_LOG,
) -> str:
    table_rows = [
        [
            r.experiment,
            r.metric_name,
            r.champion_value,
            r.challenger_value,
            r.ci_or_spread,
            r.verdict,
            r.source_pr,
        ]
        for r in rows
    ]
    body = (
        real_data_badge("docs/RESULTS_AND_LIMITATIONS.md")
        + "<p>Every real comparison this repository has run, including every "
        "null/negative result -- not a selected subset.</p>"
        + table(
            [
                "experiment",
                "metric",
                "champion",
                "challenger",
                "CI / spread",
                "verdict",
                "source PR",
            ],
            table_rows,
        )
    )
    return page("Experiment comparison", "Experiment comparison (CI and negative results)", body)
