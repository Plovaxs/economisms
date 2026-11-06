# Research-job HTTP API, v1

PR-047 adds an authenticated single-host ASGI boundary over
[the durable local job backend](./LOCAL_JOBS.md). Workers remain separate
Linux processes. This service runs synthetic research recipes; it does not
add order execution, broker, live-trading or payment endpoints. R0 remains
NO-GO, and the full blueprint remains unfinished.

## Local setup

```bash
pip install -e ".[dev,service]"
python -m prometheus.service init-auth \
  --credentials .prometheus/api/auth.json --token-file .prometheus/api/token \
  --owner local
python -m prometheus.service serve --root .prometheus/api \
  --credentials .prometheus/api/auth.json
```

Run `python -m prometheus.jobs --root .prometheus/api work` separately.
Both processes must use the same private local state directory, queue policy
and source environment. The API queues work; it does not train models in a
request thread. A changed source/dependency environment causes queued jobs
to fail the existing runtime-match check rather than silently execute under
different code. Submit a new request/key after an intentional change.

The listener defaults to `127.0.0.1:8765`. `--host` accepts an IP address;
binding outside loopback requires both `--tls-cert` and `--tls-key`.
`--port 0` asks the protocol server to allocate a port. The ASGI application
also rejects cleartext outside loopback. Forwarded client/scheme headers
are not trusted by the supplied server configuration. Deployed TLS,
certificates/key management, at-rest encryption and ingress trust must still
be independently configured/verified.

Provisioning creates a random 256-bit token in a private file and stores
only its SHA-256 digest in the separate credential file. It refuses to
overwrite either destination and prints file paths only. Protect the token
as a secret; do not put it in query strings, shell arguments or repository
files. Examples use the ignored `.prometheus/` state directory.

## Authentication and revocation

Private credential schema version 1:

```json
{
  "schema_version": 1,
  "credentials": [
    {
      "subject": "local-worker-client",
      "owner": "local",
      "scopes": ["read", "write"],
      "token_sha256": "<64 lowercase SHA-256 hex characters>"
    }
  ]
}
```

The example digest is a placeholder, not a usable credential. Use the
provisioner to generate a real random token. Credential files must be
process-owner-controlled regular files, private to that owner, at most
64 KiB, and contain at most 128 bindings. Symlinks/FIFOs, duplicate token
hashes, unknown scopes/fields and invalid identities are refused. `read`
is required; adding `write` permits submission/cancellation within that
same owner namespace. No administrative cross-owner API exists.

Send `Authorization: Bearer TOKEN`. The application derives owner from
the matched binding, not from a request field, query or forwarded header.
Bindings reload on each request, with constant-time digest comparisons.
To rotate/revoke, prepare a new valid private file under the same trusted
directory and atomically replace the configured file. Invalid/unavailable
credential configuration fails closed; liveness remains separate.
An already authenticated in-flight request may complete; revocation applies
to subsequent authentication. Service tokens do not provide SSO/OIDC, MFA,
vault integration, independent access review or external audit retention.

## Contract and routes

[openapi-v1.json](./api/openapi-v1.json) is the tracked OpenAPI 3.1.1
contract for API version 1.0.0. The authenticated `GET /v1/openapi.json`
returns the same document. Generate a candidate into a new file with
`python -m prometheus.service openapi --output /tmp/prometheus-openapi.json`;
the command refuses to overwrite a destination.

| Method and route | Scope | Behavior |
|------------------|-------|----------|
| `GET /health/live` | public | process/application can respond |
| `GET /health/ready` | public | credential file, existing SQLite writer/schema/policy and artifact-directory access probe |
| `GET /v1/openapi.json` | read | versioned contract |
| `POST /v1/jobs` | write | durable async submission; 202 and Location |
| `GET /v1/jobs?limit=50&cursor=...` | read | stable owner-scoped job pages |
| `GET /v1/jobs/{job_id}` | read | status, estimates, result/artifact identities and structured execution outcome |
| `POST /v1/jobs/{job_id}/cancel` | write | durable cancellation request; inspect status until terminal |
| `GET /v1/jobs/{job_id}/artifact` | read | sealed verified artifact associated with that job; 409 before publication |

Submission requires `Content-Type: application/json` and a bounded
`Idempotency-Key`. The body contains `kind`, complete `config`, and optional
`timeout_seconds`. The nine kinds and nested schemas come from the existing
immutable runner allowlist. Missing/extra fields are rejected. Calendar
dates use ISO dates; cash uses explicit integer `minor_units` and currency;
exact quantities use numerator/positive-denominator objects or numbers.
Typed decoders additionally enforce supported currencies, nonnegative
quantities, cross-field timing and financial/model constraints. Those
semantic checks and resource policy remain authoritative beyond the
structural JSON Schema. Money is not implicitly converted between units.

Owner is not an accepted submission field. Idempotency binds normalized
kind/config and timeout within the authenticated owner. A retry returns
the same job, including at pending-job capacity; changed input under the
same key returns 409. Reusing a terminal job's key retrieves that existing
execution, so use a new key for a deliberate new execution. A disconnected
submission may already have committed: retry with the same key to resolve
an uncertain outcome. A cancellation request does not imply that a running
child has already stopped; terminal cancelled status confirms fencing.

Foreign-owner job lookups, cancellations and artifacts return the same 404
as missing jobs. Job pages use `(created_ns, job_id)` ordering and owner-bound
cursors; each page has up to 100 jobs. They are live collection traversals,
not immutable point-in-time snapshots. Separate artifact-collection filters
and market-snapshot/model-version pricing/risk report APIs remain open.

Artifact reads verify the content pin, schema and complete job/trace/recipe/
attempt/result association. ETag hashes the exact JSON response bytes.
Responses use `Cache-Control: no-store`, `nosniff` and server-generated
`X-Request-ID`. Checksums do not establish authorship or scientific approval.

Compatibility policy: `/v1` preserves existing field meanings, required
request fields and method/route semantics. Additive optional response fields
may be introduced in a minor version; the SDK tolerates unknown fields.
Breaking recipe/unit/identity/response semantics require a new major API
version and explicit migration guidance. Contract changes require a reviewed
version/fixture update. Tests compare generated and tracked contracts and
validate all nine complete default recipes. Broader SDK/version matrices
and independent compatibility review remain outstanding.

## Limits, errors and operational probes

Defaults: 64 headers, 16 KiB total header bytes, 1,052,672 wire body bytes,
10 seconds total body-read time, eight in-flight application requests,
120 requests per owner per 60 seconds and 1,200 global requests per 60
seconds. Invalid/unauthenticated requests consume the global budget;
tokens for the same owner share the owner budget. Bucket memory is bounded
across credential rotations. Existing recipe shape/precision/work budgets
and durable queue quotas additionally apply. A request rejected by the
application does not bypass those worker limits.

Capacity stays occupied until underlying work completes even if the HTTP
caller is cancelled. Request body timeouts do not abandon SQLite work in a
thread or cancel an already committed job. Shutdown drains admitted work;
new requests are rejected while liveness remains available.

Application errors use `error.code`, `message`, `request_id`,
`diagnostic_id` and nullable `field`. Schema failures identify a field and
constraint class without echoing recipe values. 401 includes a bearer
challenge; 405 includes Allow; 429/503 include Retry-After guidance.
The logger `prometheus.service.audit` emits structured INFO events with
request ID, status/code, configured subject, job/trace ID and diagnostic ID.
The provided CLI enables this logger through normal Python logging. It
excludes tokens, raw URLs/query strings, recipes and exception text.
Alternative hosts must configure/export these logs themselves; this is
not a durable distributed audit collector.

Liveness does not depend on the database or credentials. Readiness attempts
bounded SQLite writer admission and checks schema/policy plus job/event
table availability without creating a missing database. It also reads the
credential configuration and checks artifact-directory access. It does not
prove worker heartbeat/capacity, disk free space, stored-object integrity,
restore capability or absence of a later dependency race.

Limits are per API process, not cluster-wide. The supplied Uvicorn launcher
uses one API process, explicit h11/ASGI settings, no WebSocket service,
disabled forwarding/access logging, bounded protocol concurrency/backlog,
header buffering and keep-alive/shutdown settings. Protocol-server/ingress
errors can occur before application handling and may have non-JSON bodies.
The SDK reports those as protocol failures. Production connection/TLS
hardening, distributed rate limits, hard RSS/cgroups, load tests and SLO
calibration remain separate requirements.

## Typed SDK

`prometheus.service.client.ResearchClient` returns immutable typed
`JobSnapshot` and `JobPage` objects. It provides `submit`, `get_job`,
`cancel_job`, `list_jobs`, and content-pinned `get_artifact`. It does not
retry automatically. Use the same idempotency key after an uncertain
transport outcome. Artifact retrieval also checks the preceding job's
result/content identity and full lineage.

The client accepts HTTPS or HTTP with a loopback IP, rejects origin
credentials/query/path suffixes, disables redirects and environment proxies,
retains default certificate verification, bounds response bytes and applies
socket-operation timeouts. Those timeouts are not an absolute response wall
deadline or DNS budget. ServiceError retains HTTP code and correlation IDs;
protocol and transport faults have separate exception types. Applications
must separately decide polling/retry/deadline behavior and protect token
storage. No custom TLS trust bypass is included.

## Design references and validation scope

The application follows the [ASGI HTTP message contract](https://asgi.readthedocs.io/en/latest/specs/www.html),
including streamed request messages and disconnect handling. The schema uses
[OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html).
Thread offloading/cancellation behavior follows [Python asyncio](https://docs.python.org/3.14/library/asyncio-task.html).
Digest comparison uses [hmac.compare_digest](https://docs.python.org/3.14/library/hmac.html).
Server controls follow [Uvicorn's settings reference](https://github.com/Kludex/uvicorn/blob/main/docs/settings.md);
client transport follows [urllib.request](https://docs.python.org/3.14/library/urllib.request.html).
These references guide implementation; they do not certify this deployment.

Local tests cover direct ASGI failures, real TCP/SDK/server/worker execution,
revocation and lineage. See [validation_pr047.md](../evidence/validation_pr047.md)
for measured results and recorded artifacts. No internet-facing deployment,
remote CI, production authorization or independent acceptance is claimed.
