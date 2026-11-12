"""Run the real single-agent-vs-co-learning MARL comparison end to end:
`marl.diagnostics.single_vs_colearning_report`, reused UNCHANGED, trains
a household PPO policy against a fixed-wage firm rule, then compares
its evaluated household utility against the existing joint (household
+ firm) co-learning training path (`marl.training.train_joint_ppo`) --
the real "PPO-trained multi-agent reinforcement-learning policy
benchmarked against the deterministic/calibrated baseline" the `marl`
package's own docstring already claims, for the one subsystem that
previously had no orchestration/CLI layer at all.

Unlike `single_vs_colearning_report`'s own `seeds: tuple[int, ...]`
parameter (a real multi-seed sweep), this job kind exposes a single
`seed: int`, matching every other registered recipe's one-seed-per-job
convention (and this repository's manifest contract, which binds
`manifest.seed` to one integer) -- `run_marl` below passes it through
as the one-element tuple `(config.seed,)`. A genuine multi-seed sweep
remains available by calling `single_vs_colearning_report` directly.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from prometheus.core.money import Money
from prometheus.evidence.contracts import CONVENTIONS
from prometheus.evidence.export import build_evidence_bundle
from prometheus.evidence.repository_status import current_repository_gate_report
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.marl.diagnostics import SingleVsCoLearningReport, single_vs_colearning_report


@dataclass(frozen=True, slots=True)
class MarlRunConfig:
    seed: int = 0
    n_epochs: int = 30
    episodes_per_epoch: int = 8
    n_steps: int = 6
    firm_opening_capital_minor_units: int = 100_000
    """Plain minor-units int rather than a nested `Money` field -- this
    research tool is USD-only throughout, so exposing currency as a
    separately-configurable field would add decode complexity for a
    choice nothing here actually varies."""

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.n_epochs < 1:
            raise ValueError("n_epochs must be a positive integer")
        if self.episodes_per_epoch < 1:
            raise ValueError("episodes_per_epoch must be a positive integer")
        if self.n_steps < 1:
            raise ValueError("n_steps must be a positive integer")
        if self.firm_opening_capital_minor_units < 1:
            raise ValueError("firm_opening_capital_minor_units must be a positive integer")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MarlRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("marl recipe requires exactly the complete configuration fields")
        try:
            return cls(**dict(payload))
        except TypeError as exc:
            raise ValueError(f"invalid marl recipe: {exc}") from exc


@dataclass(frozen=True, slots=True)
class MarlRunResult:
    report: SingleVsCoLearningReport
    verdict: str
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def run_marl(config: MarlRunConfig) -> MarlRunResult:
    report = single_vs_colearning_report(
        seeds=(config.seed,),
        n_epochs=config.n_epochs,
        episodes_per_epoch=config.episodes_per_epoch,
        n_steps=config.n_steps,
        firm_opening_capital=Money(config.firm_opening_capital_minor_units, "USD"),
    )
    delta = report.mean_household_utility_delta()
    verdict = "co_learning_better" if delta > 0 else "single_agent_better"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "accounting_convention": CONVENTIONS["marl"],
        "config": asdict(config),
        "single_agent": [asdict(o) for o in report.single_agent],
        "co_learning": [asdict(o) for o in report.co_learning],
        "mean_household_utility_delta": delta,
        "verdict": verdict,
    }
    manifest = RunManifest(
        new_run_id("pmth-marl"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, [], current_repository_gate_report())
    bundle["marl"] = payload
    return MarlRunResult(report=report, verdict=verdict, manifest=manifest, evidence_bundle=bundle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-epochs", type=int, default=30)
    parser.add_argument("--episodes-per-epoch", type=int, default=8)
    parser.add_argument("--n-steps", type=int, default=6)
    parser.add_argument("--firm-opening-capital-minor-units", type=int, default=100_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = MarlRunConfig(
            seed=args.seed,
            n_epochs=args.n_epochs,
            episodes_per_epoch=args.episodes_per_epoch,
            n_steps=args.n_steps,
            firm_opening_capital_minor_units=args.firm_opening_capital_minor_units,
        )
    except ValueError as exc:
        parser.error(str(exc))

    result = run_marl(config)
    payload = result.evidence_bundle["marl"]
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
