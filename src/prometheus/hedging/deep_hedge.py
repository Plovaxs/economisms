"""An MLP hedging policy trained to minimize CVaR of terminal loss plus a
turnover penalty (section 3.4's loss-tail objective; Buehler et al. 2019
[R01]). Training differentiates directly through a self-financing rollout
written in PyTorch (mirroring simulate.simulate_self_financing_hedge's
accounting exactly), so gradients reach every rehedge decision.

MLO-04 ("persist training seeds, optimizer, scheduler and RNG state";
acceptance criterion: "mid-run resume reproduces experiment within
tolerance") and MLO-05 ("track learning curves and gradient
diagnostics"; acceptance criterion: "experiment log contains
step/epoch/seed metadata") are additive to the training loop below:
`train_deep_hedge` always returns a `final_checkpoint` (policy,
optimizer and minibatch-sampling generator state) and a per-epoch
`epoch_log`, and accepts an optional `resume_from` to continue training
from an earlier checkpoint instead of starting fresh. Resuming is
deterministic because minibatch sampling is drawn from its OWN local
`torch.Generator` (seeded and snapshotted/restored independently of the
global RNG `torch.manual_seed` affects only at weight initialization,
which a resumed run immediately overwrites via `load_state_dict`
anyway) -- confirmed, not assumed, by a test that trains N epochs
uninterrupted and separately trains the same N epochs split at an
arbitrary midpoint with a resume in between, and checks the two runs'
final policy weights match exactly.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np
import torch
from torch import nn

from prometheus.volterra.instruments import OptionType


class HedgePolicyMLP(nn.Module):
    """Maps (log-moneyness, fraction of time remaining, previous holding)
    to a bounded target holding in [-1, 1] (HDG-04: bounded actions)."""

    def __init__(self, hidden_size: int = 32) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(3, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        output: torch.Tensor = torch.tanh(self.net(features)).squeeze(-1)
        return output


def _build_features(
    spot: torch.Tensor, remaining_fraction: float, holdings: torch.Tensor, strike: float
) -> torch.Tensor:
    log_moneyness = torch.log(spot / strike)
    remaining = torch.full_like(spot, remaining_fraction)
    return torch.stack([log_moneyness, remaining, holdings], dim=1)


def _differentiable_cvar(losses: torch.Tensor, alpha: float) -> torch.Tensor:
    """The same quantile-integral estimator as
    titan.risk_metrics.historical_expected_shortfall, reimplemented on
    tensors so it is differentiable: gradient flows only to the tail (and a
    fractional weight to the boundary) observations -- the correct
    subgradient of empirical CVaR (Rockafellar-Uryasev)."""
    n = losses.shape[0]
    sorted_losses, _ = torch.sort(losses)
    k = min(math.ceil(alpha * n), n)
    tail_sum = sorted_losses[k:].sum()
    boundary_value = sorted_losses[k - 1]
    boundary_weight = k - alpha * n
    numerator = tail_sum + boundary_weight * boundary_value
    denominator = n * (1 - alpha)
    result: torch.Tensor = numerator / denominator
    return result


def _rollout(
    policy: HedgePolicyMLP,
    price_paths: torch.Tensor,
    dt: float,
    strike: float,
    maturity: float,
    option_type: OptionType,
    risk_free_rate: float,
    cost_rate: float,
    initial_premium: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Differentiable self-financing rollout. Returns
    (terminal_loss, total_turnover), each of shape (batch,)."""
    batch_size, n_plus_1 = price_paths.shape
    n_steps = n_plus_1 - 1
    holdings = torch.zeros(batch_size)
    cash = torch.full((batch_size,), float(initial_premium))
    turnover = torch.zeros(batch_size)
    cash_accrual = math.exp(risk_free_rate * dt)

    for t in range(n_steps):
        s_t = price_paths[:, t]
        remaining_fraction = max(maturity - t * dt, 1e-6) / maturity
        features = _build_features(s_t, remaining_fraction, holdings, strike)
        target = policy(features)

        trade = target - holdings
        cost = cost_rate * trade.abs() * s_t
        cash = (cash - trade * s_t - cost) * cash_accrual
        holdings = target
        turnover = turnover + trade.abs()

    s_terminal = price_paths[:, -1]
    if option_type == "call":
        payoff = torch.clamp(s_terminal - strike, min=0.0)
    else:
        payoff = torch.clamp(strike - s_terminal, min=0.0)

    final_wealth = cash + holdings * s_terminal - payoff
    terminal_loss = -final_wealth
    return terminal_loss, turnover


@dataclass(frozen=True, slots=True)
class EpochRecord:
    epoch: int
    seed: int
    objective: float
    gradient_norm: float


@dataclass(frozen=True, slots=True)
class TrainingCheckpoint:
    epoch: int
    seed: int
    policy_state_dict: dict[str, torch.Tensor]
    optimizer_state_dict: dict[str, object]
    generator_state: torch.Tensor


@dataclass(frozen=True, slots=True)
class DeepHedgeTrainingResult:
    policy: HedgePolicyMLP
    objective_history: list[float]
    epoch_log: tuple[EpochRecord, ...] = field(default_factory=tuple)
    final_checkpoint: TrainingCheckpoint | None = None


def train_deep_hedge(
    price_paths: np.ndarray,
    dt: float,
    strike: float,
    maturity: float,
    option_type: OptionType,
    risk_free_rate: float,
    cost_rate: float,
    initial_premium: float,
    cvar_alpha: float = 0.95,
    turnover_penalty: float = 0.0,
    n_epochs: int = 100,
    batch_size: int = 256,
    learning_rate: float = 1e-2,
    seed: int = 0,
    resume_from: TrainingCheckpoint | None = None,
) -> DeepHedgeTrainingResult:
    """Train a HedgePolicyMLP by sampling random minibatches of
    `price_paths` at each epoch. `price_paths` should be physical-measure
    (P) paths -- the policy only ever observes realized prices, never
    anything measure-specific -- the examples in this repository use
    stochastica.gbm, which may carry a nonzero equity risk premium (mu
    distinct from the risk-free rate used for cash financing).

    `resume_from`, if given, must carry the SAME `seed` (checked below)
    and continues training from its own recorded epoch through
    `n_epochs`, rather than training from epoch 0 -- see this module's
    own docstring for why this reproduces the uninterrupted run exactly."""
    if resume_from is not None and resume_from.seed != seed:
        raise ValueError(
            f"resume_from.seed ({resume_from.seed}) must match the seed passed to "
            f"train_deep_hedge ({seed}) -- resuming with a different seed would not "
            "reproduce the uninterrupted run"
        )
    torch.manual_seed(seed)
    n_paths = price_paths.shape[0]
    if batch_size > n_paths:
        raise ValueError("batch_size must not exceed the number of available paths")

    paths_tensor = torch.tensor(price_paths, dtype=torch.float32)
    policy = HedgePolicyMLP()
    optimizer = torch.optim.Adam(policy.parameters(), lr=learning_rate)
    history: list[float] = []
    epoch_log: list[EpochRecord] = []
    generator = torch.Generator().manual_seed(seed)
    start_epoch = 0

    if resume_from is not None:
        policy.load_state_dict(resume_from.policy_state_dict)
        optimizer.load_state_dict(resume_from.optimizer_state_dict)
        generator.set_state(resume_from.generator_state)
        start_epoch = resume_from.epoch

    for epoch in range(start_epoch, n_epochs):
        idx = torch.randint(0, n_paths, (batch_size,), generator=generator)
        batch = paths_tensor[idx]

        terminal_loss, turnover = _rollout(
            policy,
            batch,
            dt,
            strike,
            maturity,
            option_type,
            risk_free_rate,
            cost_rate,
            initial_premium,
        )
        objective = (
            _differentiable_cvar(terminal_loss, cvar_alpha) + turnover_penalty * turnover.mean()
        )

        optimizer.zero_grad()
        objective.backward()  # type: ignore[no-untyped-call]
        grad_norm_sq = sum(
            float(p.grad.detach().pow(2).sum().item())
            for p in policy.parameters()
            if p.grad is not None
        )
        optimizer.step()
        objective_value = float(objective.item())
        history.append(objective_value)
        epoch_log.append(
            EpochRecord(
                epoch=epoch, seed=seed, objective=objective_value,
                gradient_norm=math.sqrt(grad_norm_sq),
            )
        )

    final_checkpoint = TrainingCheckpoint(
        epoch=n_epochs,
        seed=seed,
        policy_state_dict={k: v.clone() for k, v in policy.state_dict().items()},
        optimizer_state_dict=copy.deepcopy(optimizer.state_dict()),
        generator_state=generator.get_state().clone(),
    )
    return DeepHedgeTrainingResult(
        policy=policy,
        objective_history=history,
        epoch_log=tuple(epoch_log),
        final_checkpoint=final_checkpoint,
    )


def generate_policy_hedge_ratios(
    policy: HedgePolicyMLP,
    price_paths: np.ndarray,
    dt: float,
    strike: float,
    maturity: float,
) -> np.ndarray:
    """Run a trained (or untrained, for a negative control) policy in
    inference mode over `price_paths`, causally, using the exact same
    feature construction as training, to produce a (n_paths, n_steps)
    hedge-ratio array compatible with
    simulate.simulate_self_financing_hedge -- so a learned policy is
    evaluated through the identical accounting used for the baselines
    (HDG-09, HDG-13)."""
    policy.eval()
    n_paths, n_plus_1 = price_paths.shape
    n_steps = n_plus_1 - 1
    paths_tensor = torch.tensor(price_paths, dtype=torch.float32)
    holdings = torch.zeros(n_paths)
    ratios = np.empty((n_paths, n_steps))
    with torch.no_grad():
        for t in range(n_steps):
            s_t = paths_tensor[:, t]
            remaining_fraction = max(maturity - t * dt, 1e-6) / maturity
            features = _build_features(s_t, remaining_fraction, holdings, strike)
            action = policy(features)
            holdings = action
            ratios[:, t] = action.numpy()
    return ratios


def evaluate_policy_action(
    policy: HedgePolicyMLP,
    spot: float,
    remaining_fraction: float,
    prev_holdings: float,
    strike: float,
) -> float:
    """A single-state inference call, as opposed to
    generate_policy_hedge_ratios' whole-path batch -- for a caller stepping
    through a simulation one macro step at a time (see hedging.online and
    orchestration.multi_step_run) rather than pre-generating a full price
    path up front. Uses the exact same feature construction as training and
    batch inference, so results agree with generate_policy_hedge_ratios
    call for call (tested in test_deep_hedge.py)."""
    if not math.isfinite(spot) or spot <= 0 or not math.isfinite(strike) or strike <= 0:
        raise ValueError("spot and strike must be finite and positive")
    if not math.isfinite(remaining_fraction) or not 0 <= remaining_fraction <= 1:
        raise ValueError("remaining_fraction must be in [0, 1]")
    if not math.isfinite(prev_holdings):
        raise ValueError("prev_holdings must be finite")
    policy.eval()
    with torch.no_grad():
        spot_tensor = torch.tensor([spot], dtype=torch.float32)
        holdings_tensor = torch.tensor([prev_holdings], dtype=torch.float32)
        features = _build_features(spot_tensor, remaining_fraction, holdings_tensor, strike)
        action = policy(features)
    return float(action.item())
