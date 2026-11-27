"""Modern deep forecasters, small enough to train on a few hundred monthly observations.

Every model reads a window of the last 12 months (channel 0 is the monthly growth rate of the CPI,
and
optional further channels are macro series) and forecasts next month's growth. They are written from
scratch; none of them is the published implementation.

* `NBeats` (Oreshkin et al. 2020): stacked fully connected blocks, each emitting a backcast that is
  subtracted from the input before the next block and a forecast that is summed.
* `NHiTS` (Challu et al. 2023): the same, but each block first max-pools its input at its own
rate, so
  blocks specialise in different time scales.
* `PatchTST` (Nie et al. 2023): the window is cut into patches, each patch is embedded, and a
  Transformer encoder reads the patches (channel-independent).
* `DeepAR` (Salinas et al. 2020): a recurrent network that outputs the mean and scale of a
Gaussian for
  the next value at every step, trained by likelihood, so it forecasts a distribution.
* `TFTLite` (Lim et al. 2021, much reduced): learned variable selection, an LSTM encoder, one
  self-attention layer with a gate and quantile outputs.
* `SSMNet` (Gu et al. 2022; Gu and Dao 2023): stacked diagonal linear state-space layers; with
  `selective=True` the step size depends on the input, which is the idea behind Mamba. The scan is
  an
  ordinary loop over 12 steps, not Mamba's hardware kernel.

With about 340 training months (1962 to 1989) these models have far more parameters than data, so
the
interesting question is whether their structure compensates; see the study that uses them.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

WINDOW = 12
QUANTILES = (0.1, 0.5, 0.9)


def _mlp(sizes: list[int]) -> nn.Sequential:
    layers: list[nn.Module] = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers.append(nn.ReLU())
    return nn.Sequential(*layers)


class Forecaster(nn.Module):
    """A forecaster has a training loss on (window, target) and a point forecast."""

    def loss(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        return F.mse_loss(self.point(x), y)

    def point(self, x: torch.Tensor) -> torch.Tensor:
        raise NotImplementedError


class NBeats(Forecaster):
    def __init__(self, width: int = 64, blocks: int = 3) -> None:
        super().__init__()
        self.stack = nn.ModuleList(_mlp([WINDOW, width, width, WINDOW + 1]) for _ in range(blocks))

    def point(self, x: torch.Tensor) -> torch.Tensor:
        residual = x[:, :, 0]
        forecast = torch.zeros(x.shape[0], device=x.device)
        for block in self.stack:
            out = block(residual)
            residual = residual - out[:, :WINDOW]
            forecast = forecast + out[:, WINDOW]
        return forecast


class NHiTS(Forecaster):
    def __init__(self, width: int = 64, pools: tuple[int, ...] = (4, 2, 1)) -> None:
        super().__init__()
        self.pools = pools
        self.stack = nn.ModuleList(
            _mlp([WINDOW // p, width, width, WINDOW // p + 1]) for p in pools
        )

    def point(self, x: torch.Tensor) -> torch.Tensor:
        residual = x[:, :, 0]
        forecast = torch.zeros(x.shape[0], device=x.device)
        for pool, block in zip(self.pools, self.stack, strict=True):
            pooled = F.max_pool1d(residual.unsqueeze(1), pool).squeeze(1) if pool > 1 else residual
            out = block(pooled)
            back = out[:, : WINDOW // pool]
            if pool > 1:
                back = F.interpolate(back.unsqueeze(1), size=WINDOW, mode="nearest").squeeze(1)
            residual = residual - back
            forecast = forecast + out[:, -1]
        return forecast


class PatchTST(Forecaster):
    def __init__(self, patch: int = 3, dim: int = 16, layers: int = 2) -> None:
        super().__init__()
        self.patch = patch
        n_patches = WINDOW // patch
        self.embed = nn.Linear(patch, dim)
        self.position = nn.Parameter(0.02 * torch.randn(n_patches, dim))
        layer = nn.TransformerEncoderLayer(
            dim, nhead=2, dim_feedforward=2 * dim, dropout=0.1, batch_first=True
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=layers)
        self.head = nn.Linear(n_patches * dim, 1)

    def point(self, x: torch.Tensor) -> torch.Tensor:
        patches = x[:, :, 0].reshape(x.shape[0], -1, self.patch)
        encoded = self.encoder(self.embed(patches) + self.position)
        out: torch.Tensor = self.head(encoded.flatten(1)).squeeze(-1)
        return out


class DeepAR(Forecaster):
    def __init__(self, hidden: int = 24) -> None:
        super().__init__()
        self.rnn = nn.GRU(1, hidden, batch_first=True)
        self.mu = nn.Linear(hidden, 1)
        self.scale = nn.Linear(hidden, 1)

    def distribution(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Mean and scale of the NEXT value after each step of the window: shape (B, WINDOW)."""
        states, _ = self.rnn(x[:, :, :1])
        mu = self.mu(states).squeeze(-1)
        sigma = F.softplus(self.scale(states).squeeze(-1)) + 1e-3
        return mu, sigma

    def loss(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        mu, sigma = self.distribution(x)
        targets = torch.cat([x[:, 1:, 0], y.unsqueeze(1)], dim=1)
        nll = 0.5 * ((targets - mu) / sigma) ** 2 + torch.log(sigma)
        return nll.mean()

    def point(self, x: torch.Tensor) -> torch.Tensor:
        return self.distribution(x)[0][:, -1]


class GatedResidual(nn.Module):
    def __init__(self, size: int) -> None:
        super().__init__()
        self.fc1 = nn.Linear(size, size)
        self.fc2 = nn.Linear(size, 2 * size)
        self.norm = nn.LayerNorm(size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        a, b = self.fc2(F.elu(self.fc1(x))).chunk(2, dim=-1)
        out: torch.Tensor = self.norm(x + a * torch.sigmoid(b))
        return out


class TFTLite(Forecaster):
    def __init__(self, channels: int, hidden: int = 24) -> None:
        super().__init__()
        self.channels = channels
        self.embed = nn.ModuleList(nn.Linear(1, hidden) for _ in range(channels))
        self.select = nn.Linear(channels, channels)
        self.grn_in = GatedResidual(hidden)
        self.lstm = nn.LSTM(hidden, hidden, batch_first=True)
        self.attn = nn.MultiheadAttention(hidden, num_heads=1, batch_first=True)
        self.gate = nn.Linear(hidden, hidden)
        self.grn_out = GatedResidual(hidden)
        self.head = nn.Linear(hidden, len(QUANTILES))

    def quantiles(self, x: torch.Tensor) -> torch.Tensor:
        weights = torch.softmax(self.select(x), dim=-1)  # (B, L, C): learned variable selection
        parts = [self.grn_in(self.embed[c](x[:, :, c : c + 1])) for c in range(self.channels)]
        mixed = sum(weights[:, :, c : c + 1] * parts[c] for c in range(self.channels))
        states, _ = self.lstm(mixed)
        attended, _ = self.attn(states, states, states, need_weights=False)
        merged = self.grn_out(states + torch.sigmoid(self.gate(attended)) * attended)
        out: torch.Tensor = self.head(merged[:, -1])
        return out

    def loss(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        q = self.quantiles(x)
        level = torch.tensor(QUANTILES, device=x.device)
        error = y.unsqueeze(1) - q
        return torch.maximum(level * error, (level - 1.0) * error).mean()

    def point(self, x: torch.Tensor) -> torch.Tensor:
        return self.quantiles(x)[:, 1]


class SSMBlock(nn.Module):
    def __init__(self, dim: int, state: int = 8, *, selective: bool) -> None:
        super().__init__()
        self.selective = selective
        self.log_a = nn.Parameter(torch.log(torch.arange(1, state + 1).float()).repeat(dim, 1))
        self.b = nn.Parameter(0.1 * torch.randn(dim, state))
        self.c = nn.Parameter(0.1 * torch.randn(dim, state))
        self.skip = nn.Parameter(torch.ones(dim))
        if selective:
            self.dt_proj = nn.Linear(dim, dim)
        else:
            self.log_dt = nn.Parameter(torch.full((dim,), math.log(0.3)))
        self.norm = nn.LayerNorm(dim)

    def forward(self, u: torch.Tensor) -> torch.Tensor:
        batch, length, dim = u.shape
        a = -torch.exp(self.log_a)  # (dim, state), stable: negative real part
        if self.selective:
            dt = F.softplus(self.dt_proj(u))
        else:
            dt = F.softplus(self.log_dt).expand(batch, length, dim)
        h = torch.zeros(batch, dim, a.shape[1], device=u.device)
        outs = []
        for t in range(length):
            step = dt[:, t].unsqueeze(-1)  # (B, dim, 1)
            h = torch.exp(step * a) * h + step * self.b * u[:, t].unsqueeze(-1)
            outs.append((h * self.c).sum(-1))
        y = torch.stack(outs, dim=1) + self.skip * u
        out: torch.Tensor = self.norm(u + F.gelu(y))
        return out


class SSMNet(Forecaster):
    def __init__(self, channels: int, *, selective: bool, dim: int = 16, layers: int = 2) -> None:
        super().__init__()
        self.embed = nn.Linear(channels, dim)
        self.blocks = nn.ModuleList(SSMBlock(dim, selective=selective) for _ in range(layers))
        self.head = nn.Linear(dim, 1)

    def point(self, x: torch.Tensor) -> torch.Tensor:
        h = self.embed(x)
        for block in self.blocks:
            h = block(h)
        out: torch.Tensor = self.head(h[:, -1]).squeeze(-1)
        return out


def build_forecaster(name: str, channels: int) -> Forecaster:
    if name == "nbeats":
        return NBeats()
    if name == "nhits":
        return NHiTS()
    if name == "patchtst":
        return PatchTST()
    if name == "deepar":
        return DeepAR()
    if name == "tft_lite":
        return TFTLite(channels)
    if name == "s4d":
        return SSMNet(channels, selective=False)
    if name == "mamba_lite":
        return SSMNet(channels, selective=True)
    raise ValueError(f"unknown forecaster {name!r}")


FORECASTERS = ("nbeats", "nhits", "patchtst", "deepar", "tft_lite", "s4d", "mamba_lite")


@dataclass(frozen=True, slots=True)
class FitReport:
    epochs_run: int
    best_validation_loss: float


def fit_forecaster(
    model: Forecaster,
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    validation_y: np.ndarray,
    *,
    seed: int,
    max_epochs: int = 200,
    patience: int = 25,
    batch_size: int = 64,
    learning_rate: float = 2e-3,
) -> FitReport:
    """Mini-batch Adam; the validation split only chooses the epoch (early stopping)."""
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    x = torch.as_tensor(train_x, dtype=torch.float32)
    y = torch.as_tensor(train_y, dtype=torch.float32)
    vx = torch.as_tensor(validation_x, dtype=torch.float32)
    vy = torch.as_tensor(validation_y, dtype=torch.float32)
    optimiser = torch.optim.Adam(model.parameters(), lr=learning_rate)
    best, best_state, stale, epochs = math.inf, copy.deepcopy(model.state_dict()), 0, 0
    for _ in range(max_epochs):
        epochs += 1
        model.train()
        order = torch.randperm(x.shape[0], generator=generator)
        for lo in range(0, x.shape[0], batch_size):
            idx = order[lo : lo + batch_size]
            loss = model.loss(x[idx], y[idx])
            optimiser.zero_grad()
            loss.backward()  # type: ignore[no-untyped-call]
            optimiser.step()
        model.eval()
        with torch.no_grad():
            validation = float(model.loss(vx, vy))
        if validation < best - 1e-9:
            best, best_state, stale = validation, copy.deepcopy(model.state_dict()), 0
        else:
            stale += 1
            if stale >= patience:
                break
    model.load_state_dict(best_state)
    return FitReport(epochs, best)


def forecast_point(model: Forecaster, x: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        return np.asarray(model.point(torch.as_tensor(x, dtype=torch.float32)).numpy(), dtype=float)


def forecast_gaussian(model: DeepAR, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean and scale of the next value, for a DeepAR."""
    model.eval()
    with torch.no_grad():
        mu, sigma = model.distribution(torch.as_tensor(x, dtype=torch.float32))
    return np.asarray(mu[:, -1].numpy(), dtype=float), np.asarray(sigma[:, -1].numpy(), dtype=float)
