"""Tensor-train (matrix product state) decomposition for high-dimensional integrals.

A `d`-dimensional table with `n` values per axis has `n^d` entries, the curse of dimensionality. A
tensor train writes it as a chain of `d` small three-index cores,

    T[i1, ..., id] = G1[:, i1, :] G2[:, i2, :] ... Gd[:, id, :],

whose size is about `d * n * r^2` for the "rank" `r` of the chain. When the function is smooth and
close to a sum of few products of one-variable functions, `r` stays small as `d` grows. An integral
against a product weight is then a short chain of small matrix products.

`tt_svd` builds the decomposition from a FULL table by successive singular value decompositions
(Oseledets 2011), so it is limited to the dimensions where the full table fits in memory (here up to
seven axes of nine points). It does not implement TT-cross, the sampling variant that avoids ever
forming
the table and is what makes 100-dimensional problems feasible; nothing here claims anything at
that size.
The example is an arithmetic-average basket call priced on a Gauss-Hermite grid.
"""

from __future__ import annotations

import math

import numpy as np

RATE = 0.03
SIGMA = 0.2
MATURITY = 1.0
SPOT = 100.0
STRIKE = 100.0


def tt_svd(tensor: np.ndarray, tolerance: float) -> list[np.ndarray]:
    """Cores of a tensor train approximating `tensor` to relative accuracy `tolerance`
    (Frobenius)."""
    shape = tensor.shape
    d = len(shape)
    delta = tolerance / math.sqrt(max(d - 1, 1)) * float(np.linalg.norm(tensor))
    cores: list[np.ndarray] = []
    rest = tensor.reshape(shape[0], -1)
    rank = 1
    for k in range(d - 1):
        rest = rest.reshape(rank * shape[k], -1)
        u, s, vt = np.linalg.svd(rest, full_matrices=False)
        energy = np.cumsum((s**2)[::-1])[::-1]  # energy[i] = sum of s_j^2 for j >= i
        keep = len(s)
        for r in range(1, len(s)):  # smallest rank whose discarded tail has norm at most delta
            if energy[r] <= delta**2:
                keep = r
                break
        cores.append(u[:, :keep].reshape(rank, shape[k], keep))
        rest = s[:keep, None] * vt[:keep]
        rank = keep
    cores.append(rest.reshape(rank, shape[-1], 1))
    return cores


def tt_ranks(cores: list[np.ndarray]) -> list[int]:
    return [core.shape[2] for core in cores[:-1]]


def tt_parameters(cores: list[np.ndarray]) -> int:
    return int(sum(core.size for core in cores))


def tt_to_full(cores: list[np.ndarray]) -> np.ndarray:
    out = cores[0]
    for core in cores[1:]:
        out = np.tensordot(out, core, axes=([-1], [0]))
    return np.asarray(out.reshape([c.shape[1] for c in cores]))


def tt_integrate(cores: list[np.ndarray], weights: np.ndarray) -> float:
    """Sum over all indices of T[i1..id] * prod_k weights[i_k], by contracting the chain."""
    vector = np.ones((1,))
    for core in cores:
        matrix = np.tensordot(weights, core, axes=([0], [1]))  # (r_left, r_right)
        vector = vector @ matrix
    return float(vector[0])


def gauss_hermite(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Nodes of a standard normal and weights summing to one."""
    x, w = np.polynomial.hermite.hermgauss(n)
    return math.sqrt(2.0) * x, w / math.sqrt(math.pi)


def basket_payoff_tensor(
    d: int, n: int, *, smoothing: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """Discounted basket payoff on an n^d Gauss-Hermite grid: max(mean(S_T) - K, 0), or with
    `smoothing` c > 0 its softplus version log(1 + exp(c (mean - K))) / c, which has no kink."""
    z, w = gauss_hermite(n)
    prices = SPOT * np.exp((RATE - 0.5 * SIGMA**2) * MATURITY + SIGMA * math.sqrt(MATURITY) * z)
    total = prices
    for _ in range(d - 1):
        total = np.add.outer(total, prices)
    mean = total / d
    if smoothing > 0.0:
        value = np.logaddexp(0.0, smoothing * (mean - STRIKE)) / smoothing
    else:
        value = np.maximum(mean - STRIKE, 0.0)
    payoff = math.exp(-RATE * MATURITY) * value
    return payoff.reshape((n,) * d), w


def monte_carlo_basket(d: int, samples: int, seed: int) -> float:
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((samples, d))
    prices = SPOT * np.exp((RATE - 0.5 * SIGMA**2) * MATURITY + SIGMA * math.sqrt(MATURITY) * z)
    return float(math.exp(-RATE * MATURITY) * np.maximum(prices.mean(axis=1) - STRIKE, 0.0).mean())
