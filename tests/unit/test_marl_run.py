from dataclasses import asdict

import pytest

from prometheus.orchestration.marl_run import MarlRunConfig, run_marl


def test_config_rejects_a_negative_seed() -> None:
    with pytest.raises(ValueError, match="seed"):
        MarlRunConfig(seed=-1)


def test_config_rejects_non_positive_counts() -> None:
    with pytest.raises(ValueError, match="n_epochs"):
        MarlRunConfig(n_epochs=0)
    with pytest.raises(ValueError, match="episodes_per_epoch"):
        MarlRunConfig(episodes_per_epoch=0)
    with pytest.raises(ValueError, match="n_steps"):
        MarlRunConfig(n_steps=0)
    with pytest.raises(ValueError, match="firm_opening_capital_minor_units"):
        MarlRunConfig(firm_opening_capital_minor_units=0)


def test_config_from_dict_round_trips_a_valid_recipe() -> None:
    config = MarlRunConfig(n_epochs=5, episodes_per_epoch=3, n_steps=4)
    assert MarlRunConfig.from_dict(asdict(config)) == config


def test_config_from_dict_rejects_a_missing_or_extra_field() -> None:
    payload = asdict(MarlRunConfig())
    del payload["n_epochs"]
    with pytest.raises(ValueError, match="complete configuration fields"):
        MarlRunConfig.from_dict(payload)
    payload = asdict(MarlRunConfig())
    payload["unknown"] = 1
    with pytest.raises(ValueError, match="complete configuration fields"):
        MarlRunConfig.from_dict(payload)


def test_run_marl_produces_a_real_manifest_and_evidence_bundle() -> None:
    config = MarlRunConfig(seed=0, n_epochs=3, episodes_per_epoch=2, n_steps=3)
    result = run_marl(config)
    assert result.manifest.seed == config.seed
    assert result.verdict in ("co_learning_better", "single_agent_better")
    payload = result.evidence_bundle["marl"]
    assert payload["accounting_convention"] == "single-vs-colearning-ppo-v1"
    assert payload["schema_version"] == 1
    assert len(payload["single_agent"]) == 1  # one seed submitted
    assert len(payload["co_learning"]) == 1
    assert result.evidence_bundle["run_manifest"]["result_hash"] == result.manifest.result_hash


def test_run_marl_is_deterministic_for_a_fixed_seed() -> None:
    config = MarlRunConfig(seed=0, n_epochs=3, episodes_per_epoch=2, n_steps=3)
    first = run_marl(config)
    second = run_marl(config)
    assert first.evidence_bundle["marl"]["mean_household_utility_delta"] == (
        second.evidence_bundle["marl"]["mean_household_utility_delta"]
    )
