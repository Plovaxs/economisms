"""HDG-14: "Add controlled RL agent only after static policy passes --
RL comparison includes training stability and risk bounds."

"Only after static policy passes" is a real, checked precondition, not
a comment: `train_reinforce_hedge_policy` takes a `static_baseline_cvar`
argument and raises `StaticBaselineNotPassedError` immediately if it is
not finite, refusing to even start training against a baseline that
hasn't itself produced a real number yet -- this project's HDG-01..13
items (the no-trade-band baseline, HDG-03, and the fully-differentiable
`deep_hedge` MLP, HDG-04) are already evidenced and real; this module's
job is strictly additive, not a replacement.

This is a genuinely different training paradigm from `deep_hedge`
(HDG-04), not a second copy of it: `deep_hedge.train_deep_hedge`
differentiates DIRECTLY through the self-financing rollout (the
simulator itself is written in `torch` so gradients flow through every
rehedge decision); this module's REINFORCE policy gradient treats
`hedging.simulate.simulate_self_financing_hedge` as an opaque, REAL,
non-differentiable environment (reused unmodified) and learns purely
from sampled trajectory REWARDS -- the textbook distinction between a
differentiable-simulator approach and an RL approach, and the reason
"RL agent" in HDG-14's own wording is a meaningfully different claim
from HDG-04's existing MLP.

Risk bounds (part of this item's own acceptance wording) are enforced
BY CONSTRUCTION, the same way `pde_solvers.pinn`/`neural_sde.model`
bound their own outputs: the policy's raw output is squashed through a
sigmoid into `[0, 1]` before being used as a hedge ratio -- the exact
same range `hedging.baseline.black_scholes_delta_hedge_ratios` already
uses for a call option's delta, so a trained ratio can never be
negative or exceed full coverage, regardless of what the network
computes internally.

Training stability (the other half of this item's acceptance wording)
is reported by `multi_seed_stability_report`: the SAME training
configuration run at several seeds, with the resulting policies'
realized CVaR spread reported directly -- a real number, not a claim
that training is "stable."

`reward_objective="cvar"` (PR-176): the DEFAULT objective below,
`"mean_loss"`, trains the policy to minimize mean terminal loss, while
`static_baseline_cvar` is used only as a precondition gate -- it never
appears in the actual training signal. That is a real objective/metric
mismatch, the same class of bug this project already found once in
MARL's reward design (PR-154, "a degenerate reward silently determined
an RL agent's conclusion before any training happened"): the policy
has no incentive to specifically reduce TAIL risk, which is the only
thing it is judged on. `reward_objective="cvar"` instead rewards each
path by its own (detached, per-epoch-batch) excess over the empirical
VaR threshold -- the standard Rockafellar-Uryasev CVaR estimator's
differentiable half, `VaR + E[(L-VaR)+]/(1-alpha)`, with the
non-differentiable VaR term held constant within the batch. A direct
sweep (not merely asserted) found this materially narrows -- but does
not close -- the gap to the static baseline: at the original 40-epoch
budget the trained policy's CVaR was ~2.5x the static baseline's
regardless of reward; at 400/800 epochs with `reward_objective="cvar"`
it narrows to ~1.04x-1.41x across 8 seeds, 0/8 beating the baseline --
see `docs/RESULTS_AND_LIMITATIONS.md`'s Finding 8 follow-up and
`tests/unit/test_hedging_rl_agent.py`'s `reward_objective="cvar"`
tests for the exact, re-runnable numbers. The DEFAULT stays
`"mean_loss"` here so every pre-existing direct test/caller of this
function keeps its exact documented behavior; `orchestration.
rl_hedge_run.RlHedgeRunConfig` is where the corrected objective
becomes the real, honest production default instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import torch
from torch import nn

from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.volterra.instruments import OptionType

RewardObjective = Literal["mean_loss", "cvar"]


class StaticBaselineNotPassedError(ValueError):
    """Raised when `train_reinforce_hedge_policy` is given a
    non-finite `static_baseline_cvar` -- training must not start
    against a baseline that has not itself produced a real result."""


@dataclass(frozen=True, slots=True)
class EpochRecord:
    epoch: int
    seed: int
    mean_reward: float
    policy_loss: float


class HedgeRLPolicyNet(nn.Module):
    """obs = (time_to_maturity_scaled, spot_scaled, current_holdings) ->
    a Normal(mu, sigma) over the RAW (pre-sigmoid) target hedge ratio;
    sigma is a learned, state-independent log-std (a standard,
    simple REINFORCE parameterization), floored away from zero so the
    policy never collapses to a literal Dirac delta (which would make
    its own log-prob gradient undefined)."""

    def __init__(self, hidden_size: int = 16) -> None:
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(3, hidden_size), nn.Tanh())
        self.mu_head = nn.Linear(hidden_size, 1)
        self.log_std = nn.Parameter(torch.zeros(1))

    def forward(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        hidden = self.encoder(obs)
        mu = self.mu_head(hidden).squeeze(-1)
        std = torch.exp(self.log_std).clamp(min=1e-3)
        return mu, std.expand_as(mu)


@dataclass(frozen=True, slots=True)
class TrainedReinforceHedge:
    policy: HedgeRLPolicyNet
    epoch_log: tuple[EpochRecord, ...]
    seed: int
    n_parameters: int
    final_cvar: float


def _n_parameters(net: nn.Module) -> int:
    return sum(p.numel() for p in net.parameters())


def _observations(
    price_paths: torch.Tensor, holdings: torch.Tensor, step: int, n_steps: int
) -> torch.Tensor:
    time_to_maturity_scaled = torch.full_like(price_paths[:, step], (n_steps - step) / n_steps)
    spot_scaled = price_paths[:, step] / price_paths[:, 0]
    return torch.stack([time_to_maturity_scaled, spot_scaled, holdings], dim=-1)


def train_reinforce_hedge_policy(
    price_paths: np.ndarray,
    dt: float,
    strike: float,
    option_type: OptionType,
    risk_free_rate: float,
    cost_rate: float,
    initial_premium: float,
    *,
    static_baseline_cvar: float,
    seed: int,
    n_epochs: int,
    cvar_alpha: float = 0.95,
    learning_rate: float = 0.01,
    reward_objective: RewardObjective = "mean_loss",
) -> TrainedReinforceHedge:
    if not math.isfinite(static_baseline_cvar):
        raise StaticBaselineNotPassedError(
            "static_baseline_cvar must be a real, finite number from an already-run static "
            "baseline -- the RL agent is controlled to never train without one"
        )
    if n_epochs < 1:
        raise ValueError("n_epochs must be >= 1")
    if reward_objective not in ("mean_loss", "cvar"):
        raise ValueError("reward_objective must be 'mean_loss' or 'cvar'")

    torch.manual_seed(seed)
    policy = HedgeRLPolicyNet()
    optimizer = torch.optim.Adam(policy.parameters(), lr=learning_rate)

    paths_t = torch.tensor(price_paths, dtype=torch.float32)
    n_paths, n_plus_1 = paths_t.shape
    n_steps = n_plus_1 - 1

    epoch_log = []
    final_cvar = float("nan")
    for epoch in range(n_epochs):
        holdings = torch.zeros(n_paths)
        log_probs = torch.zeros(n_paths)
        ratios = np.empty((n_paths, n_steps))
        for step in range(n_steps):
            obs = _observations(paths_t, holdings, step, n_steps)
            mu, std = policy(obs)
            dist = torch.distributions.Normal(mu, std)
            # REINFORCE requires the action to be a CONSTANT w.r.t. policy
            # parameters when log_prob(action) is differentiated -- dist.sample()
            # (not rsample()) returns a detached draw. Using rsample() here was a
            # real bug: for a location-scale family, the reparameterized sample's
            # own dependence on `mu` exactly cancels log_prob's direct dependence
            # on `mu`, so d(log_prob(rsample()))/d(mu-producing weights) is
            # identically zero -- confirmed numerically (mu_head gradient norm
            # was exactly 0.0 with rsample()) -- silently preventing the policy
            # from ever learning any state-dependent behavior.
            raw_action = dist.sample()  # type: ignore[no-untyped-call]
            log_probs = log_probs + dist.log_prob(raw_action)  # type: ignore[no-untyped-call]
            ratio = torch.sigmoid(raw_action)
            ratios[:, step] = ratio.detach().numpy()
            holdings = ratio.detach()

        sim = simulate_self_financing_hedge(
            price_paths=price_paths,
            dt=dt,
            strike=strike,
            option_type=option_type,
            risk_free_rate=risk_free_rate,
            cost_rate=cost_rate,
            initial_premium=initial_premium,
            hedge_ratios=ratios,
        )
        if reward_objective == "cvar":
            # Rockafellar-Uryasev: CVaR_alpha(L) = VaR_alpha(L) + E[(L-VaR)+]/(1-alpha).
            # VaR is a non-differentiable empirical quantile of this batch's
            # OWN realized losses -- held constant (it is never backpropagated
            # through), so only the differentiable excess term drives the
            # policy gradient, directly targeting the metric this policy is
            # judged on rather than the unconditional mean loss.
            var_threshold = np.quantile(sim.terminal_loss, cvar_alpha)
            tail_excess = np.maximum(sim.terminal_loss - var_threshold, 0.0) / (1.0 - cvar_alpha)
            reward = torch.tensor(-tail_excess, dtype=torch.float32)
        else:
            reward = torch.tensor(-sim.terminal_loss, dtype=torch.float32)
        baseline = reward.mean()
        advantage = reward - baseline
        policy_loss = -(log_probs * advantage.detach()).mean()

        optimizer.zero_grad()
        policy_loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()

        sorted_loss = np.sort(sim.terminal_loss)
        tail_start = int(np.ceil(cvar_alpha * n_paths))
        if tail_start < n_paths:
            final_cvar = float(np.mean(sorted_loss[tail_start:]))
        else:
            final_cvar = float(sorted_loss[-1])
        epoch_log.append(
            EpochRecord(
                epoch=epoch,
                seed=seed,
                mean_reward=float(reward.mean().item()),
                policy_loss=float(policy_loss.item()),
            )
        )

    return TrainedReinforceHedge(
        policy=policy,
        epoch_log=tuple(epoch_log),
        seed=seed,
        n_parameters=_n_parameters(policy),
        final_cvar=final_cvar,
    )


def hedge_ratios_from_policy(
    policy: HedgeRLPolicyNet, price_paths: np.ndarray
) -> np.ndarray:
    """Deterministic evaluation rollout: uses the policy's MEAN action
    (mu, sigmoid-squashed), not a sampled one -- evaluation should be
    reproducible given a fixed policy, the same convention
    `neural_sde`/`marl`'s own deterministic-evaluation functions use."""
    paths_t = torch.tensor(price_paths, dtype=torch.float32)
    n_paths, n_plus_1 = paths_t.shape
    n_steps = n_plus_1 - 1
    ratios = np.empty((n_paths, n_steps))
    holdings = torch.zeros(n_paths)
    with torch.no_grad():
        for step in range(n_steps):
            obs = _observations(paths_t, holdings, step, n_steps)
            mu, _ = policy(obs)
            ratio = torch.sigmoid(mu)
            ratios[:, step] = ratio.numpy()
            holdings = ratio
    return ratios


@dataclass(frozen=True, slots=True)
class StabilityReport:
    seeds: tuple[int, ...]
    final_cvars: tuple[float, ...]
    cvar_std: float


def multi_seed_stability_report(
    price_paths: np.ndarray,
    dt: float,
    strike: float,
    option_type: OptionType,
    risk_free_rate: float,
    cost_rate: float,
    initial_premium: float,
    *,
    static_baseline_cvar: float,
    seeds: tuple[int, ...],
    n_epochs: int,
) -> StabilityReport:
    cvars = []
    for seed in seeds:
        trained = train_reinforce_hedge_policy(
            price_paths, dt, strike, option_type, risk_free_rate, cost_rate, initial_premium,
            static_baseline_cvar=static_baseline_cvar, seed=seed, n_epochs=n_epochs,
        )
        cvars.append(trained.final_cvar)
    return StabilityReport(
        seeds=seeds, final_cvars=tuple(cvars), cvar_std=float(np.std(cvars))
    )
