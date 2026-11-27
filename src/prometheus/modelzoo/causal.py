"""Machine-learning estimators of causal effects, and a hazard model, on data with a known truth.

Neither estimator can be checked against a real economy's true effect, so both are tested on
SIMULATED
data where the answer is known by construction. That is a test of the method, not a measurement of
any
real effect.

* **Double machine learning** (Chernozhukov et al. 2018) for the partially linear model
  `y = theta d + g(x) + e`, `d = m(x) + v`: with cross-fitting, a neural network predicts `y` from
  `x`
  and another predicts `d` from `x`, and `theta` is the slope of the `y` residual on the `d`
  residual.
  The competitor is OLS of `y` on `d` and a linear `x`, which is biased when `g` and `m` are
  nonlinear.
* **DeepIV** (Hartford et al. 2017) for `y = f(d) + u`, where `d` is correlated with the error `u`
  through an unobserved confounder and an instrument `z` moves `d` but not `u`. A first-stage
  network
  models the distribution of `d` given `z` (a Gaussian whose mean and scale it learns), and a second
  network `f` is fitted so that its expected value over that distribution matches `y`. The
  competitors
  are OLS and linear two-stage least squares.
* **DeepSurv** (Katzman et al. 2018): a Cox proportional-hazards model whose log-risk is a neural
  network, trained on the Cox partial likelihood. The competitor is the linear Cox model (the same
  loss
  with a linear log-risk). Scored by the concordance index and by the rank correlation with the true
  risk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

# ----- double machine learning --------------------------------------------------------------------

TRUE_THETA = 0.5


@dataclass(frozen=True, slots=True)
class PartiallyLinear:
    x: np.ndarray
    d: np.ndarray
    y: np.ndarray


def make_partially_linear(n: int, *, seed: int, dim: int = 10) -> PartiallyLinear:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((n, dim))
    m = np.sin(x[:, 0]) + 0.5 * x[:, 1] ** 2 + 0.5 * x[:, 2] * x[:, 3]
    g = np.cos(x[:, 0]) + x[:, 1] ** 2 - x[:, 2] * x[:, 3] + 0.5 * np.abs(x[:, 4])
    d = m + rng.standard_normal(n)
    y = TRUE_THETA * d + g + rng.standard_normal(n)
    return PartiallyLinear(x, d, y)


def _regressor(dim: int, width: int = 32) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(dim, width), nn.GELU(), nn.Linear(width, width), nn.GELU(), nn.Linear(width, 1)
    )


def _fit_regression(x: np.ndarray, y: np.ndarray, *, epochs: int, seed: int) -> nn.Module:
    torch.manual_seed(seed)
    net = _regressor(x.shape[1])
    optimiser = torch.optim.Adam(net.parameters(), lr=3e-3, weight_decay=1e-4)
    xt = torch.as_tensor(x, dtype=torch.float32)
    yt = torch.as_tensor(y, dtype=torch.float32)
    for _ in range(epochs):
        order = torch.randperm(len(xt))
        for lo in range(0, len(xt), 128):
            idx = order[lo : lo + 128]
            loss = ((net(xt[idx]).squeeze(-1) - yt[idx]) ** 2).mean()
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
    return net


def _predict(net: nn.Module, x: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        return np.asarray(
            net(torch.as_tensor(x, dtype=torch.float32)).squeeze(-1).numpy(), dtype=float
        )


def ols_effect(data: PartiallyLinear) -> float:
    design = np.column_stack([data.d, data.x, np.ones(len(data.d))])
    return float(np.linalg.lstsq(design, data.y, rcond=None)[0][0])


def double_ml_effect(
    data: PartiallyLinear, *, folds: int = 2, epochs: int = 40, seed: int = 0
) -> float:
    n = len(data.y)
    order = np.random.default_rng(seed).permutation(n)
    y_res, d_res = np.zeros(n), np.zeros(n)
    for k in range(folds):
        test = order[k::folds]
        train = np.setdiff1d(order, test)
        y_net = _fit_regression(data.x[train], data.y[train], epochs=epochs, seed=seed + 10 * k)
        d_net = _fit_regression(data.x[train], data.d[train], epochs=epochs, seed=seed + 10 * k + 1)
        y_res[test] = data.y[test] - _predict(y_net, data.x[test])
        d_res[test] = data.d[test] - _predict(d_net, data.x[test])
    return float((d_res @ y_res) / (d_res @ d_res))


# ----- DeepIV -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IVData:
    z: np.ndarray
    d: np.ndarray
    y: np.ndarray


def structural_f(d: np.ndarray) -> np.ndarray:
    return np.asarray(np.sin(d) + 0.3 * d, dtype=float)


def make_iv_data(n: int, *, seed: int) -> IVData:
    rng = np.random.default_rng(seed)
    z = rng.uniform(-2.0, 2.0, n)
    confounder = rng.standard_normal(n)
    d = 0.8 * z + 0.9 * confounder + 0.3 * rng.standard_normal(n)
    y = structural_f(d) + 1.0 * confounder + 0.1 * rng.standard_normal(n)
    return IVData(z, d, y)


def deep_iv_fit(data: IVData, *, epochs: int, seed: int, draws: int = 8) -> nn.Module:
    torch.manual_seed(seed)
    z = torch.as_tensor(data.z[:, None], dtype=torch.float32)
    d = torch.as_tensor(data.d, dtype=torch.float32)
    y = torch.as_tensor(data.y, dtype=torch.float32)
    first = nn.Sequential(nn.Linear(1, 16), nn.Tanh(), nn.Linear(16, 2))
    opt1 = torch.optim.Adam(first.parameters(), lr=1e-2)
    for _ in range(300):
        mu, raw = first(z).unbind(-1)
        sigma = torch.nn.functional.softplus(raw) + 1e-3
        nll = (0.5 * ((d - mu) / sigma) ** 2 + torch.log(sigma)).mean()
        opt1.zero_grad()
        nll.backward()
        opt1.step()
    with torch.no_grad():
        mu, raw = first(z).unbind(-1)
        sigma = torch.nn.functional.softplus(raw) + 1e-3
    second = nn.Sequential(
        nn.Linear(1, 32), nn.Tanh(), nn.Linear(32, 32), nn.Tanh(), nn.Linear(32, 1)
    )
    opt2 = torch.optim.Adam(second.parameters(), lr=3e-3)
    generator = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        eps = torch.randn(draws, len(d), generator=generator)
        samples = (mu + sigma * eps).unsqueeze(-1)  # (draws, n, 1)
        expected = second(samples).squeeze(-1).mean(0)  # E[f(d) | z]
        loss = ((expected - y) ** 2).mean()
        opt2.zero_grad()
        loss.backward()
        opt2.step()
    return second


def deep_iv_curve(net: nn.Module, grid: np.ndarray) -> np.ndarray:
    return _predict(net, grid[:, None])


def two_stage_least_squares_curve(data: IVData, grid: np.ndarray) -> np.ndarray:
    first = np.polyfit(data.z, data.d, 1)
    fitted = np.polyval(first, data.z)
    slope, intercept = np.polyfit(fitted, data.y, 1)
    return np.asarray(slope * grid + intercept, dtype=float)


def ols_curve(data: IVData, grid: np.ndarray) -> np.ndarray:
    slope, intercept = np.polyfit(data.d, data.y, 1)
    return np.asarray(slope * grid + intercept, dtype=float)


def curve_rmse(estimate: np.ndarray, grid: np.ndarray) -> float:
    """RMSE against the true curve after removing the mean (a level is not identified by IV)."""
    truth = structural_f(grid)
    return float(np.sqrt(np.mean(((estimate - estimate.mean()) - (truth - truth.mean())) ** 2)))


# ----- survival -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurvivalData:
    x: np.ndarray
    time: np.ndarray
    event: np.ndarray  # 1 observed failure, 0 censored
    true_risk: np.ndarray


def make_survival(n: int, *, seed: int, dim: int = 6, censor_rate: float = 0.25) -> SurvivalData:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal((n, dim))
    risk = 0.8 * x[:, 0] + 0.9 * x[:, 1] * x[:, 2] + 0.6 * np.abs(x[:, 3]) - 0.5 * x[:, 4] ** 2
    shape = 1.5
    u = rng.random(n)
    event_time = (-np.log(u) / np.exp(risk)) ** (1.0 / shape)
    censor_time = rng.exponential(1.0 / censor_rate, n) * np.median(event_time) * 2.0
    observed = np.minimum(event_time, censor_time)
    return SurvivalData(x, observed, (event_time <= censor_time).astype(float), risk)


def cox_partial_likelihood(
    log_risk: torch.Tensor, time: torch.Tensor, event: torch.Tensor
) -> torch.Tensor:
    """Negative Cox partial log-likelihood (Breslow, no tie handling: continuous times)."""
    order = torch.argsort(-time)  # latest first, so the risk set of i is the prefix up to i
    risk, ev = log_risk[order], event[order]
    log_cumulative = torch.logcumsumexp(risk, dim=0)
    return -((risk - log_cumulative) * ev).sum() / ev.sum().clamp(min=1.0)


def concordance(score: np.ndarray, time: np.ndarray, event: np.ndarray) -> float:
    """Harrell's C: among comparable pairs, the share where the higher score fails earlier."""
    concordant = comparable = 0.0
    for i in range(len(time)):
        if not event[i]:
            continue
        later = time > time[i]
        comparable += float(later.sum())
        concordant += float((score[later] < score[i]).sum()) + 0.5 * float(
            (score[later] == score[i]).sum()
        )
    return concordant / comparable if comparable else math.nan


def fit_cox(
    train: SurvivalData, *, hidden: int, epochs: int, seed: int, lr: float = 5e-3
) -> nn.Module:
    """hidden = 0 gives the linear Cox model; hidden > 0 gives DeepSurv."""
    torch.manual_seed(seed)
    dim = train.x.shape[1]
    net: nn.Module = (
        nn.Linear(dim, 1, bias=False)
        if hidden == 0
        else nn.Sequential(
            nn.Linear(dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 1),
        )
    )
    x = torch.as_tensor(train.x, dtype=torch.float32)
    t = torch.as_tensor(train.time, dtype=torch.float32)
    e = torch.as_tensor(train.event, dtype=torch.float32)
    optimiser = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-4)
    for _ in range(epochs):
        loss = cox_partial_likelihood(net(x).squeeze(-1), t, e)
        optimiser.zero_grad()
        loss.backward()  # type: ignore[no-untyped-call]
        optimiser.step()
    return net


def risk_scores(net: nn.Module, x: np.ndarray) -> np.ndarray:
    return _predict(net, x)
