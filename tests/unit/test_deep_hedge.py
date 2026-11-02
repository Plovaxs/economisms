import numpy as np
import pytest

from prometheus.hedging.deep_hedge import (
    HedgePolicyMLP,
    generate_policy_hedge_ratios,
    train_deep_hedge,
)
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import historical_expected_shortfall


def _training_setup() -> dict:
    return dict(
        strike=100.0,
        maturity=1.0,
        option_type="call",
        risk_free_rate=0.05,
        cost_rate=0.005,
        initial_premium=10.0,
        cvar_alpha=0.9,
        turnover_penalty=0.001,
        n_epochs=80,
        batch_size=256,
        learning_rate=0.01,
        seed=0,
    )


def _train_paths() -> np.ndarray:
    rng = np.random.default_rng(1)
    return simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=20, n_paths=2_000, rng=rng)


def test_training_objective_decreases_over_epochs() -> None:
    cfg = _training_setup()
    dt = cfg["maturity"] / 20
    result = train_deep_hedge(_train_paths(), dt, **cfg)
    first_ten_avg = np.mean(result.objective_history[:10])
    last_ten_avg = np.mean(result.objective_history[-10:])
    assert last_ten_avg < first_ten_avg


def test_training_is_deterministic_given_a_fixed_seed() -> None:
    cfg = _training_setup()
    dt = cfg["maturity"] / 20
    paths = _train_paths()
    result_a = train_deep_hedge(paths, dt, **cfg)
    result_b = train_deep_hedge(paths, dt, **cfg)
    assert result_a.objective_history == result_b.objective_history


def test_generated_ratios_are_bounded_by_tanh_squashing() -> None:
    cfg = _training_setup()
    dt = cfg["maturity"] / 20
    result = train_deep_hedge(_train_paths(), dt, **cfg)

    rng = np.random.default_rng(99)
    test_paths = simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=20, n_paths=500, rng=rng)
    ratios = generate_policy_hedge_ratios(
        result.policy, test_paths, dt, cfg["strike"], cfg["maturity"]
    )
    assert np.all(ratios >= -1.0) and np.all(ratios <= 1.0)


def test_trained_policy_vastly_outperforms_untrained_negative_control() -> None:
    """EXP-06: an untrained (randomly initialized) policy is a required
    negative control. This does not assert the trained policy beats any
    particular baseline (e.g. delta hedging) -- the blueprint is explicit
    that such a comparison's result is not assumed in advance (section 01's
    central hypothesis) -- only that training something is better than
    training nothing, which should always hold barring a training bug."""
    cfg = _training_setup()
    dt = cfg["maturity"] / 20
    train_result = train_deep_hedge(_train_paths(), dt, **cfg)

    rng = np.random.default_rng(999)
    test_paths = simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=20, n_paths=3_000, rng=rng)

    trained_ratios = generate_policy_hedge_ratios(
        train_result.policy, test_paths, dt, cfg["strike"], cfg["maturity"]
    )
    trained_result = simulate_self_financing_hedge(
        test_paths, dt, cfg["strike"], "call", cfg["risk_free_rate"], cfg["cost_rate"],
        cfg["initial_premium"], trained_ratios,
    )

    untrained_policy = HedgePolicyMLP()
    untrained_ratios = generate_policy_hedge_ratios(
        untrained_policy, test_paths, dt, cfg["strike"], cfg["maturity"]
    )
    untrained_result = simulate_self_financing_hedge(
        test_paths, dt, cfg["strike"], "call", cfg["risk_free_rate"], cfg["cost_rate"],
        cfg["initial_premium"], untrained_ratios,
    )

    alpha = cfg["cvar_alpha"]
    trained_cvar = historical_expected_shortfall(trained_result.terminal_loss, alpha)
    untrained_cvar = historical_expected_shortfall(untrained_result.terminal_loss, alpha)
    assert trained_cvar < untrained_cvar / 2  # observed ratio in development was roughly 10x


def test_rejects_batch_size_larger_than_available_paths() -> None:
    cfg = _training_setup()
    cfg["batch_size"] = 10_000
    dt = cfg["maturity"] / 20
    with pytest.raises(ValueError):
        train_deep_hedge(_train_paths(), dt, **cfg)
