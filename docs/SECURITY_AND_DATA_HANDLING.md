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
checked. Advisory scanning exists separately, as a CI workflow that really
queries the advisory databases (`.github/workflows/security.yml`, see
[SECURITY.md](../SECURITY.md)); it is outside the hermetic test suite on
purpose, and it only knows advisories that have been published.

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

An earlier version of this list named a threat model, a network egress
allowlist, rate limiting and data classification as missing; all four have
since been built (see `CHECKLIST_STATUS.md`'s `SEC` rows) and the list had gone
stale. What is genuinely not in place:

- **Independent review of anything here** — the threat model
  ([THREAT_MODEL.md](./THREAT_MODEL.md)), the data inventory and every control
  are authored and maintained alongside the code by a single maintainer.
- **An independent penetration test** — requires a real external party; nothing
  in this repository can self-certify this (SEC-14).
- **MFA, SSO and branch-commit signing** — GitHub account/organization settings
  outside this repository's source tree. Branch protection with required
  reviews is configured (SEC-02, partial); admin enforcement is not, and the
  security scanners are not required status checks.
- **Verified certificate management** — TLS is observed end to end with real
  handshakes (SEC-05), but issuance, rotation and revocation are the operator's.
- **Image signing and provenance attestation, a custom seccomp/AppArmor profile,
  an image SBOM** — the runtime image is hardened and scanned, not signed.
- **High availability, distributed rate limiting, a WAF, a secrets manager** —
  this is a single-host service whose limits are process-local
  ([DEPLOYMENT.md](./DEPLOYMENT.md)).
- **Real personal data handling** — this project does not hold real user
  portfolios or real personal data, only synthetic/public research data, so
  privacy controls are inventoried rather than exercised.

See `CHECKLIST_STATUS.md`'s `SEC` category for the item-by-item count
this list corresponds to.
