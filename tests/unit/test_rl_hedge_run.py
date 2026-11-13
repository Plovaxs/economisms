from dataclasses import asdict

import pytest

from prometheus.orchestration.rl_hedge_run import RlHedgeRunConfig, run_rl_hedge


def test_config_rejects_a_negative_seed() -> None:
    with pytest.raises(ValueError, match="seed"):
        RlHedgeRunConfig(seed=-1)


def test_config_rejects_an_invalid_option_type() -> None:
    with pytest.raises(ValueError, match="option_type"):
        RlHedgeRunConfig(option_type="straddle")


def test_config_rejects_an_invalid_reward_objective() -> None:
    with pytest.raises(ValueError, match="reward_objective"):
        RlHedgeRunConfig(reward_objective="worst_case")  # type: ignore[arg-type]


def test_config_default_reward_objective_is_cvar_not_the_legacy_mean_loss() -> None:
    """PR-176: the production default was switched to the metric-aligned
    objective once a direct sweep showed it materially narrows the gap
    to the static baseline -- `"mean_loss"` (the original PR-158/162
    default, where `static_baseline_cvar` was only ever a precondition
    gate, never part of the training signal) remains available, opt-in."""
    assert RlHedgeRunConfig().reward_objective == "cvar"


def test_config_rejects_an_out_of_range_cvar_alpha() -> None:
    with pytest.raises(ValueError, match="cvar_alpha"):
        RlHedgeRunConfig(cvar_alpha=1.0)
    with pytest.raises(ValueError, match="cvar_alpha"):
        RlHedgeRunConfig(cvar_alpha=0.0)


def test_config_rejects_non_positive_sigma_maturity_strike_steps_paths_epochs() -> None:
    with pytest.raises(ValueError, match="sigma"):
        RlHedgeRunConfig(sigma=0.0)
    with pytest.raises(ValueError, match="maturity"):
        RlHedgeRunConfig(maturity=0.0)
    with pytest.raises(ValueError, match="n_steps"):
        RlHedgeRunConfig(n_steps=0)
    with pytest.raises(ValueError, match="n_paths"):
        RlHedgeRunConfig(n_paths=0)
    with pytest.raises(ValueError, match="strike"):
        RlHedgeRunConfig(strike=0.0)
    with pytest.raises(ValueError, match="n_epochs"):
        RlHedgeRunConfig(n_epochs=0)


def test_config_from_dict_round_trips_a_valid_recipe() -> None:
    config = RlHedgeRunConfig(n_epochs=5, n_paths=50, n_steps=4)
    assert RlHedgeRunConfig.from_dict(asdict(config)) == config


def test_config_from_dict_rejects_a_missing_or_extra_field() -> None:
    payload = asdict(RlHedgeRunConfig())
    del payload["n_epochs"]
    with pytest.raises(ValueError, match="complete configuration fields"):
        RlHedgeRunConfig.from_dict(payload)
    payload = asdict(RlHedgeRunConfig())
    payload["unknown"] = 1
    with pytest.raises(ValueError, match="complete configuration fields"):
        RlHedgeRunConfig.from_dict(payload)


def test_run_rl_hedge_produces_a_real_manifest_and_evidence_bundle() -> None:
    config = RlHedgeRunConfig(seed=0, n_paths=100, n_steps=5, n_epochs=3)
    result = run_rl_hedge(config)
    assert result.manifest.seed == config.seed
    assert result.verdict in ("rl_better", "static_better", "inconclusive")
    payload = result.evidence_bundle["rl_hedge"]
    assert payload["accounting_convention"] == "reinforce-hedge-vs-static-baseline-v1"
    assert payload["schema_version"] == 1
    assert payload["static_baseline_cvar"] == payload["static_baseline_cvar"]  # not NaN
    assert payload["trained_final_cvar"] == payload["trained_final_cvar"]  # not NaN
    assert result.evidence_bundle["run_manifest"]["result_hash"] == result.manifest.result_hash


def test_run_rl_hedge_threads_reward_objective_into_the_real_payload() -> None:
    config = RlHedgeRunConfig(seed=0, n_paths=100, n_steps=5, n_epochs=3, reward_objective="cvar")
    result = run_rl_hedge(config)
    assert result.evidence_bundle["rl_hedge"]["config"]["reward_objective"] == "cvar"


def test_run_rl_hedge_is_deterministic_for_a_fixed_seed() -> None:
    config = RlHedgeRunConfig(seed=0, n_paths=100, n_steps=5, n_epochs=3)
    first = run_rl_hedge(config)
    second = run_rl_hedge(config)
    assert first.static_baseline_cvar == second.static_baseline_cvar
    assert first.trained.final_cvar == second.trained.final_cvar
