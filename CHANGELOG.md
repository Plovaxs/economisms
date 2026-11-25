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

- **Deep hedging and neural SDE recipes tuned before the freeze (Finding 21).** With the maintainer's permission. The
  hedging policy (36 recipes, then a corner-of-grid round, validated on 32 fresh seeds) went from a held-out CVaR about
  8% above the static baseline's to about 2-4% above: better than before, still not better than the baseline, so E1
  will most likely report "equivalent", not "better". E1 now freezes the tuned recipe (learning rate 0.003, 2,000
  epochs); the legacy recipe stays for Finding 8. The neural SDE (36 recipes, selected on data before 2001-03 only)
  scores better in ordinary months than both the old recipe and a constant GBM, but degrades more under the shocks
  (0, 0 and 1 of 10 seeds better than the GBM in 2001, 2008, COVID); which recipe E4 freezes is left to the
  maintainer. No reserved seed and no data after 2023-05-03 was read.
- **Three learned models tuned on validation only (Finding 20).** Neural volatility: a GJR-GARCH anchor with a
  zero-initialised correction network, ten features and 32 units, chosen from 16 configurations on 2000-2007, beats
  Finding 17's neural model on both markets (QLIKE -0.0265 and -0.0369) and GJR-GARCH on NASDAQ (-0.0197), ties it on the
  S&P 500, and still passes no conditional-coverage test at 99%. Inflation nowcast: 24 configurations, test MAE 0.2084
  against 0.2117 for Finding 18's ridge, inconclusive. Recession classifier: out-of-fold Platt recalibration did not
  lower the Brier score (+0.0036), because the model's over-confidence is not stable across periods. A look-ahead in the
  volatility study's first feature draft was caught by its leak test and fixed. Deep hedging and the neural SDE were not
  touched (frozen protocol recipes), and no untouched data was read.
- **H2's verdict revised from "partially supported" to "not supported."** The maintainer approved it. The one robustness
  result (+6.99 against +26.45 under COVID) is a single training seed; over ten seeds the neural SDE degraded less than
  the GBM in 4 of 10 under COVID, 0 of 10 in 2001 and 4 of 10 in 2008. Changed in `FINAL_PROJECT_HYPOTHESES.md` (which
  says what changed and why), the README, `RESEARCH_CONTRIBUTIONS.md`, `FINAL_PAPER.md`, `PORTFOLIO_DEMO.md` and Finding 5
  (original numbers kept). Not "rejected": the evidence is exploratory and re-used.
- **Dimension scaling measured (audit M-04, Finding 19).** `pde_solvers.dimension_scaling`: a call on the geometric
  average of d independent assets has an exact price in every dimension, so the finite-difference grid (sparse direct
  solve) and Monte Carlo are compared at matched error. At an error of 0.02 the grid takes 0.02 s at d = 1, 0.06 s at
  d = 2, **29 s and 1.3 GB of factors at d = 3**, and does not reach it at d = 4; Monte Carlo needs about 0.04 s at every
  d. No neural solver was run, and H3's verdict is unchanged but now says it has not been shown against Monte Carlo.
- **Heston's strong convergence measured (audit M-01, Finding 19).** `heston_strong_convergence_study` drives coarse and
  fine grids with the same Brownian path: order about 0.5 (log-price 0.51, variance 0.61) when the Feller condition
  holds and about 0.30 when badly violated. `stochastica.heston` now has one shared `heston_step` (bit-identical
  paths, checked).
- **Offline install (audit L-05).** `install-linux.sh --make-offline-bundle DIR` on a connected machine, then
  `ECONOSIM_OFFLINE_DIR=DIR bash install-linux.sh` on the offline one: pip runs `--no-index`, every file is checked against
  the bundle's `SHA256SUMS`, and a bundle for another Python or architecture is refused before anything changes. The
  installer-smoke script has a `SMOKE_OFFLINE=1` mode that runs the whole install, upgrade and uninstall inside a network
  namespace with no interface, and CI has an `offline` job. See `docs/release/OFFLINE_INSTALL.md`.

- **E4 designed and built** (`prometheus.confirmatory.e4_shocks`): the neural SDE against a constant GBM shock by
  shock (2001, 2008, COVID), trained only on data before each event, `patience` fixed, no pooling, no inference
  across events, seeds 20000-20009 reserved for the frozen run. **An exploratory 10-seed run found that Finding 5's
  "more robust under COVID" result is seed 0**: the neural SDE degraded less in only 4 of 10 seeds (0 of 10 in 2001,
  4 of 10 in 2008). Notes added to Finding 5 and to H2; the verdicts are not rewritten.

- **French-factor snapshot provenance recorded.** `ff3_monthly_snapshot.csv` now has a metadata file: its download date
  was never recorded (it says so), but the library's file was downloaded again and every one of the 1,203 months
  compared: identical in all four columns. The registry now has no provenance gap. The maintainer also confirmed the
  confirmatory protocol's margins, seeds, block lengths and dates as proposed (the protocol is still not frozen).

- **Decision: no AppImage or DEB.** The maintainer weighed them (gigabyte bundle, Qt LGPL obligations, glibc and
  other distributions untestable here, the audit's own advice) and chose the install script and its clean-machine
  test as the supported route. Recorded as `declined` in the audit register; revisit with an AppImage only if
  someone cannot use the script.

## [0.5.4] -- 2026-11-24 -- an installer data-loss fix, an audit response, and a signed-provenance step

The entries below were written under `[Unreleased]` during the audit response; they ship in this release.

- **A draft confirmatory protocol** ([docs/CONFIRMATORY_PROTOCOL.md](./docs/CONFIRMATORY_PROTOCOL.md)) **and the
  analysis code for it** (`prometheus.confirmatory`). The five hypotheses were frozen after most of the experiments
  ran, so every verdict is exploratory. The draft names three primary endpoints (deep hedging on fresh seeds and
  held-out paths; the inflation base-effect rule and the GARCH-FHS value-at-risk model on data that postdate the
  committed snapshots), their statistics, equivalence margins and outcome rules, and separates *untouched* from
  *prospective* from *re-used* data. `python -m prometheus.confirmatory reproduce` runs the new code on the OLD data
  and matches 14 numbers documented in Findings 8, 15 and 18 (the forecasters are the original studies', compared
  with them by tests). The commands that would read untouched data or the reserved seeds refuse to run until the
  protocol's freeze record is complete. It is still a draft: the power notes, data-use audit and data sources do not
  exist yet, and it binds nothing until the maintainer freezes and externally anchors it.

- **Installer: a data-loss hazard fixed.** `scripts/install-linux.sh` used `ECONOSIM_HOME` for its own install
  directory, but `ECONOSIM_HOME` is also where the application keeps your results (README, DEPLOYMENT). Someone who
  followed the README and then ran `install-linux.sh --uninstall` would have deleted their results. The installer
  now uses `ECONOSIM_INSTALL_DIR`, refuses to touch `ECONOSIM_HOME`, the home directory, the root, or any non-empty
  directory it did not make (checked before anything is downloaded), and marks its own directory. Releases 0.5.2 and
  0.5.3 have the old behaviour: do not set `ECONOSIM_HOME` to a directory you care about when running their
  uninstaller. 11 tests run the real script.

- **A clean-machine installer test** (`scripts/installer-smoke.sh`, `.github/workflows/installer-smoke.yml`): installs
  from a source archive of the commit into a scratch directory, checks the files, runs `econosim desktop --check` and
  `econosim doctor`, installs again over the install (an upgrade) and checks the results survive, launches the window
  on a virtual X11 display, uninstalls and checks that only the installer's own files went. Run on fresh Ubuntu 24.04
  and Debian 12 machines, and on Ubuntu 22.04 (Python 3.10) to check the installer refuses cleanly. Not Wayland, a
  physical display, or an offline install. It passed locally on Ubuntu 24.04 before it was added.

- **An audit response register** (`docs/audit/`): the 24 November 2026 technical audit's 58 work packages, risks
  and milestones, each with a status (done, partial, needs the maintainer, needs someone outside, not started),
  the files that are its evidence and what is missing; validated and rendered from data
  (`python -m prometheus.evidence.audit_register`), with the audit's weighted score recomputed (8.118) and the
  reviewer's scores pinned: **no score is changed**, because the audit's rule is that a score moves only with
  independent evidence and nothing here is independent. Also a source manifest of the commit the audit reviewed.
  Of the 58: 6 done, 42 partial, 1 needs the maintainer's decision (AppImage/DEB), 5 need someone outside the
  project, 4 not started.

- **Documents the audit asked for:** a literature map with a scoped novelty statement (20 works, abstract-level,
  not a systematic review; `docs/LITERATURE_MAP.md`), a replication guide and a replication-report issue form, a
  roadmap with a feature freeze and the audit's non-goals, a release runbook, extension points and
  compatibility, a support matrix, and a guide to verifying a release.

- **Build-provenance attestation in the release workflow** (`actions/attest`, pinned): each release file gets a
  signed SLSA provenance attestation, verifiable with `gh attestation verify`, created before the release so a
  failure publishes nothing. **Unproven until the next release runs it.**

- **The first real run of the clean-machine test found two things.** The desktop entry said `Version=1.5`, which
  `desktop-file-utils` 0.26 (Debian 12) rejects as an unknown spec version; it now says `Version=1.0`, accepted
  everywhere. And the workflow's own `| tee` hid a failing step (a state directory the application rightly refused
  for being world-readable), so the job passed; its steps now run with `pipefail`. Ubuntu 22.04 (Python 3.10)
  refused cleanly, as intended.

- **A dataset registry and a data-quality report** (`python -m prometheus.data_ingestion.dataset_registry`,
  committed under `docs/data/`, with a drift test): for each snapshot its source, licence, vintage, checksum, rows,
  dates, frequency and lineage, and checks for blank and non-numeric cells, duplicate or out-of-order dates,
  missing periods, outliers, constant columns and header drift. It found that `ff3_monthly_snapshot.csv` has no
  metadata file (its download date and raw-file digest are not recorded) and that `kaggle_term_spread_monthly.csv`
  has a column its metadata does not declare; the other warnings are gaps the metadata already explains.

- **A mutation check** (`tools/mutation_check.py`, `.github/workflows/mutation-check.yml`, no third-party tool):
  24 deliberate faults (a flipped sign, a dropped check, an off-by-one) in the ledger, the Black-Scholes closed
  forms, the risk metrics, the hedging accounting and the block bootstrap; each must make a guarding test fail. The
  first run caught 21; the three survivors were real test gaps (nothing tested a put's payoff in the hedging
  accounting, the number of bootstrap blocks, or the interval's percentile pair) and now have tests. A catalogue
  check runs with the ordinary tests so it cannot go stale.

- **A Diebold-Mariano test** (`prometheus.experiments.forecast_comparison`) with the Harvey-Leybourne-Newbold
  small-sample correction and a Bartlett long-run variance, tested against hand computation, for its size (5%), its
  power, and the case it exists for: with serially dependent differentials the naive test over-rejects and the
  long-run variance repairs it. On Finding 18's Q1 it gives -5.84 (p = 1.5e-8), agreeing with the bootstrap
  interval; exploratory, not part of the confirmatory protocol.

- **Branch coverage of the critical modules.** The five modules the mutation check targets are now covered 100% by
  statements and branches by their own guarding tests (it was 95% for the ledger and 84% for the hedging
  accounting: untested validation and an untested funding-schedule feature, now tested), and the weekly mutation
  workflow fails if that drops.

- **More verification.** Disk-full and I/O-error injection into the artifact store (nothing half-written is ever
  visible, no staging debris, the store is not wedged); the direct runner, the job engine and the desktop session
  give the same sealed result for the same recipe; Monte Carlo standard errors are calibrated and shrink like
  N^(-1/2); the repository's two SDE integrators, run on geometric Brownian motion against its exact solution on the
  same Brownian path, have strong order 0.486 and 0.489 and means equal to the closed form of each scheme; the grid
  solver is second order in space, and its observed order in time is first-to-1.5 for a payoff
  with a kink (measured and pinned, not assumed to be 2).

- **Confirmatory protocol, ready to freeze (all but the maintainer's part).** A data-use audit
  (`docs/confirmatory/DATA_USE_AUDIT.md`) found that INFLATIONCAST already scores persistence on the 2023-2026
  not-seasonally-adjusted CPI, so E2's window is *re-used*, not untouched: only months after 2026-10 are
  confirmatory. A power note (`docs/confirmatory/power_note.json`, old data only) shows that under the protocol's
  own 0.8 rule only E1 can support a verdict; E2 and E3 are estimation-only. `python -m prometheus.confirmatory
  fetch-cpi` locked a BLS seasonally adjusted CPI series in `confirmatory_data/` without printing a value; BLS
  published no index for 2025-10, so E2 now scores one single-vintage series, excludes (and lists) the 14 target
  months that need the missing level, and repeats the endpoint with the gap interpolated as a labelled sensitivity.
  Mutation checks on the new code found two real test gaps, now closed.

- **Finding 8, corrected.** Its "~1.04x-1.41x" range was attributed to 800 epochs alone; re-running the eight seeds
  gives 1.08x-1.41x at 400 epochs and 1.04x-1.19x at 800, so the range spans both budgets. The conclusion (0 of 8
  seeds beat the baseline) is unchanged.

## [0.5.3] -- 2026-11-24 -- a desktop icon on Linux, and citation metadata

- **`CITATION.cff`.** Citation metadata (CFF 1.2.0) for the repository's "Cite this repository" button. It carries
  no DOI: none exists, and minting one needs the owner to connect the repository to an archive such as Zenodo. A
  test ties its version and release date to `pyproject.toml` and this changelog, and the release workflow refuses
  to publish if the file names another version.

- **Desktop icon on Linux.** `econosim desktop --install-launcher --desktop-icon` also places an executable launcher on
  the desktop (found through `XDG_DESKTOP_DIR`, `user-dirs.dirs` or `~/Desktop`; never created), marked trusted for
  GNOME; the installer script does this by default and the System page's button does both. Only files that carry
  ECONOSIM's marker are ever overwritten or removed; uninstalling removes the icon too.

## [0.5.2] -- 2026-11-24 -- a demo edition for the web, and a Linux installer

- **Linux installer** (`scripts/install-linux.sh`, published with each release): no root; verifies the release's source
  archive against `SHA256SUMS`, installs into a private virtualenv pinned to `uv.lock` (CPU PyTorch), adds ECONOSIM
  and its icon to the application menu; `--uninstall` removes it. The release now also publishes
  `econosim-source-<version>.tar.gz`. Tested from a clean directory to `econosim desktop --check` all clear.

- **Demo edition of the web app** (`npm run build:demo`): no token screen and no backend. It answers from
  `frontend/demo-data/recording.json`, real responses recorded by `tools/record_demo.py` from the real backend
  (ten dashboard pages, seven labs, default settings). A banner says so on every page; settings that were not
  recorded are refused instead of invented. The ordinary build contains none of it. `vercel.json` now builds it.

## [0.5.1] -- 2026-11-23 -- the first release published by CI

The first release made by `.github/workflows/release.yml` (wheel, web build, SBOM, checksums), and the
fixes the first CI run of 0.5.0 forced.

### Added

- `release.yml`: continuous delivery for both editions; a manual run is a dry run that publishes nothing.
- README "Two editions": the desktop software and the web app side by side.

### Fixed

- Desktop: small windows. A minimum size (960x600); below 800 px of height pages hide their explanatory paragraphs and the disclaimer shrinks to one line (full text in the tooltip); in a narrow result pane the verdict and actions get their own row; the lab status text elides instead of squeezing the Reset button. README screenshots regenerated (they predated the menu bar).
- Desktop: the test run no longer aborts at exit (heap corruption from signal connections to closures capturing `self`); the menu bar and menus take the theme's colours whatever the desktop palette is; the overview no longer warns about a missing web-frontend build.

## [0.5.0] -- 2026-11-20 -- the desktop application (PR-205)

This release makes the project software you open. A native Qt window runs the same engine the web
stack runs -- the allow-listed runners, the queue, the isolated worker, the verified result store --
called directly, with no listener, token or port. The web app and gateway are unchanged and still
tested. It does not change this project's NO-GO gate for live trading or real capital.

### Added
- **`econosim desktop`** (PR-205): the desktop application, behind a new `desktop` extra
  (`PySide6-Essentials`, hash-locked in `uv.lock`; the Docker image does not include it). Pages:
  *Overview*, *Labs* (all 16 runners; the parameter form is generated from each runner's config type
  and read back through the real typed decoding and resource limits), *Explorers* (the dashboard's
  views, computed in child processes, with the web views' own parameter bounds), *Findings*
  (`docs/RESULTS_AND_LIMITATIONS.md` parsed, not copied), *History* (reopen, re-run, export, audit
  chain) and *System* (gate decision, preflight, verified data files, where work is kept).
- **`econosim desktop --check`**: a headless self-test of everything but the window (forms, the seven
  explorers in child processes, one real job through the isolated worker with its result verified on
  read, findings, health, Qt, display, launcher). **`--screenshots DIR`** renders every page to PNG
  with no display. **`--install-launcher` / `--uninstall-launcher`** add or remove an application-menu
  entry (marker line, symlink refusal, atomic write; validated with `desktop-file-validate`).
- **`prometheus.desktop`**: a framework-free core (state directory rules, form derivation, a generic
  result reader, a local session over `JobStore`/`Worker`/`ArtifactStore`, the explorer registry and
  its child process, health, findings, launcher, display check) and a `ui/` package that is the only
  part needing Qt. Charts are drawn with QPainter (no charting dependency): a validated palette in a
  fixed order, thin marks, a legend for two or more series, tooltips that also appear from the
  keyboard, and a table view behind every chart.
- `evidence.license_inventory.allows_mit_project`: an SPDX license-expression evaluator.
- A menu bar (File: open the work folder, Quit with Ctrl+Q; View: pages with Ctrl+1..6 and the colour
  theme; Help: About), a `system` theme mode that follows the desktop's light/dark setting live, and
  `errors.log` in the state directory for anything uncaught -- in any thread -- with a one-line notice
  in the status bar, because a program started from an application menu has no terminal.

### Security
- **No network listener at all** for this front end; the window's state lives in a `0700` directory
  that is refused if it is a symlink, someone else's, or open to group/others, one window per
  directory, results re-verified on every read and refused if edited or attached to another job.
- **Data is shown as data.** Labels are forced to plain text (Qt's default renders HTML-looking text
  as HTML), tooltips carrying data are escaped, and the Markdown view disables raw HTML and loads no
  resource. Each is mutation-tested.
- **Display failure is caught before Qt aborts.** On X11 Qt 6.5+ aborts the whole process (a core
  dump) when `libxcb-cursor` is missing; from a menu entry that is a program that silently does
  nothing. Found on a real desktop; `econosim desktop` now names the package, notifies and leaves
  `startup-error.txt`.
- Explorer calculations run in a child process with a wall-clock limit enforced by the caller, a
  generous CPU backstop, no core dumps and a parent-death signal; the child re-validates every
  parameter itself.

### Fixed

- `tests/unit/test_license_inventory.py` said LGPL was excluded from its copyleft check but matched
  the substring `GPL`, which `LGPL` contains; and the module's docstring promised a fallback to the
  legacy `License:` metadata header that was never implemented (PySide6 publishes its SPDX
  expression only there). Both now do what they said, with an evaluator that treats `A OR B` as the
  licensee's choice and requires upper-case operators as SPDX does.
- An explorer child given a 0.2 s time limit received a 1 s CPU limit and was killed by `SIGXCPU`
  within 50 ms on a many-core machine (CPU time is summed over threads), before the caller's own
  wall-clock limit could act; the CPU limit is now a backstop.

- Building the window imported a runner (and so torch, about a second and a half) for the first lab and
  started an explorer's child process, for pages nobody had opened. Both now wait for the page's first
  showing; opening the window no longer pays for either.

### Changed
- `pyproject.toml` 0.5.0, `frontend` 0.5.0, SBOM regenerated (its scope is unchanged: the service and
  recovery runtime; `desktop` is a separate, optional extra).
- CI sets `ECONOSIM_REQUIRE_DESKTOP_TESTS=1` so that a Qt that cannot be imported *fails* the window
  tests instead of skipping them, and installs Qt's runtime libraries in its existing apt step.

## [0.4.0] -- 2026-11-20 -- real-data studies, a data-timing bug found and fixed, verified data and a preflight check (PR-197 through PR-204)

This release asked the models to learn from more real data and recorded, case by case, what that did and did not buy: four Kaggle datasets behind 24 verified data files, one look-ahead bug found in our own GDP column, and five studies, recorded as Findings 13-18, two of them with their questions written down before any number was computed. It also closes the data and secret supply chain around those snapshots. It does not change this project's NO-GO gate for live trading or real capital.

### Security
- **Verified data (PR-201).** `data_cache/MANIFEST.sha256.json` records the SHA-256 and size of every
  committed snapshot and provenance file; every snapshot loader refuses a file that does not match
  (the bytes parsed are the bytes verified). `econosim data check` verifies and `econosim data write`
  regenerates it after a deliberate refresh. The manifest is not signed: it catches drift and forces a
  visible step, not a malicious committer.
- **Hardened parsers for third-party files (PR-201).** The Kaggle builder's parsers reject `nan`/`inf`
  (which previously parsed), non-positive prices, repeated dates, short rows and oversized fields, and a
  corrupted archive no longer leaks raw `zlib.error`/`BadZipFile` (nor, from the SEC-08 sandbox, `NotImplementedError`);
  all property-tested with Hypothesis.
  Rebuilding the four snapshots from the raw zips is byte-identical to the committed files.
- **Secrets (PR-201).** The secret scan knows 13 provider token formats (Kaggle, GitHub, Slack, Google,
  Anthropic, OpenAI-style, Hugging Face, npm, PyPI, Stripe, JWT) plus sensitive file names, runs over
  every tracked file in the test suite, and `.githooks/pre-commit` (opt-in: `git config core.hooksPath
  .githooks`) refuses a commit that stages one without ever printing the matched text.

### Fixed
- **A point-in-time look-ahead in `data_cache/kaggle_us_macro_monthly.csv`.** The `GDP_YOY` column
  showed each quarter's growth one to two months before the quarter ended or was released (288 of 494
  cells; Q2-2020's -7.69% appeared on the 2020-05 row, BEA's advance estimate came on 2020-07-30). The
  other four columns were correct. Found by re-deriving the file from the raw Kaggle data with a
  committed builder; corrected, guarded by a structural regression test, and every finding that
  depended on the column was re-measured (neural SDE COVID degradation +5.58 vs. +29.97 became +6.99 vs.
  +26.45; the hybrid-quantum 5-seed mean test ROC-AUC fell from 0.842 to 0.721; verdicts of H1 and H2
  are unchanged). See `docs/RESULTS_AND_LIMITATIONS.md` Finding 13.

### Added
- `econosim doctor` (PR-204): a preflight check that the Python version, the installed dependency versions (against `uv.lock`), the data manifest, a credentials file's mode and a state directory are as they should be; and a coverage floor of 94% (96% measured) that CI enforces.
- `orchestration.inflationcast_long_study` (PR-203): the inflation nowcast on 76 years of CPI index levels, with
  five questions written down before any number was computed (Finding 18). A base-effect rule (forecast the
  monthly growth, convert exactly to year-over-year) cut the error against persistence by about a third; a
  ridge regression added about 6%; macro predictors and a longer training history did not help. One more
  committed Kaggle-derived snapshot: the CPI-U index levels from 1947.
- `orchestration.market_risk_extended_study` (PR-202): a second market (the NASDAQ composite), the S&P 500
  continued to 2023-05, an asymmetric-volatility model and a neural model trained on both markets, with
  five questions written down before any number was computed (Finding 17). Leverage asymmetry lowered the
  QLIKE loss on both markets; loosening the GARCH persistence cap raised it; no VaR model passes
  conditional coverage through 2023; pooling both markets' history closed most of the neural model's gap
  to GARCH.
- `titan.garch_family` (PR-202): GARCH(1,1) and GJR-GARCH(1,1) by Gaussian quasi-maximum likelihood,
  vectorised through a linear filter (about 100 times faster than `fit_garch11`), recovering known parameters.
- Two more Kaggle-derived snapshots with provenance (PR-202): the S&P 500 continued to 2023-05-03 (the two
  vendors agree on 10,305 shared days) and the NASDAQ composite from 1980.
- `orchestration.policy_rate_study` (PR-200): the policy simulator's own Taylor baseline evaluated on
  the real Federal Reserve data (Finding 16). It is far from the real Fed (no interest-rate smoothing);
  a neural rule beats persistence but not a linear rule with the same inputs; more history helps.
- `orchestration.market_risk_study` (PR-199): the financial-risk models evaluated on 93 years of real
  S&P 500 returns (Finding 15). No VaR model passes conditional coverage over 2008-2020; GARCH with
  filtered historical simulation is closest; the neural volatility model loses to GARCH but gains the
  most from more history.
- `orchestration.recessionnet_extended_study` (PR-198): a standalone research CLI that separates
  "more history" from "more features" on identical test months. Result (Finding 14): more recessions
  to learn from lowered the logistic regression's test Brier 0.147 -> 0.095; six extra features
  improved no learned model's Brier score.
- `prometheus.data_ingestion.kaggle_build`: a committed, tested builder that re-derives the Kaggle
  snapshots from the raw files, with `--verify-baseline` to audit a committed file.
- Four real Kaggle-derived snapshots with provenance (`.meta.json`: source, licence, SHA-256 of every
  raw file): extended US macro-financial features from 1960, the Treasury 10Y-3M term spread from
  1981-09 (CC BY-NC, non-commercial), 23,323 daily S&P 500 closes (1927-2020) and the Federal
  Reserve's policy variables (1954-2017).

## [0.3.0] -- 2026-11-18 -- a production-grade security and deployment pass (PR-191 through PR-196)

This release hardens the DEPLOYABLE software and its pipeline: the web gateway,
the dashboard, the job API, the container, the CI, and the dependency supply chain.
It does not change this project's NO-GO gate for live trading or real capital, whose
remaining blockers (an independent penetration test, a legal opinion, independent
model validation) are institutional artifacts no pull request can produce.

### Security (supply chain, containers, operations, fuzzing -- PR-193 through PR-196)
- **Continuous scanning (PR-193).** A `security` workflow audits every locked Python
  dependency (pip-audit, hash-locked in its own dependency group), the frontend
  (`npm audit` plus registry-signature verification) and the built container image
  (Trivy), weekly and on every change to what gets installed; CodeQL analyses the
  Python and TypeScript sources; Dependabot proposes grouped minor/patch updates only.
  Every workflow now pins each action to a full commit SHA, declares read-only
  permissions, bounds every job with a timeout and stops persisting the checkout token
  -- all enforced by a mechanical test.
- **Real vulnerabilities those scanners found, now fixed.** The routing library shipped
  to every browser (`react-router-dom` 6.28.0) had 3 high advisories: it is now 7.18.5,
  with 0 production findings (16 -> 6 moderate dev-only), alongside vite 6.4.5, vitest
  4.1.12 and postcss 8.5.32. The pinned build tooling had 6 advisories (setuptools
  78.1.0, wheel 0.45.1): now 84.2.1 and 0.46.3, with the byte-identical double-rebuild
  verification re-run. Node 20, end-of-life since April 2026, is now Node 24. The data
  ingestion transport would have fetched `file:`/`ftp:` URLs: it is https-only.
  ruff's security rules are on, with no blanket ignore for `src/`.
- **Container hardening (PR-194).** The image runs as an unprivileged user (it ran as
  root) from digest-pinned bases (they were pinned by a mutable tag), installs only
  hash-locked wheels and no build toolchain, and runs with a read-only root, no Linux
  capabilities, `no-new-privileges`, an init process, resource limits, rotated logs and
  health checks. The published port is bound to the host's loopback (it was bound on
  every interface for a cleartext service). A new `docker-compose.prod.yml` adds real
  TLS, and CI asserts all of this on the REAL containers and completes real TLS
  handshakes.
- **Gateway operations depth (PR-195).** A bounded static cache with ETag, gzip and 304
  (the 742 kB bundle crosses the wire as 218 kB; a repeat load transfers 0 bytes), a
  `/health/ready` endpoint that reports which backend is unavailable, a graceful-shutdown
  test against a real process, and `docs/DEPLOYMENT.md`, the operator's guide.
- **End-to-end fuzzing (PR-196).** Hypothesis drives about 900 generated requests per run at the
  gateway, the dashboard and the job API -- arbitrary targets (including a grammar of hostile
  path segments), headers, queries and bodies -- and checks that none ever reaches an app's
  catch-all 500, that the gateway never contacts a host but its two configured upstreams, and
  that the dashboard never reflects caller markup. Nothing was found; it is now a property, and
  it was shown to fail when the gateway's validation is disabled.

### Fixed (PR-193 through PR-195)
- A cached 304 response of the HTML shell would have replaced the page's
  Content-Security-Policy with the API's and blanked it on the next cached load; caught
  in review before it shipped.
- Concurrent readiness probes could report a false outage for a healthy system.
- `SECURITY.md` and `docs/SECURITY_AND_DATA_HANDLING.md` still listed a threat model, an
  egress allowlist, rate limiting and data classification as missing, and said no
  advisory feed existed; all were stale and are corrected.
- The committed SBOM still named project version 0.1.0; it is regenerated from the lock.

### Security (the gateway and dashboard -- PR-191, PR-192)
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
- **The research dashboard was hardened the same way (PR-192).** Every numeric
  query parameter used to go through a bare `int()`/`float()` with no range --
  `portfolio-risk?n=100000000000` made numpy try to allocate 745 GiB (reproduced:
  an unhandled `MemoryError`; the OS refused that one, but nothing bounded a value
  just under the limit) for a caller holding only a read-only token. Every
  parameter now has an explicit range (plain decimal numbers only -- no
  `nan`/`inf`/`1_000`/Unicode digits; repeats refused; array-size product caps),
  identifier parameters are a closed character set, and validation happens before
  anything is computed. Views no longer run on the event loop (one slow view used
  to freeze every request, `/health/live` included): they run in worker threads
  under a hard cap with a per-owner rate limit, behind a generic catch-all, with a
  JSON audit line per request and security headers on every response.
- **A shared `prometheus.httpsec` package** (security headers, the bounded
  rate limiter, the bounded executor, and the one hardened uvicorn configuration)
  now backs the gateway, the dashboard and the job API, replacing three
  hand-copied keyword lists so they cannot drift apart. uvicorn's `server:`
  banner is no longer sent by any of them, and the job API gained the standard
  security headers it lacked.

### Fixed (PR-191, PR-192)
- The dashboard's HTML error pages reflected caller-supplied text unescaped
  (`model-usage?model_id=<script>...` and `export?view=<img onerror=...>` came
  back with the raw markup; reproduced against the previous code). Hostile
  identifier values are now rejected outright, and the one place every error
  page passes through escapes whatever it is given. Not remotely exploitable in
  practice -- the routes require an `Authorization` header a cross-site link
  cannot supply -- but wrong, and now fixed.
- A non-numeric parameter or a non-ASCII query string raised an unhandled
  exception in the dashboard; both are now 400s.
- Every proxied response carried two `Date` headers (found by driving the real
  stack in a browser, not by a unit test).
- A missing `/assets/x.js` was answered with the HTML shell and status 200, and
  so was any unknown `/api/*` path; both are now JSON/plain 404s. Static MIME
  types come from a fixed table instead of the host's mime database.
- A non-ASCII query string or a NUL byte in a static path raised an unhandled
  exception; both are now clean 400s.

Python test suite: 3,710/3,710 passing, 12 skipped by design (was 3,181 + 12
skipped at 0.2.0; the gateway's tests went from 28 in 4 files to over 350, and the
dashboard gained 122). Frontend test suite: 21/21 passing.

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
