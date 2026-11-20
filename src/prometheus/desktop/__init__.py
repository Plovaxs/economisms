"""The native desktop application: ECONOSIM / PROMETHEUS-X as software you open, not a service you
browse to (PR-205 the framework-free core, PR-206 the Qt window).

**What it is.** A window over the same typed, bounded, isolated machinery the web stack already
uses -- the allow-listed runners (`orchestration.recipes`), the transactional job queue
(`jobs.store`), the isolated worker process (`jobs.worker` / `jobs.child`) and the
content-addressed, verified artifact store (`jobs.artifacts`) -- called directly, in one process,
by one local user. Nothing is reimplemented: a job started from this window passes through
`prepare_recipe` and the resource limits exactly as one submitted over HTTP does, runs in the same
resource-limited child process, and its result is read back through the same hash verification.

**What that removes.** There is no HTTP listener, no bearer token, no CORS rule, no reverse proxy
and no port. The threat model of "a service reachable over a network" has nothing to apply to
because there is no service.

**What it does not change.**

- The gate decision (NO-GO), the research-only disclaimer and every limitation in
  `docs/RESULTS_AND_LIMITATIONS.md`. The window shows the disclaimer on every page.
- It is not a security boundary against the local user: whoever can run the program can read its
  state directory. The directory is created `0700` and refused if it is not private, nothing more.
- The isolated job worker needs Linux (parent-death signalling, resource limits). On another
  platform the window opens, the explorers work, and running a job is reported as unavailable.
- The web stack (`webgateway`, `dashboard`, `service`) still exists and is still tested; this is
  an additional front door, not a replacement that deleted the old one.

**Layout.** Everything outside `ui/` is plain Python and is tested without a display;
`econosim desktop --check` exercises it in CI. `ui/` is the only part that needs the `desktop`
extra (`PySide6-Essentials`). Importing any module here is light (no Qt, numpy or torch at import
time). Reading a runner's config types and judging a recipe do load the runner modules, and so
torch, on first use -- about a second, done on a background thread at start-up (`forms.warm_up`).
What never happens in the window's own process is model code: training, simulation and every
explorer's arithmetic run in child processes, which is also what lets a job be cancelled and a
crash in one be only that job's failure.
"""
