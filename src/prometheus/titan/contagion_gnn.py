"""CONTAGION-GNN (FP-10): a graph neural network over the interbank
contagion network.

The final-project blueprint describes CONTAGION-GNN as "temporal graph
propagation across countries or banks; synthetic edges labeled"
(section 02) and `GNN(H_t, A_t, edge_mask)`, which must "separate
observed relationships from synthetic exposure scenarios" (section 04).
This repository has not licensed any real, observed interbank exposure
dataset -- the same "avoid fabricated real trade exposures" constraint
section 07 already states for country graphs. Every graph this module
builds is therefore honestly `edge_is_synthetic=True` throughout; the
`ContagionGraph` contract below can still represent an observed
(`edge_is_synthetic=False`) edge, nothing currently populates that
case -- a disclosed scope limit, not a silently hardcoded assumption.

This module does not replace `titan.contagion` (RISK-11's Eisenberg-Noe
fixed-point clearing, which remains unmodified and is the ground-truth
label generator below) -- it is additive: a GNN trained to predict the
REAL clearing outcome of a bank network from its structure and node
features, evaluated against a no-graph classical baseline
(`quantum.models.LogisticRegressionClassifier`, trained via the
pre-existing `recessionnet.training.train_classifier`, both reused
unchanged) on HELD-OUT networks (disjoint generating seeds from
training, never a held-out node within an already-trained-on network)
to show whether the graph structure itself carries real predictive
signal beyond each bank's own features. A null result (the graph does
not help) is treated as an acceptable, valid outcome, not hidden.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from prometheus.quantum.models import LogisticRegressionClassifier, count_parameters
from prometheus.recessionnet.evaluation import roc_auc
from prometheus.recessionnet.training import train_classifier
from prometheus.titan.contagion import ClearingResult, _validate_network, eisenberg_noe_clearing
from prometheus.titan.contagion import network_concentration as _network_concentration

N_NODE_FEATURES = 5


class ContagionGraphError(ValueError):
    """Raised when a `ContagionGraph`'s fields do not form a valid graph
    contract (shape mismatch, invalid liabilities/external assets --
    the latter two checks are delegated to `titan.contagion`'s own
    `_validate_network`, not re-implemented here)."""


@dataclass(frozen=True, slots=True)
class ContagionGraph:
    """The CONTAGION-GNN graph contract: a square liabilities matrix
    (bank i's nominal obligation to bank j, zero diagonal), each bank's
    external (non-interbank) assets, and an explicit per-edge
    provenance mask distinguishing an observed relationship from a
    synthetic exposure scenario (blueprint section 04's own
    distinction -- see this module's docstring for why every edge
    built here is honestly `True`)."""

    liabilities: np.ndarray
    external_assets: np.ndarray
    edge_is_synthetic: np.ndarray

    def __post_init__(self) -> None:
        n, liabilities, external_assets = _validate_network(
            self.liabilities, self.external_assets
        )
        edge_is_synthetic = np.asarray(self.edge_is_synthetic, dtype=bool)
        if edge_is_synthetic.shape != (n, n):
            raise ContagionGraphError(
                f"edge_is_synthetic must have shape ({n}, {n}), got {edge_is_synthetic.shape}"
            )
        object.__setattr__(self, "liabilities", liabilities)
        object.__setattr__(self, "external_assets", external_assets)
        object.__setattr__(self, "edge_is_synthetic", edge_is_synthetic)

    @property
    def n_banks(self) -> int:
        return int(self.liabilities.shape[0])


def simulate_contagion_graph(
    rng: np.random.Generator,
    n_banks: int,
    *,
    density: float = 0.35,
    liability_scale: float = 1.0,
    external_asset_scale: float = 1.3,
) -> ContagionGraph:
    """A random synthetic interbank network: each ordered pair (i, j),
    i != j, becomes a liability edge independently with probability
    `density`, magnitude drawn `Exponential(liability_scale)`; external
    assets are drawn `Exponential(external_asset_scale)` per bank.
    Every edge is `edge_is_synthetic=True` (see module docstring)."""
    if n_banks < 2:
        raise ValueError("n_banks must be at least 2")
    liabilities = np.zeros((n_banks, n_banks))
    for i in range(n_banks):
        for j in range(n_banks):
            if i != j and rng.random() < density:
                liabilities[i, j] = rng.exponential(liability_scale)
    external_assets = rng.exponential(external_asset_scale, size=n_banks)
    edge_is_synthetic = np.ones((n_banks, n_banks), dtype=bool)
    return ContagionGraph(liabilities, external_assets, edge_is_synthetic)


def label_graph(graph: ContagionGraph) -> ClearingResult:
    """The real, causally-computed Eisenberg-Noe clearing outcome for
    `graph` -- the ground-truth label source for everything below.
    `titan.contagion.eisenberg_noe_clearing` is called unmodified."""
    return eisenberg_noe_clearing(graph.liabilities, graph.external_assets)


def node_features(graph: ContagionGraph) -> np.ndarray:
    """Per-bank feature matrix, shape `(n_banks, N_NODE_FEATURES)`:
    external assets, total nominal obligation (`p_bar`), total degree
    (debtor + creditor edge count), and debtor/creditor HHI
    concentration (`titan.contagion.network_concentration`, reused
    unchanged, not recomputed here)."""
    has_edge = graph.liabilities > 0
    p_bar = graph.liabilities.sum(axis=1)
    degree = has_edge.sum(axis=1).astype(float) + has_edge.sum(axis=0).astype(float)
    concentration = _network_concentration(graph.liabilities)
    return np.stack(
        [
            graph.external_assets,
            p_bar,
            degree,
            concentration.debtor_concentration,
            concentration.creditor_concentration,
        ],
        axis=1,
    )


def _row_normalized_adjacency(liabilities: np.ndarray) -> np.ndarray:
    """Row-normalized exposure weights: `Pi[i, j]` is the fraction of
    bank i's total obligation owed to creditor j (zero row if i has no
    debt) -- used as the GNN's message-passing weights so a bank's
    representation is updated by a liability-weighted average of its
    creditors, the same economically meaningful weighting
    `eisenberg_noe_clearing` itself uses for loss-sharing."""
    p_bar = liabilities.sum(axis=1)
    has_debt = p_bar > 0
    safe_p_bar = np.where(has_debt, p_bar, 1.0)
    return np.where(has_debt[:, None], liabilities / safe_p_bar[:, None], 0.0)


class ContagionGNN(nn.Module):
    """A minimal 2-layer mean/exposure-weighted message-passing network
    (GCN-style): `H^{l+1}_i = relu(W_l * [H^l_i ; Pi @ H^l]_i)`, where
    `Pi` is the row-normalized liability-exposure matrix. Outputs one
    raw logit per bank (use with `nn.BCEWithLogitsLoss`, the same
    convention `quantum.models`'s classifiers use)."""

    def __init__(self, n_features: int = N_NODE_FEATURES, hidden_dim: int = 16) -> None:
        super().__init__()
        self.layer1 = nn.Linear(n_features * 2, hidden_dim)
        self.layer2 = nn.Linear(hidden_dim * 2, hidden_dim)
        self.head = nn.Linear(hidden_dim, 1)

    def forward(self, features: torch.Tensor, adjacency: torch.Tensor) -> torch.Tensor:
        agg1 = adjacency @ features
        h1 = torch.relu(self.layer1(torch.cat([features, agg1], dim=-1)))
        agg2 = adjacency @ h1
        h2 = torch.relu(self.layer2(torch.cat([h1, agg2], dim=-1)))
        output: torch.Tensor = self.head(h2).squeeze(-1)
        return output


@dataclass(frozen=True, slots=True)
class GraphExample:
    graph: ContagionGraph
    label: ClearingResult
    features: np.ndarray
    adjacency: np.ndarray


def _build_examples(seeds: tuple[int, ...]) -> tuple[GraphExample, ...]:
    examples = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        n_banks = 5 + seed % 7
        graph = simulate_contagion_graph(rng, n_banks)
        label = label_graph(graph)
        examples.append(
            GraphExample(
                graph=graph,
                label=label,
                features=node_features(graph),
                adjacency=_row_normalized_adjacency(graph.liabilities),
            )
        )
    return tuple(examples)


@dataclass(frozen=True, slots=True)
class EpochLogEntry:
    epoch: int
    loss: float


def _train_gnn(
    examples: tuple[GraphExample, ...],
    *,
    seed: int,
    hidden_dim: int,
    n_epochs: int,
    learning_rate: float,
    feature_mean: np.ndarray,
    feature_std: np.ndarray,
) -> tuple[ContagionGNN, tuple[EpochLogEntry, ...]]:
    torch.manual_seed(seed)
    model = ContagionGNN(hidden_dim=hidden_dim)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.BCEWithLogitsLoss()

    tensors = [
        (
            torch.tensor((ex.features - feature_mean) / feature_std, dtype=torch.float32),
            torch.tensor(ex.adjacency, dtype=torch.float32),
            torch.tensor(ex.label.defaulted.astype(float), dtype=torch.float32),
        )
        for ex in examples
    ]

    epoch_log: list[EpochLogEntry] = []
    for epoch in range(n_epochs):
        optimizer.zero_grad()
        total_loss = torch.tensor(0.0)
        for x, adjacency, y in tensors:
            logits = model(x, adjacency)
            total_loss = total_loss + loss_fn(logits, y)
        total_loss = total_loss / len(tensors)
        total_loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
        epoch_log.append(EpochLogEntry(epoch=epoch, loss=float(total_loss.item())))
    return model, tuple(epoch_log)


def _predict_gnn(
    model: ContagionGNN,
    examples: tuple[GraphExample, ...],
    feature_mean: np.ndarray,
    feature_std: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    probs: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    with torch.no_grad():
        for ex in examples:
            x = torch.tensor((ex.features - feature_mean) / feature_std, dtype=torch.float32)
            adjacency = torch.tensor(ex.adjacency, dtype=torch.float32)
            logits = model(x, adjacency)
            probs.append(torch.sigmoid(logits).numpy())
            labels.append(ex.label.defaulted.astype(float))
    return np.concatenate(probs), np.concatenate(labels)


@dataclass(frozen=True, slots=True)
class HeldOutContagionEvaluation:
    train_seeds: tuple[int, ...]
    test_seeds: tuple[int, ...]
    n_train_graphs: int
    n_test_graphs: int
    n_train_nodes: int
    n_test_nodes: int
    gnn_n_parameters: int
    baseline_n_parameters: int
    gnn_test_auc: float
    baseline_test_auc: float
    gnn_train_seconds: float
    baseline_train_seconds: float


def train_and_evaluate_contagion_gnn(
    *,
    train_seeds: tuple[int, ...] = tuple(range(40)),
    test_seeds: tuple[int, ...] = tuple(range(40, 55)),
    hidden_dim: int = 16,
    n_epochs: int = 200,
    learning_rate: float = 0.02,
    seed: int = 0,
) -> HeldOutContagionEvaluation:
    """Trains `ContagionGNN` on networks generated from `train_seeds`
    and a no-graph `quantum.models.LogisticRegressionClassifier`
    baseline (via the pre-existing `recessionnet.training.
    train_classifier`, unchanged) on the SAME pooled node features,
    then evaluates both on networks generated from the disjoint
    `test_seeds` -- a held-out split by network instance, never by
    node within an already-trained-on network. Returns real,
    deterministic-given-seed ROC-AUC for each, so the graph's marginal
    value (or lack of it) over raw per-bank features is an honest,
    checkable number."""
    overlap = set(train_seeds) & set(test_seeds)
    if overlap:
        raise ValueError(f"train_seeds and test_seeds must be disjoint, overlap: {overlap}")

    train_examples = _build_examples(train_seeds)
    test_examples = _build_examples(test_seeds)

    train_features = np.concatenate([ex.features for ex in train_examples], axis=0)
    feature_mean = train_features.mean(axis=0)
    feature_std = train_features.std(axis=0)
    feature_std = np.where(feature_std > 1e-12, feature_std, 1.0)

    gnn_start = time.perf_counter()
    gnn, _ = _train_gnn(
        train_examples,
        seed=seed,
        hidden_dim=hidden_dim,
        n_epochs=n_epochs,
        learning_rate=learning_rate,
        feature_mean=feature_mean,
        feature_std=feature_std,
    )
    gnn_train_seconds = time.perf_counter() - gnn_start
    gnn_test_probs, gnn_test_labels = _predict_gnn(gnn, test_examples, feature_mean, feature_std)
    gnn_test_auc = roc_auc(gnn_test_probs, gnn_test_labels)

    train_labels = np.concatenate(
        [ex.label.defaulted.astype(float) for ex in train_examples], axis=0
    )
    scaled_train_features = (train_features - feature_mean) / feature_std
    baseline_trained = train_classifier(
        lambda: LogisticRegressionClassifier(N_NODE_FEATURES),
        scaled_train_features,
        train_labels,
        seed=seed,
        n_epochs=n_epochs,
        learning_rate=learning_rate,
    )
    test_features = np.concatenate([ex.features for ex in test_examples], axis=0)
    test_labels = np.concatenate(
        [ex.label.defaulted.astype(float) for ex in test_examples], axis=0
    )
    scaled_test_features = (test_features - feature_mean) / feature_std
    with torch.no_grad():
        baseline_logits = baseline_trained.model(
            torch.tensor(scaled_test_features, dtype=torch.float32)
        )
        baseline_probs = torch.sigmoid(baseline_logits).numpy()
    baseline_test_auc = roc_auc(baseline_probs, test_labels)

    return HeldOutContagionEvaluation(
        train_seeds=train_seeds,
        test_seeds=test_seeds,
        n_train_graphs=len(train_examples),
        n_test_graphs=len(test_examples),
        n_train_nodes=int(train_features.shape[0]),
        n_test_nodes=int(test_features.shape[0]),
        gnn_n_parameters=count_parameters(gnn),
        baseline_n_parameters=baseline_trained.n_parameters,
        gnn_test_auc=gnn_test_auc,
        baseline_test_auc=baseline_test_auc,
        gnn_train_seconds=gnn_train_seconds,
        baseline_train_seconds=baseline_trained.train_seconds,
    )
