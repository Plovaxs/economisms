"""Pipelines: the output of one model is the input of the next, in code that runs.

The registry says which model is related to which; a pipeline is where one actually feeds another.
Two are built, each ending in a number a classical tool of this repository also produces, so the
chain
can be checked at its far end.

**Surrogate to hedge to risk.** A neural operator is trained to price a call as a function of
`(payoff curve, volatility * sqrt(maturity), maturity)` (`modelzoo.operators.FNO1d` with one more
input
channel), so that one forward pass gives the whole price curve. The delta of a short call is read
off
that curve by finite differences, a delta hedge is run along simulated stock paths with it, and the
profit and loss goes to `titan.risk_metrics` for its Expected Shortfall. The classical chain, the
exact
Black-Scholes delta into the same hedge and the same risk metric, is the reference; so is not
hedging.

**Simulated economy to bank losses to quantum risk.** `worldsim` simulates the banking system (the
`calibrated_banks` world, Finding 29); the annual loss rates of its banks form an empirical loss
distribution; the Expected Shortfall of that distribution is estimated by maximum-likelihood
amplitude
estimation (`modelzoo.quantum`) through the Rockafellar-Uryasev identity
`ES = VaR + E[(L - VaR)+] / (1 - alpha)`, whose second term is an amplitude. `titan.risk_metrics`
computes
the same Expected Shortfall directly from the same samples, which is the check at the end of the
chain.

Both pipelines use simulated inputs (simulated stock paths, a simulated banking system) and an ideal
quantum simulator. They show that the models fit together and agree with the classical route, not
how
any real book or bank would behave.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F
from scipy.stats import norm

from prometheus.modelzoo import operators as ops
from prometheus.modelzoo import quantum as qm
from prometheus.titan.risk_metrics import historical_expected_shortfall, historical_var
from prometheus.worldsim.bank_calibration import simulated_annual_table
from prometheus.worldsim.calibrated import calibrated_scenario
from prometheus.worldsim.world import simulate_world

RATE = ops.RATE
GRID_TRAIN = 64
GRID_HEDGE = 128
STRIKE_LOW, STRIKE_HIGH = 70.0, 130.0
TAU_LOW, TAU_HIGH = 0.05, 1.0


# ----- pipeline 1: operator surrogate -> hedge -> expected shortfall ---------------------


def bs_call_tau(spot: np.ndarray, strike: float, sigma: float, tau: float) -> np.ndarray:
    """Closed-form call value with time to maturity `tau` (rate: the module's 3%)."""
    vol = sigma * math.sqrt(tau)
    d1 = (np.log(spot / strike) + (RATE + 0.5 * sigma**2) * tau) / vol
    d2 = d1 - vol
    return np.asarray(
        spot * norm.cdf(d1) - strike * math.exp(-RATE * tau) * norm.cdf(d2), dtype=float
    )


def bs_delta_tau(spot: np.ndarray, strike: float, sigma: float, tau: float) -> np.ndarray:
    vol = sigma * math.sqrt(tau)
    return np.asarray(
        norm.cdf((np.log(spot / strike) + (RATE + 0.5 * sigma**2) * tau) / vol), dtype=float
    )


class TimeConditionedFNO(ops.FNO1d):
    """The FNO of `operators`, with the volatility channel replaced by two scalar channels:
    volatility * sqrt(maturity) and maturity."""

    def __init__(self, width: int = 32, modes: int = 12, layers: int = 4) -> None:
        super().__init__(width=width, modes=modes, layers=layers)
        self.lift = torch.nn.Conv1d(4, width, 1)

    def forward(self, payoff: torch.Tensor, scalars: torch.Tensor) -> torch.Tensor:
        batch, size = payoff.shape
        x = torch.cat(
            [
                payoff.unsqueeze(1),
                scalars[:, 0].view(batch, 1, 1).expand(batch, 1, size),
                scalars[:, 1].view(batch, 1, 1).expand(batch, 1, size),
                torch.linspace(0.0, 1.0, size).expand(batch, 1, size),
            ],
            dim=1,
        )
        x = self.lift(x)
        for spectral, skip in zip(self.spectral, self.skip, strict=True):
            x = F.gelu(spectral(x) + skip(x))
        result: torch.Tensor = self.head2(F.gelu(self.head1(x))).squeeze(1)
        return result


@dataclass(frozen=True, slots=True)
class SurfaceData:
    payoff: np.ndarray  # (n, g) scaled call payoff curves
    scalars: np.ndarray  # (n, 2) sigma * sqrt(tau), tau
    price: np.ndarray  # (n, g) scaled exact prices
    scale: np.ndarray  # (n,) the factor the curves were divided by


def make_surface_data(n: int, grid_size: int, *, seed: int) -> SurfaceData:
    rng = np.random.default_rng(seed)
    grid = ops.spot_grid(grid_size)
    strike = rng.uniform(STRIKE_LOW, STRIKE_HIGH, n)
    sigma = rng.uniform(ops.SIGMA_LOW, ops.SIGMA_HIGH, n)
    tau = rng.uniform(TAU_LOW, TAU_HIGH, n)
    payoff = np.maximum(grid[None, :] - strike[:, None], 0.0)
    price = np.stack([bs_call_tau(grid, strike[i], sigma[i], tau[i]) for i in range(n)])
    scale = np.maximum(payoff.max(axis=1), 1e-9)
    return SurfaceData(
        payoff / scale[:, None],
        np.stack([sigma * np.sqrt(tau), tau], axis=1),
        price / scale[:, None],
        scale,
    )


def train_surface(
    data: SurfaceData, *, epochs: int, seed: int, batch_size: int = 64
) -> TimeConditionedFNO:
    torch.manual_seed(seed)
    generator = torch.Generator().manual_seed(seed)
    model = TimeConditionedFNO()
    optimiser = torch.optim.Adam(model.parameters(), lr=2e-3)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)
    payoff = torch.as_tensor(data.payoff, dtype=torch.float32)
    scalars = torch.as_tensor(data.scalars, dtype=torch.float32)
    price = torch.as_tensor(data.price, dtype=torch.float32)
    for _ in range(epochs):
        order = torch.randperm(len(payoff), generator=generator)
        for lo in range(0, len(payoff), batch_size):
            idx = order[lo : lo + batch_size]
            loss = F.mse_loss(model(payoff[idx], scalars[idx]), price[idx])
            optimiser.zero_grad()
            loss.backward()  # type: ignore[no-untyped-call]
            optimiser.step()
        schedule.step()
    return model


def surrogate_delta(
    model: TimeConditionedFNO, spots: np.ndarray, strike: float, sigma: float, tau: float
) -> np.ndarray:
    """Delta of a call at `spots`: the model's price curve on a 128-point grid, differentiated by
    central differences and read at each spot. (The FNO runs on a grid it was not trained on.)"""
    grid = ops.spot_grid(GRID_HEDGE)
    payoff = np.maximum(grid - strike, 0.0)
    scale = max(float(payoff.max()), 1e-9)
    model.eval()
    with torch.no_grad():
        curve = model(
            torch.as_tensor(payoff[None] / scale, dtype=torch.float32),
            torch.as_tensor([[sigma * math.sqrt(tau), tau]], dtype=torch.float32),
        )[0].numpy()
    curve = curve.astype(float) * scale
    slope = np.gradient(curve, grid)
    return np.asarray(np.clip(np.interp(spots, grid, slope), 0.0, 1.0), dtype=float)


@dataclass(frozen=True, slots=True)
class HedgeResult:
    errors: dict[
        str, np.ndarray
    ]  # hedging error (portfolio value minus payoff) per path, per strategy
    mean_abs_delta_error: float


def run_hedge(
    model: TimeConditionedFNO,
    *,
    seed: int,
    paths: int = 2000,
    steps: int = 52,
    strike: float = 100.0,
    sigma: float = 0.2,
    drift: float = 0.05,
    spot0: float = 100.0,
) -> HedgeResult:
    """Short one call, hedge weekly with the surrogate's delta, with the exact delta, or not at
    all."""
    rng = np.random.default_rng(seed)
    dt = 1.0 / steps
    premium = float(bs_call_tau(np.array([spot0]), strike, sigma, 1.0)[0])
    spot = np.full(paths, spot0)
    value = {name: np.full(paths, premium) for name in ("surrogate", "exact")}
    held = {name: np.zeros(paths) for name in value}
    delta_gap: list[float] = []
    for i in range(steps):
        tau = 1.0 - i * dt
        deltas = {
            "surrogate": surrogate_delta(model, spot, strike, sigma, tau),
            "exact": bs_delta_tau(spot, strike, sigma, tau),
        }
        delta_gap.append(float(np.abs(deltas["surrogate"] - deltas["exact"]).mean()))
        z = rng.standard_normal(paths)
        nxt = spot * np.exp((drift - 0.5 * sigma**2) * dt + sigma * math.sqrt(dt) * z)
        for name in value:
            held[name] = deltas[name]
            cash = value[name] - held[name] * spot
            value[name] = held[name] * nxt + cash * math.exp(RATE * dt)
        spot = nxt
    payoff = np.maximum(spot - strike, 0.0)
    errors = {name: value[name] - payoff for name in value}
    errors["unhedged"] = premium * math.exp(RATE) - payoff
    return HedgeResult(errors, float(np.mean(delta_gap)))


def hedge_risk(errors: np.ndarray, alpha: float = 0.95) -> dict[str, float]:
    """Spread and tail of the hedging error, the tail through `titan.risk_metrics`."""
    losses = -errors
    return {
        "std": float(np.std(errors)),
        "var": float(historical_var(losses, alpha)),
        "expected_shortfall": float(historical_expected_shortfall(losses, alpha)),
    }


# ----- pipeline 2: simulated banks -> loss distribution -> quantum expected shortfall ----


def bank_loss_samples(seeds: tuple[int, ...]) -> np.ndarray:
    """Annual net charge-off rates (percent of loans) of the simulated `calibrated_banks` world."""
    config = calibrated_scenario("calibrated_banks")
    samples: list[float] = []
    for seed in seeds:
        table = simulated_annual_table(simulate_world(config, seed))
        samples.extend(float(x) for x in table["nco"])
    return np.asarray(samples, dtype=float)


@dataclass(frozen=True, slots=True)
class LossAmplitude:
    distribution: qm.OptionDistribution
    value_at_risk: float
    top: float  # the largest bin centre: the payoff's scale
    alpha: float

    def expected_shortfall(self, amplitude: float) -> float:
        """ES = VaR + E[(L - VaR)+] / (1 - alpha), with E[(L - VaR)+] = amplitude * (top - VaR)."""
        return self.value_at_risk + amplitude * (self.top - self.value_at_risk) / (1.0 - self.alpha)


def loss_amplitude(samples: np.ndarray, alpha: float = 0.95, qubits: int = 6) -> LossAmplitude:
    bins = 2**qubits
    counts, edges = np.histogram(samples, bins=bins, range=(0.0, float(samples.max()) * 1.0001))
    centres = 0.5 * (edges[:-1] + edges[1:])
    var = float(historical_var(samples, alpha))
    top = float(centres.max())
    payoff = np.clip(np.maximum(centres - var, 0.0) / max(top - var, 1e-12), 0.0, 1.0)
    dist = qm.OptionDistribution(counts / counts.sum(), payoff)
    return LossAmplitude(dist, var, top, alpha)


def quantum_expected_shortfall(
    info: LossAmplitude, schedule: tuple[int, ...], shots: int, rng: np.random.Generator
) -> tuple[float, int]:
    amplitude, calls = qm.mlae_estimate(info.distribution.amplitude, schedule, shots, rng)
    return info.expected_shortfall(amplitude), calls


def monte_carlo_expected_shortfall(
    info: LossAmplitude, samples: int, rng: np.random.Generator
) -> float:
    amplitude = qm.monte_carlo_amplitude(info.distribution, samples, rng)
    return info.expected_shortfall(amplitude)
