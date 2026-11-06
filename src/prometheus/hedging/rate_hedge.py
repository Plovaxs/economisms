"""Causal current-rate MLP and a parameter-matched rate-blind ablation.

Both policies train through identical changing-rate cash accounting and use
identical data/minibatches. Only the fourth input differs: standardized
current rate or zero. No future rates, macro states or outcomes are features.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from prometheus.experiments.manifest import compute_result_hash
from prometheus.hedging.comparison import HedgeComparisonSettings
from prometheus.hedging.deep_hedge import _differentiable_cvar
from prometheus.volterra.instruments import OptionType


class RateHedgePolicyMLP(nn.Module):
    def __init__(self, *, rate_aware: bool, rate_center: float, rate_scale: float) -> None:
        super().__init__()
        if type(rate_aware) is not bool:
            raise ValueError("rate_aware must be bool")
        if not math.isfinite(rate_center) or not math.isfinite(rate_scale) or rate_scale <= 0:
            raise ValueError("rate center must be finite and scale finite positive")
        self.rate_aware, self.rate_center, self.rate_scale = rate_aware, rate_center, rate_scale
        self.net = nn.Sequential(
            nn.Linear(4, 32),
            nn.ReLU(),
            nn.Linear(32, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        result: torch.Tensor = torch.tanh(self.net(features)).squeeze(-1)
        return result

    def features(
        self,
        spot: torch.Tensor,
        remaining: float,
        holdings: torch.Tensor,
        strike: float,
        current_rate: torch.Tensor,
    ) -> torch.Tensor:
        rate = (
            (current_rate - self.rate_center) / self.rate_scale
            if self.rate_aware
            else torch.zeros_like(current_rate)
        )
        return torch.stack(
            (torch.log(spot / strike), torch.full_like(spot, remaining), holdings, rate), dim=1
        )


def parameter_hash(policy: RateHedgePolicyMLP) -> str:
    h = hashlib.sha256()
    for name, tensor in sorted(policy.state_dict().items()):
        h.update(name.encode())
        h.update(tensor.detach().cpu().numpy().astype("<f4", copy=False).tobytes())
    return h.hexdigest()


def rate_policy_hash(policy: RateHedgePolicyMLP) -> str:
    """Bind parameters AND feature semantics, including the ablation switch."""
    return compute_result_hash(
        {
            "parameters_sha256": parameter_hash(policy),
            "feature_schema": "log-moneyness,remaining-fraction,previous-holding,current-rate-v1",
            "rate_aware": policy.rate_aware,
            "rate_center": policy.rate_center,
            "rate_scale": policy.rate_scale,
        }
    )


def _data(price_paths: np.ndarray, decision_rates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    paths, rates = np.asarray(price_paths, dtype=float), np.asarray(decision_rates, dtype=float)
    if paths.ndim != 2 or paths.shape[0] < 1 or paths.shape[1] < 2:
        raise ValueError("positive paths with at least two observations are required")
    if rates.shape == (paths.shape[1],):
        rates = np.broadcast_to(rates, paths.shape)
    if rates.shape != paths.shape:
        raise ValueError("decision_rates require one rate per path/observation")
    if not np.all(np.isfinite(paths)) or np.any(paths <= 0) or not np.all(np.isfinite(rates)):
        raise ValueError("prices must be finite positive and rates finite")
    # The learned policy runs in float32. Reject inputs that overflow/underflow on conversion.
    with np.errstate(over="ignore", under="ignore"):
        p32, r32 = paths.astype(np.float32), rates.astype(np.float32)
    if not np.all(np.isfinite(p32)) or np.any(p32 <= 0) or not np.all(np.isfinite(r32)):
        raise ValueError("data cannot be represented as finite positive float32 prices/rates")
    return paths, rates


def rate_hedge_rollout(
    policy: RateHedgePolicyMLP,
    paths: torch.Tensor,
    rates: torch.Tensor,
    dt: float,
    strike: float,
    option_type: OptionType,
    cost_rate: float,
    premium: float,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Differentiable trade-then-accrue rollout; returns loss, turnover, cost, targets.

    Inputs are validated at training/inference boundaries. rates[:,t] is
    known at the opening of interval t; expiry's rate is never consumed.
    """
    n_paths, n_obs = paths.shape
    holdings, cash = torch.zeros(n_paths), torch.full((n_paths,), float(premium))
    turnover, cost_sum = torch.zeros(n_paths), torch.zeros(n_paths)
    targets = []
    for t in range(n_obs - 1):
        spot = paths[:, t]
        target = policy(
            policy.features(spot, (n_obs - 1 - t) / (n_obs - 1), holdings, strike, rates[:, t])
        )
        trade = target - holdings
        cost = cost_rate * trade.abs() * spot
        cash = (cash - trade * spot - cost) * torch.exp(rates[:, t] * dt)
        turnover = turnover + trade.abs()
        cost_sum = cost_sum + cost
        holdings = target
        targets.append(target)
    intrinsic = paths[:, -1] - strike if option_type == "call" else strike - paths[:, -1]
    loss = -(cash + holdings * paths[:, -1] - torch.clamp(intrinsic, min=0.0))
    return loss, turnover, cost_sum, torch.stack(targets, dim=1)


@dataclass(frozen=True, slots=True)
class RateTrainingDiagnostic:
    objective: float
    cvar: float
    mean_loss: float
    mean_turnover: float
    gradient_norm_before_clip: float
    gradient_clipped: bool
    saturation_fraction: float


@dataclass(frozen=True, slots=True)
class RateHedgeTrainingResult:
    policy: RateHedgePolicyMLP
    initial_parameter_hash: str
    minibatches_sha256: str
    diagnostics: tuple[RateTrainingDiagnostic, ...]


def train_rate_hedge(
    price_paths: np.ndarray,
    decision_rates: np.ndarray,
    settings: HedgeComparisonSettings,
    *,
    dt: float,
    initial_premium: float,
    rate_aware: bool,
    rate_center: float,
    rate_scale: float,
    max_gradient_norm: float,
    seed: int,
) -> RateHedgeTrainingResult:
    paths, rates = _data(price_paths, decision_rates)
    if not isinstance(settings, HedgeComparisonSettings):
        raise ValueError("settings must be HedgeComparisonSettings")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if any(not math.isfinite(v) or v <= 0 for v in (dt, max_gradient_norm)):
        raise ValueError("dt and gradient bound must be finite positive")
    if not math.isfinite(initial_premium):
        raise ValueError("initial premium must be finite")
    if settings.batch_size > len(paths):
        raise ValueError("batch_size must not exceed available paths")
    x, r = torch.tensor(paths, dtype=torch.float32), torch.tensor(rates, dtype=torch.float32)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        policy = RateHedgePolicyMLP(
            rate_aware=rate_aware, rate_center=rate_center, rate_scale=rate_scale
        )
    initial_hash = parameter_hash(policy)
    optimizer = torch.optim.Adam(policy.parameters(), lr=settings.learning_rate)
    generator = torch.Generator().manual_seed(seed)
    batch_hash = hashlib.sha256()
    diagnostics = []
    for _ in range(settings.n_train_epochs):
        idx = torch.randint(0, len(paths), (settings.batch_size,), generator=generator)
        batch_hash.update(idx.numpy().astype("<i8", copy=False).tobytes())
        losses, turnover, _, targets = rate_hedge_rollout(
            policy,
            x[idx],
            r[idx],
            dt,
            settings.strike,
            settings.option_type,
            settings.cost_rate,
            initial_premium,
        )
        cvar = _differentiable_cvar(losses, settings.cvar_alpha)
        objective = cvar + settings.turnover_penalty * turnover.mean()
        if not bool(torch.isfinite(objective)):
            raise ValueError("non-finite training objective")
        optimizer.zero_grad()
        objective.backward()  # type: ignore[no-untyped-call]
        norm = float(torch.nn.utils.clip_grad_norm_(policy.parameters(), max_gradient_norm))
        if not math.isfinite(norm):
            raise ValueError("non-finite training gradients")
        optimizer.step()
        if any(not bool(torch.isfinite(p).all()) for p in policy.parameters()):
            raise ValueError("non-finite fitted policy parameters")
        diagnostics.append(
            RateTrainingDiagnostic(
                float(objective.detach()),
                float(cvar.detach()),
                float(losses.detach().mean()),
                float(turnover.detach().mean()),
                norm,
                norm > max_gradient_norm,
                float((targets.detach().abs() >= 0.99).float().mean()),
            )
        )
    return RateHedgeTrainingResult(policy, initial_hash, batch_hash.hexdigest(), tuple(diagnostics))


def generate_rate_hedge_ratios(
    policy: RateHedgePolicyMLP,
    price_paths: np.ndarray,
    decision_rates: np.ndarray,
    *,
    strike: float,
) -> np.ndarray:
    paths, rates = _data(price_paths, decision_rates)
    if not math.isfinite(strike) or strike <= 0:
        raise ValueError("strike must be finite positive")
    x, r = torch.tensor(paths, dtype=torch.float32), torch.tensor(rates, dtype=torch.float32)
    holdings = torch.zeros(len(paths))
    result = np.empty((len(paths), paths.shape[1] - 1))
    policy.eval()
    with torch.no_grad():
        for t in range(paths.shape[1] - 1):
            features = policy.features(
                x[:, t], (paths.shape[1] - 1 - t) / (paths.shape[1] - 1), holdings, strike, r[:, t]
            )
            holdings = policy(features)
            result[:, t] = holdings.numpy()
    if not np.all(np.isfinite(result)):
        raise ValueError("non-finite inferred targets")
    return result
