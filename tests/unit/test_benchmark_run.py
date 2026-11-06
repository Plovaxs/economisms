import json
import math
from dataclasses import replace

import pytest

from prometheus.experiments.hedge_benchmark import PRIMARY_ENDPOINT
from prometheus.experiments.manifest import compute_result_hash
from prometheus.orchestration.benchmark_run import BenchmarkRunConfig, main, run_benchmark


@pytest.fixture(scope="module")
def config():
    return BenchmarkRunConfig(
        n_steps=3,
        n_train_paths=32,
        batch_size=16,
        n_train_epochs=3,
        n_eval_paths=64,
        n_bootstrap_resamples=24,
        test_seeds=(100, 200),
    )


@pytest.fixture(scope="module", params=["call", "put"])
def result(request, config):
    return run_benchmark(replace(config, option_type=request.param))


def test_report_preserves_all_seed_results_and_financial_metrics(result) -> None:
    assert result.report.primary_endpoint == PRIMARY_ENDPOINT
    assert len(result.report.per_seed_results) == 2
    for item in result.report.per_seed_results:
        assert item.bootstrap.point_estimate == pytest.approx(item.delta_cvar - item.policy_cvar)
        for value in (
            item.delta_mean_loss,
            item.policy_mean_loss,
            item.delta_mean_cost,
            item.policy_mean_cost,
            item.delta_mean_turnover,
            item.policy_mean_turnover,
        ):
            assert math.isfinite(value)
        assert item.delta_mean_cost >= 0 and item.policy_mean_cost >= 0
        assert item.delta_mean_turnover >= 0 and item.policy_mean_turnover >= 0
    if result.report.all_seeds_exclude_zero_same_direction():
        expected = "policy_better" if result.report.mean_point_estimate() > 0 else "delta_better"
    else:
        expected = "inconclusive"
    assert result.verdict == expected


def test_recipe_and_policy_hash_are_bound_to_exported_payload(result) -> None:
    bundle = result.evidence_bundle
    payload = bundle["benchmark"]
    assert compute_result_hash(payload) == result.manifest.result_hash
    assert compute_result_hash(result.report.result_payload()) == result.report.manifest.result_hash
    assert payload["policy_content_hash"] == bundle["model_cards"][0]["content_hash"]
    assert payload["policy_content_hash"] == payload["evaluation"]["config"]["policy_content_hash"]
    assert payload["config"]["initial_premium"] > 0
    assert payload["training_data"]["shape"] == [32, 4]
    assert len(payload["training_data"]["sha256"]) == 64
    assert payload["config"]["train_path_seed"] not in payload["config"]["test_seeds"]
    assert bundle["gate_report"]["decision"] == "NO-GO"
    assert "not pooled CVaR" in bundle["model_cards"][0]["metric_uncertainty_note"]


def test_seed_order_does_not_change_each_seeds_draws_or_bootstrap(config) -> None:
    forward = run_benchmark(config)
    backward = run_benchmark(replace(config, test_seeds=tuple(reversed(config.test_seeds))))
    assert forward.report.per_seed_results == tuple(reversed(backward.report.per_seed_results))
    assert (
        forward.evidence_bundle["benchmark"]["policy_content_hash"]
        == (backward.evidence_bundle["benchmark"]["policy_content_hash"])
    )


def test_different_test_seeds_cannot_change_training(config) -> None:
    first = run_benchmark(config)
    second = run_benchmark(replace(config, test_seeds=(300, 400)))
    for field in ("policy_content_hash", "training_objective_history", "training_data"):
        assert (
            first.evidence_bundle["benchmark"][field] == second.evidence_bundle["benchmark"][field]
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"test_seeds": ()},
        {"test_seeds": (1, 100)},
        {"test_seeds": (100, 100)},
        {"test_seeds": (True,)},
        {"seed": -1},
        {"n_steps": 0},
        {"n_train_epochs": 0},
        {"n_train_paths": 1},
        {"volatility": float("nan")},
        {"mu": float("inf")},
        {"maturity": False},
        {"spot": 0.0},
        {"cost_rate": -0.1},
        {"cvar_alpha": 1.0},
        {"bootstrap_confidence": 0.0},
        {"initial_premium": -1.0},
        {"option_type": "invalid"},
    ],
)
def test_invalid_recipe_is_rejected(config, overrides) -> None:
    with pytest.raises(ValueError):
        replace(config, **overrides)


def test_cli_produces_a_complete_benchmark_artifact(tmp_path, capsys) -> None:
    path = tmp_path / "results" / "benchmark.json"
    assert (
        main(
            [
                "--steps",
                "2",
                "--train-paths",
                "16",
                "--batch-size",
                "8",
                "--train-epochs",
                "1",
                "--eval-paths",
                "16",
                "--bootstrap-resamples",
                "8",
                "--test-seeds",
                "100",
                "200",
                "--output",
                str(path),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    bundle = json.loads(path.read_text())
    assert summary["result_hash"] == compute_result_hash(bundle["benchmark"])
    assert len(bundle["benchmark"]["evaluation"]["per_seed"]) == 2


def test_cli_rejects_training_seed_in_test_set(tmp_path) -> None:
    path = tmp_path / "benchmark.json"
    with pytest.raises(SystemExit) as error:
        main(["--test-seeds", "1", "100", "--output", str(path)])
    assert error.value.code == 2
    assert not path.exists()
