"""MAR-08: "Implement PPO or comparable baseline with deterministic
seeding -- Training manifest reproduces learning-curve statistics."
MAR-04/MAR-05: household/firm policy learning via this same trainer.

A genuine, simplified PPO, not a different, unrelated algorithm wearing
the name: a clipped-ratio surrogate objective (`clip_eps`), multiple
gradient epochs reusing the same collected batch (`ppo_inner_epochs`),
and advantage estimation from a time-indexed return-to-go baseline
(mean return at each within-episode step across the batch) rather than
a learned value-function network with GAE -- the honest simplification
this toy, low-dimensional, short-horizon environment does not need the
extra machinery for; full GAE/a value network would be a defensible
upgrade for a longer-horizon or higher-dimensional problem, not claimed
here. Action distribution is `torch.distributions.Beta` over the
network's own `(alpha, beta)` output (both `>= 1`, via
`softplus(...) + 1`, keeping the density unimodal rather than
U-shaped at the support boundary) -- the exact-support, exact-log-prob
choice for a [0, 1] continuous fraction action, used so no squash/
Jacobian-correction bookkeeping is needed the way a sigmoid-of-Normal
action would require.

`train_joint_ppo` handles both MAR-04 (household alone), MAR-05 (firm
alone) and the MAR-09/MAR-11 co-learning case with ONE function
(`train_household`/`train_firm` flags, with a fixed-rule policy
supplied for whichever side is not being trained) rather than three
near-duplicate loops -- the same "parameterize the difference out"
reasoning `recessionnet.training`'s single loop already applies to its
own classification/regression split, and `EpochLogEntry` is imported
and reused from there as-is for the per-epoch log shape.

Reward computation (including the `bequest_weight` ending-net-worth
term that gives the household's consumption problem a genuine interior
optimum rather than a degenerate always-spend-everything one -- see
`env.py`'s own docstring for the numeric sweep that found this) is kept
identical to `env.run_rollout`'s, deliberately duplicated rather than
imported, for the reason below.

Disclosed asymmetry between the two learned agents, found while
verifying this module rather than assumed: the FIRM's reward has no
equivalent bequest-style interior optimum, and this is not an oversight
-- `firm_profit` is the firm's real net-worth delta in a pure
circular-flow model with no separate production function, so a firm
whose customer (the household) saves part of every payment it receives
can never out-earn what it pays in wages; the reward-maximizing policy
genuinely IS to minimize wage payment. A trained firm policy (seed=0,
40 epochs) converges to a wage fraction of ~0.033 (consistently, across
steps), which beats every fixed-wage baseline tested from 0.1 to 0.9 --
real evidence of correct policy learning toward this reward structure's
actual optimum, not evidence of an interesting trade-off, because this
particular reward structure does not have one. MAR-05's "improvement
checked against rule-based counterfactuals" is satisfied by that
baseline comparison, not by an interior-optimum story the household's
bequest-augmented problem can honestly tell and this one cannot.

This loop deliberately does NOT reuse `env.run_rollout` for data
collection -- it needs to additionally record each sampled action's
log-probability under the CURRENT (not fixed-rule) policy for the PPO
update, which `run_rollout`'s plain `Observation -> Action` callable
signature has no channel for. It reuses every primitive `run_rollout`
itself is built from (`feasibility.project_fraction_to_amount`, the
real `econosim.agents`/`Economy`, the identical reward definitions from
`env.py`) -- so this is a second, necessarily-different ROLLOUT LOOP
SHAPE around the same real economy and reward primitives, not a second,
inconsistent one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import torch
from torch import nn
from torch.distributions import Beta

from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.marl.env import FirmPolicy, HouseholdPolicy, firm_observation, household_observation
from prometheus.marl.feasibility import project_fraction_to_amount
from prometheus.marl.spaces import FirmAction, HouseholdAction
from prometheus.quantum.models import count_parameters
from prometheus.recessionnet.training import EpochLogEntry


class _ScalarAgentObservation(Protocol):
    """The common shape `HouseholdObservation` and `FirmObservation`
    both already satisfy structurally -- a Protocol rather than a
    shared base class, since neither was designed to inherit from one
    and adding that coupling now would be a change `spaces.py` does
    not otherwise need. Declared as read-only properties, matching the
    frozen dataclasses that actually satisfy this Protocol."""

    @property
    def cash_balance_minor(self) -> int: ...
    @property
    def net_worth_minor(self) -> int: ...
    @property
    def step(self) -> int: ...

_OBS_SCALE_MINOR = 100_000.0  # 1,000.00 currency units; a fixed, disclosed scaling constant


class BetaPolicyNet(nn.Module):
    """3-dim scaled observation (cash, net_worth, step/horizon) -> a
    Beta(alpha, beta) distribution over a [0, 1] fraction action."""

    def __init__(self, hidden_size: int = 16) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(3, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
        )
        self.alpha_head = nn.Linear(hidden_size, 1)
        self.beta_head = nn.Linear(hidden_size, 1)

    def forward(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        hidden = self.encoder(obs)
        alpha = nn.functional.softplus(self.alpha_head(hidden)).squeeze(-1) + 1.0
        beta = nn.functional.softplus(self.beta_head(hidden)).squeeze(-1) + 1.0
        return alpha, beta


def _scale_obs(cash_minor: int, net_worth_minor: int, step: int, n_steps: int) -> torch.Tensor:
    return torch.tensor(
        [cash_minor / _OBS_SCALE_MINOR, net_worth_minor / _OBS_SCALE_MINOR, step / n_steps],
        dtype=torch.float32,
    )


def _net_mean_fraction(
    net: BetaPolicyNet, observation: _ScalarAgentObservation, n_steps: int
) -> float:
    obs_t = _scale_obs(
        observation.cash_balance_minor, observation.net_worth_minor, observation.step, n_steps
    )
    with torch.no_grad():
        alpha, beta = net(obs_t.unsqueeze(0))
    return float((alpha / (alpha + beta)).squeeze(0))


def deterministic_household_policy(net: BetaPolicyNet, n_steps: int) -> HouseholdPolicy:
    """A non-stochastic evaluation wrapper (Beta distribution MEAN, not
    a sample) -- for reporting final learned-policy performance without
    sampling noise, and for feeding a co-trained net as the "other
    agent" into a single-agent-trained partner's own rollout."""
    return lambda observation: HouseholdAction(
        consumption_fraction=_net_mean_fraction(net, observation, n_steps)
    )


def deterministic_firm_policy(net: BetaPolicyNet, n_steps: int) -> FirmPolicy:
    return lambda observation: FirmAction(
        wage_fraction=_net_mean_fraction(net, observation, n_steps)
    )


@dataclass(frozen=True, slots=True)
class JointTrainingResult:
    household_net: BetaPolicyNet | None
    firm_net: BetaPolicyNet | None
    household_epoch_log: tuple[EpochLogEntry, ...]
    firm_epoch_log: tuple[EpochLogEntry, ...]
    seed: int
    n_steps: int


def _returns_to_go(rewards: list[float]) -> list[float]:
    returns = [0.0] * len(rewards)
    running = 0.0
    for t in range(len(rewards) - 1, -1, -1):
        running += rewards[t]
        returns[t] = running
    return returns


def train_joint_ppo(
    *,
    seed: int,
    n_epochs: int,
    episodes_per_epoch: int,
    n_steps: int,
    firm_opening_capital: Money,
    train_household: bool,
    train_firm: bool,
    household_fixed_rule: HouseholdPolicy | None = None,
    firm_fixed_rule: FirmPolicy | None = None,
    hidden_size: int = 16,
    learning_rate: float = 0.02,
    clip_eps: float = 0.2,
    ppo_inner_epochs: int = 4,
    bequest_weight: float = 1.0,
) -> JointTrainingResult:
    if not train_household and household_fixed_rule is None:
        raise ValueError("household_fixed_rule is required when train_household is False")
    if not train_firm and firm_fixed_rule is None:
        raise ValueError("firm_fixed_rule is required when train_firm is False")
    if n_epochs < 1 or episodes_per_epoch < 1 or n_steps < 1:
        raise ValueError("n_epochs, episodes_per_epoch and n_steps must all be >= 1")

    torch.manual_seed(seed)
    household_net = BetaPolicyNet(hidden_size) if train_household else None
    firm_net = BetaPolicyNet(hidden_size) if train_firm else None
    household_opt = (
        torch.optim.Adam(household_net.parameters(), lr=learning_rate) if household_net else None
    )
    firm_opt = torch.optim.Adam(firm_net.parameters(), lr=learning_rate) if firm_net else None

    household_epoch_log: list[EpochLogEntry] = []
    firm_epoch_log: list[EpochLogEntry] = []

    for epoch in range(n_epochs):
        hh_obs, hh_actions, hh_old_logp, hh_returns = [], [], [], []
        fm_obs, fm_actions, fm_old_logp, fm_returns = [], [], [], []
        hh_total_rewards, fm_total_rewards = [], []

        for _ in range(episodes_per_epoch):
            economy = Economy()
            household = economy.add_household("hh-0")
            firm = economy.add_firm("firm-0")
            firm.capitalize(firm_opening_capital, step=0)

            ep_hh_obs, ep_hh_actions, ep_hh_logp, ep_hh_rewards = [], [], [], []
            ep_fm_obs, ep_fm_actions, ep_fm_logp, ep_fm_rewards = [], [], [], []

            for step in range(n_steps):
                firm_net_worth_before = firm.net_worth
                f_obs = firm_observation(firm, step)
                if firm_net is not None:
                    obs_t = _scale_obs(
                        f_obs.cash_balance_minor, f_obs.net_worth_minor, step, n_steps
                    )
                    alpha, beta = firm_net(obs_t.unsqueeze(0))
                    dist = Beta(alpha.squeeze(0), beta.squeeze(0))
                    sample = dist.sample()
                    logp = dist.log_prob(sample)  # type: ignore[no-untyped-call]
                    firm_action = FirmAction(wage_fraction=float(sample))
                    ep_fm_obs.append(obs_t)
                    ep_fm_actions.append(sample.detach())
                    ep_fm_logp.append(logp.detach())
                else:
                    assert firm_fixed_rule is not None
                    firm_action = firm_fixed_rule(f_obs)
                wage = project_fraction_to_amount(firm_action.wage_fraction, firm.cash_balance)
                if wage.is_positive():
                    firm.pay_wages(household, wage, step=step)

                h_obs = household_observation(household, step)
                if household_net is not None:
                    obs_t = _scale_obs(
                        h_obs.cash_balance_minor, h_obs.net_worth_minor, step, n_steps
                    )
                    alpha, beta = household_net(obs_t.unsqueeze(0))
                    dist = Beta(alpha.squeeze(0), beta.squeeze(0))
                    sample = dist.sample()
                    logp = dist.log_prob(sample)  # type: ignore[no-untyped-call]
                    household_action = HouseholdAction(consumption_fraction=float(sample))
                    ep_hh_obs.append(obs_t)
                    ep_hh_actions.append(sample.detach())
                    ep_hh_logp.append(logp.detach())
                else:
                    assert household_fixed_rule is not None
                    household_action = household_fixed_rule(h_obs)
                spend = project_fraction_to_amount(
                    household_action.consumption_fraction, household.cash_balance
                )
                if spend.is_positive():
                    household.consume(firm, spend, step=step)

                consumption_major = spend.minor_units / 100.0
                household_utility = 0.0 if spend.is_zero() else math.log1p(consumption_major)
                if step == n_steps - 1:
                    ending_net_worth_major = max(household.net_worth.minor_units, 0) / 100.0
                    household_utility += bequest_weight * math.log1p(ending_net_worth_major)
                firm_profit = (
                    firm.net_worth.minor_units - firm_net_worth_before.minor_units
                ) / 100.0
                ep_hh_rewards.append(household_utility)
                ep_fm_rewards.append(firm_profit)

            if household_net is not None:
                hh_obs.append(torch.stack(ep_hh_obs))
                hh_actions.append(torch.stack(ep_hh_actions))
                hh_old_logp.append(torch.stack(ep_hh_logp))
                hh_returns.append(_returns_to_go(ep_hh_rewards))
                hh_total_rewards.append(sum(ep_hh_rewards))
            if firm_net is not None:
                fm_obs.append(torch.stack(ep_fm_obs))
                fm_actions.append(torch.stack(ep_fm_actions))
                fm_old_logp.append(torch.stack(ep_fm_logp))
                fm_returns.append(_returns_to_go(ep_fm_rewards))
                fm_total_rewards.append(sum(ep_fm_rewards))

        if household_net is not None and household_opt is not None:
            loss = _ppo_update(
                household_net, household_opt, hh_obs, hh_actions, hh_old_logp, hh_returns,
                clip_eps=clip_eps, ppo_inner_epochs=ppo_inner_epochs,
            )
            household_epoch_log.append(EpochLogEntry(epoch=epoch, loss=loss))
        if firm_net is not None and firm_opt is not None:
            loss = _ppo_update(
                firm_net, firm_opt, fm_obs, fm_actions, fm_old_logp, fm_returns,
                clip_eps=clip_eps, ppo_inner_epochs=ppo_inner_epochs,
            )
            firm_epoch_log.append(EpochLogEntry(epoch=epoch, loss=loss))

    return JointTrainingResult(
        household_net=household_net,
        firm_net=firm_net,
        household_epoch_log=tuple(household_epoch_log),
        firm_epoch_log=tuple(firm_epoch_log),
        seed=seed,
        n_steps=n_steps,
    )


def _ppo_update(
    net: BetaPolicyNet,
    optimizer: torch.optim.Optimizer,
    obs_batch: list[torch.Tensor],
    actions_batch: list[torch.Tensor],
    old_logp_batch: list[torch.Tensor],
    returns_batch: list[list[float]],
    *,
    clip_eps: float,
    ppo_inner_epochs: int,
) -> float:
    obs = torch.stack(obs_batch)  # (episodes, n_steps, 3)
    actions = torch.stack(actions_batch)  # (episodes, n_steps)
    old_logp = torch.stack(old_logp_batch)  # (episodes, n_steps)
    returns = torch.tensor(returns_batch, dtype=torch.float32)  # (episodes, n_steps)

    time_baseline = returns.mean(dim=0, keepdim=True)  # mean return at each within-episode step
    advantages = returns - time_baseline
    std = advantages.std()
    if std > 1e-8:
        advantages = (advantages - advantages.mean()) / (std + 1e-8)

    last_loss = 0.0
    n_episodes, n_steps, _ = obs.shape
    flat_obs = obs.reshape(n_episodes * n_steps, 3)
    flat_actions = actions.reshape(n_episodes * n_steps)
    flat_old_logp = old_logp.reshape(n_episodes * n_steps)
    flat_advantages = advantages.reshape(n_episodes * n_steps)

    for _ in range(ppo_inner_epochs):
        alpha, beta = net(flat_obs)
        dist = Beta(alpha, beta)
        new_logp = dist.log_prob(flat_actions.clamp(1e-4, 1.0 - 1e-4))  # type: ignore[no-untyped-call]
        ratio = torch.exp(new_logp - flat_old_logp)
        surrogate_1 = ratio * flat_advantages
        surrogate_2 = torch.clamp(ratio, 1.0 - clip_eps, 1.0 + clip_eps) * flat_advantages
        loss = -torch.min(surrogate_1, surrogate_2).mean()
        optimizer.zero_grad()
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
        last_loss = float(loss.detach())
    return last_loss


def n_parameters(net: BetaPolicyNet) -> int:
    return count_parameters(net)
