import hashlib
import json
from dataclasses import replace

import numpy as np
import pytest

from prometheus.core.seeds import SeedHierarchy
from prometheus.experiments.manifest import compute_result_hash
from prometheus.hedging.baseline import black_scholes_delta_hedge_ratios
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.orchestration.study_run import (
    MarketScenario,
    StudyRunConfig,
    TrainingSeed,
    interval_verdict,
    main,
    run_study,
)
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import historical_expected_shortfall


@pytest.fixture(scope="module")
def config():
    return StudyRunConfig(
        training_seeds=(TrainingSeed(0, 1), TrainingSeed(7, 2)),
        test_seeds=(100, 200),
        n_steps=3,
        n_train_paths=32,
        batch_size=16,
        n_train_epochs=3,
        n_eval_paths=64,
        n_bootstrap_resamples=32,
    )


@pytest.fixture(scope="module", params=["call", "put"])
def study(request, config):
    cfg = replace(config, option_type=request.param)
    return cfg, run_study(cfg)


def test_every_training_test_scenario_cell_is_retained(study) -> None:
    config, result = study
    assert len(result.scenarios) == 3
    assert len(result.evidence_bundle["study"]["training"]) == 2
    for scenario in result.scenarios:
        assert len(scenario.cells) == 4
        assert np.shape(scenario.differences) == (2, 2)
        assert {cell.training for cell in scenario.cells} == set(config.training_seeds)
        assert {cell.evaluation.test_seed for cell in scenario.cells} == set(config.test_seeds)
        assert scenario.uncertainty.crossed.point_estimate == pytest.approx(
            np.mean(scenario.differences)
        )
        assert scenario.uncertainty.crossed.confidence == pytest.approx(1 - 0.05 / 3)
        assert scenario.uncertainty.n_training_seeds == scenario.uncertainty.n_test_banks == 2
        assert scenario.distribution_shift == (scenario.scenario.name != "baseline")
    expected = "inconclusive"
    if all(item.verdict == "policy_better" for item in result.scenarios):
        expected = "policy_better"
    elif all(item.verdict == "delta_better" for item in result.scenarios):
        expected = "delta_better"
    assert result.verdict == expected


def test_policies_share_identical_actual_test_paths_and_delta_baseline(study) -> None:
    _, result = study
    for scenario in result.scenarios:
        for seed in (100, 200):
            rows = [cell.evaluation for cell in scenario.cells if cell.evaluation.test_seed == seed]
            assert len({row.path_hash for row in rows}) == 1
            assert len(rows[0].path_hash) == 64
            assert len({row.delta_cvar for row in rows}) == 1
            assert len({row.delta_mean_cost for row in rows}) == 1
    baseline, _, higher_costs = result.scenarios
    assert [cell.evaluation.path_hash for cell in baseline.cells] == [
        cell.evaluation.path_hash for cell in higher_costs.cells
    ]


def test_stress_paths_change_without_giving_delta_oracle_volatility(study) -> None:
    config, result = study
    stress = next(item for item in result.scenarios if item.scenario.name == "high_volatility")
    row = stress.cells[0].evaluation
    paths = simulate_gbm_paths(
        config.spot,
        stress.scenario.mu,
        stress.scenario.volatility,
        config.maturity,
        config.n_steps,
        config.n_eval_paths,
        SeedHierarchy(row.test_seed).stream("held-out-paths"),
    )
    assert row.path_hash == hashlib.sha256(paths.astype("<f8").tobytes()).hexdigest()
    dt = config.maturity / config.n_steps
    targets = black_scholes_delta_hedge_ratios(
        paths,
        dt,
        config.strike,
        config.maturity,
        config.risk_free_rate,
        config.volatility,
        config.option_type,
    )
    actual_premium = result.manifest.config["initial_premium"]
    manual = simulate_self_financing_hedge(
        paths,
        dt,
        config.strike,
        config.option_type,
        config.risk_free_rate,
        stress.scenario.cost_rate,
        actual_premium,
        targets,
    )
    assert row.delta_cvar == pytest.approx(
        historical_expected_shortfall(manual.terminal_loss, config.cvar_alpha)
    )


def test_manifest_binds_training_replicates_data_models_and_all_cells(study) -> None:
    _, result = study
    payload = result.evidence_bundle["study"]
    assert result.manifest.result_hash == compute_result_hash(payload)
    records = payload["training"]
    assert len({item["policy_content_hash"] for item in records}) == 2
    assert len({item["training_data_sha256"] for item in records}) == 2
    assert {item["policy_content_hash"] for item in records} == {
        card["content_hash"] for card in result.evidence_bundle["model_cards"]
    }
    assert result.evidence_bundle["gate_report"]["decision"] == "NO-GO"


def test_each_policy_trains_once_and_never_retrains_for_stress_scenarios(
    config, monkeypatch
) -> None:
    import prometheus.orchestration.study_run as module

    original = module.train_deep_hedge
    calls = []

    def record(*args, **kwargs):
        calls.append(kwargs["seed"])
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "train_deep_hedge", record)
    run_study(config)
    assert calls == [0, 7]


def test_order_of_declared_seeds_and_scenarios_cannot_change_inference(config) -> None:
    first = run_study(config)
    second = run_study(
        replace(
            config,
            training_seeds=tuple(reversed(config.training_seeds)),
            test_seeds=tuple(reversed(config.test_seeds)),
            scenarios=tuple(reversed(config.scenarios)),
        )
    )
    assert first.scenarios == second.scenarios
    assert first.manifest.result_hash == second.manifest.result_hash


def test_stress_configuration_cannot_affect_training(config) -> None:
    first = run_study(config)
    second = run_study(replace(config, scenarios=(config.scenarios[0],)))
    assert first.evidence_bundle["study"]["training"] == second.evidence_bundle["study"]["training"]
    # Tail allocation changes, while the baseline cell results remain identical.
    assert first.scenarios[0].cells == second.scenarios[0].cells
    assert (
        first.scenarios[0].uncertainty.crossed.confidence
        > second.scenarios[0].uncertainty.crossed.confidence
    )


@pytest.mark.parametrize(
    "low,high,margin,expected",
    [
        (0.2, 0.5, 0.1, "policy_better"),
        (-0.5, -0.2, 0.1, "delta_better"),
        (0.0, 0.5, 0.0, "inconclusive"),
        (0.1, 0.5, 0.1, "inconclusive"),
        (-0.1, 0.5, 0.0, "inconclusive"),
    ],
)
def test_economic_margin_is_predeclared_and_strict(low, high, margin, expected) -> None:
    assert interval_verdict(low, high, margin) == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"training_seeds": (TrainingSeed(0, 1),)},
        {"training_seeds": (TrainingSeed(0, 1), TrainingSeed(0, 2))},
        {"training_seeds": (TrainingSeed(0, 1), TrainingSeed(7, 1))},
        {"training_seeds": (TrainingSeed(0, 1), TrainingSeed(7, 100))},
        {"test_seeds": (100,)},
        {"test_seeds": (100, 100)},
        {"scenarios": ()},
        {"scenarios": (MarketScenario("baseline", 0.08, 0.2, 0.005),) * 2},
        {"primary_scenario": "unknown"},
        {"economic_margin": float("nan")},
        {"n_train_epochs": 0},
        {"bootstrap_confidence": float(np.nextafter(1.0, 0.0))},
        {"seed": -1},
    ],
)
def test_invalid_crossed_design_is_rejected_before_training(config, overrides) -> None:
    with pytest.raises(ValueError):
        replace(config, **overrides)


@pytest.mark.parametrize(
    "parameters",
    [
        ("", 0.08, 0.2, 0.005),
        ("invalid", float("nan"), 0.2, 0.005),
        ("invalid", 0.08, 0.0, 0.005),
        ("invalid", 0.08, 0.2, -0.1),
    ],
)
def test_invalid_scenario_is_rejected(parameters) -> None:
    with pytest.raises(ValueError):
        MarketScenario(*parameters)


def test_cli_exports_complete_study_recipe(tmp_path, capsys) -> None:
    output = tmp_path / "study.json"
    assert (
        main(
            [
                "--policy-seeds",
                "0",
                "7",
                "--train-path-seeds",
                "1",
                "2",
                "--test-seeds",
                "100",
                "200",
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
                "--output",
                str(output),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(output.read_text())["study"]
    assert summary["training_runs"] == 2 and summary["scenarios"] == 3
    assert summary["result_hash"] == compute_result_hash(payload)


def test_cli_rejects_unpaired_training_seed_lists(tmp_path) -> None:
    output = tmp_path / "study.json"
    with pytest.raises(SystemExit) as error:
        main(["--policy-seeds", "0", "7", "--train-path-seeds", "1", "--output", str(output)])
    assert error.value.code == 2
    assert not output.exists()
