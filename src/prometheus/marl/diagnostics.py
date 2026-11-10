"""MAR-09: "Measure multi-agent nonstationarity and instability -- Report
policy drift and convergence diagnostics across seeds."
MAR-11: "Separate single-agent and co-learning experiments -- Ablation
isolates impact of simultaneous learning."
MAR-12: "Measure welfare distribution, inequality and outcomes --
Evaluation includes distributional and aggregate metrics."
MAR-13: "Evaluate unseen tax/monetary parameter shifts -- Held-out shock
performance reported with uncertainty."

MAR-09 and MAR-11 share one real experiment design, not two separate
ones: `single_vs_colearning_report` trains the household policy ALONE
(firm fixed-rule, MAR-11's "single-agent" condition) across several
seeds, then trains household+firm SIMULTANEOUSLY (MAR-11's "co-learning"
condition) across the SAME seeds, and reports the across-seed spread of
final evaluated household utility under each condition -- MAR-09's
"policy drift and convergence diagnostics across seeds" is exactly that
spread, read off the co-learning condition specifically (more seed-to-
seed variance there, if any, IS the nonstationarity signal MAR-09 asks
for, since the household is now chasing a moving target in the firm's
own concurrently-changing policy).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from prometheus.core.money import Money
from prometheus.marl.baselines import FixedWageRule
from prometheus.marl.env import run_rollout
from prometheus.marl.training import (
    deterministic_firm_policy,
    deterministic_household_policy,
    train_joint_ppo,
)

DEFAULT_FIRM_CAPITAL = Money(100_000, "USD")


@dataclass(frozen=True, slots=True)
class SeedOutcome:
    seed: int
    household_utility: float
    firm_profit: float


@dataclass(frozen=True, slots=True)
class SingleVsCoLearningReport:
    single_agent: tuple[SeedOutcome, ...]
    co_learning: tuple[SeedOutcome, ...]

    def _household_utilities(self, outcomes: tuple[SeedOutcome, ...]) -> list[float]:
        return [o.household_utility for o in outcomes]

    def single_agent_household_std(self) -> float:
        return statistics.pstdev(self._household_utilities(self.single_agent))

    def co_learning_household_std(self) -> float:
        return statistics.pstdev(self._household_utilities(self.co_learning))

    def mean_household_utility_delta(self) -> float:
        """Co-learning mean minus single-agent mean -- positive means
        co-learning helped the household on average, negative means it
        hurt; this function does not editorialize about which."""
        single_mean = statistics.mean(self._household_utilities(self.single_agent))
        co_mean = statistics.mean(self._household_utilities(self.co_learning))
        return co_mean - single_mean


def single_vs_colearning_report(
    *,
    seeds: tuple[int, ...],
    n_epochs: int = 30,
    episodes_per_epoch: int = 8,
    n_steps: int = 6,
    firm_opening_capital: Money = DEFAULT_FIRM_CAPITAL,
) -> SingleVsCoLearningReport:
    if not seeds:
        raise ValueError("seeds must be non-empty")
    single_outcomes = []
    co_outcomes = []
    for seed in seeds:
        single = train_joint_ppo(
            seed=seed, n_epochs=n_epochs, episodes_per_epoch=episodes_per_epoch, n_steps=n_steps,
            firm_opening_capital=firm_opening_capital, train_household=True, train_firm=False,
            firm_fixed_rule=FixedWageRule(0.5),
        )
        assert single.household_net is not None
        policy = deterministic_household_policy(single.household_net, n_steps)
        result = run_rollout(
            household_policy=policy, firm_policy=FixedWageRule(0.5), n_steps=n_steps,
            firm_opening_capital=firm_opening_capital,
        )
        single_outcomes.append(
            SeedOutcome(
                seed=seed,
                household_utility=result.total_household_utility(),
                firm_profit=0.0,
            )
        )

        co = train_joint_ppo(
            seed=seed, n_epochs=n_epochs, episodes_per_epoch=episodes_per_epoch, n_steps=n_steps,
            firm_opening_capital=firm_opening_capital, train_household=True, train_firm=True,
        )
        assert co.household_net is not None and co.firm_net is not None
        hh_policy = deterministic_household_policy(co.household_net, n_steps)
        fm_policy = deterministic_firm_policy(co.firm_net, n_steps)
        co_result = run_rollout(
            household_policy=hh_policy, firm_policy=fm_policy, n_steps=n_steps,
            firm_opening_capital=firm_opening_capital,
        )
        co_outcomes.append(
            SeedOutcome(
                seed=seed,
                household_utility=co_result.total_household_utility(),
                firm_profit=co_result.total_firm_profit(),
            )
        )
    return SingleVsCoLearningReport(
        single_agent=tuple(single_outcomes), co_learning=tuple(co_outcomes)
    )


def gini_coefficient(values: list[float]) -> float:
    """Standard Gini coefficient (mean absolute difference / (2 * mean)),
    0 = perfect equality, approaching 1 = maximal inequality. Defined as
    0.0 for an all-zero or empty population (no inequality to measure)."""
    if not values:
        raise ValueError("values must be non-empty")
    n = len(values)
    mean_value = sum(values) / n
    if mean_value == 0:
        return 0.0
    absolute_differences = sum(abs(a - b) for a in values for b in values)
    return absolute_differences / (2 * n * n * mean_value)


@dataclass(frozen=True, slots=True)
class WelfareReport:
    final_net_worths: tuple[float, ...]
    total_utilities: tuple[float, ...]

    def gini_of_final_net_worth(self) -> float:
        return gini_coefficient(list(self.final_net_worths))

    def aggregate_utility(self) -> float:
        return sum(self.total_utilities)

    def mean_utility(self) -> float:
        return sum(self.total_utilities) / len(self.total_utilities)


def welfare_report_across_heterogeneous_households(
    *,
    household_policy_fn: object,
    firm_opening_capitals: tuple[Money, ...],
    n_steps: int = 6,
) -> WelfareReport:
    """Population heterogeneity is modeled via each household facing a
    DIFFERENT, INDEPENDENT firm/opening-capital condition (a proxy for
    heterogeneous local economic conditions), not N households sharing
    one simultaneous firm -- a disclosed simplification, not a claim of
    a fully simultaneous multi-household market. `household_policy_fn`
    is called once per condition (a `HouseholdPolicy`-shaped callable);
    typed `object` here only because `env.HouseholdPolicy` is a
    `Callable` type alias Python does not let a dataclass field re-type
    narrowly without a protocol -- callers pass a real `HouseholdPolicy`."""
    if not firm_opening_capitals:
        raise ValueError("firm_opening_capitals must be non-empty")
    final_net_worths = []
    total_utilities = []
    for capital in firm_opening_capitals:
        result = run_rollout(
            household_policy=household_policy_fn,  # type: ignore[arg-type]
            firm_policy=FixedWageRule(0.5),
            n_steps=n_steps,
            firm_opening_capital=capital,
        )
        final_net_worths.append(result.final_household_net_worth_minor / 100.0)
        total_utilities.append(result.total_household_utility())
    return WelfareReport(
        final_net_worths=tuple(final_net_worths), total_utilities=tuple(total_utilities)
    )


@dataclass(frozen=True, slots=True)
class OODShockReport:
    in_distribution_utilities: tuple[float, ...]
    shocked_utilities: tuple[float, ...]

    def mean_degradation(self) -> float:
        in_mean = statistics.mean(self.in_distribution_utilities)
        shock_mean = statistics.mean(self.shocked_utilities)
        return in_mean - shock_mean

    def degradation_std(self) -> float:
        """Spread of (in-distribution - shocked) utility across seeds --
        the uncertainty measure MAR-13's acceptance criterion asks for,
        a simple multi-seed spread rather than a bootstrap (this
        project's `experiments.bootstrap` is a PAIRED-sample tool for
        two candidates evaluated on the identical set of draws; here
        each seed produces one trained policy, not a resampleable
        population of outcomes from a single policy, so a direct
        across-seed spread is the honestly-fitting choice, not a
        forced reuse of a tool built for a different shape of
        comparison)."""
        deltas = [
            in_u - shock_u
            for in_u, shock_u in zip(
                self.in_distribution_utilities, self.shocked_utilities, strict=True
            )
        ]
        return statistics.pstdev(deltas)


def evaluate_ood_wage_shock(
    *,
    seeds: tuple[int, ...],
    training_firm_capital: Money,
    shocked_firm_capital: Money,
    n_epochs: int = 30,
    episodes_per_epoch: int = 8,
    n_steps: int = 6,
) -> OODShockReport:
    """Trains a household policy under `training_firm_capital` (the
    household never sees `shocked_firm_capital` during training -- no
    retraining happens between the two evaluations below) and evaluates
    the SAME trained, frozen policy under both conditions, once per
    seed."""
    if not seeds:
        raise ValueError("seeds must be non-empty")
    if training_firm_capital == shocked_firm_capital:
        raise ValueError("shocked_firm_capital must differ from training_firm_capital")
    in_distribution = []
    shocked = []
    for seed in seeds:
        trained = train_joint_ppo(
            seed=seed, n_epochs=n_epochs, episodes_per_epoch=episodes_per_epoch, n_steps=n_steps,
            firm_opening_capital=training_firm_capital, train_household=True, train_firm=False,
            firm_fixed_rule=FixedWageRule(0.5),
        )
        assert trained.household_net is not None
        policy = deterministic_household_policy(trained.household_net, n_steps)
        in_result = run_rollout(
            household_policy=policy, firm_policy=FixedWageRule(0.5), n_steps=n_steps,
            firm_opening_capital=training_firm_capital,
        )
        shock_result = run_rollout(
            household_policy=policy, firm_policy=FixedWageRule(0.5), n_steps=n_steps,
            firm_opening_capital=shocked_firm_capital,
        )
        in_distribution.append(in_result.total_household_utility())
        shocked.append(shock_result.total_household_utility())
    return OODShockReport(
        in_distribution_utilities=tuple(in_distribution), shocked_utilities=tuple(shocked)
    )


__all__ = [
    "SeedOutcome",
    "SingleVsCoLearningReport",
    "single_vs_colearning_report",
    "gini_coefficient",
    "WelfareReport",
    "welfare_report_across_heterogeneous_households",
    "OODShockReport",
    "evaluate_ood_wage_shock",
]
