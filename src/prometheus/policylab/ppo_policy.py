"""A constrained PPO policy for POLICYLAB-RL, reusing `prometheus.marl
.training`'s PPO machinery directly rather than re-deriving a parallel
implementation: `BetaPolicyNet` (an exact-support `[0, 1]` action
distribution, no squash/Jacobian bookkeeping needed), `_returns_to_go`
and `_ppo_update` (the clipped-surrogate update over one collected batch)
are all architecture/semantics-agnostic -- they operate on whatever 3-dim
observation tensor is handed to them, so this module supplies its own
observation encoding (`inflation_gap, output_gap, step / n_steps`) and
reuses the rest of `marl.training` unmodified, the same way `marl.training`
itself is reused unchanged by `orchestration.marl_run` elsewhere in this
repository.

The Beta sample already lives in `[0, 1]` by construction (no network
output can leave that range); scaling it by `rate_max` keeps the proposed
rate within `[0, rate_max]` before `PolicyLabEnvironment.step` applies its
own (rate-of-change) clamp on top -- both constraints are therefore
enforced regardless of what the network has learned.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import torch
from torch.distributions import Beta

from prometheus.marl.training import BetaPolicyNet, _ppo_update, _returns_to_go, n_parameters
from prometheus.policylab.environment import (
    PolicyLabEnvConfig,
    PolicyLabEnvironment,
    PolicyLabState,
)
from prometheus.recessionnet.training import EpochLogEntry

__all__ = [
    "PolicyLabTrainingResult",
    "deterministic_policy",
    "n_parameters",
    "train_policylab_ppo",
]


def _obs_tensor(state: PolicyLabState, inflation_target: float, n_steps: int) -> torch.Tensor:
    inflation_gap = state.inflation - inflation_target
    return torch.tensor(
        [inflation_gap, state.output_gap, state.step / n_steps], dtype=torch.float32
    )


def _mean_rate(
    net: BetaPolicyNet,
    state: PolicyLabState,
    inflation_target: float,
    n_steps: int,
    rate_max: float,
) -> float:
    obs_t = _obs_tensor(state, inflation_target, n_steps)
    with torch.no_grad():
        alpha, beta = net(obs_t.unsqueeze(0))
    fraction = float((alpha / (alpha + beta)).squeeze(0))
    return fraction * rate_max


def deterministic_policy(
    net: BetaPolicyNet, config: PolicyLabEnvConfig
) -> Callable[[PolicyLabState], float]:
    """A non-stochastic evaluation wrapper (the Beta distribution's MEAN,
    not a sample), matching `marl.training.deterministic_household_policy`'s
    own convention for reporting final learned-policy performance without
    sampling noise."""
    return lambda state: _mean_rate(
        net, state, config.inflation_target, config.n_steps, config.rate_max
    )


@dataclass(frozen=True, slots=True)
class PolicyLabTrainingResult:
    net: BetaPolicyNet
    epoch_log: tuple[EpochLogEntry, ...]
    seed: int


def train_policylab_ppo(
    *,
    env_config: PolicyLabEnvConfig,
    lambda_rate: float,
    seed: int,
    n_epochs: int,
    episodes_per_epoch: int,
    train_seeds: tuple[int, ...],
    hidden_size: int = 16,
    learning_rate: float = 0.02,
    clip_eps: float = 0.2,
    ppo_inner_epochs: int = 4,
) -> PolicyLabTrainingResult:
    if n_epochs < 1 or episodes_per_epoch < 1:
        raise ValueError("n_epochs and episodes_per_epoch must both be >= 1")
    if len(train_seeds) == 0:
        raise ValueError("train_seeds must be non-empty")

    torch.manual_seed(seed)
    net = BetaPolicyNet(hidden_size)
    optimizer = torch.optim.Adam(net.parameters(), lr=learning_rate)
    epoch_log: list[EpochLogEntry] = []
    global_episode_index = 0

    for epoch in range(n_epochs):
        obs_batch: list[torch.Tensor] = []
        actions_batch: list[torch.Tensor] = []
        old_logp_batch: list[torch.Tensor] = []
        returns_batch: list[list[float]] = []

        for _ in range(episodes_per_epoch):
            env_seed = train_seeds[global_episode_index % len(train_seeds)]
            global_episode_index += 1
            env = PolicyLabEnvironment(env_config, lambda_rate=lambda_rate)
            state = env.reset(env_seed)

            ep_obs: list[torch.Tensor] = []
            ep_actions: list[torch.Tensor] = []
            ep_logp: list[torch.Tensor] = []
            ep_rewards: list[float] = []
            done = False
            while not done:
                obs_t = _obs_tensor(state, env_config.inflation_target, env_config.n_steps)
                alpha, beta = net(obs_t.unsqueeze(0))
                dist = Beta(alpha.squeeze(0), beta.squeeze(0))
                sample = dist.sample()
                logp = dist.log_prob(sample)  # type: ignore[no-untyped-call]
                proposed_rate = float(sample) * env_config.rate_max
                state, reward, done = env.step(proposed_rate)
                ep_obs.append(obs_t)
                ep_actions.append(sample.detach())
                ep_logp.append(logp.detach())
                ep_rewards.append(reward)

            obs_batch.append(torch.stack(ep_obs))
            actions_batch.append(torch.stack(ep_actions))
            old_logp_batch.append(torch.stack(ep_logp))
            returns_batch.append(_returns_to_go(ep_rewards))

        loss = _ppo_update(
            net,
            optimizer,
            obs_batch,
            actions_batch,
            old_logp_batch,
            returns_batch,
            clip_eps=clip_eps,
            ppo_inner_epochs=ppo_inner_epochs,
        )
        epoch_log.append(EpochLogEntry(epoch=epoch, loss=loss))

    return PolicyLabTrainingResult(net=net, epoch_log=tuple(epoch_log), seed=seed)
