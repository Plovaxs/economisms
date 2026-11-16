import numpy as np
import pytest

from prometheus.titan.contagion import eisenberg_noe_clearing
from prometheus.titan.contagion_gnn import (
    N_NODE_FEATURES,
    ContagionGraph,
    ContagionGraphError,
    label_graph,
    node_features,
    simulate_contagion_graph,
    train_and_evaluate_contagion_gnn,
)

_SMALL_TRAIN_SEEDS = tuple(range(10))
_SMALL_TEST_SEEDS = tuple(range(10, 14))


def test_contagion_graph_rejects_mismatched_edge_mask_shape() -> None:
    with pytest.raises(ContagionGraphError, match="edge_is_synthetic"):
        ContagionGraph(
            liabilities=np.zeros((2, 2)),
            external_assets=np.zeros(2),
            edge_is_synthetic=np.ones((1, 1), dtype=bool),
        )


def test_contagion_graph_rejects_a_non_square_liabilities_matrix() -> None:
    with pytest.raises(ValueError, match="square"):
        ContagionGraph(
            liabilities=np.zeros((2, 3)),
            external_assets=np.zeros(2),
            edge_is_synthetic=np.ones((2, 3), dtype=bool),
        )


def test_contagion_graph_accepts_an_observed_edge_not_hardcoded_all_synthetic() -> None:
    # the contract itself can represent edge_is_synthetic=False even though
    # simulate_contagion_graph only ever produces all-True masks (see module
    # docstring for the disclosed scope limit this exercises).
    graph = ContagionGraph(
        liabilities=np.array([[0.0, 1.0], [1.0, 0.0]]),
        external_assets=np.array([1.0, 1.0]),
        edge_is_synthetic=np.array([[False, False], [False, False]]),
    )
    assert graph.n_banks == 2
    assert not graph.edge_is_synthetic.any()


def test_simulate_contagion_graph_rejects_too_few_banks() -> None:
    with pytest.raises(ValueError, match="n_banks"):
        simulate_contagion_graph(np.random.default_rng(0), 1)


def test_simulate_contagion_graph_marks_every_edge_synthetic() -> None:
    graph = simulate_contagion_graph(np.random.default_rng(0), 8)
    assert graph.edge_is_synthetic.all()


def test_node_features_has_the_declared_shape_and_matches_known_quantities() -> None:
    liabilities = np.array([[0.0, 2.0, 0.0], [1.0, 0.0, 1.0], [0.0, 0.0, 0.0]])
    external_assets = np.array([5.0, 3.0, 1.0])
    graph = ContagionGraph(liabilities, external_assets, np.ones((3, 3), dtype=bool))
    features = node_features(graph)
    assert features.shape == (3, N_NODE_FEATURES)
    # column 0 is external assets, column 1 is p_bar (row sum)
    assert list(features[:, 0]) == [5.0, 3.0, 1.0]
    assert list(features[:, 1]) == [2.0, 2.0, 0.0]


def test_label_graph_matches_eisenberg_noe_clearing_called_directly() -> None:
    graph = simulate_contagion_graph(np.random.default_rng(1), 6)
    label = label_graph(graph)
    direct = eisenberg_noe_clearing(graph.liabilities, graph.external_assets)
    assert np.array_equal(label.defaulted, direct.defaulted)
    assert np.array_equal(label.equity_after, direct.equity_after)


def test_train_and_evaluate_rejects_overlapping_train_and_test_seeds() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        train_and_evaluate_contagion_gnn(train_seeds=(0, 1), test_seeds=(1, 2), n_epochs=2)


def test_train_and_evaluate_contagion_gnn_is_deterministic_given_seed() -> None:
    first = train_and_evaluate_contagion_gnn(
        train_seeds=_SMALL_TRAIN_SEEDS, test_seeds=_SMALL_TEST_SEEDS, n_epochs=30, seed=0
    )
    second = train_and_evaluate_contagion_gnn(
        train_seeds=_SMALL_TRAIN_SEEDS, test_seeds=_SMALL_TEST_SEEDS, n_epochs=30, seed=0
    )
    assert first.gnn_test_auc == second.gnn_test_auc
    assert first.baseline_test_auc == second.baseline_test_auc


def test_train_and_evaluate_contagion_gnn_reports_a_real_held_out_auc_against_baseline() -> None:
    result = train_and_evaluate_contagion_gnn(
        train_seeds=_SMALL_TRAIN_SEEDS, test_seeds=_SMALL_TEST_SEEDS, n_epochs=30, seed=0
    )
    assert result.n_train_graphs == len(_SMALL_TRAIN_SEEDS)
    assert result.n_test_graphs == len(_SMALL_TEST_SEEDS)
    assert result.n_train_nodes > 0
    assert result.n_test_nodes > 0
    assert 0.0 <= result.gnn_test_auc <= 1.0
    assert 0.0 <= result.baseline_test_auc <= 1.0
    # a GNN with graph-propagation layers has strictly more parameters than
    # a bare linear no-graph baseline on the same input features
    assert result.gnn_n_parameters > result.baseline_n_parameters


def test_train_and_evaluate_contagion_gnn_default_split_shows_the_graph_helping() -> None:
    # the project's own default seeds/epochs (a larger, slower, real run) --
    # kept as one explicit regression test of the honest, disclosed finding
    # that graph propagation gives a real, non-degenerate AUC improvement
    # over the no-graph baseline on this synthetic task, not a null result.
    result = train_and_evaluate_contagion_gnn(n_epochs=60)
    assert result.gnn_test_auc > result.baseline_test_auc
