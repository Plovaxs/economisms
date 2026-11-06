# PR-045 local validation — 2026-11-03

Scope: complete-artifact checksum snapshots, strict evidence contracts,
offline audit, model-card/training fingerprint binding and full-blueprint
traceability. Work remains local, uncommitted and not independently reviewed.
This slice does not claim the whole blueprint or industrial readiness is
complete. The full 374-item scope remains in the implementation plan.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 85 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 1,173 passed in 34.53 seconds; 97% line coverage |
| `git diff --check` | Passed |
| Default twelve-month sealed example | Valid; all twelve steps completed |
| Strict sealed replay | Exact computational result; no runtime changes |
| Offline audit with supplied content pin | Checksum/schema/fingerprint audit passed without numerical replay |
| Legacy artifact audit with explicit opt-in | Passed; correctly reported `legacy_unsealed` |
| Complete requirement register | 374 unique items, 29 categories, exact source PDF/checklist inputs, valid seal |

Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1 and PyTorch 2.15.0+cpu were
observed. Reference, replay and final local package source share this digest:

```text
e516a871c319c504a3b6043217d53dafeac24bb899d962b6925138b462006da4
```

## Reproduction

```bash
.venv/bin/python -m prometheus.orchestration.monetary_run \
  --output evidence/integrity_reference.json
.venv/bin/python -m prometheus.evidence.verify evidence/integrity_reference.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/integrity_reference.json --require-integrity \
  --output evidence/integrity_replay.json
.venv/bin/python -m prometheus.evidence.verify \
  evidence/monetary_reference.json --allow-legacy
.venv/bin/python -m prometheus.evidence.requirements \
  --pdf docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf \
  --output docs/implementation/blueprint_register.json
```

The twelve-month computational result retains its historical identity:

```text
69743a65c3ec661ed793d670d3880ccdf453325b5ff192199f58890f2d482b98
```

The recorded complete-reference content pin is:

```text
e729fcab5904ce1862c7a6c1c1ed9b2eb0064435c0a2a76715137ee2ad8c658c
```

Unlike the computational result hash, complete-artifact content includes
run ID/time, model cards, gate, runtime and replay metadata. A new run is
expected to have a different content pin even when its computational result
matches. The recorded reference can be checked against its specific pin:

```bash
.venv/bin/python -m prometheus.evidence.verify evidence/integrity_reference.json \
  --expected-content-sha256 e729fcab5904ce1862c7a6c1c1ed9b2eb0064435c0a2a76715137ee2ad8c658c
```

The example pin was observed locally for validation. The tool does not
establish that an externally supplied pin is independently trustworthy.
The recorded audit outputs are `integrity_audit.json` and
`legacy_audit_pr045.json` in this directory.

## Integrity and metadata contract

New exports normalize a detached JSON snapshot, then validate and seal it
before creating any temporary output. All top-level content except the
seal itself is hashed. Existing invalid/stale seals are rejected instead of
silently recomputed. Caller mutations to nested objects cannot alter the
sealed snapshot. Atomic file replacement and cleanup remain in place.

The seal records schema version, SHA-256 algorithm and explicit Python
sorted-key/default-separator JSON canonicalization. It is not a signature,
authorship certificate or cross-language RFC canonical-JSON claim. Removing
a seal causes strict audit/replay to fail. Legacy access is explicit in the
new auditor; compatible replay reports whether input was sealed or legacy.

Shared strict JSON reading rejects duplicate keys, NaN/Infinity tokens,
numeric exponent overflow such as `1e9999`, and key collisions introduced
by JSON snapshot normalization. Metadata validation checks exact record
fields, dates/timezones, finite named metrics, provenance hashes and
dependency-version structure. Model-card fingerprints/counts must match
declared computational training metadata. Failed experiments cannot carry
successful model cards.

Direct model-card construction rejects boolean/non-finite/overflowing
metrics and conditional/approved status without a named reviewer. Gate
construction rejects boolean approver substitutes and sunset dates before
the decision. Names and metadata do not independently authenticate a review
or grant approval; the current repository gate stays NO-GO.

Offline audit reports its actual scope: checksum, metadata schema and
declared fingerprint consistency. It neither trains/simulates nor proves
the numerical conclusions. Importing the auditor does not load Torch or
training modules. Actual replay still reconstructs typed recipes and runs
training/simulation, detecting fabricated results even after explicit
unsigned rehashing.

## Full-blueprint scope registry

The supplied Downloads PDF and repository PDF match SHA-256:

```text
6745f7dd2b027378fbafbd9a870b84d86489932d2068fa10abf0d604ef3bac75
```

The generated registry retains all 374 requirements across 29 categories:
362 research/enterprise items and 12 separately gated external/live items.
Every item includes its requirement text, acceptance criterion, source PDF
page/layout rows, category/track and unreviewed repository-note links.
Duplicate IDs, missing requirements and unexpected cardinality fail the
parser. Input PDF/checklist hashes and the registry seal are retained.

There are 91 IDs with repository notes and 283 without notes. Note presence
does not establish completion: partial evidence and repeated references
remain partial/unreviewed. All 374 acceptance statuses stay NOT VERIFIED;
owners/reviewers are not invented. The implementation plan retains all
categories and distinguishes remaining engineering from actual human
review/authorization requirements.

Tests reconstruct the entire tracked inventory and compare it to current
PDF/checklist inputs. CI configuration now declares `poppler-utils`, the
system dependency used for extraction. This workflow change was prepared
locally; no remote CI execution is claimed. Raw extracted-text checksums
are diagnostic because Poppler formatting versions can differ; parsed
inventory and input hashes are checked for drift.

## Verification coverage and limits

Tests alter every artifact section, reject malformed seals and externally
pinned-content mismatches, and confirm old destinations survive failures.
All existing generic replay fixtures now also exercise strict sealed
replay. Explicit legacy fixtures preserve historical computational-contract
tests. Model-card and gate tests exercise malformed fields, fingerprint
mismatches, missing/duplicate cards, invalid dates, boolean approvals and
non-finite metric values. Existing independent numerical and economic tests
remain part of the complete project suite.

No dependency lock, signed artifact identity, external immutable storage,
production authorization, complete learned-model/data/API/operations stack
or independent scientific acceptance is claimed. Those requirements remain
visible in the full-scope register and implementation plan. **R0 remains
NO-GO; the user's full-blueprint objective remains unfinished.**
