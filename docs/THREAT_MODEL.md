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
| Untrusted uploaded dataset → ingestion pipeline | `data_ingestion.dataset_sandbox` | Format validation/sandboxing (SEC-08, already evidenced) |
| CI / dependency resolution → built artifact | `tools/reproducible_build.py`, `uv.lock` | Hash-pinned bootstrap install, locked resolution, double independent-snapshot rebuild before the wheel is trusted |
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
| A leaked service token is reused after rotation | `evidence.credential_rotation_drill` (DRI-03); token stored only as a SHA-256 digest, never logged | Implemented, drilled |
| A future data point leaks into a decision that should not have seen it yet (point-in-time violation) | `econosim.pit`'s fail-closed predicate; `evidence.pit_leak_response` (DRI-04) for after-the-fact response | Implemented, drilled |
| A hardcoded secret is committed | `evidence.security_scan.secret_scan`, run before every commit | Implemented; local pattern scan only, not a live-database check (disclosed) |
| A compromised/tampered dependency enters the install | `tools/reproducible_build.py`'s double-rebuild-from-independent-snapshots check, hash-pinned bootstrap | Implemented |
| A model is promoted to `staged`/`approved` without passing provenance/validation | `evidence.model_registry.promote_to_approved` (MLO-10) rejects it structurally | Implemented |
| An attacker sends a malformed/oversized dataset to the ingestion sandbox | `data_ingestion.dataset_sandbox` | Implemented (SEC-08) |
| An insider (the single maintainer) silently merges an unreviewed, unapproved change | None — genuinely open | **Not addressed.** A single-maintainer repository has no second-party review by construction. See SEC-02/SEC-03/GOV-11 in `CHECKLIST_STATUS.md` for why this needs real organizational structure this repository's source tree cannot itself provide. |
| A live CVE in a pinned dependency goes undetected | None — genuinely open | **Not addressed.** See `docs/SECURITY_AND_DATA_HANDLING.md`'s disclosed-gaps list. |

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
