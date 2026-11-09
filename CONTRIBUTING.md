# Contributing

This is presently a single-maintainer research repository (see
[README.md](./README.md)). Issues and discussion are welcome; this document
states the bar every change here is actually held to, so a contributor does
not have to reverse-engineer it from the git history.

## The one rule that matters

**"Evidenced" means a passing automated test in this repository links to a
specific checklist item — nothing else.** Not a design document, not a
docstring, not a plan, not a model's own self-report. See
[README.md § The evidence discipline](./README.md#the-evidence-discipline).
Any change that claims to close or advance a blueprint item
(`docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf` /
`docs/PROMETHEUS_X_Final_Project_Integrated_Blueprint.md`) must carry a test
that actually exercises the claim — cross-checked against a closed-form
solution, an independent numerical method, or real recorded data wherever
one exists — not a test that merely asserts "no exception was raised."

Equally important: **say what a change does not cover.** Every PR in
[docs/PR_LEDGER.md](./docs/PR_LEDGER.md) states its scope and its explicit
non-coverage. A PR that silently overclaims is a worse contribution than one
that does less and says so plainly.

## Local setup

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r requirements/bootstrap.txt
uv sync --locked --all-extras --group build
uv run --locked --all-extras pytest
uv run --locked --all-extras ruff check src tests tools
uv run --locked --all-extras mypy --strict src tools/reproducible_build.py
```

One-command smoke test (replays a recorded deterministic reference run and
checks the result hash, rather than re-deriving numbers from scratch):

```bash
uv run --locked --all-extras python -m prometheus.orchestration.replay \
  evidence/api_reference.json --require-integrity --output dist/reference-replay.json
```

Requires Python 3.11+. See [pyproject.toml](./pyproject.toml) for the full
dependency/extras list and [.github/workflows/ci.yml](./.github/workflows/ci.yml)
for the exact sequence CI runs on every push/PR (reproducible-build rebuild,
lint, format check on platform modules, `mypy --strict`, full test suite with
coverage, then the reference replay on the pinned reference Python profile).

## Code style

Not a separate style guide — read any existing module and match it. The
consistent conventions across this codebase:

- `from __future__ import annotations` at the top of every module.
- Full type hints everywhere; `mypy --strict` must pass with zero errors on
  every file you touch.
- `@dataclass(frozen=True, slots=True)` for data-carrying types; validation
  in `__post_init__`, not scattered through callers.
- Deterministic by construction: every stochastic routine takes an explicit
  `seed`; nothing reads wall-clock time, process-random state, or
  unseeded `numpy`/`torch` global RNG for anything that affects a result.
- Docstrings explain **why**, not what — a design rationale, a cited
  acceptance criterion, a discriminating test case, a disclosed
  approximation. If the code already says *what* it does, the docstring
  should not repeat it.
- Prefer composing an existing module (`core.calendar`, `core.seeds`,
  `data_ingestion.transport.HttpTransport`, `experiments.manifest.compute_result_hash`,
  `evidence.model_card.ModelCard`, …) over writing a parallel one. Check
  `src/prometheus/` for something that already does what you need before
  adding new shared infrastructure.
- `ruff check` clean on every touched file — no `# noqa` to silence a real
  finding.

## Network-reachability-first discipline for new data sources

Before writing a connector against any external host, confirm from the
actual environment you're building in that the host is reachable, and
disclose what you actually tested. This repository has, more than once,
found an authoritative-looking host (e.g. `home.treasury.gov`) unreachable
from its own CI/sandbox environment and used a verified, equally
authoritative substitute instead (e.g. FRED's public republication of the
same U.S. Treasury CMT series) — stated explicitly in the code and in
`CHECKLIST_STATUS.md`, never silently. Fabricating or assuming reachability
is not acceptable; neither is quietly using a different source than the one
named without saying so.

## Secrets

Never commit a credential, token, or API key — real or placeholder-shaped.
Before any commit, this repository's own
[`prometheus.evidence.security_scan.secret_scan`](./src/prometheus/evidence/security_scan.py)
function (regex patterns for AWS keys, PEM headers, generic
`api_key="..."`-style assignments) is run over changed files, plus a plain
grep for anything that looks like a secret. See
[SECURITY.md](./SECURITY.md) for how to report a credential that did leak.

## Bookkeeping after a change that closes or advances a checklist item

1. Add real test(s) that evidence the specific acceptance criterion.
2. Update `CHECKLIST_STATUS.md` — a new "Evidenced today" section (narrative
   + exact evidence location) if advancing an item, or a corrected note if
   fixing a previously wrong claim.
3. Regenerate the machine-readable register:
   ```bash
   python -m prometheus.evidence.requirements \
     --pdf docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf \
     --checklist CHECKLIST_STATUS.md \
     --output docs/implementation/blueprint_register.json
   ```
4. Diff the register before/after and confirm only the intended item's
   `repository_notes`/`implementation_evidence_status` fields changed —
   nothing else should drift.
5. Update `README.md`'s coverage badges/table and append a row + narrative
   paragraph to `docs/PR_LEDGER.md`.

## Commit messages

End commit messages with the attribution line the tooling that made the
change actually used (e.g. `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`
for AI-assisted changes) — see recent `git log` for the convention in
practice.

## Code of conduct and security policy

See [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md) and [SECURITY.md](./SECURITY.md).
