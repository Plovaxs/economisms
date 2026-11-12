from dataclasses import asdict

import pytest

from prometheus.orchestration.neural_sde_run import (
    DEFAULT_CSV_PATH,
    NeuralSdeRunConfig,
    run_neural_sde_job,
)


def test_default_csv_path_points_at_the_committed_real_snapshot() -> None:
    assert DEFAULT_CSV_PATH.name == "kaggle_us_macro_monthly.csv"
    assert DEFAULT_CSV_PATH.exists()


def test_config_rejects_a_non_positive_max_epochs() -> None:
    with pytest.raises(ValueError, match="max_epochs"):
        NeuralSdeRunConfig(max_epochs=0)


def test_config_rejects_a_non_positive_patience() -> None:
    with pytest.raises(ValueError, match="patience"):
        NeuralSdeRunConfig(patience=0)


def test_config_rejects_a_negative_seed() -> None:
    with pytest.raises(ValueError, match="seed"):
        NeuralSdeRunConfig(seed=-1)


def test_config_from_dict_round_trips_a_valid_recipe() -> None:
    config = NeuralSdeRunConfig(seed=1, max_epochs=7, patience=3)
    assert NeuralSdeRunConfig.from_dict(asdict(config)) == config


def test_config_from_dict_rejects_a_missing_field() -> None:
    payload = asdict(NeuralSdeRunConfig())
    del payload["max_epochs"]
    with pytest.raises(ValueError, match="complete configuration fields"):
        NeuralSdeRunConfig.from_dict(payload)


def test_config_from_dict_rejects_an_extra_field() -> None:
    """In particular: `csv_path` must NOT be accepted -- this config
    deliberately does not expose it, so a job submission cannot point
    the loader at an arbitrary filesystem path."""
    payload = asdict(NeuralSdeRunConfig())
    payload["csv_path"] = "/etc/passwd"
    with pytest.raises(ValueError, match="complete configuration fields"):
        NeuralSdeRunConfig.from_dict(payload)


def test_run_neural_sde_job_produces_a_real_manifest_and_evidence_bundle() -> None:
    config = NeuralSdeRunConfig(seed=0, max_epochs=2, patience=1)
    result = run_neural_sde_job(config)
    assert result.manifest.seed == config.seed
    payload = result.evidence_bundle["neural_sde"]
    assert payload["accounting_convention"] == "neural-sde-benchmark-v1"
    assert payload["schema_version"] == 1
    assert payload["config"] == asdict(config)
    assert "benchmark_report" in payload
    assert result.evidence_bundle["run_manifest"]["result_hash"] == result.manifest.result_hash
