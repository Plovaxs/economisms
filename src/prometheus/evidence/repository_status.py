"""Builders for this repository's own, real evidence artifacts.

Not a demo: current_repository_gate_report() reflects this repository's
actual review state (no independent reviewer, no security/ops sign-off),
and build_deep_hedge_model_card() cards the one trained model that exists
in this repository -- the PR-007 MLP hedging policy -- with real, specific
limitations rather than placeholder text.
"""

from __future__ import annotations

import hashlib
from datetime import date

import torch

from prometheus.evidence.gate_report import GateDecisionForm
from prometheus.evidence.model_card import ModelCard
from prometheus.hedging.deep_hedge import HedgePolicyMLP


def policy_content_hash(policy: HedgePolicyMLP) -> str:
    """A content hash of a trained policy's parameters -- independent of
    any filesystem path, so it stays meaningful whether or not the policy
    is ever saved to disk."""
    hasher = hashlib.sha256()
    for name, tensor in sorted(policy.state_dict().items()):
        hasher.update(name.encode("utf-8"))
        hasher.update(tensor.detach().cpu().numpy().tobytes())
    return hasher.hexdigest()


def build_deep_hedge_model_card(
    policy: HedgePolicyMLP,
    n_train_paths: int,
    train_seed: int,
    test_cvar: float,
    test_mean_loss: float,
    cvar_alpha: float,
) -> ModelCard:
    return ModelCard(
        model_id="prometheus-hedging-mlp-v0",
        model_type=(
            "Feedforward MLP hedging policy (3 inputs, 2 hidden layers of 32 "
            "units, tanh-bounded scalar output)"
        ),
        framework=f"PyTorch {torch.__version__}",
        version="0.1.0",
        license="MIT",
        content_hash=policy_content_hash(policy),
        intended_use=(
            "Research demonstration of CVaR-based deep hedging (Buehler et al. "
            "2019) on synthetic single-asset European-option GBM paths. Not "
            "calibrated to, or validated against, real market data."
        ),
        prohibited_use=(
            "Any live trading, order routing, or real-money hedging decision. Any "
            "use outside the single-asset European vanilla call/put GBM setting it "
            "was trained on (not evaluated under Heston, jumps, multiple assets, or "
            "real market microstructure)."
        ),
        input_schema_summary=(
            "Per path per step: (log(S_t / strike), fraction of time-to-maturity "
            "remaining in [0, 1], previous holding in [-1, 1]), each a float32 "
            "scalar. Output: a tanh-bounded target holding in [-1, 1]."
        ),
        training_data_summary=(
            f"{n_train_paths} synthetic GBM paths (prometheus.stochastica.gbm), "
            f"physical-measure, seed={train_seed}; no empirical/historical data."
        ),
        primary_metrics={
            f"test_cvar_{int(cvar_alpha * 100)}": test_cvar,
            "test_mean_terminal_loss": test_mean_loss,
        },
        metric_uncertainty_note=(
            "Single training run, single held-out test-seed point estimate. See "
            "prometheus.experiments.hedge_benchmark for a multi-seed, paired-"
            "bootstrap-CI comparison against the delta baseline -- at the one "
            "configuration explored during development, the two were "
            "statistically indistinguishable."
        ),
        failure_modes=(
            "Not evaluated out-of-distribution: different volatility regime, jump "
            "risk, or real market microstructure.",
            "Trained and evaluated with a single random seed per call; "
            "objective_history shows convergence on that one training seed, not "
            "across seeds.",
            "No formal verification that the tanh action bound [-1, 1] is "
            "appropriate outside a single-share-per-option vanilla setting.",
        ),
        independent_reviewer=None,
        approval_status="NOT REVIEWED",
        created_at=date.today(),
    )


def current_repository_gate_report() -> GateDecisionForm:
    """This repository's actual, current gate status -- generated from
    code, not hand-typed, and matching the blueprint's own section 19
    verdict: NO-GO, because no independent review of anything here has
    happened yet."""
    return GateDecisionForm(
        gate="R0",
        artifact_version="0.1.0",
        scope_enabled=(
            "Local in-memory double-entry ledger simulation (PR-001/002)",
            "Deterministic macro time engine: calendar, seeds, point-in-time "
            "data, shocks (PR-003)",
            "Classical GBM/Heston and macro-conditioned (non-neural) path "
            "simulation (PR-004/009)",
            "Black-Scholes/Monte Carlo pricing (PR-005)",
            "Historical/parametric VaR and Expected Shortfall (PR-006)",
            "Delta and CVaR-trained MLP hedge simulation against synthetic "
            "paths (PR-007)",
            "A first paired-bootstrap research benchmark (PR-008)",
        ),
        scope_prohibited=(
            "Live trading, order routing, or any connection to a brokerage",
            "Use of real (non-synthetic) market or portfolio data",
            "Any claim of regulatory, model-risk, or security certification",
        ),
        evidence_index=("CHECKLIST_STATUS.md", "README.md"),
        open_findings=(
            "No independent review of any module (MGR-07 not satisfied)",
            "Of the blueprint's 374-item checklist, roughly 9 PRs' worth of IDs "
            "are evidenced by passing tests; the large majority remain NOT "
            "VERIFIED (see CHECKLIST_STATUS.md for the exact list)",
            "No security, MLOps, data-governance, or compliance control "
            "implemented",
            "No economy/market/hedge subsystem is wired to another at the "
            "orchestration level; each is called standalone",
        ),
        scientific_approval=None,
        security_ops_approval=None,
        legal_compliance_assessment=None,
        decision="NO-GO",
        decided_at=date.today(),
        sunset_date=None,
    )
