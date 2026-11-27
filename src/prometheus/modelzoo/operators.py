"""Operator learning: a Fourier Neural Operator (FNO), a DeepONet and a plain MLP, learning the
Black-Scholes *pricing operator*.

The operator maps a whole function to a whole function: the terminal payoff of a European
portfolio, as a curve over the spot price, to its value today, as a curve over the spot price. For a
portfolio of calls the answer is exact (a weighted sum of closed-form Black-Scholes calls), so every
model is judged against the truth, not against another approximation.

Data: payoff(S) = sum_k w_k * max(S - K_k, 0) with 1 to `max_kinks` calls, strikes K_k in [70, 130]
and weights w_k in [-1, 1]; the volatility sigma in [0.10, 0.40] is a second input; the rate (3%)
and
the maturity (1 year) are fixed. Inputs and targets of a sample are divided by the sample's largest
absolute payoff, so the relative error is the same in every unit.

Three architectures:

* `FNO1d` (Li et al. 2021): lift, then Fourier layers that multiply the lowest `modes` Fourier
  coefficients by learned complex weights and add a pointwise skip, then project. It is defined on
  functions, so it runs on any grid.
* `DeepONet` (Lu et al. 2021): a branch network reads the payoff at fixed sensors, a trunk network
  reads the query spot, and the price is their inner product. It can be asked about any spot.
* `MLPBaseline`: one dense network from the payoff vector to the price vector, tied to one grid.

The two fixed-grid models (DeepONet's sensors, the MLP) are made to work on another grid by linear
interpolation of the input, and the MLP of its output too; the FNO needs nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F
from scipy.stats import norm
from torch import nn

SPOT_LOW = 40.0
SPOT_HIGH = 160.0
STRIKE_LOW = 70.0
STRIKE_HIGH = 130.0
SIGMA_LOW = 0.10
SIGMA_HIGH = 0.40
RATE = 0.03
MATURITY = 1.0


def spot_grid(size: int) -> np.ndarray:
    return np.linspace(SPOT_LOW, SPOT_HIGH, size)


def bs_call(spot: np.ndarray, strike: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Closed-form Black-Scholes call value, broadcasting; rate and maturity are the module's."""
    spot, strike, sigma = np.broadcast_arrays(
        np.asarray(spot, float), np.asarray(strike, float), np.asarray(sigma, float)
    )
    vol_t = sigma * np.sqrt(MATURITY)
    d1 = (np.log(spot / strike) + (RATE + 0.5 * sigma**2) * MATURITY) / vol_t
    d2 = d1 - vol_t
    return np.asarray(
        spot * norm.cdf(d1) - strike * np.exp(-RATE * MATURITY) * norm.cdf(d2), dtype=float
    )


@dataclass(frozen=True, slots=True)
class OperatorData:
    payoff: np.ndarray  # (n, g) scaled payoff curves
    sigma: np.ndarray  # (n,)
    price: np.ndarray  # (n, g) scaled exact prices
    grid: np.ndarray  # (g,)

    @property
    def size(self) -> int:
        return int(self.payoff.shape[0])


def make_operator_data(
    n: int, grid_size: int, *, seed: int, min_kinks: int = 1, max_kinks: int = 3
) -> OperatorData:
    if n < 1 or grid_size < 8 or not 1 <= min_kinks <= max_kinks:
        raise ValueError("n >= 1, grid_size >= 8 and 1 <= min_kinks <= max_kinks are required")
    rng = np.random.default_rng(seed)
    grid = spot_grid(grid_size)
    sigma = rng.uniform(SIGMA_LOW, SIGMA_HIGH, size=n)
    payoff = np.zeros((n, grid_size))
    price = np.zeros((n, grid_size))
    for i in range(n):
        kinks = int(rng.integers(min_kinks, max_kinks + 1))
        strikes = rng.uniform(STRIKE_LOW, STRIKE_HIGH, size=kinks)
        weights = rng.uniform(-1.0, 1.0, size=kinks)
        payoff[i] = (weights[:, None] * np.maximum(grid[None, :] - strikes[:, None], 0.0)).sum(0)
        price[i] = (weights[:, None] * bs_call(grid[None, :], strikes[:, None], sigma[i])).sum(0)
    scale = np.maximum(np.abs(payoff).max(axis=1, keepdims=True), 1e-9)
    return OperatorData(payoff / scale, sigma, price / scale, grid)


def relative_l2(pred: np.ndarray, truth: np.ndarray) -> float:
    """Mean over samples of ||pred - truth|| / ||truth||."""
    num = np.linalg.norm(pred - truth, axis=1)
    den = np.maximum(np.linalg.norm(truth, axis=1), 1e-12)
    return float(np.mean(num / den))


def _coords(batch: int, size: int, device: torch.device) -> torch.Tensor:
    return torch.linspace(0.0, 1.0, size, device=device).expand(batch, 1, size)


class SpectralConv1d(nn.Module):
    def __init__(self, channels: int, modes: int) -> None:
        super().__init__()
        self.modes = modes
        scale = 1.0 / channels
        self.weight = nn.Parameter(
            scale * torch.randn(channels, channels, modes, dtype=torch.cfloat)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        size = x.shape[-1]
        spectrum = torch.fft.rfft(x)
        keep = min(self.modes, spectrum.shape[-1])
        out = torch.zeros_like(spectrum)
        out[:, :, :keep] = torch.einsum(
            "bix,iox->box", spectrum[:, :, :keep], self.weight[:, :, :keep]
        )
        result: torch.Tensor = torch.fft.irfft(out, n=size)
        return result


class FNO1d(nn.Module):
    def __init__(self, width: int = 32, modes: int = 12, layers: int = 4) -> None:
        super().__init__()
        self.lift = nn.Conv1d(3, width, 1)
        self.spectral = nn.ModuleList(SpectralConv1d(width, modes) for _ in range(layers))
        self.skip = nn.ModuleList(nn.Conv1d(width, width, 1) for _ in range(layers))
        self.head1 = nn.Conv1d(width, 64, 1)
        self.head2 = nn.Conv1d(64, 1, 1)

    def forward(self, payoff: torch.Tensor, sigma: torch.Tensor) -> torch.Tensor:
        batch, size = payoff.shape
        x = torch.cat(
            [
                payoff.unsqueeze(1),
                sigma.view(batch, 1, 1).expand(batch, 1, size),
                _coords(batch, size, payoff.device),
            ],
            dim=1,
        )
        x = self.lift(x)
        for spectral, skip in zip(self.spectral, self.skip, strict=True):
            x = F.gelu(spectral(x) + skip(x))
        result: torch.Tensor = self.head2(F.gelu(self.head1(x))).squeeze(1)
        return result


def _mlp(sizes: list[int]) -> nn.Sequential:
    layers: list[nn.Module] = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers.append(nn.GELU())
    return nn.Sequential(*layers)


class DeepONet(nn.Module):
    def __init__(self, sensors: int = 64, latent: int = 64, hidden: int = 128) -> None:
        super().__init__()
        self.sensors = sensors
        self.branch = _mlp([sensors + 1, hidden, hidden, latent])
        self.trunk = _mlp([1, hidden, hidden, latent])
        self.bias = nn.Parameter(torch.zeros(1))

    def forward(self, payoff: torch.Tensor, sigma: torch.Tensor) -> torch.Tensor:
        batch, size = payoff.shape
        seen = payoff
        if size != self.sensors:
            seen = F.interpolate(
                payoff.unsqueeze(1), size=self.sensors, mode="linear", align_corners=True
            )
            seen = seen.squeeze(1)
        b = self.branch(torch.cat([seen, sigma.view(batch, 1)], dim=1))  # (B, p)
        t = self.trunk(torch.linspace(0.0, 1.0, size, device=payoff.device).view(size, 1))  # (g, p)
        priced: torch.Tensor = b @ t.T + self.bias
        return priced


class MLPBaseline(nn.Module):
    def __init__(self, size: int = 64, hidden: int = 256) -> None:
        super().__init__()
        self.size = size
        self.net = _mlp([size + 1, hidden, hidden, size])

    def forward(self, payoff: torch.Tensor, sigma: torch.Tensor) -> torch.Tensor:
        batch, size = payoff.shape
        seen = payoff
        if size != self.size:
            seen = F.interpolate(
                payoff.unsqueeze(1), size=self.size, mode="linear", align_corners=True
            )
            seen = seen.squeeze(1)
        out = self.net(torch.cat([seen, sigma.view(batch, 1)], dim=1))
        if size != self.size:
            out = F.interpolate(out.unsqueeze(1), size=size, mode="linear", align_corners=True)
            out = out.squeeze(1)
        result: torch.Tensor = out
        return result


def build_model(name: str, grid_size: int) -> nn.Module:
    if name == "fno":
        return FNO1d()
    if name == "deeponet":
        return DeepONet(sensors=grid_size)
    if name == "mlp":
        return MLPBaseline(size=grid_size)
    raise ValueError(f"unknown operator model {name!r}; expected fno, deeponet or mlp")


@dataclass(frozen=True, slots=True)
class OperatorTraining:
    epochs: int
    final_loss: float
    seconds: float
    parameters: int


def train_operator(
    model: nn.Module,
    data: OperatorData,
    *,
    epochs: int,
    seed: int,
    batch_size: int = 64,
    learning_rate: float = 2e-3,
) -> OperatorTraining:
    if epochs < 1:
        raise ValueError("epochs must be positive")
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    payoff = torch.as_tensor(data.payoff, dtype=torch.float32)
    sigma = torch.as_tensor(data.sigma, dtype=torch.float32)
    price = torch.as_tensor(data.price, dtype=torch.float32)
    optimiser = torch.optim.Adam(model.parameters(), lr=learning_rate)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)
    start = time.perf_counter()
    loss_value = float("nan")
    model.train()
    for _ in range(epochs):
        order = torch.randperm(data.size, generator=generator)
        for lo in range(0, data.size, batch_size):
            idx = order[lo : lo + batch_size]
            loss = F.mse_loss(model(payoff[idx], sigma[idx]), price[idx])
            optimiser.zero_grad()
            loss.backward()  # type: ignore[no-untyped-call]
            optimiser.step()
            loss_value = float(loss.detach())
        schedule.step()
    return OperatorTraining(
        epochs=epochs,
        final_loss=loss_value,
        seconds=time.perf_counter() - start,
        parameters=sum(p.numel() for p in model.parameters()),
    )


def predict(model: nn.Module, data: OperatorData) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        out = model(
            torch.as_tensor(data.payoff, dtype=torch.float32),
            torch.as_tensor(data.sigma, dtype=torch.float32),
        )
    return np.asarray(out.numpy(), dtype=float)
