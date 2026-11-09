# Security Policy

## Scope

ECONOSIM is research and simulation software. It is **NO-GO for
production** — this is the project's own, unchanged internal gate decision
(see [`evidence/gate_report_r0.json`](./evidence/gate_report_r0.json) and
[README.md § Status & disclaimers](./README.md#status--disclaimers)). It does
not execute real trades, move real money, or hold real customer funds. The
optional local HTTP service
([`docs/RESEARCH_API.md`](./docs/RESEARCH_API.md)) is a single-host,
loopback-by-default ASGI boundary over a local research-job queue, intended
for local/research use, not public deployment.

This policy covers vulnerabilities in:

- the Python package under [`src/prometheus/`](./src/prometheus/);
- the optional local service and client (`prometheus.service`);
- the build/CI tooling under [`tools/`](./tools) and
  [`.github/workflows/`](./.github/workflows).

It does not cover the research findings themselves (a model underperforming
a baseline is a result, not a vulnerability — see
[docs/RESULTS_AND_LIMITATIONS.md](./docs/RESULTS_AND_LIMITATIONS.md)), nor
third-party dependencies (report those upstream).

## Reporting a vulnerability

Please **do not open a public GitHub issue** for a security vulnerability.
Use GitHub's private vulnerability reporting instead: open this repository's
**Security** tab → **Report a vulnerability**, which creates a private
advisory visible only to the maintainers until a fix is ready. This avoids
publishing exploit details before a patch exists, without requiring a
published contact address.

Please include:

- the affected file(s)/function(s) and, if possible, a minimal reproduction;
- what you expected vs. what actually happened;
- your assessment of impact (what an attacker could actually do with it).

## What to expect

This is a single-maintainer research repository (see
[CONTRIBUTING.md](./CONTRIBUTING.md)) — there is no SLA and no bug bounty.
A genuine report will get looked at and, if confirmed, fixed and disclosed
honestly (the same evidence discipline the rest of this project runs on
applies to security fixes: a fix ships with a regression test proving the
vulnerable behavior is gone, not just a claim that it is).

## Response owner and patch cadence (SEC-15)

The project maintainer is the sole response owner for every report — see
[CONTRIBUTING.md](./CONTRIBUTING.md) for what "maintainer" means in this
single-maintainer repository (no second identity is fabricated here to
imply a team that doesn't exist). Patch cadence, stated honestly rather
than as a fabricated SLA: a confirmed vulnerability in this project's own
code is fixed and merged to `main` (this repository has no separate
release-branch cadence to patch against) at the next available working
session; there is no guaranteed turnaround time. Dependency advisories are
addressed by bumping the pinned version in `uv.lock` once a confirmed fix
is available upstream — this repository does not currently run an
automated live-CVE feed (see
[docs/SECURITY_AND_DATA_HANDLING.md](./docs/SECURITY_AND_DATA_HANDLING.md)
for why), so a dependency vulnerability is addressed when reported or
discovered during a dependency bump, not necessarily proactively.

## Existing controls (what's already in place, and what isn't)

- **Secret scanning**: [`prometheus.evidence.security_scan.secret_scan`](./src/prometheus/evidence/security_scan.py)
  runs over changed files before every commit in this project's own
  workflow, matching hardcoded-secret shapes (AWS keys, PEM headers,
  generic `api_key="..."` assignments). It is a fixed local pattern scan,
  **not** a live CVE/advisory database query — see that module's own
  docstring for why (this repository's hermetic, network-independent test
  discipline has no reliable way to query a live database from CI).
- **No credential redirects**: `prometheus.service.client` explicitly
  disables automatic redirect-following for authenticated requests and
  never logs or echoes the bearer token.
- **TLS**: the local service refuses cleartext binding outside loopback
  (`127.0.0.1`) without both `--tls-cert` and `--tls-key` supplied; the
  client uses Python's default TLS verification context.
- **Dependency pinning**: `uv.lock` pins exact resolved versions; CI
  installs with `--require-hashes --only-binary=:all:` for the bootstrap
  tool and `--locked` for everything else, and rebuilds the wheel twice
  from independent source snapshots to confirm reproducibility
  (`tools/reproducible_build.py`) before installing it with `--no-deps
  --offline`.
- **Not implemented** (see `CHECKLIST_STATUS.md`'s `SEC` category for the
  current count): live vulnerability/dependency CVE scanning, a formal
  threat model document, branch-protection/MFA enforcement (GitHub account
  settings, outside this repository's own code), a network egress
  allowlist for ingestion/model-serving, per-tenant rate limiting, and an
  independent penetration test. These require either a live external
  service this sandboxed environment cannot reliably query, or real
  organizational/platform configuration outside what a repository's source
  tree can itself prove — see
  [CONTRIBUTING.md](./CONTRIBUTING.md) for why this project will not mark
  something "evidenced" on the strength of a plan alone.
