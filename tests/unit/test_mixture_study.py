import copy
import json
from dataclasses import asdict, replace

import numpy as np
import pytest

from prometheus.econosim.price_economy import EconomyRunConfig
from prometheus.evidence.export import export_evidence_bundle
from prometheus.experiments.manifest import compute_result_hash, json_default
from prometheus.hedging.comparison import HedgeComparisonSettings
from prometheus.orchestration.mixture_study import MixtureStudyConfig, main, run_mixture_study
from prometheus.orchestration.monetary_study import FeedbackScenario, array_hash
from prometheus.orchestration.rate_study import run_rate_study
from prometheus.orchestration.replay import read_evidence_bundle, replay_evidence_bundle
from prometheus.orchestration.study_run import TrainingSeed
from prometheus.titan.risk_metrics import historical_expected_shortfall


@pytest.fixture(scope="module")
def config():
    return MixtureStudyConfig(
        training_seeds=(TrainingSeed(0, 1), TrainingSeed(7, 2)),
        test_seeds=(100, 200),
        training_macro_seeds=(11, 22),
        scenarios=(
            FeedbackScenario("baseline"),
            FeedbackScenario("delayed", publication_lag_months=2),
        ),
        economy=EconomyRunConfig(n_steps=4, productivity_shock_step=2, productivity_noise_std=0.03),
        hedge=HedgeComparisonSettings(n_train_paths=16, batch_size=8, n_train_epochs=2),
        n_eval_paths=8,
        n_bootstrap_resamples=10,
        n_nested_resamples=15,
    )


@pytest.fixture(scope="module")
def result(config):
    return run_mixture_study(config)


def test_loss_observer_receives_detached_copies_and_cannot_change_original_report(config):
    original = run_rate_study(config.rate_config())
    calls = []

    def observer(name, row, bank, arm, losses):
        assert not losses.flags.writeable
        calls.append((name, row, bank, arm))
        losses.setflags(write=True)
        losses[:] = np.nan

    observed = run_rate_study(config.rate_config(), loss_observer=observer)
    assert observed.manifest.result_hash == original.manifest.result_hash
    assert len(calls) == 24


def test_exported_loss_cubes_reconstruct_mixture_and_conditional_cvar_points(config, result):
    p = result.evidence_bundle["mixture_study"]
    assert result.valid and p["primary_endpoint"].startswith("mean_retraining_")
    assert compute_result_hash(p["conditional_study"]) == p["conditional_result_hash"]
    for summary, conditional in zip(
        p["scenarios"], p["conditional_study"]["scenarios"], strict=True
    ):
        losses = {arm: np.array(values) for arm, values in summary["losses"].items()}
        assert summary["loss_cube_shape"] == [2, 2, 8]
        for arm, cube in losses.items():
            assert array_hash(cube) == summary["losses_sha256"][arm]
            for cell in conditional["cells"]:
                i = [0, 7].index(cell["training_seed"]["policy_seed"])
                j = [100, 200].index(cell["test_seed"])
                assert array_hash(cube[i, j]) == cell[arm]["terminal_loss_sha256"]
        for contrast, comparator in [
            ("rate_blind_minus_rate_aware", "rate_blind"),
            ("delta_minus_rate_aware", "delta"),
        ]:
            point = summary["contrasts"][contrast]["uncertainty"]["point"]
            expected = []
            for i in range(2):
                a = historical_expected_shortfall(
                    losses[comparator][i].flatten(), config.hedge.cvar_alpha
                )
                b = historical_expected_shortfall(
                    losses["rate_aware"][i].flatten(), config.hedge.cvar_alpha
                )
                assert point["comparator_cvars"][i] == pytest.approx(a)
                assert point["policy_cvars"][i] == pytest.approx(b)
                expected.append(a - b)
            assert point["mean_difference"] == pytest.approx(np.mean(expected))
            assert point["mean_cell_cvar_difference"] == pytest.approx(
                conditional["contrasts"][contrast]["uncertainty"]["crossed"]["point_estimate"]
            )
    for card in result.evidence_bundle["model_cards"]:
        assert "primary_empirical_macro_mixture_cvar" in card["primary_metrics"]
    assert p["scenario_contrast_confidence"] == pytest.approx(0.9875)


def test_nested_settings_never_change_training_data_models_or_loss_samples(config, result):
    other = run_mixture_study(replace(config, n_nested_resamples=4))
    p, q = result.evidence_bundle["mixture_study"], other.evidence_bundle["mixture_study"]
    assert p["conditional_result_hash"] == q["conditional_result_hash"]
    assert p["conditional_study"] == q["conditional_study"]
    assert [s["losses"] for s in p["scenarios"]] == [s["losses"] for s in q["scenarios"]]


def test_axis_order_cannot_change_results(config, result):
    other = run_mixture_study(
        replace(
            config,
            training_seeds=config.training_seeds[::-1],
            test_seeds=config.test_seeds[::-1],
            scenarios=config.scenarios[::-1],
            training_macro_seeds=config.training_macro_seeds[::-1],
        )
    )
    assert other.manifest.result_hash == result.manifest.result_hash


def test_failed_macro_experiment_produces_no_mixture_inference_and_replays(config):
    bad = replace(config, economy=replace(config.economy, max_price_evaluations=3))
    run = run_mixture_study(bad)
    p = run.evidence_bundle["mixture_study"]
    assert not run.valid and run.verdict is None and not p["scenarios"]
    assert not run.evidence_bundle["model_cards"] and p["invalid_reasons"]
    assert replay_evidence_bundle(run.evidence_bundle).matches


def test_actual_replay_retrains_and_recomputes_nested_risk_and_samples(result, tmp_path):
    path = export_evidence_bundle(result.evidence_bundle, tmp_path / "mixture.json")
    bundle = read_evidence_bundle(path)
    assert replay_evidence_bundle(bundle).matches
    forged = copy.deepcopy(bundle)
    forged.pop("artifact_integrity", None)  # Explicit unsealed revision for replay test.
    forged["mixture_study"]["scenarios"][0]["losses"]["rate_aware"][0][0][0] += 10
    forged["run_manifest"]["result_hash"] = compute_result_hash(forged["mixture_study"])
    assert not replay_evidence_bundle(forged).matches


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_nested_resample_count_is_rejected(config, value):
    with pytest.raises(ValueError):
        replace(config, n_nested_resamples=value)


def test_complete_recipe_and_cli(config, tmp_path, capsys):
    payload = asdict(config)
    missing = dict(payload)
    del missing["n_nested_resamples"]
    with pytest.raises(ValueError, match="complete configuration"):
        MixtureStudyConfig.from_dict(missing)
    recipe, output = tmp_path / "recipe.json", tmp_path / "out.json"
    recipe.write_text(json.dumps(payload, default=json_default))
    assert main(["--recipe", str(recipe), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert replay_evidence_bundle(read_evidence_bundle(output)).matches


def test_invalid_cli_recipe_preserves_existing_destination(config, tmp_path, capsys):
    payload = asdict(config)
    payload["n_nested_resamples"] = 0
    recipe, output = tmp_path / "invalid.json", tmp_path / "existing.json"
    recipe.write_text(json.dumps(payload, default=json_default))
    output.write_text("existing audited artifact")
    with pytest.raises(SystemExit) as failure:
        main(["--recipe", str(recipe), "--output", str(output)])
    assert failure.value.code == 2
    assert output.read_text() == "existing audited artifact"
    assert "positive integer" in capsys.readouterr().err
