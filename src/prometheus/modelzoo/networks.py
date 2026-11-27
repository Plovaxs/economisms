"""A graph neural network for shock propagation through a production network.

Sectors buy inputs from each other. With technical-coefficient matrix `A` (entry a_ij is the input
from sector i needed per unit of sector j's output), a change `d` in final demand changes total
output by the **Leontief inverse**: x = (I - A)^(-1) d = d + A d + A^2 d + ... . The k-th term of
that series is the shock after k rounds of buying from suppliers, which is exactly what k rounds
of message passing on the graph compute.

`ShockGNN` is a message-passing network: each layer updates a sector's state from its own state
and the
mean of its customers' and its suppliers' states, `L` layers reach `L` steps down the supply
chain, and
the readout is the predicted change in the sector's output. It is trained on many small random
networks and tested on larger ones it has never seen (a graph network has no fixed size).
Competitors:

* the exact Leontief inverse (the truth, to machine precision);
* the truncated series with the same reach, `sum_{k<=L} A^k d` (what `L` rounds of buying gives);
* the same network with the graph removed (each sector sees only its own shock).

No input-output table is committed to this repository, so the networks are SIMULATED: random sparse
coefficient matrices with column sums below one, flagged as such wherever a result is reported. The
claim tested is about the method, not about any real economy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn


def random_io_matrix(
    n: int, *, seed: int, density: float = 0.15, spectral: float = 0.7
) -> np.ndarray:
    """A random sparse technical-coefficient matrix with spectral radius `spectral` (< 1)."""
    rng = np.random.default_rng(seed)
    mask = rng.random((n, n)) < density
    a = np.where(mask, rng.random((n, n)), 0.0)
    np.fill_diagonal(a, 0.0)
    radius = float(np.max(np.abs(np.linalg.eigvals(a)))) if a.any() else 1.0
    return np.asarray(a * (spectral / max(radius, 1e-9)), dtype=float)


def leontief_response(a: np.ndarray, demand: np.ndarray) -> np.ndarray:
    return np.asarray(np.linalg.solve(np.eye(len(a)) - a, demand), dtype=float)


def truncated_response(a: np.ndarray, demand: np.ndarray, reach: int) -> np.ndarray:
    total = demand.copy()
    term = demand.copy()
    for _ in range(reach):
        term = a @ term
        total = total + term
    return np.asarray(total, dtype=float)


@dataclass(frozen=True, slots=True)
class GraphBatch:
    adjacency: torch.Tensor  # (n, n) technical coefficients
    demand: torch.Tensor  # (b, n)
    response: torch.Tensor  # (b, n) exact Leontief response


def make_graph_batch(n: int, shocks: int, *, seed: int) -> GraphBatch:
    a = random_io_matrix(n, seed=seed)
    rng = np.random.default_rng(seed + 1)
    demand = rng.standard_normal((shocks, n)) * (rng.random((shocks, n)) < 0.3)
    response = np.stack([leontief_response(a, d) for d in demand])
    return GraphBatch(
        torch.as_tensor(a, dtype=torch.float32),
        torch.as_tensor(demand, dtype=torch.float32),
        torch.as_tensor(response, dtype=torch.float32),
    )


class ShockGNN(nn.Module):
    def __init__(self, layers: int = 3, width: int = 16, *, use_graph: bool = True) -> None:
        super().__init__()
        self.use_graph = use_graph
        self.lift = nn.Linear(1, width)
        self.self_w = nn.ModuleList(nn.Linear(width, width) for _ in range(layers))
        self.customer_w = nn.ModuleList(nn.Linear(width, width, bias=False) for _ in range(layers))
        self.supplier_w = nn.ModuleList(nn.Linear(width, width, bias=False) for _ in range(layers))
        self.head = nn.Linear(width, 1)

    def forward(self, adjacency: torch.Tensor, demand: torch.Tensor) -> torch.Tensor:
        h = self.lift(demand.unsqueeze(-1))  # (b, n, width)
        for own, customer, supplier in zip(
            self.self_w, self.customer_w, self.supplier_w, strict=True
        ):
            update = own(h)
            if self.use_graph:
                # a_ij links supplier i to customer j
                update = update + customer(torch.einsum("ij,bjw->biw", adjacency, h))
                update = update + supplier(torch.einsum("ji,bjw->biw", adjacency, h))
            h = h + torch.relu(update)
        out: torch.Tensor = self.head(h).squeeze(-1)
        return out


def train_gnn(
    model: ShockGNN, graphs: list[GraphBatch], *, epochs: int, seed: int, lr: float = 3e-3
) -> float:
    torch.manual_seed(seed)
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)
    loss_value = float("nan")
    for _ in range(epochs):
        for graph in graphs:
            loss = ((model(graph.adjacency, graph.demand) - graph.response) ** 2).mean()
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            loss_value = float(loss.detach())
        schedule.step()
    return loss_value


def relative_error(pred: np.ndarray, truth: np.ndarray) -> float:
    return float(np.linalg.norm(pred - truth) / np.linalg.norm(truth))


def evaluate_gnn(model: ShockGNN, graph: GraphBatch) -> float:
    model.eval()
    with torch.no_grad():
        out = model(graph.adjacency, graph.demand)
    return relative_error(out.numpy(), graph.response.numpy())


def evaluate_truncation(graph: GraphBatch, reach: int) -> float:
    a = graph.adjacency.numpy().astype(float)
    pred = np.stack([truncated_response(a, d, reach) for d in graph.demand.numpy().astype(float)])
    return relative_error(pred, graph.response.numpy())
