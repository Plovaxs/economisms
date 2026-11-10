# Architecture decision records

GOV-05: create an architecture decision record process; acceptance —
"at least one reviewed ADR per major scientific interface."

## The process

An ADR is written when a design choice (a) could reasonably have gone
another way, (b) affects a "major scientific interface" (a subsystem
boundary another part of the codebase depends on), and (c) has a real,
checkable consequence (a test, a measured number) backing the choice
made. Each ADR below is extracted from a real module's own docstring
that already stated the rationale at the time the decision was made —
not reconstructed after the fact from memory.

**Honest status**: every ADR below is real and dated. **None has been
independently reviewed by a second person** — this is a single-
maintainer repository (`CONTRIBUTING.md`). GOV-05 is marked **partial**:
the ADR process and real records exist; the "reviewed" half does not.

## ADR-001: Discretization scheme for Heston stochastic volatility

**Status**: Accepted (PR that introduced `stochastica.heston`).
**Decision**: log-Euler on price (keeps `S` positive by construction)
combined with full-truncation Euler on variance (Lord, Koekkoek & van
Dijk, 2010).
**Alternatives considered**: Andersen's QE scheme (more accurate at
large time steps).
**Consequence, measured**: fitted weak-convergence order ≈ 0.91 against
the closed-form reference price across a step-halving sweep (theory
predicts ≈ 1), independently re-verified in this session. See
`docs/MATHEMATICAL_APPENDIX.md § Heston stochastic volatility`.
**Rationale**: a simple, well-understood, positivity-preserving scheme
was chosen over a more accurate but more complex one; the Feller-ratio
diagnostic in `stochastica.heston` itself tells a caller when this
scheme's bias is likely to matter, rather than hiding the tradeoff.

## ADR-002: FRED as the Treasury yield-curve data source, not home.treasury.gov

**Status**: Accepted (PR-146).
**Decision**: source US Treasury CMT yields from FRED's public
`fredgraph.csv` export rather than `home.treasury.gov` directly.
**Alternatives considered**: `home.treasury.gov` (the nominally primary
source).
**Consequence, measured**: `home.treasury.gov` timed out repeatedly
from this environment's network, confirmed by direct `urllib` probe
before any connector code was written; FRED's republication is
confirmed reachable and is the same underlying Federal Reserve H.15
release, not a secondary reseller.
**Rationale**: network-reachability-first discipline (see
`CONTRIBUTING.md`) — verify a source is actually reachable from the
real build environment before committing to it, and disclose a
substitution explicitly rather than silently.

## ADR-003: Small, CPU-only models over larger/deep ones across every ML subsystem

**Status**: Accepted (recurring, from `recessionnet` through `marl`).
**Decision**: every learned model in this repository (RECESSIONNET,
Q-MACRO, the hedging MLP, `neural_sde`, `pde_solvers`' PINN/deep-BSDE,
`marl`'s PPO policies) uses a small hidden size (~16-32), CPU-only
training, completing in low tens of seconds.
**Alternatives considered**: larger architectures, GPU training.
**Consequence, measured**: repeatedly, a small/simple baseline matches
or beats a larger learned model on this project's actual (small, real)
datasets — PR-142/143/145/150's real "no significant difference" or
"simpler model wins" findings. `pde_solvers`' classical grid solver
beating both neural methods on speed AND accuracy in 1D is the same
pattern again.
**Rationale**: matching model capacity to real, honestly small
datasets, rather than defaulting to a larger architecture that would
either overfit or need infrastructure (GPU) this environment doesn't
reliably have.

## ADR-004: Composition over reinvention for shared primitives

**Status**: Accepted (project-wide convention, `CONTRIBUTING.md`).
**Decision**: a new module reuses an existing primitive
(`experiments.manifest.compute_result_hash` for content-addressing,
`evidence.alert_routing` for severity/escalation, `core.ledger` for
all double-entry accounting, `data_ingestion.transport.HttpTransport`
for all network calls) rather than writing a parallel one with
slightly different shape.
**Consequence, measured**: `marl.feasibility`'s action-projection layer
composes with, rather than duplicates, the ledger's own
`InsufficientFundsError`/`CreditLimitExceededError` enforcement;
`data_ingestion.egress_allowlist`'s denial path reuses
`evidence.alert_routing` rather than inventing a second alerting
scheme. Both are named explicitly in their own module docstrings as a
deliberate choice.
**Rationale**: a single, well-tested primitive is easier to trust and
audit than N near-identical ones; this is stated as a standing rule in
`CONTRIBUTING.md § Code style`, not just an informal habit.
