# Changelog

All notable changes to ECONOSIM / PROMETHEUS-X, summarized for humans and
grouped by when they actually landed. This is a curated digest, not the
evidence trail: every line below is backed by one or more real,
independently-verified pull requests, described in exhaustive, per-PR
detail in [docs/PR_LEDGER.md](./docs/PR_LEDGER.md). The current
per-category blueprint status lives in
[CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md), and the project overview and
quickstart live in [README.md](./README.md).

Until now, this project had never cut a version release -- `pyproject.toml`
had carried `0.1.0`, unbumped, since the first commit. Entries are grouped
by real commit date (read from `git log`, UTC), not retrofitted to a
semantic-version history that never happened before `0.2.0`. Newest first.

## [Unreleased]

### Security
- **The web gateway was rewritten around a closed request-target grammar (PR-191).**
  It used to build the upstream URL by prefix-matching and string
  concatenation, so a client chose the authority of the URL the gateway
  requested -- confirmed over a real socket: `/api/jobs.attacker.example/x`
  against a portless upstream made it resolve and dial
  `jobs-api.attacker.example`, and its 502 body echoed the internal upstream
  URL. Routing is now a pure function (`webgateway/routing.py`) that matches
  whole path segments only, rejects rather than "cleans" anything outside RFC
  3986's path grammar (dot-segments, encoded slashes, NUL, `?`/`#`, non-ASCII),
  forwards the client's still-encoded path, and has its final URL authority
  re-checked against the configured upstream; a Hypothesis property test
  proves a routed path can never change the authority, escape its prefix or
  carry a query/fragment, for arbitrary input.
- **A hardened upstream transport.** The old `urllib` transport followed
  redirects (re-sending the caller's `Authorization` header to the redirect
  target and hiding the 3xx from the client), honoured `http_proxy`, spoke
  `file:`/`ftp:`, and buffered without limit. The replacement
  (`webgateway/proxy.py`, on `http.client`) never follows a redirect, never
  reads proxy environment variables, speaks http(s) only, can be pinned to the
  two configured origins, caps response size while streaming and enforces a
  total deadline, and returns generic error text.
- **Edge controls.** Per-client token-bucket rate limiting (memory-bounded; it
  sits in front of the backends' pre-authentication shared budget, which an
  unauthenticated flood could otherwise exhaust), request and response body
  ceilings, a bounded number of in-flight upstream calls, and proxied calls
  moved off the event loop (one slow backend response used to freeze every
  request, the health probe included).
- **Security headers on every response**: a Content-Security-Policy with no
  third-party origin and no `unsafe-*` source, `nosniff`, frame `DENY`,
  `no-referrer`, a deny-all `Permissions-Policy`, COOP/CORP `same-origin`, HSTS
  over HTTPS only. Enforced headers are replaced, never merged, so a backend
  cannot weaken them; server banners are dropped.
- **Fonts are self-hosted** (`@fontsource/inter`, `@fontsource/jetbrains-mono`)
  instead of loaded from Google Fonts on every page load -- which is what makes
  the strict CSP possible, and means the UI no longer contacts a third party.

### Fixed
- Every proxied response carried two `Date` headers (found by driving the real
  stack in a browser, not by a unit test).
- A missing `/assets/x.js` was answered with the HTML shell and status 200, and
  so was any unknown `/api/*` path; both are now JSON/plain 404s. Static MIME
  types come from a fixed table instead of the host's mime database.
- A non-ASCII query string or a NUL byte in a static path raised an unhandled
  exception; both are now clean 400s.

Python test suite: 3,434/3,434 passing, 12 skipped by design (was 3,181 + 12
skipped; the gateway's tests went from 28 in 4 files to 281 in 8). Frontend
test suite: 21/21 passing.

## [0.2.0] -- 2026-11-18 -- a "feels like real software" pass: error handling, a CLI, and the project's first version bump (PR-190)

### Added
- A React error boundary (`frontend/src/components/ErrorBoundary.tsx`),
  wrapping the routed page content and styled to match the existing
  dark-glass UI. Before this, a render-time exception in any page
  component white-screened the entire app with no fallback at all --
  `DataStateView` only ever covered fetch-level loading/error states, not
  render-time ones. The boundary recovers automatically on navigation
  (via a `resetKey`) or through a "Try again" button, and the sidebar
  stays usable even while a page is crashed.
- A favicon (`frontend/public/favicon.svg`), referenced from
  `index.html`. The app previously shipped with no `<link rel="icon">`
  at all.
- A single installed CLI command, `econosim` (`prometheus.cli:main`, via
  `[project.scripts]`), dispatching to each subsystem's existing
  `main(argv)` (`dashboard`, `jobs`, `recovery`, `service`,
  `webgateway`). Previously every subsystem required remembering its own
  `python -m prometheus.<name>` invocation; now `econosim dashboard serve
  --demo` (for example) works the same way after `pip install -e .`.
  Each subsystem's `main` is imported lazily on dispatch, not at
  `prometheus.cli` import time, so a base install missing the `recovery`
  or `service` extras can still run `econosim --help` or any other
  subcommand without crashing on an extra it doesn't need -- checked by
  a dedicated AST-based test, not just by inspection. Also added
  `econosim --version`, reading the real installed package metadata
  rather than a hardcoded string.
- This changelog, and the project's first version bump
  (`pyproject.toml`/`frontend/package.json` `0.1.0` -> `0.2.0`, tagged
  `v0.2.0`).

### Fixed
- `README.md`'s test-count badge had read "3,183 / 3,183 passing" since
  the figure was introduced, but `docs/PR_LEDGER.md`'s own entries from
  that same point describe 12 tests as "skipped by design, same as
  before" -- i.e. the 3,183 figure already meant *collected*, not
  *passed*, and had drifted from the actually-passing count (3,171) by
  exactly the skipped total. A real, fresh `pytest -q` run (3,181 passed,
  12 skipped, 3,193 collected -- the last 10 of which are this PR's own
  new `test_cli.py`) confirms the corrected arithmetic: 3,171 + 10 = 3,181.
  No tests were lost; the badge was just quietly citing the wrong one of
  two numbers that happen to look alike.

Frontend test suite: 21/21 passing (was 16/16, +5 for the error boundary).
Python test suite: 3,181/3,181 passing, 12 skipped by design (was
3,171/3,171 + 12 skipped, +10 for the CLI dispatcher). `ruff`/`mypy --strict`
clean on every new and touched file.

## 2026-11-16 -- 2026-11-17 -- an industrial-grade pass: CI finally goes green, the demo gets a real web server, and honest trading-readiness mechanisms (PR-184 through PR-189)

- **Fixed:** `evidence/gate_report_r0.json` had gone stale for roughly 135
  PRs with no test catching it -- fixed, with a permanent regression test
  so it can't happen silently again (PR-184).
- **Fixed:** `.github/workflows/ci.yml` had never once run successfully
  since its first commit on 2026-11-07 -- an unquoted YAML value
  (`:all:`) made the whole workflow fail to parse before scheduling a
  single job. Fixed, then hardened through seven further real,
  independently-discovered bugs surfaced by actually watching pushed CI
  runs rather than trusting local checks alone: a stale wheel-install
  path, a `mypy --strict` / numpy-version edge case, and cross-machine
  floating-point non-determinism traced to three distinct causes --
  ending in an honest admission that bit-exact replay across different
  physical machines isn't achievable, so it's gated behind an explicit
  opt-in environment variable instead of asserted by default in CI
  (PR-185; confirmed green on real run `44070069912`, closing Thrust A).
- **Added:** `prometheus.webgateway`, a small reverse-proxy ASGI app that
  serves the built React frontend and proxies `/api/jobs/*` and
  `/api/dashboard/*` to the existing backends -- replaying Vite's dev-only
  proxy rules for real, so the production build actually runs somewhere
  instead of only existing as a dev-server artifact. Packaged with a
  multi-stage `Dockerfile` and a 5-service `docker-compose.yml`. Two more
  real bugs were found and fixed by actually running the stack in CI, not
  just building it: a named-volume permission error and a
  container-startup race (PR-187; confirmed green on real run
  `44088221331`, closing Thrust B).
- **Added:** `prometheus.trading_readiness` -- mechanism-level
  implementations of 10 of the blueprint's 12 live-trading-readiness
  items: a mock broker, a pre-trade risk gate, a one-way kill switch, a
  5-role sign-off gate, position/cash reconciliation, fault injection, an
  append-only surveillance log, shadow trading, a capital risk-budget
  report, and an import-graph charter guard proving the package is never
  imported by any real code path (PR-188, PR-189). The remaining 2 items
  -- a real legal/regulatory opinion and real independent model validation
  -- honestly stay **NOT VERIFIED**: no code can produce a one-time
  external deliverable, and PR-189 says so in prose instead of faking a
  hollow schema. This project's **NO-GO for production / no live
  trading** gate decision is unchanged by any of the above.

## 2026-11-16 -- closing the final-project addendum's last four open items (PR-182, PR-183)

- POLICYLAB-RL (constrained PPO vs. a genuine Taylor rule), CONTAGION-GNN
  (a graph neural network over the interbank network), VOLTERRA-GEN (a
  conditional economic scenario generator), and a shared-vs-independent
  encoder ablation -- the last four final-project items still marked NOT
  VERIFIED -- were all built and closed (PR-182).
- MACROCORE's full multi-horizon scope closed, including a real negative
  result where the shared encoder didn't help (PR-183).

## 2026-11-15 -- a real full-stack smoke test and the final paper (PR-179, PR-180, PR-181)

- A real end-to-end smoke test of the whole web stack, and
  `docs/FINAL_PAPER.md` closing FP-22 -- a real namespace-shadowing test
  bug was found and fixed along the way (PR-179).
- A hypothesis-numbering collision between `docs/PROBLEM_STATEMENT.md`'s
  P1-P3 and `docs/FINAL_PAPER.md`'s frozen H1-H5 set, found and fixed
  (PR-180).
- A real TITAN report bundling horizon, units and cost together, closing
  FP-16 (PR-181).

## 2026-11-11 -- 2026-11-13 -- the unified React frontend, and governance/compliance closing out (PR-165 through PR-178)

- A real, unified React frontend (`frontend/`) built over every engine
  that previously only had CLI or dashboard access, plus a one-command
  dev launcher, `run_dev.sh` (PR-174).
- INFLATIONCAST built end to end with a real deep-learning dashboard GUI
  (PR-173).
- CIQ, EXP and GOV blueprint categories closed to 100% -- two-person
  approval enforcement, a RACI register, a replication digest (PR-166).
  LCH closed to 100% after a real mislabeling bug was found in
  RECESSIONNET's training data by an independent assessment (PR-168). 11
  committed reference bundles were discovered silently stale and fixed,
  with a permanent regression test (PR-169).
- The Hyprland/omarchy-style dark-glass visual language pushed further
  across the frontend, and `README.md` restructured as a readable
  project showcase rather than an accretive patch log.

## 2026-11-08 -- 2026-11-10 -- operational readiness, incident response, and five new deep-learning subsystems (PR-111 through PR-164)

- OPS, REL, DRI, AUD and GOV blueprint categories built out: SLOs, p95
  load testing, alert routing with a severity taxonomy, incident
  runbooks, tabletop drills for compromised credentials and corrupt-data
  response, and a tamper-evident hash-chained audit log -- closing most
  of those categories to 100%.
- Five new subsystems, each closing its own blueprint category:
  RECESSIONNET (with a hybrid quantum classifier challenger, plus a real
  gradient-dead-zone bug found and fixed in its angle embedding), Q-MACRO,
  a neural stochastic differential equation subsystem (NSD), a
  PDE/numerical-methods subsystem, and a multi-agent reinforcement
  learning subsystem (MAR).
- A real research dashboard subsystem (PR-159); governance, security and
  privacy registers -- license inventory, threat model, PII scan, and
  data-sharing access grants.

## 2026-11-07 -- the service layer and the bulk of the original blueprint (PR-015 through PR-110)

- The async job service and model-lifecycle tooling (checkpointing,
  retraining triggers, reproducible-inference verification); data
  governance (schema contracts with quarantine, raw/normalized/features
  storage layers, dataset provenance, license scanning); and most of the
  original 374-item blueprint's evidence base.

## 2026-11-02 -- repository foundations (PR-001 through PR-014)

- The core simulation engines: a stock-flow ledger, the macro time
  engine, STOCHASTICA (GBM/Heston), VOLTERRA (pricing), TITAN (risk), a
  CVaR-trained deep-hedging baseline, government/central-bank agents, and
  the first end-to-end demonstration run.

---

For the exhaustive, PR-by-PR account behind every line above -- including
every disclosed limitation and what each PR deliberately does *not*
claim -- see [docs/PR_LEDGER.md](./docs/PR_LEDGER.md).
