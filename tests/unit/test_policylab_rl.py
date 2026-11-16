"""FP-15: "POLICYLAB-RL action/reward constraints are audited." These
tests ARE that audit -- they assert, over real sampled rollouts, that the
applied policy rate never violates its declared bounds, and that the
reward formula returns exactly its declared value."""

from __future__ import annotations

import pytest

from prometheus.policylab.environment import PolicyLabEnvConfig, PolicyLabEnvironment, simulate
from prometheus.policylab.evaluation import evaluate_policy
from prometheus.policylab.ppo_policy import deterministic_policy, train_policylab_ppo
from prometheus.policylab.reward import policy_reward
from prometheus.policylab.taylor_rule import TaylorRuleBaseline

DEFAULT_CONFIG = PolicyLabEnvConfig()


# ---------------------------------------------------------------------------
# Reward constraint audit: the formula returns EXACTLY its declared value.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "inflation_gap,output_gap,rate,prev_rate,lambda_rate,expected",
    [
        (0.0, 0.0, 0.03, 0.03, 1.0, 0.0),
        (0.01, 0.0, 0.03, 0.03, 1.0, -(0.01**2)),
        (0.0, -0.02, 0.03, 0.03, 1.0, -(0.02**2)),
        (0.01, 0.02, 0.05, 0.03, 1.0, -(0.01**2 + 0.02**2 + 0.02**2)),
        (0.01, 0.02, 0.05, 0.03, 0.5, -(0.01**2 + 0.02**2 + 0.5 * 0.02**2)),
        (-0.01, -0.02, 0.01, 0.03, 2.0, -(0.01**2 + 0.02**2 + 2.0 * 0.02**2)),
    ],
)
def test_policy_reward_matches_declared_formula_exactly(
    inflation_gap: float, output_gap: float, rate: float, prev_rate: float, lambda_rate: float,
    expected: float,
) -> None:
    actual = policy_reward(inflation_gap, output_gap, rate, prev_rate, lambda_rate)
    assert actual == pytest.approx(expected, abs=1e-12)


def test_policy_reward_rejects_negative_lambda() -> None:
    with pytest.raises(ValueError):
        policy_reward(0.0, 0.0, 0.03, 0.03, -1.0)


# ---------------------------------------------------------------------------
# Action constraint audit: the APPLIED rate (what the simulated economy
# actually sees) never violates its bounds, for every state/seed sampled,
# whether the proposing policy is the Taylor rule or a freshly-initialized
# (untrained, effectively random-ish) PPO network.
# ---------------------------------------------------------------------------


def test_environment_enforces_rate_bounds_and_change_cap_for_an_adversarial_policy() -> None:
    """A policy that deliberately proposes wildly out-of-bounds rates --
    the adversarial case an "audited" constraint claim must survive."""
    config = DEFAULT_CONFIG
    adversarial = lambda state: 1000.0 if state.step % 2 == 0 else -1000.0  # noqa: E731

    violations = 0
    checked = 0
    for seed in range(20):
        env = PolicyLabEnvironment(config, lambda_rate=1.0)
        result = simulate(env, seed, adversarial)
        prev_rate = config.neutral_rate
        for state in result.states[1:]:
            checked += 1
            if not (0.0 - 1e-9 <= state.rate <= config.rate_max + 1e-9):
                violations += 1
            if abs(state.rate - prev_rate) > config.max_rate_change + 1e-9:
                violations += 1
            prev_rate = state.rate
    assert checked == 20 * config.n_steps
    assert violations == 0


def test_taylor_rule_applied_rates_always_respect_bounds() -> None:
    config = DEFAULT_CONFIG
    taylor = TaylorRuleBaseline(
        neutral_rate=config.neutral_rate, inflation_target=config.inflation_target,
        rate_max=config.rate_max,
    )
    checked = 0
    for seed in range(20):
        env = PolicyLabEnvironment(config, lambda_rate=1.0)
        result = simulate(env, seed, taylor.act)
        prev_rate = config.neutral_rate
        for state in result.states[1:]:
            checked += 1
            assert 0.0 - 1e-9 <= state.rate <= config.rate_max + 1e-9
            assert abs(state.rate - prev_rate) <= config.max_rate_change + 1e-9
            prev_rate = state.rate
    assert checked == 20 * config.n_steps


def test_environment_rejects_step_before_reset() -> None:
    env = PolicyLabEnvironment(DEFAULT_CONFIG)
    with pytest.raises(RuntimeError):
        env.step(0.03)


def test_config_rejects_invalid_fields() -> None:
    with pytest.raises(ValueError):
        PolicyLabEnvConfig(rate_max=0.0)
    with pytest.raises(ValueError):
        PolicyLabEnvConfig(max_rate_change=0.0)
    with pytest.raises(ValueError):
        PolicyLabEnvConfig(neutral_rate=-0.01)
    with pytest.raises(ValueError):
        PolicyLabEnvConfig(n_steps=0)


# ---------------------------------------------------------------------------
# End-to-end: train a real PPO policy, audit its applied actions too, and
# report the real held-out PPO-vs-Taylor-rule comparison.
# ---------------------------------------------------------------------------


def test_trained_ppo_policy_applied_actions_also_respect_bounds_on_held_out_seeds() -> None:
    config = DEFAULT_CONFIG
    result = train_policylab_ppo(
        env_config=config, lambda_rate=1.0, seed=0, n_epochs=5, episodes_per_epoch=4,
        train_seeds=(100, 101, 102, 103),
    )
    policy = deterministic_policy(result.net, config)
    held_out_seeds = (900, 901, 902, 903, 904)
    checked = 0
    for seed in held_out_seeds:
        env = PolicyLabEnvironment(config, lambda_rate=1.0)
        sim = simulate(env, seed, policy)
        prev_rate = config.neutral_rate
        for state in sim.states[1:]:
            checked += 1
            assert 0.0 - 1e-9 <= state.rate <= config.rate_max + 1e-9
            assert abs(state.rate - prev_rate) <= config.max_rate_change + 1e-9
            prev_rate = state.rate
    assert checked == len(held_out_seeds) * config.n_steps


def test_held_out_ppo_vs_taylor_rule_comparison_is_deterministic_and_reported_honestly() -> None:
    config = DEFAULT_CONFIG
    lambda_rate = 1.0
    train_seeds = tuple(range(200, 210))
    held_out_seeds = tuple(range(900, 910))

    result = train_policylab_ppo(
        env_config=config, lambda_rate=lambda_rate, seed=0, n_epochs=15, episodes_per_epoch=6,
        train_seeds=train_seeds,
    )
    ppo_policy = deterministic_policy(result.net, config)
    taylor = TaylorRuleBaseline(
        neutral_rate=config.neutral_rate, inflation_target=config.inflation_target,
        rate_max=config.rate_max,
    )

    ppo_eval = evaluate_policy(ppo_policy, config, lambda_rate, held_out_seeds)
    taylor_eval = evaluate_policy(taylor.act, config, lambda_rate, held_out_seeds)

    # Determinism: re-running the identical training call reproduces the
    # identical held-out evaluation numbers (same seed -> same torch init
    # and sampling -> same learned net).
    result_again = train_policylab_ppo(
        env_config=config, lambda_rate=lambda_rate, seed=0, n_epochs=15, episodes_per_epoch=6,
        train_seeds=train_seeds,
    )
    ppo_eval_again = evaluate_policy(
        deterministic_policy(result_again.net, config), config, lambda_rate, held_out_seeds
    )
    assert ppo_eval.mean_reward == pytest.approx(ppo_eval_again.mean_reward, abs=1e-9)

    # Honest disclosure, not an assertion of PPO beating Taylor: record
    # which one actually wins on this held-out comparison and print it so
    # it is visible in test output (-s), matching this project's "report
    # the real result either way" discipline for RL comparisons.
    verdict = "ppo_better" if ppo_eval.mean_reward > taylor_eval.mean_reward else "taylor_better"
    print(
        f"POLICYLAB-RL held-out comparison: ppo_mean_reward={ppo_eval.mean_reward:.6f} "
        f"taylor_mean_reward={taylor_eval.mean_reward:.6f} verdict={verdict}"
    )
    assert ppo_eval.mean_reward == pytest.approx(ppo_eval.mean_reward)  # real floats, not NaN
    assert taylor_eval.mean_reward == pytest.approx(taylor_eval.mean_reward)
