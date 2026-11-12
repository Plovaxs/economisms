from dataclasses import asdict

import pytest

from prometheus.orchestration.pde_solver_run import PdeSolverRunConfig, run_pde_solver


def test_config_rejects_a_negative_seed() -> None:
    with pytest.raises(ValueError, match="seed"):
        PdeSolverRunConfig(seed=-1)


def test_config_rejects_non_positive_volatility_maturity_or_strike() -> None:
    with pytest.raises(ValueError, match="volatility"):
        PdeSolverRunConfig(volatility=0.0)
    with pytest.raises(ValueError, match="maturity"):
        PdeSolverRunConfig(maturity=0.0)
    with pytest.raises(ValueError, match="strike"):
        PdeSolverRunConfig(strike=0.0)


def test_config_rejects_a_tiny_grid_or_non_positive_epoch_counts() -> None:
    with pytest.raises(ValueError, match="n_space_grid_1d"):
        PdeSolverRunConfig(n_space_grid_1d=1)
    with pytest.raises(ValueError, match="pinn_epochs"):
        PdeSolverRunConfig(pinn_epochs=0)
    with pytest.raises(ValueError, match="bsde_epochs"):
        PdeSolverRunConfig(bsde_epochs=0)


def test_config_from_dict_round_trips_a_valid_recipe() -> None:
    config = PdeSolverRunConfig(n_space_grid_1d=50, pinn_epochs=5, bsde_epochs=3)
    assert PdeSolverRunConfig.from_dict(asdict(config)) == config


def test_config_from_dict_rejects_a_missing_or_extra_field() -> None:
    payload = asdict(PdeSolverRunConfig())
    del payload["strike"]
    with pytest.raises(ValueError, match="complete configuration fields"):
        PdeSolverRunConfig.from_dict(payload)
    payload = asdict(PdeSolverRunConfig())
    payload["unknown"] = 1
    with pytest.raises(ValueError, match="complete configuration fields"):
        PdeSolverRunConfig.from_dict(payload)


def test_run_pde_solver_produces_a_real_manifest_and_four_comparison_rows() -> None:
    """Small, fast config: `n_space_grid_1d`/`pinn_epochs`/`bsde_epochs`
    are all genuinely configurable (unlike `pde_solvers.benchmark.
    compute_cost_comparison`'s own fixed 1500/400 internal epoch
    counts, which this adapter does not call for exactly that reason --
    see the module docstring)."""
    config = PdeSolverRunConfig(n_space_grid_1d=20, pinn_epochs=3, bsde_epochs=2)
    result = run_pde_solver(config)
    assert result.manifest.seed == config.seed
    payload = result.evidence_bundle["pde_solver"]
    assert payload["accounting_convention"] == "pde-cost-accuracy-comparison-v1"
    assert payload["schema_version"] == 1
    methods = {row["method"] for row in payload["rows"]}
    assert methods == {"black_scholes_closed_form", "crank_nicolson_grid", "pinn", "deep_bsde"}
    assert all(row["price"] == row["price"] for row in payload["rows"])  # no NaN
    assert result.evidence_bundle["run_manifest"]["result_hash"] == result.manifest.result_hash


def test_run_pde_solver_is_deterministic_for_a_fixed_seed() -> None:
    config = PdeSolverRunConfig(n_space_grid_1d=20, pinn_epochs=3, bsde_epochs=2, seed=0)
    first = run_pde_solver(config)
    second = run_pde_solver(config)
    first_prices = [row["price"] for row in first.evidence_bundle["pde_solver"]["rows"]]
    second_prices = [row["price"] for row in second.evidence_bundle["pde_solver"]["rows"]]
    assert first_prices == second_prices
