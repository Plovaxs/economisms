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
            "bootstrap-CI comparison against the delta baseline. Historical "
            "numbers from before PR-015 must be rerun after its financing "
            "correction; no policy superiority is assumed."
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
            "Deterministic macro time engine: calendar, seeds, point-in-time data, shocks (PR-003)",
            "Classical GBM/Heston and macro-conditioned (non-neural) path simulation (PR-004/009)",
            "Black-Scholes/Monte Carlo pricing (PR-005)",
            "Historical/parametric VaR and Expected Shortfall (PR-006)",
            "Delta and CVaR-trained MLP hedge simulation against synthetic paths (PR-007)",
            "A first paired-bootstrap research benchmark (PR-008)",
            "End-to-end demonstration and monthly StepHooks scenario with online "
            "delta/MLP hedging, conditional portfolio risk and evidence export (PR-011/014/015)",
            "Government taxes/transfers/bonds and a scalar central-bank policy-rate agent (PR-012)",
            "Single-firm labor/goods quantity clearing with ledger settlement (PR-013)",
            "Reproducible benchmark/retraining stress recipes and exact artifact "
            "replay (PR-016/017)",
            "Exact budget-feasible price discovery, inventory and atomic market "
            "settlement (PR-018)",
            "Publication-lagged price/output policy feedback coupled to market and hedge financing "
            "with explicit opening/closing rate timing (PR-019)",
            "Crossed retraining/shared macro-market banks across publication, payroll and "
            "supply-shock scenarios with conditional-CVaR diagnostics (PR-020)",
            "Matched current-rate feature ablation with independent macro training banks, "
            "variable-rate differentiable accounting and optimization diagnostics (PR-021)",
            "Synthetic instrument calibration, American/forward pricing and mixed position "
            "valuation; portfolio, covariance, factor and network-risk modules (PR-022..040)",
            "Ledger-backed central-bank/interbank operations, causal risk circuit breaker "
            "and bank interest/write-off primitives (PR-026..043)",
            "Empirical macro/market-mixture CVaR with paired nested resampling and "
            "retained terminal-loss provenance (PR-044)",
            "Detached whole-artifact checksum snapshots, strict metadata/fingerprint "
            "validation, offline audit and complete 374-item traceability register (PR-045)",
            "Allowlisted typed recipes, bounded local SQLite job queue, fenced Linux workers "
            "and no-clobber quota-controlled artifact publication (PR-046)",
            "Versioned authenticated ASGI research-job API, owner-derived read/write scopes, "
            "bounded request admission, readiness, OpenAPI and typed SDK (PR-047)",
            "Hash-locked CPU dependency/build profiles, two-snapshot wheel rebuild checks, "
            "dependency SBOM and encrypted verified local snapshot/restore with lease fencing "
            "(PR-048; no container/offsite/production acceptance)",
        ),
        scope_prohibited=(
            "Live trading, order routing, or any connection to a brokerage",
            "Use of real (non-synthetic) market or portfolio data",
            "Any claim of regulatory, model-risk, or security certification",
        ),
        evidence_index=("CHECKLIST_STATUS.md", "README.md"),
        open_findings=(
            "No independent review of any module (MGR-07 not satisfied)",
            "The blueprint's 374-item checklist remains NOT VERIFIED pending "
            "review; CHECKLIST_STATUS.md distinguishes test evidence from full acceptance",
            "A basic lint/type/test CI workflow exists; deployment security, model "
            "lifecycle, data-governance and compliance controls remain unimplemented",
            "Reference scenarios use synthetic single-asset GBM and separate economic/hedge "
            "balance sheets; price and policy response rules are not empirically calibrated",
            "Black-Scholes marks and conditional risk freeze the closing rate; no joint "
            "stochastic-rate Q valuation or full dynamic-policy risk forecast is implemented",
        ),
        scientific_approval=None,
        security_ops_approval=None,
        legal_compliance_assessment=None,
        decision="NO-GO",
        decided_at=date.today(),
        sunset_date=None,
    )
