import copy
import json
from dataclasses import asdict, replace

import numpy as np
import pytest

from prometheus.core.seeds import SeedHierarchy
from prometheus.econosim.price_economy import EconomyRunConfig
from prometheus.evidence.export import export_evidence_bundle
from prometheus.experiments.manifest import compute_result_hash
from prometheus.hedging.comparison import HedgeComparisonSettings
from prometheus.hedging.rate_paths import rate_scheduled_gbm
from prometheus.orchestration.monetary_run import (
    run_monetary_macro_path,
    run_monetary_simulation,
)
from prometheus.orchestration.monetary_study import (
    FeedbackScenario,
    MonetaryStudyConfig,
    array_hash,
    main,
    run_monetary_study,
)
from prometheus.orchestration.replay import read_evidence_bundle, replay_evidence_bundle
from prometheus.orchestration.study_run import TrainingSeed


@pytest.fixture(scope="module")
def config():
    return MonetaryStudyConfig(
        training_seeds=(TrainingSeed(0, 1), TrainingSeed(7, 2)),
        test_seeds=(100, 200),
        scenarios=(
            FeedbackScenario("baseline"),
            FeedbackScenario("delayed", publication_lag_months=2),
        ),
        economy=EconomyRunConfig(n_steps=6, productivity_shock_step=2, productivity_noise_std=0.03),
        hedge=HedgeComparisonSettings(
            n_train_paths=24, n_train_epochs=2, batch_size=12, risk_eval_n_paths=16
        ),
        n_eval_paths=24,
        n_bootstrap_resamples=30,
    )


@pytest.fixture(scope="module")
def result(config):
    return run_monetary_study(config)


def test_macro_only_path_matches_every_online_macro_field(config):
    cfg = config.macro_config(100, config.scenarios[0])
    macro = run_monetary_macro_path(cfg)
    full = run_monetary_simulation(cfg)
    assert macro.valid and full.valid
    for a, b in zip(macro.steps, full.steps, strict=True):
        for key, value in asdict(a).items():
            assert value == asdict(b)[key]


def test_complete_crossing_shares_banks_and_keeps_every_retraining(config, result):
    p = result.evidence_bundle["monetary_study"]
    assert result.valid
    assert len(p["training"]) == 2
    assert len(result.evidence_bundle["model_cards"]) == 2
    for row, card in zip(p["training"], result.evidence_bundle["model_cards"], strict=True):
        assert row["policy_content_hash"] == card["content_hash"]
    for scenario in p["scenarios"]:
        assert len(scenario["cells"]) == 4
        assert len(scenario["banks"]) == 2
        assert {(c["training_seed"]["policy_seed"], c["test_seed"]) for c in scenario["cells"]} == {
            (0, 100),
            (0, 200),
            (7, 100),
            (7, 200),
        }
        for bank in scenario["banks"]:
            hashes = {
                c["market_paths_sha256"]
                for c in scenario["cells"]
                if c["test_seed"] == bank["test_seed"]
            }
            assert hashes == {bank["market_paths_sha256"]}
            assert len(bank["decision_rates"]) == 7
            assert bank["macro"]["valid"]
            assert len(bank["macro"]["steps"]) == 6
        matrix = np.array(scenario["differences"])
        manual = np.array(
            [c["delta"]["cvar"] - c["policy"]["cvar"] for c in scenario["cells"]]
        ).reshape(2, 2)
        assert np.array_equal(matrix, manual)
        assert scenario["uncertainty"]["crossed"]["point_estimate"] == pytest.approx(manual.mean())
        assert scenario["uncertainty"]["n_training_seeds"] == 2
        assert scenario["uncertainty"]["n_test_banks"] == 2
    assert p["scenario_interval_confidence"] == pytest.approx(0.975)
    for i in range(2):
        a, b = (s["banks"][i] for s in p["scenarios"])
        assert a["standard_normals_sha256"] == b["standard_normals_sha256"]
        assert a["economy_seed"] == b["economy_seed"]
        # Before lagged policy can differ, common productivity draws produce the same economy.
        assert a["macro"]["steps"][0]["economic"] == b["macro"]["steps"][0]["economic"]


def test_reversing_declared_axes_cannot_change_inference_or_result_hash(config, result):
    reversed_run = run_monetary_study(
        replace(
            config,
            training_seeds=config.training_seeds[::-1],
            test_seeds=config.test_seeds[::-1],
            scenarios=config.scenarios[::-1],
        )
    )
    assert reversed_run.manifest.result_hash == result.manifest.result_hash


def test_stress_changes_realized_volatility_costs_without_changing_training_or_macro(
    config, result
):
    stressed = run_monetary_study(
        replace(
            config,
            scenarios=tuple(
                replace(s, volatility_multiplier=1.75, cost_multiplier=2.0)
                for s in config.scenarios
            ),
        )
    )
    p = result.evidence_bundle["monetary_study"]
    q = stressed.evidence_bundle["monetary_study"]
    assert p["training"] == q["training"]
    assert p["initial_premium"] == q["initial_premium"]
    for original, other in zip(p["scenarios"], q["scenarios"], strict=True):
        for a, b in zip(original["banks"], other["banks"], strict=True):
            assert a["macro_sha256"] == b["macro_sha256"]
            assert a["standard_normals_sha256"] == b["standard_normals_sha256"]
            assert a["market_paths_sha256"] != b["market_paths_sha256"]


def test_bank_hash_reconstructs_from_released_rates_and_named_market_normals(config, result):
    bank = result.evidence_bundle["monetary_study"]["scenarios"][0]["banks"][0]
    normals = (
        SeedHierarchy(bank["test_seed"])
        .stream("macro-study-market-normals")
        .standard_normal((24, 6))
    )
    assert array_hash(normals) == bank["standard_normals_sha256"]
    paths = rate_scheduled_gbm(100.0, 0.04, 0.2, 1 / 12, np.array(bank["decision_rates"]), normals)
    assert array_hash(paths) == bank["market_paths_sha256"]


def test_no_training_or_inference_when_any_macro_bank_fails(config, monkeypatch):
    import prometheus.orchestration.monetary_study as module

    def forbidden(*args, **kwargs):
        pytest.fail("an invalid experiment must not train a successful subset")

    monkeypatch.setattr(module, "train_deep_hedge", forbidden)
    broken = replace(config, economy=replace(config.economy, max_price_evaluations=3))
    run = run_monetary_study(broken)
    p = run.evidence_bundle["monetary_study"]
    assert not run.valid and run.verdict is None
    assert len(p["invalid_reasons"]) == 4
    assert not p["training"] and not run.evidence_bundle["model_cards"]
    for s in p["scenarios"]:
        assert len(s["banks"]) == 2
        assert not s["cells"] and s["uncertainty"] is None and s["verdict"] is None


def test_actual_replay_retrains_and_recomputes_macro_banks(config, result, tmp_path):
    path = export_evidence_bundle(result.evidence_bundle, tmp_path / "study.json")
    b = read_evidence_bundle(path)
    decoded = MonetaryStudyConfig.from_dict(b["monetary_study"]["config"])
    assert asdict(decoded) == asdict(config)
    assert compute_result_hash(b["monetary_study"]) == result.manifest.result_hash
    replay = replay_evidence_bundle(b)
    assert replay.matches and not replay.runtime_changes
    tampered = copy.deepcopy(b)
    tampered.pop("artifact_integrity", None)  # Explicit unsealed revision for replay test.
    tampered["monetary_study"]["scenarios"][0]["cells"][0]["difference"] += 100
    tampered["run_manifest"]["result_hash"] = compute_result_hash(tampered["monetary_study"])
    assert not replay_evidence_bundle(tampered).matches


@pytest.mark.parametrize(
    "override",
    [
        {"seed": True},
        {"n_eval_paths": 0},
        {"n_bootstrap_resamples": 0},
        {"test_seeds": (100,)},
        {"test_seeds": (100, 100)},
        {"test_seeds": (True, 2)},
        {"training_seeds": (TrainingSeed(0, 1),)},
        {"training_seeds": (TrainingSeed(0, 1), TrainingSeed(0, 2))},
        {"training_seeds": (TrainingSeed(0, 1), TrainingSeed(2, 1))},
        {"scenarios": ()},
        {"scenarios": (FeedbackScenario("a"), FeedbackScenario("a"))},
        {"primary_scenario": "missing"},
        {"economic_margin": -1.0},
        {"economic_margin": np.nan},
        {"bootstrap_confidence": 1.0},
    ],
)
def test_invalid_study_settings_are_rejected(config, override):
    with pytest.raises(ValueError):
        replace(config, **override)


@pytest.mark.parametrize(
    "override",
    [
        {"name": ""},
        {"publication_lag_months": 0},
        {"publication_lag_months": True},
        {"productivity_shock_factor": -1.0},
        {"payroll_rate_sensitivity": np.inf},
        {"volatility_multiplier": 0.0},
        {"cost_multiplier": -1.0},
        {"cost_multiplier": True},
    ],
)
def test_invalid_scenario_settings_are_rejected(override):
    with pytest.raises(ValueError):
        FeedbackScenario(**({"name": "baseline"} | override))


@pytest.mark.parametrize(
    "key,field",
    [
        ("policy", "inertia"),
        ("hedge", "cost_rate"),
        ("economy", "n_steps"),
        ("training_seeds", "path_seed"),
        ("scenarios", "cost_multiplier"),
    ],
)
def test_recipe_requires_every_nested_field(config, key, field):
    values = asdict(config)
    nested = values[key][0] if key in ("training_seeds", "scenarios") else values[key]
    del nested[field]
    with pytest.raises(ValueError, match="complete"):
        MonetaryStudyConfig.from_dict(values)


def test_cli_runs_a_complete_json_recipe(config, tmp_path, capsys):
    from prometheus.experiments.manifest import json_default

    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps(asdict(config), default=json_default))
    output = tmp_path / "study.json"
    assert main(["--recipe", str(recipe), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert read_evidence_bundle(output)["monetary_study"]["valid"]


def test_one_failed_bank_suppresses_successful_subset_inference(config, monkeypatch):
    import prometheus.orchestration.monetary_study as module

    original = module.run_monetary_macro_path
    calls = []

    def one_failure(cfg):
        calls.append(cfg)
        actual = original(cfg)
        return (
            replace(actual, valid=False, invalid_reasons=("forced bank failure",))
            if len(calls) == 1
            else actual
        )

    monkeypatch.setattr(module, "run_monetary_macro_path", one_failure)
    run = run_monetary_study(config)
    payload = run.evidence_bundle["monetary_study"]
    assert not run.valid and len(calls) == 4
    assert len(payload["invalid_reasons"]) == 1
    assert (
        sum(
            bank["macro"]["valid"]
            for scenario in payload["scenarios"]
            for bank in scenario["banks"]
        )
        == 3
    )
    assert all(not s["cells"] and s["verdict"] is None for s in payload["scenarios"])
    assert not payload["training"]


def test_zero_policy_cell_matches_closed_form_financing_and_fractional_tail(config, monkeypatch):
    import torch

    import prometheus.orchestration.monetary_study as module
    from prometheus.hedging.deep_hedge import DeepHedgeTrainingResult, HedgePolicyMLP

    calls = []

    def fixed_zero_policy(*args, **kwargs):
        calls.append(kwargs["seed"])
        policy = HedgePolicyMLP()
        for parameter in policy.parameters():
            torch.nn.init.zeros_(parameter)
        return DeepHedgeTrainingResult(policy, [0.0])

    monkeypatch.setattr(module, "train_deep_hedge", fixed_zero_policy)
    cfg = replace(config, n_eval_paths=3, hedge=replace(config.hedge, cvar_alpha=0.5))
    run = run_monetary_study(cfg)
    assert calls == [0, 7]  # One training per row, never per scenario/bank.
    payload = run.evidence_bundle["monetary_study"]
    for scenario in payload["scenarios"]:
        for bank in scenario["banks"]:
            rates = np.array(bank["decision_rates"])
            z = (
                SeedHierarchy(bank["test_seed"])
                .stream("macro-study-market-normals")
                .standard_normal((3, 6))
            )
            prices = rate_scheduled_gbm(100.0, 0.04, 0.2, 1 / 12, rates, z)
            losses = np.maximum(prices[:, -1] - 100.0, 0.0) - payload["initial_premium"] * np.exp(
                rates[:-1].sum() / 12
            )
            ordered = sorted(losses)
            expected_cvar = (ordered[-1] + 0.5 * ordered[-2]) / 1.5
            for cell in scenario["cells"]:
                if cell["test_seed"] == bank["test_seed"]:
                    assert cell["policy"]["cvar"] == pytest.approx(expected_cvar, abs=1e-12)
                    assert cell["policy"]["mean_loss"] == pytest.approx(losses.mean())
                    assert cell["policy"]["mean_cost"] == 0.0
                    assert cell["policy"]["mean_turnover"] == 0.0
