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


def test_more_patience_improves_in_distribution_score_but_destroys_ood_robustness() -> None:
    """PR-176: checked whether `patience=20` (the production default)
    is simply undertraining this model, the same confound this session
    fixed for several other subsystems. It is NOT -- the opposite is
    true, and this matters because the project's OWN headline positive
    finding for `neural_sde` (RQ2/H2: real OOD robustness under the
    2020 COVID shock) depends on it. `benchmark_report`'s "held-out"
    evaluation set is the SAME `validation_examples` early stopping
    selects on, so a better in-distribution log_score at higher
    patience is partly expected, not necessarily a better model -- and
    checking the genuinely untouched COVID OOD window settles it: at
    `patience=60`, in-distribution log_score improves (~4.82 -> ~3.92)
    but COVID-window degradation EXPLODES (~5.58 -> ~48.75, now WORSE
    than the ~29.97 the classical GBM baseline degrades by) -- the
    model has overfit the in-distribution set at the direct expense of
    the real, valuable property this subsystem actually has. This is
    positive evidence FOR keeping `patience=20`, not a reason to raise
    it -- "train harder" is the wrong instinct here, confirmed by
    checking rather than assumed."""
    low_patience = run_neural_sde_job(NeuralSdeRunConfig(seed=0, patience=20))
    high_patience = run_neural_sde_job(NeuralSdeRunConfig(seed=0, patience=60))
    low_ood = low_patience.evidence_bundle["neural_sde"]["ood_report"]
    high_ood = high_patience.evidence_bundle["neural_sde"]["ood_report"]

    assert (
        high_patience.evidence_bundle["neural_sde"]["benchmark_report"]["log_score"]["neural_sde"]
        < low_patience.evidence_bundle["neural_sde"]["benchmark_report"]["log_score"]["neural_sde"]
    ), "higher patience should improve the in-distribution score measured on its own selection set"
    assert high_ood["neural_degradation"] > 5 * low_ood["neural_degradation"], (
        "the same higher patience should badly worsen real, untouched COVID-window robustness"
    )
    assert low_ood["neural_degradation"] < low_ood["baseline_degradation"], (
        "at the production default, neural_sde still beats the classical baseline here"
    )
    assert high_ood["neural_degradation"] > high_ood["baseline_degradation"], (
        "at higher patience, it no longer does -- the positive finding is specifically lost"
    )
