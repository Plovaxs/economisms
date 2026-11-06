import copy
import json
from dataclasses import asdict, replace

import numpy as np
import pytest

from prometheus.econosim.price_economy import EconomyRunConfig
from prometheus.evidence.export import export_evidence_bundle
from prometheus.experiments.manifest import compute_result_hash, json_default
from prometheus.hedging.comparison import HedgeComparisonSettings
from prometheus.orchestration.monetary_study import FeedbackScenario, array_hash
from prometheus.orchestration.rate_study import (
    PRIMARY_CONTRAST,
    RateStudyConfig,
    build_rate_training_data,
    main,
    run_rate_study,
)
from prometheus.orchestration.replay import read_evidence_bundle, replay_evidence_bundle
from prometheus.orchestration.study_run import TrainingSeed


@pytest.fixture(scope="module")
def config():
    return RateStudyConfig(
        training_seeds=(TrainingSeed(0, 1), TrainingSeed(7, 2)),
        test_seeds=(100, 200),
        training_macro_seeds=(11, 22),
        scenarios=(
            FeedbackScenario("baseline"),
            FeedbackScenario("delayed", publication_lag_months=2),
        ),
        economy=EconomyRunConfig(n_steps=5, productivity_shock_step=2, productivity_noise_std=0.03),
        hedge=HedgeComparisonSettings(n_train_paths=24, batch_size=12, n_train_epochs=2),
        n_eval_paths=24,
        n_bootstrap_resamples=20,
    )


@pytest.fixture(scope="module")
def result(config):
    return run_rate_study(config)


def test_training_arms_are_parameter_and_data_matched_with_full_crossing(config, result):
    assert result.valid
    p = result.evidence_bundle["rate_study"]
    assert len(p["training"]) == len(result.evidence_bundle["model_cards"]) == 4
    assert len(p["training_data"]) == 2
    for i in range(2):
        blind, aware = p["training"][i * 2 : i * 2 + 2]
        assert blind["arm"] == "rate_blind" and aware["arm"] == "rate_aware"
        assert blind["initial_parameter_hash"] == aware["initial_parameter_hash"]
        assert blind["minibatches_sha256"] == aware["minibatches_sha256"]
        assert blind["policy_content_hash"] != aware["policy_content_hash"]
        assert len(blind["diagnostics"]) == len(aware["diagnostics"]) == 2
    for row, card in zip(p["training"], result.evidence_bundle["model_cards"], strict=True):
        assert row["policy_content_hash"] == card["content_hash"]
        assert card["approval_status"] == "NOT REVIEWED"
        assert "fourth feature" in card["input_schema_summary"]
    for s in p["scenarios"]:
        assert len(s["cells"]) == 4 and len(s["banks"]) == 2
        for cell in s["cells"]:
            for arm in ("delta", "rate_blind", "rate_aware"):
                assert all(
                    np.isfinite(cell[arm][key])
                    for key in ("cvar", "mean_loss", "mean_cost", "mean_turnover")
                )
            assert (
                cell["differences"][PRIMARY_CONTRAST]
                == cell["rate_blind"]["cvar"] - cell["rate_aware"]["cvar"]
            )
        for bank in s["banks"]:
            assert {
                c["market_paths_sha256"] for c in s["cells"] if c["test_seed"] == bank["test_seed"]
            } == {bank["market_paths_sha256"]}
        for name, contrast in s["contrasts"].items():
            matrix = np.array(contrast["differences"])
            assert matrix.shape == (2, 2)
            assert np.array_equal(matrix.flatten(), [c["differences"][name] for c in s["cells"]])
            assert contrast["uncertainty"]["crossed"]["point_estimate"] == pytest.approx(
                matrix.mean()
            )
    assert p["scenario_contrast_confidence"] == pytest.approx(1 - 0.05 / 4)


def test_test_seeds_and_scenarios_cannot_change_training_data_or_fitted_models(config, result):
    changed = run_rate_study(
        replace(
            config,
            test_seeds=(300, 400),
            scenarios=tuple(
                replace(
                    s, productivity_shock_factor=0.2, volatility_multiplier=1.5, cost_multiplier=2.0
                )
                for s in config.scenarios
            ),
        )
    )
    p, q = result.evidence_bundle["rate_study"], changed.evidence_bundle["rate_study"]
    assert p["training_data"] == q["training_data"]
    assert p["training"] == q["training"]
    assert p["initial_premium"] == q["initial_premium"]
    assert (
        p["scenarios"][0]["banks"][0]["market_paths_sha256"]
        != q["scenarios"][0]["banks"][0]["market_paths_sha256"]
    )


def test_all_declared_axes_can_be_reversed_without_changing_results(config, result):
    other = run_rate_study(
        replace(
            config,
            training_seeds=config.training_seeds[::-1],
            test_seeds=config.test_seeds[::-1],
            scenarios=config.scenarios[::-1],
            training_macro_seeds=config.training_macro_seeds[::-1],
        )
    )
    assert other.manifest.result_hash == result.manifest.result_hash


def test_training_pool_records_balanced_allocations_rates_and_independent_macro_seeds(config):
    cfg = replace(config, hedge=replace(config.hedge, n_train_paths=25))
    x, r, record, reasons = build_rate_training_data(cfg, cfg.training_seeds[0])
    assert not reasons and x.shape == r.shape == (25, 6)
    assert [bank["n_paths"] for bank in record["banks"]] == [13, 12]
    assert record["market_paths_sha256"] == array_hash(x)
    assert record["decision_rates_sha256"] == array_hash(r)
    assert np.all(r[:, 0] == cfg.initial_rate)
    assert np.unique(r[:, 2:]).size > 1
    _, _, independent, _ = build_rate_training_data(cfg, cfg.training_seeds[1])
    assert {b["economy_seed"] for b in record["banks"]}.isdisjoint(
        {b["economy_seed"] for b in independent["banks"]}
    )
    start = 0
    for bank in record["banks"]:
        assert compute_result_hash(bank["macro"]) == bank["macro_sha256"]
        assert np.array_equal(r[start], bank["decision_rates"])
        start += bank["n_paths"]


def test_any_training_macro_failure_suppresses_all_fitting_and_inference(config, monkeypatch):
    import prometheus.orchestration.rate_study as module

    actual = module.run_monetary_macro_path
    calls = []

    def one_failure(cfg):
        calls.append(cfg)
        path = actual(cfg)
        return (
            replace(path, valid=False, invalid_reasons=("forced training bank failure",))
            if len(calls) == 1
            else path
        )

    def forbidden(*args, **kwargs):
        pytest.fail("failed training bank must invalidate all arms")

    monkeypatch.setattr(module, "run_monetary_macro_path", one_failure)
    monkeypatch.setattr(module, "train_rate_hedge", forbidden)
    run = run_rate_study(config)
    p = run.evidence_bundle["rate_study"]
    assert not run.valid and run.verdict is None
    assert len(calls) == 4 and len(p["invalid_reasons"]) == 1
    assert not p["training"] and not run.evidence_bundle["model_cards"]
    assert all(not s["cells"] for s in p["scenarios"])
    assert all(c["uncertainty"] is None for s in p["scenarios"] for c in s["contrasts"].values())


def test_actual_replay_retrains_both_arms_and_rejects_fabricated_results(result, tmp_path):
    path = export_evidence_bundle(result.evidence_bundle, tmp_path / "rate.json")
    bundle = read_evidence_bundle(path)
    assert compute_result_hash(bundle["rate_study"]) == result.manifest.result_hash
    assert replay_evidence_bundle(bundle).matches
    changed = copy.deepcopy(bundle)
    changed.pop("artifact_integrity", None)  # Explicit unsealed revision for replay test.
    changed["rate_study"]["scenarios"][0]["cells"][0]["rate_aware"]["cvar"] += 10
    changed["run_manifest"]["result_hash"] = compute_result_hash(changed["rate_study"])
    assert not replay_evidence_bundle(changed).matches


@pytest.mark.parametrize(
    "override",
    [
        {"training_macro_seeds": (100, 11)},
        {"training_macro_seeds": (11,)},
        {"training_macro_seeds": (11, 11)},
        {"training_macro_seeds": (True, 22)},
        {"rate_feature_scale": 0.0},
        {"rate_feature_scale": True},
        {"max_gradient_norm": np.inf},
        {"training_scenario": FeedbackScenario("train", volatility_multiplier=2.0)},
    ],
)
def test_invalid_ablation_controls_are_rejected(config, override):
    with pytest.raises(ValueError):
        replace(config, **override)


@pytest.mark.parametrize(
    "missing", ["training_macro_seeds", "rate_feature_scale", "max_gradient_norm"]
)
def test_new_configuration_fields_cannot_silently_default(config, missing):
    payload = asdict(config)
    del payload[missing]
    with pytest.raises(ValueError, match="complete configuration"):
        RateStudyConfig.from_dict(payload)


def test_cli_uses_complete_recipe_and_exports_a_replayable_bundle(config, tmp_path, capsys):
    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps(asdict(config), default=json_default))
    output = tmp_path / "out.json"
    assert main(["--recipe", str(recipe), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert replay_evidence_bundle(read_evidence_bundle(output)).matches


def test_failed_evaluation_and_training_banks_replay_as_invalid(config):
    bad = replace(config, economy=replace(config.economy, max_price_evaluations=3))
    run = run_rate_study(bad)
    p = run.evidence_bundle["rate_study"]
    assert not run.valid and run.verdict is None and not p["training"]
    assert len(p["invalid_reasons"]) == 8
    assert all(not bank["macro"]["valid"] for s in p["scenarios"] for bank in s["banks"])
    assert replay_evidence_bundle(run.evidence_bundle).matches
