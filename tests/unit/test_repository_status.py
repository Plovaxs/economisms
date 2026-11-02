import numpy as np

from prometheus.evidence.repository_status import (
    build_deep_hedge_model_card,
    current_repository_gate_report,
    policy_content_hash,
)
from prometheus.hedging.deep_hedge import HedgePolicyMLP, train_deep_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths


def test_current_repository_gate_report_is_no_go_with_no_approvers() -> None:
    """This test is meant to start failing the moment this repository
    actually earns an independent review -- at which point it should be
    updated to reflect the new, real state, not patched to keep passing."""
    report = current_repository_gate_report()
    assert report.decision == "NO-GO"
    assert report.scientific_approval is None
    assert report.security_ops_approval is None
    assert len(report.open_findings) > 0
    assert len(report.scope_prohibited) > 0


def test_policy_content_hash_is_deterministic_for_identical_weights() -> None:
    policy_a = HedgePolicyMLP()
    policy_b = HedgePolicyMLP()
    policy_b.load_state_dict(policy_a.state_dict())
    assert policy_content_hash(policy_a) == policy_content_hash(policy_b)


def test_policy_content_hash_differs_for_different_weights() -> None:
    policy_a = HedgePolicyMLP()
    policy_b = HedgePolicyMLP()  # different random init
    assert policy_content_hash(policy_a) != policy_content_hash(policy_b)


def test_build_deep_hedge_model_card_for_a_trained_policy() -> None:
    dt = 1.0 / 20
    rng = np.random.default_rng(1)
    train_paths = simulate_gbm_paths(100.0, 0.08, 0.2, 1.0, n_steps=20, n_paths=500, rng=rng)
    result = train_deep_hedge(
        train_paths,
        dt,
        strike=100.0,
        maturity=1.0,
        option_type="call",
        risk_free_rate=0.05,
        cost_rate=0.005,
        initial_premium=10.0,
        n_epochs=10,
        batch_size=128,
        seed=0,
    )

    card = build_deep_hedge_model_card(
        result.policy,
        n_train_paths=500,
        train_seed=0,
        test_cvar=4.1,
        test_mean_loss=0.5,
        cvar_alpha=0.9,
    )

    assert card.approval_status == "NOT REVIEWED"
    assert card.independent_reviewer is None
    assert card.content_hash == policy_content_hash(result.policy)
    assert "test_cvar_90" in card.primary_metrics
    assert "live trading" in card.prohibited_use.lower()
