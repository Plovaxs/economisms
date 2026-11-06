"""Champion/challenger comparison report (MLO-14: "support comparison
against last approved champion model"; acceptance criterion: "champion/
challenger report generated with matched data").

The champion must genuinely BE the "last approved" model, not merely a
caller-asserted label: `build_champion_challenger_report` checks the
champion's `model_registry.ModelRegistryEntry.history` (MLO-08) for at
least one `approved` transition, reusing that registry's own audit
trail rather than trusting an unchecked claim, and raises
`ChampionNeverApprovedError` if none exists.

"Matched data" is enforced, not assumed: `champion_outcomes` and
`challenger_outcomes` must have identical shape, since the whole point
of a paired comparison is that both models were evaluated on the SAME
underlying scenarios, index for index. The comparison itself reuses
`experiments.bootstrap.paired_bootstrap_difference` (not reinvented)
to get a confidence interval on the metric DIFFERENCE
(challenger - champion); `higher_is_better` has no default, since
getting it backwards would silently invert which model the report
concludes is better -- the same reasoning this project applies
elsewhere to any field whose default could silently change a
conclusion (e.g. `service.reports`'s `measure` field, AUD-04).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from prometheus.evidence.model_package import ModelPackage
from prometheus.evidence.model_registry import ModelRegistryEntry
from prometheus.experiments.bootstrap import BootstrapResult, paired_bootstrap_difference


class ChampionNeverApprovedError(ValueError):
    """Raised when the champion's registry entry has no `approved`
    transition anywhere in its history."""


@dataclass(frozen=True, slots=True)
class ChampionChallengerReport:
    champion: ModelPackage
    challenger: ModelPackage
    metric_name: str
    comparison: BootstrapResult
    challenger_is_better: bool


def build_champion_challenger_report(
    champion: ModelPackage,
    champion_entry: ModelRegistryEntry,
    challenger: ModelPackage,
    metric_fn: Callable[[np.ndarray], float],
    champion_outcomes: np.ndarray,
    challenger_outcomes: np.ndarray,
    metric_name: str,
    rng: np.random.Generator,
    higher_is_better: bool,
) -> ChampionChallengerReport:
    if not any(t.to_state == "approved" for t in champion_entry.history):
        raise ChampionNeverApprovedError(
            f"{champion.model_id}@{champion.model_version}: its registry entry has never been "
            "approved -- cannot serve as the 'last approved champion' to compare against"
        )
    if champion_outcomes.shape != challenger_outcomes.shape:
        raise ValueError(
            "champion_outcomes and challenger_outcomes must have matching shape -- this "
            "comparison requires MATCHED data, evaluated on the same underlying scenarios"
        )
    comparison = paired_bootstrap_difference(
        metric_fn, challenger_outcomes, champion_outcomes, rng
    )
    challenger_is_better = (
        comparison.ci_low > 0.0 if higher_is_better else comparison.ci_high < 0.0
    )
    return ChampionChallengerReport(
        champion=champion,
        challenger=challenger,
        metric_name=metric_name,
        comparison=comparison,
        challenger_is_better=challenger_is_better,
    )
