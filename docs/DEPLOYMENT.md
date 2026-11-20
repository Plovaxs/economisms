# Deployment guide

How to run ECONOSIM/PROMETHEUS-X as a hardened, single-host service, what each
control actually does, and what it does not give you. Read
[What this is not](#what-this-is-not) before relying on any of it.

## What this is not

This is the **research platform's** deployment: a web gateway, a dashboard, a
job API and a job worker, on one host. It is hardened the way a careful
single-host service should be (below), and every claim in this guide is backed
by a test or a CI check named next to it.

It is **not** a statement that the project is cleared for production use. Its
own gate decision (`evidence/gate_report_r0.json`) is **NO-GO for live trading,
real capital or any real brokerage connection**, and nothing in this guide
changes that: the remaining blockers are institutional artifacts (an
independent penetration test, a legal opinion, independent model validation) no
amount of hardening can produce. It is also single-host: no high availability,
no horizontal scaling, and every rate limit is process-local.

## Architecture

```
browser ──HTTP(S)──▶ webgateway :8080 (or :8443 with TLS)
                       │  serves the built frontend; proxies, over loopback:
                       ├──▶ jobs API    127.0.0.1:8765   (/api/jobs/*)
                       └──▶ dashboard   127.0.0.1:8766   (/api/dashboard/*)
        worker ──▶ the same job store on the /data volume
```

In Docker the three backends share the gateway container's network namespace,
so they bind **127.0.0.1** and are unreachable from anywhere but the gateway.
Only the gateway publishes a port, and only on the host's loopback.

## Quick start (Docker)

```bash
docker compose up --build            # builds the image, starts every service
open http://localhost:8080           # the demo UI
docker compose exec webgateway cat /data/token   # the bearer token to paste in
```

The published port is `127.0.0.1:8080`, deliberately **not** reachable from the
network: this stack speaks cleartext HTTP. To serve anything beyond the local
machine, use the TLS overlay below rather than widening the port mapping.

A volume created by an older, root-running version of this image keeps its
root ownership; run `docker compose down -v` once to recreate it.

## TLS

```bash
mkdir -p tls
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  -keyout tls/key.pem -out tls/cert.pem          # or bring your own certificate
chmod 0400 tls/key.pem && sudo chown 10001:10001 tls/key.pem tls/cert.pem   # chmod FIRST: after the chown you no longer own it
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
curl --cacert tls/cert.pem https://localhost:8443/health/live
```

The containers run as uid 10001, so that user must be able to read the key (a
bind-mounted secret keeps the host file's numeric owner and mode). With the
overlay the gateway **refuses to bind a network interface without a
certificate**, HSTS and an `upgrade-insecure-requests` CSP appear on HTTPS
responses (and only there), and the server's minimum protocol is TLS 1.2.
Evidence: `tests/unit/test_webgateway_tls.py` (real handshakes against a real
server), and the `tls-smoke-test` job in `.github/workflows/docker-build.yml`,
which runs the overlay with a throwaway certificate.

Certificate issuance, rotation and revocation are yours: nothing here renews a
certificate. If a TLS-terminating reverse proxy sits in front instead, start the
gateway with `--trusted-proxy-hops N` (the number of trusted proxies) so the
rate limiter keys on the real client address from `X-Forwarded-For`; with the
default `0` that header is ignored entirely.

## Running without Docker

```bash
econosim service init-auth --credentials auth.json --token-file token --owner alice
econosim jobs --root ROOT work &
econosim service serve --root ROOT --credentials auth.json --port 8765 &
econosim dashboard serve --credentials auth.json --port 8766 --demo &
econosim webgateway serve --dist frontend/dist     # after `npm run build`
```

`./run_dev.sh` does this plus the Vite dev server with hot reload. The Vite dev
server is a development tool: do not expose it.

## Configuration

Gateway flags (`econosim webgateway serve --help`):

| Flag | Default | Effect |
|---|---|---|
| `--max-connections` | 128 | concurrent connections before new ones get 503 |
| `--max-request-body-bytes` | 1,052,672 | larger request bodies get 413 (equals the job API's own limit) |
| `--max-response-bytes` | 33,554,432 | larger backend responses become 502 |
| `--upstream-timeout` | 30 | seconds to wait for a backend before 502 |
| `--max-upstream-inflight` | 16 | concurrent backend calls; beyond it, 503 + `Retry-After` |
| `--rate-limit-per-second` / `--rate-limit-burst` | 20 / 100 | per-client token bucket; `0` disables |
| `--trusted-proxy-hops` | 0 | trusted reverse proxies in front (see TLS) |
| `--tls-cert` / `--tls-key` | none | serve HTTPS |

The dashboard runs at most 4 computations at once and rate-limits per owner
(10 requests/second, burst 60); the job API's budgets are `ServicePolicy`
(`service/application.py`). Resource limits for the containers are in
`docker-compose.yml` (`mem_limit`, `cpus`, `pids_limit`); raise the worker's
`mem_limit` before running larger jobs.

## Health and readiness

| Endpoint | Meaning | Use it for |
|---|---|---|
| gateway `GET /health/live` | this process is up | restart decisions |
| gateway `GET /health/ready` | both backends answer; `503` names which one does not | load-balancer decisions |
| jobs API `GET /health/live`, `/health/ready` | process up / credentials, job store and artifact store usable | |
| dashboard `GET /health/live` | process up | |

All are unauthenticated. The gateway's readiness probe is rate-limited like any
other request (liveness is exempt, so an orchestrator can always ask whether the
process is up), and its results are coalesced for a second so polling cannot
amplify load on the backends. The compose health checks
use the liveness endpoints, so a restarting backend does not make Docker restart
a healthy gateway.

## Logs and tracing

Every process writes one JSON object per request to stdout (Docker rotates them:
10 MB x 3 files per container). None ever contains a query string or a
credential, and a hostile path cannot forge a line (the path is JSON-escaped and
truncated).

| Event | Process | Notable fields |
|---|---|---|
| `gateway_request` | gateway | `request_id`, `method`, `path`, `status`, `route`, `duration_ms`, `client`, `upstream_status`, `upstream_request_id` |
| `service_request` | job API | `request_id`, `status`, `code`, `subject`, `job_id` |
| `dashboard_request` | dashboard | `request_id`, `status`, `path`, `subject` |

Correlate a browser request to the backend's audit line with the response
headers: `x-gateway-request-id` is the gateway's, `x-request-id` is the
backend's, and the gateway's own log line carries the backend's as
`upstream_request_id`. Rate-limit denials are logged at most once per second per
client, so an attacker's request rate cannot become the log volume.

## Operations

- **Preflight** with `econosim doctor [--credentials FILE] [--state-dir DIR]` (PR-204): it checks the
  Python version, that every installed dependency matches `uv.lock` (a drift in the numerical stack is
  a failure -- CI found more than once that a different numpy changes a result), that every data
  snapshot still matches its manifest, that the credentials file is a regular file only its owner can
  read, and that the state directory is writable. It exits non-zero on any failure, makes no network
  call and is a diagnostic, not a control: it tells you what is wrong, it does not stop anything.
- **Stop** with `docker compose stop` (SIGTERM). The gateway stops accepting
  connections, lets in-flight requests finish (up to 20 s) and then exits
  with the conventional SIGTERM status (uvicorn re-raises the signal once the
  drain is done); `tests/unit/test_webgateway_graceful_shutdown.py` runs exactly
  this against a real process and a request parked inside a slow backend.
- **Upgrade**: `git pull && docker compose up -d --build`.
- **Back up and restore** the job store with the encrypted snapshot tool:
  `econosim recovery keygen --output snapshot.key`, then
  `econosim recovery create --root ROOT --output snap.bin --key-file snapshot.key`,
  `... verify --input snap.bin --key-file snapshot.key` and
  `... restore --input snap.bin --key-file snapshot.key --destination DIR`.
  See [OPERATIONS_RUNBOOK.md](./OPERATIONS_RUNBOOK.md).
- **Rotate a credential**: provision a new credential file with `init-auth`; the
  credential store is re-read on every request, so a rotated or revoked token
  stops working immediately. See the credential-compromise runbook in
  [OPERATIONS_RUNBOOK.md](./OPERATIONS_RUNBOOK.md).

## The desktop application (no service at all)

`econosim desktop` is not a deployment of the stack above: it starts no server, takes no token and
opens no port. It is one process, run by one user, that calls the job queue, the isolated worker and
the artifact store directly. Install the extra (`uv sync --locked --extra desktop`; on X11 also your
distribution's `libxcb-cursor` package), run `econosim desktop`, and your work is kept in
`$ECONOSIM_HOME`, else `$XDG_DATA_HOME/econosim`, else `~/.local/share/econosim` -- created `0700`, and
refused if it is a symlink, someone else's, or readable by others. One window per directory.

- **Menu entry:** `econosim desktop --install-launcher` writes a freedesktop entry and an icon under
  `~/.local/share` (nothing elsewhere, nothing with elevated rights) pointing at *this environment's*
  interpreter by absolute path, so moving or deleting the environment breaks it; run the command
  again to repair it. `--uninstall-launcher` removes only the files it wrote.
- **Self-test:** `econosim desktop --check` runs everything but the window -- every runner's form, the
  seven explorers in child processes, one real job through the isolated worker, the findings, the
  health report, Qt and the display -- in a throwaway directory, in about ten seconds.
- **Limits:** one job at a time, up to 30 minutes of wall clock each (a constant, because the queue
  stores the policy it was created with and refuses to open under another). The thread pools are
  pinned to one thread unless you export a number, so CPU time is wall time and results match the
  reference environment.
- **Not provided:** an installer or a bundled binary, signed releases, Windows or macOS support for
  running jobs, and auto-update. See [THREAT_MODEL.md](./THREAT_MODEL.md) for the boundary.

## What is enforced where

| Control | Where | Checked by |
|---|---|---|
| Closed request-target grammar, whole-segment routing, no client-chosen upstream | gateway | `test_webgateway_routing.py` (Hypothesis), `test_webgateway_realserver.py` |
| Transport never follows redirects or reads proxy env; response ceiling | gateway | `test_webgateway_proxy.py` (real loopback servers) |
| Per-client rate limit; bounded bodies and concurrency; compute off the event loop | gateway, dashboard | `test_httpsec_*`, `test_webgateway_app.py`, `test_dashboard_hardening.py` |
| Security headers and CSP with no third-party origin | every response | the same, plus the real-browser check recorded in PR-191 |
| Every numeric parameter bounded; error pages escaped | dashboard | `test_dashboard_params.py`, `test_dashboard_hardening.py` |
| Unprivileged user, read-only root, no capabilities, health, limits | containers | `test_container_posture.py` and `docker-build.yml` (real containers) |
| Dependency, image and static-analysis scanning, weekly | CI | `.github/workflows/security.yml`, `codeql.yml` |
| Actions pinned by SHA, least-privilege tokens, job timeouts | CI | `test_supply_chain_posture.py` |
| Every committed data snapshot matches `data_cache/MANIFEST.sha256.json` on load | every snapshot loader | `test_snapshot_integrity.py` (each loader refuses an altered file) |
| Third-party data files parse to finite, unique, sorted series or fail with one contained error | the data builder | `test_data_parser_fuzz.py` |
| No secret and no sensitive file name in any tracked file; staged content scanned before a commit | CI test, opt-in hook | `test_security_scan.py`, `test_secret_scan_cli.py`, `.githooks/pre-commit` |
| Test coverage of the package stays at or above 94% (96% measured) | CI | `pyproject.toml` `fail_under`, `test_coverage_floor.py` |
| Environment matches `uv.lock`, the data manifest and the credentials file's mode | the operator, before starting | `econosim doctor`, `test_doctor.py` |
| The desktop state directory is private, one window per directory, results verified on every read | the desktop application | `test_desktop_paths.py`, `test_desktop_session.py` |
| The window never computes: jobs and explorers run in limited child processes that die with it | the desktop application | `test_desktop_session.py`, `test_desktop_explorers.py`, `test_desktop_ui_window.py` |
| Data shown in the window is text, never markup | the desktop application | `test_desktop_ui_widgets.py`, `test_desktop_ui_window.py` |
| The window refuses to start, and says why, where Qt could not | the desktop application | `test_desktop_display.py` |

## What you do not get

High availability or scale-out; distributed rate limiting; a WAF; certificate
lifecycle management; SSO/MFA; a secrets manager (the credential file is a
private, owner-only local file); audit-log retention beyond Docker's rotation;
protection against slow-header connections beyond `--max-connections` (uvicorn
has no header-read timeout, so a TLS-terminating reverse proxy with header
timeouts is the right answer for anything beyond one host); or an independent
penetration test. See [SECURITY.md](../SECURITY.md) and
[THREAT_MODEL.md](./THREAT_MODEL.md) for the full account.
