import numpy as np
import pytest
import torch

from prometheus.hedging.comparison import HedgeComparisonSettings
from prometheus.hedging.rate_hedge import (
    RateHedgePolicyMLP,
    generate_rate_hedge_ratios,
    parameter_hash,
    rate_hedge_rollout,
    rate_policy_hash,
    train_rate_hedge,
)
from prometheus.hedging.simulate import simulate_self_financing_hedge


def model(aware=True):
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(4)
        return RateHedgePolicyMLP(rate_aware=aware, rate_center=0.03, rate_scale=0.1)


def data():
    return np.array([[100.0, 105.0, 98.0, 110.0], [100.0, 95.0, 102.0, 90.0]]), np.array(
        [[0.03, 0.10, -0.01, 0.07], [0.03, -0.02, 0.15, 0.05]]
    )


@pytest.mark.parametrize("kind", ["call", "put"])
def test_differentiable_changing_rate_accounting_matches_shared_numpy_simulator(kind):
    paths, rates = data()
    policy = model()
    loss, turnover, costs, targets = rate_hedge_rollout(
        policy,
        torch.tensor(paths, dtype=torch.float32),
        torch.tensor(rates, dtype=torch.float32),
        1 / 12,
        100.0,
        kind,
        0.005,
        8.0,
    )
    generated = generate_rate_hedge_ratios(policy, paths, rates, strike=100.0)
    assert np.array_equal(targets.detach().numpy(), generated)
    result = simulate_self_financing_hedge(
        paths, 1 / 12, 100.0, kind, 0.03, 0.005, 8.0, generated, funding_rates=rates[:, :-1]
    )
    assert np.allclose(loss.detach().numpy(), result.terminal_loss, atol=2e-5)
    assert np.allclose(turnover.detach().numpy(), result.total_turnover, atol=1e-6)
    assert np.allclose(costs.detach().numpy(), result.total_cost, atol=1e-6)
    loss.mean().backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in policy.parameters())
    assert any(torch.count_nonzero(p.grad) > 0 for p in policy.parameters())


def test_only_current_rate_changes_aware_targets_and_blind_arm_ignores_rates():
    paths = np.full((1, 4), 100.0)
    rates = np.array([[0.03, 0.08, 0.12, 0.25]])
    aware = model()
    for parameter in aware.parameters():
        torch.nn.init.zeros_(parameter)
    with torch.no_grad():
        aware.net[0].weight[0, 3] = 1.0
        aware.net[2].weight[0, 0] = 1.0
        aware.net[4].weight[0, 0] = 1.0
    actions = generate_rate_hedge_ratios(aware, paths, rates, strike=100.0)
    assert np.allclose(actions[0], np.tanh([0.0, 0.5, 0.9]))
    changed = rates.copy()
    changed[0, 2:] = [-0.01, -0.1]
    future = generate_rate_hedge_ratios(aware, paths, changed, strike=100.0)
    assert np.array_equal(actions[:, :2], future[:, :2])
    assert future[0, 2] == 0.0
    expiry = rates.copy()
    expiry[:, -1] = 100.0
    assert np.array_equal(actions, generate_rate_hedge_ratios(aware, paths, expiry, strike=100.0))
    blind = model(False)
    assert np.array_equal(
        generate_rate_hedge_ratios(blind, paths, rates, strike=100.0),
        generate_rate_hedge_ratios(blind, paths, changed, strike=100.0),
    )
    future_prices = paths.copy()
    future_prices[:, -1] = 1000.0
    assert np.array_equal(
        actions, generate_rate_hedge_ratios(aware, future_prices, rates, strike=100.0)
    )


def test_policy_hash_binds_feature_semantics_and_scaling():
    aware, blind = model(), model(False)
    assert parameter_hash(aware) == parameter_hash(blind)
    assert rate_policy_hash(aware) != rate_policy_hash(blind)
    old_hash = rate_policy_hash(aware)
    aware.rate_scale *= 2
    assert rate_policy_hash(aware) != old_hash


def test_training_is_deterministic_paired_and_preserves_global_rng():
    paths, rates = data()
    settings = HedgeComparisonSettings(n_train_paths=2, batch_size=2, n_train_epochs=4)
    state = torch.random.get_rng_state().clone()
    kwargs = dict(
        dt=1 / 12,
        initial_premium=8.0,
        rate_center=0.03,
        rate_scale=0.1,
        max_gradient_norm=1.0,
        seed=17,
    )
    aware = train_rate_hedge(paths, rates, settings, rate_aware=True, **kwargs)
    assert torch.equal(state, torch.random.get_rng_state())
    blind = train_rate_hedge(paths, rates, settings, rate_aware=False, **kwargs)
    repeated = train_rate_hedge(paths, rates, settings, rate_aware=True, **kwargs)
    assert aware.initial_parameter_hash == blind.initial_parameter_hash
    assert aware.minibatches_sha256 == blind.minibatches_sha256 == repeated.minibatches_sha256
    assert rate_policy_hash(aware.policy) == rate_policy_hash(repeated.policy)
    assert aware.diagnostics == repeated.diagnostics
    assert len(aware.diagnostics) == 4
    assert all(
        np.isfinite(d.objective) and 0 <= d.saturation_fraction <= 1 for d in aware.diagnostics
    )
    assert any(d.gradient_clipped for d in aware.diagnostics)
    assert np.max(np.abs(generate_rate_hedge_ratios(aware.policy, paths, rates, strike=100.0))) <= 1


@pytest.mark.parametrize("change", ["shape", "nan", "negative", "overflow32", "underflow32"])
def test_invalid_training_inputs_are_rejected(change):
    paths, rates = data()
    if change == "shape":
        rates = rates[:, :-1]
    elif change == "nan":
        rates[0, 0] = np.nan
    elif change == "negative":
        paths[0, 0] = -1
    elif change == "overflow32":
        paths[0, 0] = 1e100
    else:
        paths[0, 0] = 1e-100
    with pytest.raises(ValueError):
        generate_rate_hedge_ratios(model(), paths, rates, strike=100.0)


@pytest.mark.parametrize(
    "override",
    [
        {"rate_scale": 0.0},
        {"max_gradient_norm": -1.0},
        {"dt": 0.0},
        {"initial_premium": np.nan},
        {"seed": True},
    ],
)
def test_training_controls_are_validated(override):
    paths, rates = data()
    settings = HedgeComparisonSettings(n_train_paths=2, batch_size=2, n_train_epochs=2)
    kwargs = dict(
        dt=1 / 12,
        initial_premium=8.0,
        rate_center=0.03,
        rate_scale=0.1,
        max_gradient_norm=10.0,
        seed=0,
        rate_aware=True,
    )
    with pytest.raises(ValueError):
        train_rate_hedge(paths, rates, settings, **(kwargs | override))


def test_identical_rate_history_makes_blind_and_aware_training_exactly_equal():
    paths, _ = data()
    rates = np.full(paths.shape, 0.03)
    settings = HedgeComparisonSettings(n_train_paths=2, batch_size=2, n_train_epochs=3)
    kwargs = dict(
        dt=1 / 12,
        initial_premium=8.0,
        rate_center=0.03,
        rate_scale=0.1,
        max_gradient_norm=10.0,
        seed=4,
    )
    aware = train_rate_hedge(paths, rates, settings, rate_aware=True, **kwargs)
    blind = train_rate_hedge(paths, rates, settings, rate_aware=False, **kwargs)
    assert parameter_hash(aware.policy) == parameter_hash(blind.policy)
    assert aware.diagnostics == blind.diagnostics
