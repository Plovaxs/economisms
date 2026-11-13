"""Run the real REINFORCE hedging agent end to end: simulate GBM paths
(`stochastica.gbm.simulate_gbm_paths`), compute a real static
delta-hedge-with-no-trade-band baseline CVaR
(`hedging.baseline.black_scholes_delta_hedge_ratios` ->
`hedging.baseline.apply_no_trade_band` ->
`hedging.simulate.simulate_self_financing_hedge`), then train
`hedging.rl_agent.train_reinforce_hedge_policy` against that REAL,
already-passing baseline -- HDG-14's own "add controlled RL agent only
after static policy passes" precondition, enforced by that function
itself (`StaticBaselineNotPassedError`). This is the exact chain
already proven in `tests/unit/test_hedging_rl_agent.py`'s own
`_static_baseline_cvar` helper; every primitive here is reused
unchanged, for the one subsystem that previously had no
orchestration/CLI layer at all.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

import numpy as np

from prometheus.evidence.contracts import CONVENTIONS
from prometheus.evidence.export import build_evidence_bundle
from prometheus.evidence.repository_status import current_repository_gate_report
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.baseline import apply_no_trade_band, black_scholes_delta_hedge_ratios
from prometheus.hedging.rl_agent import (
    RewardObjective,
    TrainedReinforceHedge,
    train_reinforce_hedge_policy,
)
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.volterra.instruments import OptionType

Verdict = Literal["rl_better", "static_better", "inconclusive"]
_VERDICT_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class RlHedgeRunConfig:
    seed: int = 0
    s0: float = 100.0
    mu: float = 0.05
    sigma: float = 0.2
    maturity: float = 1.0
    n_steps: int = 20
    n_paths: int = 2_000
    strike: float = 100.0
    option_type: OptionType = "call"
    risk_free_rate: float = 0.03
    cost_rate: float = 0.001
    initial_premium: float = 5.0
    cvar_alpha: float = 0.95
    n_epochs: int = 400
    learning_rate: float = 0.01
    band_width: float = 0.05
    reward_objective: RewardObjective = "cvar"
    """"cvar" (the default): the policy is rewarded by its own excess
    over the batch's empirical VaR threshold, directly targeting the
    CVaR metric it is judged against -- see `hedging.rl_agent`'s module
    docstring for why this is a real, measured fix (not merely a more
    aggressive setting) for an objective/metric mismatch that previously
    went unaudited. "mean_loss" reproduces the original (PR-158/162)
    behavior, where `static_baseline_cvar` is used only as a
    precondition gate, never in the training signal."""

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.sigma <= 0:
            raise ValueError("sigma must be positive")
        if self.maturity <= 0:
            raise ValueError("maturity must be positive")
        if self.n_steps < 1:
            raise ValueError("n_steps must be a positive integer")
        if self.n_paths < 1:
            raise ValueError("n_paths must be a positive integer")
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        if self.option_type not in ("call", "put"):
            raise ValueError("option_type must be 'call' or 'put'")
        if not 0.0 < self.cvar_alpha < 1.0:
            raise ValueError("cvar_alpha must be in (0, 1)")
        if self.n_epochs < 1:
            raise ValueError("n_epochs must be a positive integer")
        if not 0.0 <= self.band_width < 1.0:
            raise ValueError("band_width must be in [0, 1)")
        if self.reward_objective not in ("mean_loss", "cvar"):
            raise ValueError("reward_objective must be 'mean_loss' or 'cvar'")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RlHedgeRunConfig:
        if set(payload) != {item.name for item in fields(cls)}:
            raise ValueError("rl_hedge recipe requires exactly the complete configuration fields")
        try:
            return cls(**dict(payload))
        except TypeError as exc:
            raise ValueError(f"invalid rl_hedge recipe: {exc}") from exc


@dataclass(frozen=True, slots=True)
class RlHedgeRunResult:
    trained: TrainedReinforceHedge
    static_baseline_cvar: float
    verdict: Verdict
    manifest: RunManifest
    evidence_bundle: dict[str, Any]


def _verdict(static_baseline_cvar: float, final_cvar: float) -> Verdict:
    """Lower CVaR (less tail loss) is better; a difference within a
    tight float tolerance is reported as inconclusive rather than
    manufacturing a winner from noise."""
    diff = final_cvar - static_baseline_cvar
    if abs(diff) <= _VERDICT_TOLERANCE:
        return "inconclusive"
    return "rl_better" if diff < 0 else "static_better"


def run_rl_hedge(config: RlHedgeRunConfig) -> RlHedgeRunResult:
    rng = np.random.default_rng(config.seed)
    paths = simulate_gbm_paths(
        s0=config.s0,
        mu=config.mu,
        sigma=config.sigma,
        maturity=config.maturity,
        n_steps=config.n_steps,
        n_paths=config.n_paths,
        rng=rng,
    )
    dt = config.maturity / config.n_steps
    delta_ratios = black_scholes_delta_hedge_ratios(
        paths, dt, config.strike, config.maturity, config.risk_free_rate, config.sigma,
        config.option_type,
    )
    static_ratios = apply_no_trade_band(delta_ratios, band_width=config.band_width)
    static_sim = simulate_self_financing_hedge(
        paths, dt, config.strike, config.option_type, config.risk_free_rate, config.cost_rate,
        config.initial_premium, static_ratios,
    )
    sorted_loss = np.sort(static_sim.terminal_loss)
    tail_start = int(np.ceil(config.cvar_alpha * len(sorted_loss)))
    static_baseline_cvar = float(np.mean(sorted_loss[tail_start:]))

    trained = train_reinforce_hedge_policy(
        paths, dt, config.strike, config.option_type, config.risk_free_rate, config.cost_rate,
        config.initial_premium,
        static_baseline_cvar=static_baseline_cvar,
        seed=config.seed,
        n_epochs=config.n_epochs,
        cvar_alpha=config.cvar_alpha,
        learning_rate=config.learning_rate,
        reward_objective=config.reward_objective,
    )
    verdict = _verdict(static_baseline_cvar, trained.final_cvar)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "accounting_convention": CONVENTIONS["rl_hedge"],
        "config": asdict(config),
        "static_baseline_cvar": static_baseline_cvar,
        "trained_final_cvar": trained.final_cvar,
        "n_parameters": trained.n_parameters,
        "epoch_log": [asdict(e) for e in trained.epoch_log],
        "verdict": verdict,
    }
    manifest = RunManifest(
        new_run_id("pmth-rl-hedge"),
        now_iso(),
        config.seed,
        asdict(config),
        compute_result_hash(payload),
    )
    bundle = build_evidence_bundle(manifest, [], current_repository_gate_report())
    bundle["rl_hedge"] = payload
    return RlHedgeRunResult(
        trained=trained,
        static_baseline_cvar=static_baseline_cvar,
        verdict=verdict,
        manifest=manifest,
        evidence_bundle=bundle,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--s0", type=float, default=100.0)
    parser.add_argument("--mu", type=float, default=0.05)
    parser.add_argument("--sigma", type=float, default=0.2)
    parser.add_argument("--maturity", type=float, default=1.0)
    parser.add_argument("--n-steps", type=int, default=20)
    parser.add_argument("--n-paths", type=int, default=2_000)
    parser.add_argument("--strike", type=float, default=100.0)
    parser.add_argument("--option-type", choices=("call", "put"), default="call")
    parser.add_argument("--risk-free-rate", type=float, default=0.03)
    parser.add_argument("--cost-rate", type=float, default=0.001)
    parser.add_argument("--initial-premium", type=float, default=5.0)
    parser.add_argument("--cvar-alpha", type=float, default=0.95)
    parser.add_argument("--n-epochs", type=int, default=400)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--band-width", type=float, default=0.05)
    parser.add_argument("--reward-objective", choices=("mean_loss", "cvar"), default="cvar")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        config = RlHedgeRunConfig(
            seed=args.seed, s0=args.s0, mu=args.mu, sigma=args.sigma, maturity=args.maturity,
            n_steps=args.n_steps, n_paths=args.n_paths, strike=args.strike,
            option_type=args.option_type, risk_free_rate=args.risk_free_rate,
            cost_rate=args.cost_rate, initial_premium=args.initial_premium,
            cvar_alpha=args.cvar_alpha, n_epochs=args.n_epochs,
            learning_rate=args.learning_rate, band_width=args.band_width,
            reward_objective=args.reward_objective,
        )
    except ValueError as exc:
        parser.error(str(exc))

    result = run_rl_hedge(config)
    payload = result.evidence_bundle["rl_hedge"]
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
