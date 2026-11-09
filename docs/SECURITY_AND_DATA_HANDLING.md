# System security and data-handling guide

This is the internal architecture companion to [SECURITY.md](../SECURITY.md)
(which covers *reporting* a vulnerability). This document describes the
real controls that exist in this codebase today, with their exact scope
and limits — and, as plainly, the controls that do not exist yet. See
`CHECKLIST_STATUS.md`'s `SEC` category for the authoritative, test-backed
status of each item; this document is the narrative index into that.

## Authentication (local service)

[`prometheus.service.auth`](../src/prometheus/service/auth.py): private-
file, hashed service credentials with per-request rotation/revocation.
Explicitly **not** an OIDC/SSO or vault integration — this is local
single-host token auth. A plain token is never persisted by the reader or
returned in diagnostics; only its SHA-256 digest is stored in the
credential file, and provisioning refuses to overwrite an existing
credential/token file rather than silently rotating over one. See
[docs/RESEARCH_API.md](./RESEARCH_API.md) for the provisioning command.

## Transport

The local service refuses cleartext binding outside loopback
(`127.0.0.1`) unless both `--tls-cert` and `--tls-key` are supplied.
[`prometheus.service.client`](../src/prometheus/service/client.py) uses
Python's default TLS verification context, explicitly disables automatic
redirect-following on authenticated requests (so a redirect cannot be used
to exfiltrate a bearer token to an unintended host), and does not inherit
environment proxy settings.

## Data at rest

[`prometheus.recovery.snapshot`](../src/prometheus/recovery/snapshot.py):
streamed AES-256-GCM recovery snapshots on a trusted local filesystem.
Decryption/authentication happens completely into private staging before
any metadata is parsed, and only a verified new state root is ever
published. **Explicitly out of scope** (stated in that module's own
docstring, repeated here so it isn't missed): offsite transfer, vault
custody, and production RPO/RTO — those require real infrastructure this
repository's source tree cannot itself provide or prove.

## Secret handling

[`prometheus.evidence.security_scan.secret_scan`](../src/prometheus/evidence/security_scan.py)
matches a fixed, self-contained set of regex patterns (AWS access key IDs,
PEM private key headers, generic `api_key="..."`-style assignments)
against file contents, and is run over every changed file before a commit
in this project's own workflow (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
This is deliberately **not** a live-CVE-database vulnerability scan — see
that module's own docstring for why fabricating results against a
database that was never actually queried would misrepresent what was
checked.

## Data licensing / provenance

Every real external data source this project ingests today (U.S. Treasury
CMT yields via FRED, World Bank Open Data, the Kenneth French Data
Library, a Kaggle-republished FRED-derived dataset) is confirmed free/
open, with the exact license recorded on every
[`MacroObservation`](./DATA_DICTIONARY.md#macroobservation--point-in-time-macro-data)'s
`source_license` field. `prometheus.evidence.security_scan.license_scan`
sweeps tracked files for restricted-redistribution vendor names
(Bloomberg, Refinitiv/Thomson Reuters, FactSet, S&P Capital IQ, LSEG,
Morningstar Direct) or explicit no-redistribution marker phrases — a
sweep of this repository's real tracked source tree is expected, and
confirmed, to find zero matches.

## Deterministic, reviewable builds

CI (`.github/workflows/ci.yml`) installs the bootstrap tool with
`--require-hashes --only-binary=:all:`, resolves every other dependency
with `uv sync --locked`, rebuilds the wheel **twice from independent
source snapshots** to confirm bit-for-bit reproducibility
(`tools/reproducible_build.py`), and only then installs that verified
wheel with `--no-deps --offline` — a compromised or substituted
dependency cannot enter the pipeline silently between those steps. A
software bill of materials is published at
[`docs/release/dependency-sbom.cdx.json`](./release/dependency-sbom.cdx.json).

## What is not implemented, and why that's stated here rather than silently assumed

- **Live vulnerability/dependency CVE scanning** — needs a live, current
  advisory database this hermetic test environment cannot reliably query.
- **A formal written threat model** (assets, trust boundaries, misuse
  cases) — not yet published as a standalone document.
- **Branch protection / MFA / least-privilege maintainer enforcement** —
  GitHub organization/account settings outside this repository's own
  source tree; cannot be proven by a test in this repository.
- **A network egress allowlist** for data ingestion and model serving —
  not implemented; every connector in `data_ingestion/` currently reaches
  whatever host its configuration names.
- **Per-tenant rate limiting** on the local service — not implemented;
  it is a single-local-user service today, not a multi-tenant one.
- **Formal data classification** of confidential portfolio/user data —
  not implemented; this project does not currently hold real user
  portfolios or real personal data, only synthetic/public research data.
- **An independent penetration test** — requires a real external party;
  nothing in this repository can self-certify this.

See `CHECKLIST_STATUS.md`'s `SEC` category for the item-by-item count
this list corresponds to.
