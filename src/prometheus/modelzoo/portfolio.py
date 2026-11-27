"""Decision-focused learning for a long-only portfolio, with a differentiable optimisation layer.

`LongOnlyQP` is a layer in the spirit of OptNet (Amos and Kolter 2017) and cvxpylayers (Agrawal et
al.
2019): it solves

    minimise  0.5 w' S w - (1/risk_aversion) mu' w     subject to  sum(w) = 1,  w >= 0

exactly (an active-set search over supports, so it is meant for a handful of assets) and its
backward
pass differentiates the solution with respect to the expected returns `mu` through the KKT
conditions
on the free variables, so a network that produces `mu` can be trained on the *decision's* outcome.

`two_stage_fit` trains a return predictor on mean squared error (predict, then optimise). `dfl_fit`
trains the same predictor through the layer on the realised utility of the portfolio it implies
(decision-focused learning, Wilder et al. 2019). The assets are the three Fama-French factor
portfolios
(market, size, value; committed monthly data), the features are each factor's recent returns, the
covariance is a shrunk 60-month estimate, and the score is the out-of-sample Sharpe ratio.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn


def solve_long_only(
    covariance: np.ndarray, mu: np.ndarray, risk_aversion: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return (weights, free-set mask). Exact for small n: try supports, keep the KKT-feasible
    one."""
    n = len(mu)
    q = mu / risk_aversion
    best: tuple[float, np.ndarray] | None = None
    for size in range(1, n + 1):
        for support in itertools.combinations(range(n), size):
            idx = list(support)
            kkt = np.zeros((size + 1, size + 1))
            kkt[:size, :size] = covariance[np.ix_(idx, idx)]
            kkt[:size, size] = -1.0
            kkt[size, :size] = 1.0
            rhs = np.concatenate([q[idx], [1.0]])
            try:
                sol = np.linalg.solve(kkt, rhs)
            except np.linalg.LinAlgError:
                continue
            w = np.zeros(n)
            w[idx] = sol[:size]
            nu = sol[size]
            if (w[idx] < -1e-10).any():
                continue
            gradient = (
                covariance @ w - q - nu
            )  # reduced cost of each variable; >= 0 off the support
            if size < n and (np.delete(gradient, idx) < -1e-9).any():
                continue
            value = 0.5 * w @ covariance @ w - q @ w
            if best is None or value < best[0] - 1e-12:
                best = (value, w)
    if best is None:
        raise RuntimeError("no feasible support found for the long-only QP")
    weights = np.clip(best[1], 0.0, None)
    weights = weights / weights.sum()
    return weights, weights > 1e-9


class _QPFunction(torch.autograd.Function):
    @staticmethod
    def forward(
        ctx: object, mu: torch.Tensor, covariance: torch.Tensor, risk_aversion: float
    ) -> torch.Tensor:
        cov = covariance.detach().numpy().astype(float)
        out = np.zeros(mu.shape)
        free_masks = []
        for i in range(mu.shape[0]):
            w, free = solve_long_only(cov[i], mu[i].detach().numpy().astype(float), risk_aversion)
            out[i] = w
            free_masks.append(free)
        ctx.cov = cov  # type: ignore[attr-defined]
        ctx.free = free_masks  # type: ignore[attr-defined]
        ctx.risk_aversion = risk_aversion  # type: ignore[attr-defined]
        return torch.as_tensor(out, dtype=mu.dtype)

    @staticmethod
    def backward(ctx: object, grad_output: torch.Tensor) -> tuple[torch.Tensor, None, None]:
        cov, free_masks, ra = ctx.cov, ctx.free, ctx.risk_aversion  # type: ignore[attr-defined]
        grad = np.zeros(grad_output.shape)
        g = grad_output.detach().numpy().astype(float)
        for i, free in enumerate(free_masks):
            idx = np.flatnonzero(free)
            size = len(idx)
            kkt = np.zeros((size + 1, size + 1))
            kkt[:size, :size] = cov[i][np.ix_(idx, idx)]
            kkt[:size, size] = -1.0
            kkt[size, :size] = 1.0
            inverse = np.linalg.inv(kkt)
            # dw_F / dmu_F = (1 / risk_aversion) * (top-left block of the KKT inverse)
            grad[i, idx] = (inverse[:size, :size] @ g[i, idx]) / ra
        return torch.as_tensor(grad, dtype=grad_output.dtype), None, None


def long_only_weights(
    mu: torch.Tensor, covariance: torch.Tensor, risk_aversion: float
) -> torch.Tensor:
    out: torch.Tensor = _QPFunction.apply(mu, covariance, risk_aversion)
    return out


# ----- data and strategies ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactorData:
    months: np.ndarray  # yyyymm
    returns: np.ndarray  # (T, 3) monthly excess returns of Mkt-RF, SMB, HML in percent / 100
    features: np.ndarray  # (T, 6): last month and trailing 12-month mean of each factor
    covariance: np.ndarray  # (T, 3, 3) shrunk 60-month covariance known at the START of each month


def load_factor_data(path: str) -> FactorData:
    raw = np.genfromtxt(path, delimiter=",", skip_header=1)
    months = raw[:, 0].astype(int)
    returns = raw[:, 1:4] / 100.0
    t = len(months)
    features = np.full((t, 6), np.nan)
    covariance = np.full((t, 3, 3), np.nan)
    for i in range(60, t):
        last = returns[i - 1]
        mean12 = returns[i - 12 : i].mean(axis=0)
        features[i] = np.concatenate([last, mean12])
        window = returns[i - 60 : i]
        sample = np.cov(window.T)
        target = np.diag(np.diag(sample))
        covariance[i] = 0.7 * sample + 0.3 * target + 1e-8 * np.eye(3)
    return FactorData(months, returns, features, covariance)


class ReturnNet(nn.Module):
    def __init__(self, n_in: int = 6, width: int = 16) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_in, width), nn.Tanh(), nn.Linear(width, 3))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out: torch.Tensor = self.net(x)
        return out


def _scale(x: np.ndarray, rows: np.ndarray) -> np.ndarray:
    mean, std = x[rows].mean(axis=0), x[rows].std(axis=0) + 1e-9
    return np.asarray((x - mean) / std)


def fit_predictor(
    data: FactorData,
    train_rows: np.ndarray,
    *,
    decision_focused: bool,
    risk_aversion: float,
    epochs: int,
    seed: int,
) -> ReturnNet:
    torch.manual_seed(seed)
    x = torch.as_tensor(_scale(np.nan_to_num(data.features), train_rows), dtype=torch.float32)
    r = torch.as_tensor(data.returns, dtype=torch.float32)
    cov = torch.as_tensor(np.nan_to_num(data.covariance), dtype=torch.float32)
    net = ReturnNet()
    optimiser = torch.optim.Adam(net.parameters(), lr=3e-3, weight_decay=1e-3)
    rows = torch.as_tensor(train_rows)
    for _ in range(epochs):
        order = rows[torch.randperm(len(rows))]
        for lo in range(0, len(order), 128):
            idx = order[lo : lo + 128]
            mu = net(x[idx])
            if decision_focused:
                w = long_only_weights(mu, cov[idx], risk_aversion)
                realised = (w * r[idx]).sum(-1)
                loss = -(realised - 0.5 * risk_aversion * realised**2).mean()
            else:
                loss = ((mu - r[idx]) ** 2).mean()
            optimiser.zero_grad()
            loss.backward()  # type: ignore[no-untyped-call]
            optimiser.step()
    return net


def strategy_returns(
    data: FactorData,
    rows: np.ndarray,
    weights: np.ndarray,
) -> np.ndarray:
    return np.asarray((weights * data.returns[rows]).sum(axis=1), dtype=float)


def predicted_weights(
    net: ReturnNet, data: FactorData, train_rows: np.ndarray, rows: np.ndarray, risk_aversion: float
) -> np.ndarray:
    x = torch.as_tensor(_scale(np.nan_to_num(data.features), train_rows), dtype=torch.float32)
    with torch.no_grad():
        mu = net(x[rows])
    cov = torch.as_tensor(data.covariance[rows], dtype=torch.float32)
    return np.asarray(long_only_weights(mu, cov, risk_aversion).numpy(), dtype=float)


def min_variance_weights(data: FactorData, rows: np.ndarray) -> np.ndarray:
    out = np.zeros((len(rows), 3))
    for i, row in enumerate(rows):
        out[i], _ = solve_long_only(data.covariance[row], np.zeros(3), 1.0)
    return out


def sharpe(returns: np.ndarray) -> float:
    """Annualised Sharpe ratio of monthly excess returns."""
    sd = float(np.std(returns, ddof=1))
    return float(np.sqrt(12.0) * np.mean(returns) / sd) if sd > 0 else 0.0
