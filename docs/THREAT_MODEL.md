# Threat model

SEC-01: assets, trust boundaries, and misuse cases for this repository's
real, current architecture — not a generic enterprise-SaaS threat model
copied from a template. Each row below maps to the control that actually
addresses it, cited to its implementing module, with the honest gaps
named rather than glossed over. See
[docs/SECURITY_AND_DATA_HANDLING.md](./SECURITY_AND_DATA_HANDLING.md) for
the narrative companion to this table.

## Assets

| Asset | Where it lives | Sensitivity |
|---|---|---|
| Service bearer tokens | Private local file, SHA-256 digest only in the credential store | High — grants API access |
| Encrypted recovery snapshots | Local filesystem, AES-256-GCM | Medium — research state, not real financial data |
| Source code / test suite integrity | This git repository | High — the entire evidence discipline depends on it not being silently altered |
| Ingested macro/market data | `MacroObservation` records, all from confirmed free/open sources | Low — no restricted-license or confidential data is ingested today |
| Model artifacts (RECESSIONNET, Q-MACRO, hedging MLP) | `evidence.model_registry`/`model_package` | Low-medium — research models, no production decision authority |

**Explicitly not an asset in this system today**: real customer funds,
real brokerage credentials, real personal/portfolio data. This project
does not hold any of these — see
[README.md § Status & disclaimers](../README.md#status--disclaimers).

## Trust boundaries

| Boundary | Crossed by | Control |
|---|---|---|
| External data source → this repository | `data_ingestion.*` connectors fetching over HTTPS | `data_ingestion.egress_allowlist.AllowlistedTransport` (SEC-10) restricts which hosts a connector may reach; `evidence.security_scan.license_scan` sweeps for restricted-vendor data |
| Network client → local service | `prometheus.service` ASGI app | `service.auth` token verification; loopback-only bind unless TLS cert/key supplied; no credential-redirect-following in the paired client |
| Browser / any network client → web gateway | `prometheus.webgateway`: the one origin a browser talks to; serves the built frontend and reverse-proxies the two backends | A closed request-target grammar and whole-segment routing (`webgateway.routing`); a transport that never follows redirects or reads proxy environment variables and can be pinned to the two configured origins (`webgateway.proxy`); a per-client token-bucket rate limit in front of the backends' own budgets (`webgateway.ratelimit`); bounded request/response bodies, bounded upstream concurrency, blocking I/O kept off the event loop; security headers including a third-party-free CSP on every response (`webgateway.headers`); generic 500s and a structured access log with no query string or credential |
| Authenticated caller → research dashboard | `prometheus.dashboard` (`dashboard.app`): computed views over simulations and a model training run | `service.auth` bearer tokens, owner-scoped portfolio access (`dashboard.auth`); every numeric parameter range-checked before anything is computed (`dashboard.params`); computation off the event loop under a hard cap with a per-owner token bucket (`httpsec`); every error page escaped; a script-less CSP on HTML pages; generic 500s and a JSON audit line per request |
| Container → host | the runtime image as deployed by `docker-compose.yml` | An unprivileged user (uid 10001), a read-only root filesystem, every capability dropped, `no-new-privileges`, init, pid/CPU/memory limits, no build toolchain in the image, loopback-only published port, optional TLS overlay; asserted on the REAL containers by `docker-build.yml` |
| Untrusted uploaded dataset → ingestion pipeline | `data_ingestion.dataset_sandbox` | Format validation/sandboxing (SEC-08, already evidenced) |
| CI / dependency resolution → built artifact | `tools/reproducible_build.py`, `uv.lock` | Hash-pinned bootstrap install, locked resolution, double independent-snapshot rebuild before the wheel is trusted; every CI action pinned to a commit SHA, read-only tokens, job timeouts, no persisted checkout credentials (`test_supply_chain_posture.py`); a weekly advisory scan of every locked Python and npm dependency and the built image (`security.yml`) |
| Caller → point-in-time data store | `econosim.pit.PointInTimeStore.as_of` | No "give me the latest value" accessor exists — a caller structurally cannot see not-yet-eligible data |

## Misuse cases

| Misuse case | Mapped control | Status |
|---|---|---|
| A connector is pointed at an attacker-controlled host (typo, compromised DNS, supply-chain tamper of a connector's own URL constant) and exfiltrates query parameters or receives poisoned data | `AllowlistedTransport` denies and alerts (SEC-10) | Implemented as a primitive; **not yet wired into any connector's actual call site** — disclosed gap, see `CHECKLIST_STATUS.md`'s SEC-10 entry |
| A client crafts a request path so the gateway contacts a host of the attacker's choosing (authority injection in the upstream URL) | `webgateway.routing` (closed grammar, whole-segment match), the transport's origin allowlist, and a final authority assertion in `webgateway.app` | Implemented and property-tested. **The first gateway (PR-187) was confirmed vulnerable** for portless hostname upstreams (`/api/jobs.attacker.example/x` dialed `jobs-api.attacker.example`); fixed in PR-191 |
| A backend redirect makes the gateway re-send the caller's bearer token to another host | `webgateway.proxy` never follows redirects; the 3xx is relayed to the client | Implemented; the old `urllib` transport was confirmed to do exactly this against two real local servers |
| An unauthenticated flood exhausts the backends' shared pre-authentication rate budget and locks every real user out | `webgateway.ratelimit`: per-client token bucket in front of it | Implemented; process-local, so one gateway process only |
| An oversized or slow request body, or a slow backend, ties up memory, threads or the event loop | Request/response byte ceilings, a body deadline, a bounded in-flight upstream count, `asyncio.to_thread` for proxied calls, `--max-connections` | Implemented. Slow *header* reads are bounded only by `--max-connections` (uvicorn has no header-read timeout) -- disclosed, not closed |
| Script injection into the single-page app | A CSP with `default-src 'none'`, no `unsafe-*` source and no third-party origin; fonts are self-hosted | Implemented; checked in a real Firefox session (zero violations across all 18 routes), **not** on Chrome/Safari |
| A hostile path forges or floods the access log | The logged path is JSON-escaped and truncated; denied requests are logged at most once per second per client | Implemented |
| A caller holding only a read-only token asks the dashboard for an absurd amount of work (a huge array, a training run with a million epochs) and starves every other user | `dashboard.params` bounds every numeric parameter before computation, including product caps on array size; `httpsec.BoundedExecutor` caps concurrent computation; a per-owner token bucket | Implemented. **The previous dashboard was confirmed to accept all of it** (`n=100000000000` reproduced as an unhandled 745 GiB `MemoryError`); fixed in PR-192. CPU use inside the permitted ranges is bounded but not metered per caller beyond the rate limit |
| Caller-supplied text is reflected into a server-rendered HTML error page as live markup | Identifier parameters are a closed character set (rejected, never echoed); the single error-page path escapes whatever it is given; the HTML CSP forbids script | Implemented. The previous code reflected `<script>`/`<img onerror>` unescaped (reproduced); requires an `Authorization` header a cross-site link cannot supply, so not remotely exploitable in practice |
| One slow view freezes the dashboard (and its health probe) for every caller | Views run in worker threads; slots are held until the thread really finishes | Implemented; reproduced as a real-socket test that fails on the previous code |
| A leaked service token is reused after rotation | `evidence.credential_rotation_drill` (DRI-03); token stored only as a SHA-256 digest, never logged | Implemented, drilled |
| A future data point leaks into a decision that should not have seen it yet (point-in-time violation) | `econosim.pit`'s fail-closed predicate; `evidence.pit_leak_response` (DRI-04) for after-the-fact response | Implemented, drilled |
| A secret, or a file that should never be committed, is pushed | `evidence.security_scan.secret_scan` (AWS, PEM, generic assignments and, since PR-201, the token formats of Kaggle, GitHub, Slack, Google, Anthropic, OpenAI-style keys, Hugging Face, npm, PyPI, Stripe and JWTs) plus `path_scan`, over every tracked file in the test suite with no allowlist; `secret_scan_cli --staged` and `.githooks/pre-commit` refuse the commit itself and never print the matched text | Implemented. Fixed local patterns, not a live check: a secret in a format with no pattern is not found. The hook is opt-in per clone and `--no-verify` bypasses it; CI can only detect after a push. A pickaxe search of all 131 commits at PR-201 matched only the scanner's own deliberately fake fixtures |
| A compromised/tampered dependency enters the install | `tools/reproducible_build.py`'s double-rebuild-from-independent-snapshots check, hash-pinned bootstrap, hash-locked wheels only in the image (`--no-build`), `npm ci --ignore-scripts` and `npm audit signatures` | Implemented |
| A compromised or moved GitHub Action tag runs attacker code in CI with a write token | Every action pinned to a full commit SHA, top-level `permissions: contents: read`, `persist-credentials: false`, no `pull_request_target` | Implemented and mechanically tested; a pinned action still has to be reviewed when Dependabot bumps it |
| A process inside the container is compromised and tries to persist, escalate or reach the host | Non-root, read-only root, no capabilities, `no-new-privileges`, resource limits (see the container boundary) | Implemented on the REAL containers; Docker's default seccomp profile applies, no custom profile |
| The cleartext demo port is reachable from the network | The published port is bound to the host's loopback; the TLS overlay refuses to bind a network interface without a certificate | Implemented |
| A model is promoted to `staged`/`approved` without passing provenance/validation | `evidence.model_registry.promote_to_approved` (MLO-10) rejects it structurally | Implemented |
| An attacker sends a malformed/oversized dataset to the ingestion sandbox | `data_ingestion.dataset_sandbox` | Implemented (SEC-08) |
| A committed data snapshot is altered (a one-cell edit, a bad merge, a refresh script) and every model trained on it shifts without anyone noticing | `data_cache/MANIFEST.sha256.json` plus `data_ingestion.snapshot_integrity`: every loader verifies the bytes it parses | Implemented and tested on every loader (eleven at 0.4.0). **Unsigned**: someone who can rewrite a CSV can rewrite the manifest, so this catches drift and forces a visible, deliberate step; it does not stop a malicious committer (that is what required reviews are for) |
| A third-party data file (a Kaggle CSV, an archive) is malformed, corrupted or hostile: `nan` prices, repeated dates, a truncated download | `kaggle_build`'s parsers reject non-finite values, non-positive prices, duplicate dates, short rows and oversized fields; `read_zip_members` turns every zip-library error into `SnapshotParseError`; the SEC-08 sandbox bounds size and compression ratio | Implemented and fuzzed (`test_data_parser_fuzz.py`). The previous parsers accepted `nan` and leaked raw `zlib.error` / `BadZipFile` from a corrupted archive, and the sandbox let `NotImplementedError` escape on an unsupported zip version (all reproduced) |
| An insider (the single maintainer) silently merges an unreviewed, unapproved change | None — genuinely open | **Not addressed.** A single-maintainer repository has no second-party review by construction. See SEC-02/SEC-03/GOV-11 in `CHECKLIST_STATUS.md` for why this needs real organizational structure this repository's source tree cannot itself provide. |
| A live CVE in a pinned dependency goes undetected | `.github/workflows/security.yml`: pip-audit over every locked Python requirement, `npm audit`, Trivy on the image -- on every dependency change AND weekly; CodeQL for the sources | Implemented. The first real runs found 16 frontend vulnerabilities (3 HIGH in the production router), 6 advisories in the pinned build tooling and fixable image findings, all fixed (PR-193/194). A scanner only knows PUBLISHED advisories, the numerics stack is excluded from automated updates, and 6 moderate dev-only npm findings remain |

## What this threat model deliberately does not cover

Live infrastructure this project does not operate (a production
deployment, a multi-tenant hosting environment, real user accounts) —
threat-modeling infrastructure that does not exist would be speculative,
not evidence. When/if a real deployment exists, this document should be
extended, not replaced.

## Review status

This threat model was authored and is maintained alongside the code it
describes, re-derived from the real current architecture each time it is
updated (confirm by cross-checking the "Control" column against the cited
module). **It has not been independently reviewed** by a second party —
see `CHECKLIST_STATUS.md`'s SEC-01 entry for this honestly disclosed gap;
"reviewed and mapped to controls" per this item's acceptance criterion is
satisfied for the mapping half, not the independent-review half.
