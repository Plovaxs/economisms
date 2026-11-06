import copy
import json
from dataclasses import replace

import pytest

from prometheus.core.money import Money
from prometheus.evidence.export import export_evidence_bundle
from prometheus.experiments.manifest import compute_result_hash
from prometheus.hedging.comparison import HedgeComparisonSettings
from prometheus.orchestration.benchmark_run import BenchmarkRunConfig, run_benchmark
from prometheus.orchestration.economy_run import EconomyRunConfig, run_economy
from prometheus.orchestration.mixture_study import MixtureStudyConfig, run_mixture_study
from prometheus.orchestration.monetary_run import MonetaryRunConfig, run_monetary_simulation
from prometheus.orchestration.monetary_study import (
    FeedbackScenario,
    MonetaryStudyConfig,
    run_monetary_study,
)
from prometheus.orchestration.multi_step_run import MultiStepRunConfig, run_multi_step_simulation
from prometheus.orchestration.rate_study import RateStudyConfig, run_rate_study
from prometheus.orchestration.replay import (
    main,
    read_evidence_bundle,
    replay_evidence_bundle,
    verified_payload,
)
from prometheus.orchestration.study_run import StudyRunConfig, TrainingSeed, run_study


@pytest.fixture(scope="module")
def monthly_config():
    return MultiStepRunConfig(
        n_steps=3,
        policy_shock_step=2,
        n_train_paths=16,
        n_train_epochs=2,
        risk_eval_n_paths=16,
    )


@pytest.fixture(
    scope="module",
    params=[
        "monthly",
        "benchmark",
        "study",
        "economy",
        "monetary",
        "monetary_study",
        "rate_study",
        "mixture_study",
    ],
)
def bundle(request, monthly_config, tmp_path_factory):
    if request.param == "monthly":
        result = run_multi_step_simulation(monthly_config)
    elif request.param == "benchmark":
        result = run_benchmark(
            BenchmarkRunConfig(
                n_steps=3,
                n_train_paths=16,
                batch_size=8,
                n_train_epochs=2,
                n_eval_paths=16,
                n_bootstrap_resamples=8,
                test_seeds=(100, 200),
            )
        )
    elif request.param == "study":
        result = run_study(
            StudyRunConfig(
                training_seeds=(TrainingSeed(0, 1), TrainingSeed(7, 2)),
                test_seeds=(100, 200),
                n_steps=3,
                n_train_paths=16,
                batch_size=8,
                n_train_epochs=2,
                n_eval_paths=16,
                n_bootstrap_resamples=8,
            )
        )
    elif request.param == "economy":
        result = run_economy(EconomyRunConfig(n_steps=3, productivity_shock_step=2))
    elif request.param == "monetary":
        result = run_monetary_simulation(
            MonetaryRunConfig(
                economy=EconomyRunConfig(n_steps=3, productivity_shock_step=2),
                hedge=HedgeComparisonSettings(
                    n_train_paths=16, batch_size=8, n_train_epochs=2, risk_eval_n_paths=16
                ),
            )
        )
    elif request.param == "monetary_study":
        result = run_monetary_study(
            MonetaryStudyConfig(
                training_seeds=(TrainingSeed(0, 1), TrainingSeed(7, 2)),
                test_seeds=(100, 200),
                scenarios=(FeedbackScenario("baseline"),),
                economy=EconomyRunConfig(n_steps=3, productivity_shock_step=2),
                hedge=HedgeComparisonSettings(
                    n_train_paths=16, batch_size=8, n_train_epochs=2, risk_eval_n_paths=16
                ),
                n_eval_paths=16,
                n_bootstrap_resamples=8,
            )
        )
    elif request.param == "rate_study":
        result = run_rate_study(
            RateStudyConfig(
                training_seeds=(TrainingSeed(0, 1), TrainingSeed(7, 2)),
                test_seeds=(100, 200),
                training_macro_seeds=(11, 22),
                scenarios=(FeedbackScenario("baseline"),),
                economy=EconomyRunConfig(n_steps=3, productivity_shock_step=2),
                hedge=HedgeComparisonSettings(n_train_paths=16, batch_size=8, n_train_epochs=2),
                n_eval_paths=16,
                n_bootstrap_resamples=8,
            )
        )
    else:
        result = run_mixture_study(
            MixtureStudyConfig(
                training_seeds=(TrainingSeed(0, 1), TrainingSeed(7, 2)),
                test_seeds=(100, 200),
                training_macro_seeds=(11, 22),
                scenarios=(FeedbackScenario("baseline"),),
                economy=EconomyRunConfig(n_steps=3, productivity_shock_step=2),
                hedge=HedgeComparisonSettings(n_train_paths=16, batch_size=8, n_train_epochs=2),
                n_eval_paths=8,
                n_bootstrap_resamples=8,
                n_nested_resamples=8,
            )
        )
    path = tmp_path_factory.mktemp(request.param) / "bundle.json"
    export_evidence_bundle(result.evidence_bundle, path)
    legacy = read_evidence_bundle(path)
    legacy.pop("artifact_integrity")  # Keep legacy computational-contract coverage explicit.
    return legacy


def _payload_key(bundle):
    return next(
        key
        for key in (
            "simulation",
            "benchmark",
            "study",
            "economy",
            "monetary",
            "monetary_study",
            "rate_study",
            "mixture_study",
        )
        if key in bundle
    )


def _rehash(bundle):
    key = _payload_key(bundle)
    bundle["run_manifest"]["result_hash"] = compute_result_hash(bundle[key])
    return bundle


def test_replay_retrains_and_reproduces_the_exported_result(bundle) -> None:
    result = replay_evidence_bundle(bundle)
    assert result.matches
    assert result.expected_hash == result.observed_hash
    assert result.runtime_changes == ()
    assert result.evidence_bundle["run_manifest"]["run_id"] != bundle["run_manifest"]["run_id"]
    assert result.evidence_bundle["replay"]["matches"]


def test_recorded_failed_scenario_replays_as_failed_not_successful(monthly_config) -> None:
    failed = run_multi_step_simulation(
        replace(
            monthly_config,
            firm_seed_capital=Money(10_000),
            consumption_propensity=0.0,
        )
    )
    result = replay_evidence_bundle(failed.evidence_bundle)
    assert result.matches
    assert not result.evidence_bundle["simulation"]["valid"]
    assert result.evidence_bundle["simulation"]["mlp_final_wealth"] is None


def test_modified_payload_is_rejected_before_any_training(bundle, monkeypatch) -> None:
    import prometheus.orchestration.benchmark_run as benchmark_module
    import prometheus.orchestration.economy_run as economy_module
    import prometheus.orchestration.mixture_study as mixture_module
    import prometheus.orchestration.monetary_run as monetary_module
    import prometheus.orchestration.monetary_study as monetary_study_module
    import prometheus.orchestration.multi_step_run as monthly_module
    import prometheus.orchestration.rate_study as rate_study_module
    import prometheus.orchestration.study_run as study_module

    def unexpected_run(*args):
        pytest.fail("tampered evidence must be rejected before training")

    monkeypatch.setattr(benchmark_module, "run_benchmark", unexpected_run)
    monkeypatch.setattr(monthly_module, "run_multi_step_simulation", unexpected_run)
    monkeypatch.setattr(study_module, "run_study", unexpected_run)
    monkeypatch.setattr(economy_module, "run_economy", unexpected_run)
    monkeypatch.setattr(monetary_module, "run_monetary_simulation", unexpected_run)
    monkeypatch.setattr(monetary_study_module, "run_monetary_study", unexpected_run)
    monkeypatch.setattr(rate_study_module, "run_rate_study", unexpected_run)
    monkeypatch.setattr(mixture_module, "run_mixture_study", unexpected_run)
    tampered = copy.deepcopy(bundle)
    key = _payload_key(bundle)
    tampered[key]["config"]["cost_rate"] = 0.02
    with pytest.raises(ValueError, match="recorded result_hash"):
        replay_evidence_bundle(tampered)


def test_rehashing_fabricated_results_does_not_make_replay_match(bundle) -> None:
    tampered = copy.deepcopy(bundle)
    if "simulation" in tampered:
        tampered["simulation"]["initial_premium"] += 1.0
    elif "benchmark" in tampered:
        tampered["benchmark"]["evaluation"]["per_seed"][0]["delta_cvar"] += 1.0
    elif "study" in tampered:
        tampered["study"]["scenarios"][0]["cells"][0]["evaluation"]["delta_cvar"] += 1.0
    elif "economy" in tampered:
        tampered["economy"]["steps"][0]["firm_cash"]["minor_units"] += 1
    elif "monetary_study" in tampered:
        tampered["monetary_study"]["scenarios"][0]["cells"][0]["difference"] += 1.0
    elif "mixture_study" in tampered:
        tampered["mixture_study"]["scenarios"][0]["losses"]["rate_aware"][0][0][0] += 1.0
    elif "rate_study" in tampered:
        tampered["rate_study"]["scenarios"][0]["cells"][0]["rate_aware"]["cvar"] += 1.0
    else:
        tampered["monetary"]["steps"][0]["financial"]["closing_spot"] += 1.0
    result = replay_evidence_bundle(_rehash(tampered))
    assert not result.matches
    assert result.observed_hash == bundle["run_manifest"]["result_hash"]
    assert not result.evidence_bundle["replay"]["matches"]


@pytest.mark.parametrize("field", ["config", "seed", "result_hash"])
def test_manifest_cannot_disagree_with_its_payload(bundle, field) -> None:
    tampered = copy.deepcopy(bundle)
    if field == "config":
        tampered["run_manifest"]["config"]["seed"] += 1
    elif field == "seed":
        tampered["run_manifest"]["seed"] += 1
    else:
        tampered["run_manifest"]["result_hash"] = "invalid"
    with pytest.raises(ValueError):
        verified_payload(tampered)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("accounting_convention", "unknown"),
    ],
)
def test_unsupported_payload_versions_are_rejected(bundle, field, value) -> None:
    tampered = copy.deepcopy(bundle)
    key = _payload_key(bundle)
    tampered[key][field] = value
    with pytest.raises(ValueError, match="unsupported"):
        verified_payload(_rehash(tampered))


@pytest.mark.parametrize("change", ["extra", "missing"])
def test_recipe_decoder_never_silently_uses_defaults(bundle, change) -> None:
    tampered = copy.deepcopy(bundle)
    key = _payload_key(bundle)
    config = tampered[key]["config"]
    if change == "extra":
        config["unknown_field"] = 0
    else:
        del config[
            {
                "monetary": "publication_lag_months",
                "monetary_study": "n_eval_paths",
                "rate_study": "rate_feature_scale",
                "mixture_study": "n_nested_resamples",
            }.get(key, "n_steps")
        ]
    tampered["run_manifest"]["config"] = copy.deepcopy(config)
    with pytest.raises(ValueError, match="complete configuration"):
        replay_evidence_bundle(_rehash(tampered))


def test_runtime_drift_is_reported_without_confusing_it_with_result_drift(bundle) -> None:
    changed = copy.deepcopy(bundle)
    changed["runtime"]["source_sha256"] = "0" * 64
    result = replay_evidence_bundle(changed)
    assert result.matches
    assert result.runtime_changes == ("source_sha256",)


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"x": NaN}',
        '{"x": Infinity}',
        '{"x": 1, "x": 2}',
        '{"config": {"seed": 0, "seed": 1}}',
    ],
)
def test_json_reader_rejects_invalid_or_nonfinite_evidence(tmp_path, content) -> None:
    path = tmp_path / "input.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        read_evidence_bundle(path)


def test_cli_replay_preserves_source_and_exports_comparison(bundle, tmp_path, capsys) -> None:
    source = export_evidence_bundle(bundle, tmp_path / "source.json")
    before = source.read_bytes()
    output = tmp_path / "replays" / "new.json"
    assert main([str(source), "--output", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["matches"]
    assert source.read_bytes() == before
    assert read_evidence_bundle(output)["replay"]["matches"]


def test_cli_mismatch_has_nonzero_exit_status(bundle, tmp_path, capsys) -> None:
    modified = copy.deepcopy(bundle)
    key = _payload_key(bundle)
    if key == "study":
        modified[key]["training"][0]["training_objective_history"][0] += 1.0
    elif key == "economy":
        modified[key]["steps"][0]["settlement"]["produced"]["numerator"] += 1
    elif key == "monetary_study":
        modified[key]["training"][0]["objective_history"][0] += 1.0
    elif key == "mixture_study":
        modified[key]["scenarios"][0]["losses"]["rate_aware"][0][0][0] += 1.0
    elif key == "rate_study":
        modified[key]["training"][0]["diagnostics"][0]["objective"] += 1.0
    elif key == "monetary":
        modified[key]["training"]["objective_history"][0] += 1.0
    else:
        modified[key]["training_objective_history"][0] += 1.0
    source = export_evidence_bundle(_rehash(modified), tmp_path / "source.json")
    assert main([str(source)]) == 1
    assert not json.loads(capsys.readouterr().out)["matches"]


def test_cli_refuses_to_overwrite_its_source(bundle, tmp_path) -> None:
    source = export_evidence_bundle(bundle, tmp_path / "source.json")
    before = source.read_bytes()
    with pytest.raises(SystemExit) as error:
        main([str(source), "--output", str(source)])
    assert error.value.code == 2
    assert source.read_bytes() == before


def test_sealed_artifacts_replay_under_strict_integrity_mode(bundle):
    from prometheus.evidence.integrity import seal_evidence_bundle

    sealed = seal_evidence_bundle(bundle)
    result = replay_evidence_bundle(sealed, require_integrity=True)
    assert result.matches and result.input_integrity == "sha256_verified"
    assert result.evidence_bundle["replay"]["input_integrity"] == "sha256_verified"
    with pytest.raises(ValueError, match="required"):
        replay_evidence_bundle(bundle, require_integrity=True)
