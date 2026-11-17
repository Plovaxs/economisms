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
            "The PROMETHEUS-X final-project addendum (ECONOSIM-X): point-in-time-safe "
            "feature/label eligibility gating, classical persistence/AR(p)/VAR(p) "
            "forecasting baselines, and a real World Bank Open Data ingestion "
            "(PR-055/056/060)",
            "RECESSIONNET recession classifier (base rate/logistic/classical-MLP/"
            "hybrid-quantum, validation-selected early stopping) and the "
            "`prometheus.quantum` differentiable circuit layer it introduced "
            "(PR-139, corrected PR-141/142), independently re-grounded on a real "
            "Kaggle macro snapshot (GDP/unemployment-claims/Fed-funds/M2/NASDAQ, "
            "PR-145) and a real US Treasury yield-curve feature (PR-178)",
            "Q-MACRO quantum-vs-classical regression benchmark (PR-143) and "
            "MACROCORE's classical AR/VAR/persistence baselines extended to a "
            "shared-Transformer-encoder multihorizon GDP/rate/unemployment "
            "forecaster benchmarked against them (PR-183)",
            "INFLATIONCAST mixed-frequency CPI nowcasting against real BLS CPI "
            "data, with an uncertainty-calibrated recurrent model and a real "
            "browser dashboard view (PR-173)",
            "CONTAGION-GNN interbank-contagion graph classifier, VOLTERRA-GEN a "
            "labeled conditional scenario generator, POLICYLAB-RL a constrained-"
            "PPO-vs-Taylor-rule policy benchmark, and a shared-vs-independent "
            "multi-task encoder ablation (PR-182)",
            "PDE solvers (PINN/deep BSDE), multi-agent RL household/firm policy "
            "training, and a REINFORCE hedging agent each newly orchestrated as a "
            "submittable job kind, alongside a unified React/TypeScript frontend "
            "and JSON dashboard views over all of the above (16 job kinds total, "
            "PR-174)",
            "A frozen, dated final-project hypotheses document and a final paper "
            "assembling every frozen and disclosed null/negative result "
            "(PR-172/179)",
            "A real-vs-known-fixed CI pipeline (eight genuine bugs found and "
            "fixed by actually running it, not just editing it -- a YAML "
            "syntax error, a missing lockfile extra, a wheel-install path "
            "assumption, a numpy-version-specific type error, and three "
            "distinct classes of cross-machine floating-point/timing "
            "non-determinism), and a `prometheus.webgateway` reverse-proxy "
            "that serves the existing React frontend's real build output "
            "plus Docker packaging for the whole stack, independently "
            "verified on a real Docker-capable CI runner (PR-185/187)",
            "`prometheus.trading_readiness`: real, tested EXT-* mechanisms "
            "(a mock broker, a pre-trade risk gate, a one-way kill switch, "
            "position/cash reconciliation, a 5-distinct-role arming gate) "
            "run only against an in-memory mock broker that makes no real "
            "network call -- the institutional half of each EXT-* item "
            "(a real broker agreement, real named officers) remains "
            "exactly as unmet as before this package existed (PR-188)",
        ),
        scope_prohibited=(
            "Live trading, order routing, or any connection to a brokerage",
            "Live or real-time market data feeds, and any real client or "
            "portfolio holdings -- the historical, licensed macro/market "
            "datasets used for offline research and backtesting (World Bank, "
            "Kenneth French factors, a Kaggle FRED mirror, BLS CPI, the US "
            "Treasury yield curve; see scope_enabled) are a disclosed, narrow "
            "exception to this, never live or client data",
            "Any claim of regulatory, model-risk, or security certification",
        ),
        evidence_index=("CHECKLIST_STATUS.md", "README.md"),
        open_findings=(
            "No independent review of any module (MGR-07 not satisfied)",
            "The blueprint's 374-item checklist remains formally NOT VERIFIED "
            "pending independent review, per its own protocol; 356 of 374 items "
            "carry a repository evidence note tying them to a real test or "
            "finding, 18 do not (see the next finding)",
            "Model-lifecycle provenance (RunManifest code/data hashes, model_id) "
            "is now populated by real trained models (FP-20); independent review, "
            "model-risk sign-off, and data-governance/compliance processes remain "
            "unimplemented regardless (MGR-07/14, CMP-04/06/07/08, PRV-06/10)",
            "The original econosim reference scenarios still use synthetic "
            "single-asset GBM with response rules that are not empirically "
            "calibrated; RECESSIONNET/Q-MACRO/INFLATIONCAST/MACROCORE separately "
            "train against real licensed data, but neither track has been "
            "independently reviewed",
            "Black-Scholes marks and conditional risk freeze the closing rate; no joint "
            "stochastic-rate Q valuation or full dynamic-policy risk forecast is implemented",
            "The 18 original-blueprint items with no repository evidence note "
            "are not closeable by further code in this project's own context: "
            "DAT-02/03 (FRED-MD/QD, ALFRED) are unreachable from this "
            "environment; SEC-14 (an independent penetration test) cannot be "
            "self-performed; PRV-06/10, MGR-07/14, CMP-04/06/07/08 require real "
            "external legal/regulatory/compliance review this solo research "
            "project has no institution to provide; and EXT-02/09 each ask for "
            "a one-time external deliverable (a named entity's regulatory "
            "opinion; independent model validation) no code can produce. "
            "`prometheus.trading_readiness` (PR-188) closes the MECHANISM half "
            "of EXT-03/04/05/06/12 -- a real, tested control exists for each -- "
            "but the INSTITUTIONAL half of every EXT-* item (a real broker "
            "agreement, real named officers, real capital) remains exactly as "
            "unmet as the live-trading deployment scope_prohibited already "
            "rules out; see CHECKLIST_STATUS.md's EXT-* rows for exactly which "
            "half of each is, and is not, met",
        ),
        scientific_approval=None,
        security_ops_approval=None,
        legal_compliance_assessment=None,
        decision="NO-GO",
        decided_at=date.today(),
        sunset_date=None,
    )
