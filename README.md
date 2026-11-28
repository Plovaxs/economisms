<div align="center">

<img src="./docs/images/banner.svg" alt="ECONOSIM / PROMETHEUS-X: classical, deep-learning and hybrid-quantum models benchmarked side by side on real data" width="100%">

<br>

[![Tests](https://img.shields.io/badge/tests-5%2C446%20passing-brightgreen)](./docs/PR_LEDGER.md)
[![CI](https://github.com/Plovaxs/economisms/actions/workflows/ci.yml/badge.svg)](https://github.com/Plovaxs/economisms/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.5.4-informational)](./CHANGELOG.md)
[![Lint & Types](https://img.shields.io/badge/ruff%20%2B%20mypy--strict-clean-brightgreen)](./CHECKLIST_STATUS.md)
[![Blueprint coverage](https://img.shields.io/badge/blueprint%20coverage-361%2F374%20(96.5%25)-blue)](./CHECKLIST_STATUS.md)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](./LICENSE)

**[Screenshots](#screenshots)** ·
**[Key findings](#key-findings)** ·
**[Get started](#get-started)** ·
**[Architecture](#architecture)** ·
**[Evidence](#the-evidence-discipline)** ·
**[Documentation](#documentation)**

</div>

> [!WARNING]
> **Research and simulation only.** Nothing in this repository is financial advice, a trading system,
> or infrastructure for live trading. The project's own gate decision is **NO-GO**, and nothing here
> changes it. See [Status & disclaimers](#status--disclaimers).

<p align="center">
  <img src="./docs/images/hero.png" alt="The desktop application and the web app side by side, both showing the INFLATIONCAST lab with a real result" width="100%">
</p>

## What this is

**Beyond Model Complexity: An Empirical Evaluation of Classical, Deep Learning, and Hybrid Quantum
Models for Quantitative Economic and Financial Tasks.** ECONOSIM (formerly PROMETHEUS) is a
from-scratch research platform that puts that question to real data, with a hard rule attached:
**nothing counts as a finding unless a specific, reproducible, currently-passing test produced it.**

It is also built to be *looked at*: two front doors over one engine, a native desktop application
and a web app, both showing live computed output rather than mock-ups.

|  |  |
|---|---|
| **Findings** | 34 numbered findings, the negative ones as prominent as the positive ones |
| **Model zoo** | 106 requested models: 28 written, 6 already here, 72 not built with their reasons; 52 hypotheses judged, 33 supported, 13 inconclusive, 6 contradicted |
| **Labs** | 16 runnable studies: forecasting, models and solvers, simulations, hedging studies |
| **Explorers** | 8 live views: economy, market paths, option pricing, hedge ratios, portfolio risk, shock transmission, experiment comparison, validation issues |
| **Data** | 29 committed data snapshots, each verified against a SHA-256 manifest every time it is read |
| **Evidence** | 361 / 374 blueprint items tied to a passing test; 5,490 tests passed in CI (Python 3.11 to 3.14) |
| **Front doors** | native Qt desktop app, React web app (with a no-install demo edition), the `econosim` CLI |
| **Make it yours** | twelve themes, a command palette (`Ctrl K`), a waybar-style status bar, an interactive 3D model web, and settings for text size, contrast, motion, colour-blind-safe charts and click targets, in both front doors ([what is checked and what is not](./docs/INTERFACE_AND_ACCESSIBILITY.md)) |

## Screenshots

Every image below was rendered from the running code: the desktop pages by `econosim desktop
--screenshots`, the web pages from the demo edition of the React app in a real browser (see
[how they are made](./CONTRIBUTING.md)). The lab results are real computations, not drawings.
The web demo shows responses recorded from the real backend at default settings and says so in a banner.

### Desktop application

Eight pages in the sidebar: **Overview**, **Labs**, **Explorers**, **Findings**, **Atlas**, **History**, **System**, **Settings**.
Dark by default; it follows your desktop's light or dark setting live, or you can pick one.

<table>
<tr>
<td width="50%"><img src="./docs/images/desktop/overview.png" alt="Desktop Overview page"><br><sub><b>Overview.</b> The project's standing (NO-GO, research only) is on every page. Installation check, data snapshots verified, jobs run and findings recorded, and three ways in.</sub></td>
<td width="50%"><img src="./docs/images/desktop/labs-parameters.png" alt="Desktop Labs page with the INFLATIONCAST parameter form"><br><sub><b>Labs, parameters.</b> Sixteen runners in four groups. The form is generated from each runner's own config type and says how close each value is to its limit before anything runs.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/desktop/labs-result.png" alt="Desktop Labs page showing a finished INFLATIONCAST result"><br><sub><b>Labs, result.</b> A real INFLATIONCAST job (about three seconds in this capture): verdict, best challenger, data source, a model comparison chart with a table twin, re-run, export and the result hash.</sub></td>
<td width="50%"><img src="./docs/images/desktop/explorers-market-paths.png" alt="Desktop Explorers page showing the market-paths fan chart"><br><sub><b>Explorers, market paths.</b> Simulated price paths and their 5th / 50th / 95th percentile fan. Each explorer is computed in a child process with the same parameter bounds as the web views.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/desktop/explorers-pricing.png" alt="Desktop Explorers page showing option value against payoff"><br><sub><b>Explorers, option pricing.</b> Closed-form Black–Scholes price and Greeks, with value and payoff across spot prices.</sub></td>
<td width="50%"><img src="./docs/images/desktop/findings.png" alt="Desktop Findings page with a searchable list of 34 findings"><br><sub><b>Findings.</b> All 34 findings from <code>docs/RESULTS_AND_LIMITATIONS.md</code>, searchable, shown as written, including the ones where the more complex model lost.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/desktop/atlas.png" alt="Desktop Atlas page: the model web with the Fourier Neural Operator selected"><br><sub><b>Atlas.</b> The model zoo as a web: models on the outer ring by family, the baselines they were judged against inside, two pipelines in the middle. Every line is an edge of a graph validated against the code and the recorded studies. Select a model for its baselines, its recorded verdicts and the finding.</sub></td>
<td width="50%"><img src="./docs/images/desktop/atlas-light.png" alt="Desktop Atlas page in the light theme"><br><sub><b>Atlas, light theme.</b> The same page; shapes, not colour alone, say which model is which.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/desktop/history.png" alt="Desktop History page listing jobs"><br><sub><b>History.</b> Every job that has run here. Results are verified against their hash each time they are opened; the queue's hash-chained audit log can be recomputed.</sub></td>
<td width="50%"><img src="./docs/images/desktop/system.png" alt="Desktop System page showing the standing of the project"><br><sub><b>System.</b> What this software may be used for, the open findings against the gate, whether the installation matches the one the results came from, and where your work is kept.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/desktop/settings.png" alt="Desktop Settings page"><br><sub><b>Settings.</b> Theme, a high-contrast variant, text size from 85% to 150% (charts included), reduced motion, and how the Atlas opens. Every change applies at once and is saved to a private file in the state directory.</sub></td>
<td width="50%"><img src="./docs/images/desktop/atlas-2d.png" alt="Desktop Atlas page in the 2D view"><br><sub><b>Atlas, 2D.</b> The same graph on rings, for when you would rather not rotate anything. The 3D web turns with the mouse, the wheel and the keyboard.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/desktop/overview-light.png" alt="Desktop Overview page in the light theme"><br><sub><b>Light theme.</b> The same Overview in the light theme.</sub></td>
<td width="50%"><img src="./docs/images/desktop/explorers-market-paths-light.png" alt="Desktop market-paths explorer in the light theme"><br><sub><b>Light theme, chart.</b> Chart colours were checked for colour-vision-deficiency separation in both themes.</sub></td>
</tr>
</table>

### Web app

<table>
<tr>
<td width="18%" valign="top"><img src="./docs/images/web/sidebar.png" alt="The web app's sidebar: eleven dashboard views and seven deep-learning labs"><br><sub><b>Sidebar.</b> Eleven dashboard views, the seven deep-learning labs, the model-zoo Atlas and Settings. Above it, a status bar with five workspaces (Alt 1 to Alt 5), the gate state, the theme and the command palette.</sub></td>
<td valign="top"><img src="./docs/images/web/overview.png" alt="Web app overview page with the demo banner"><br><sub><b>Overview.</b> The demo edition says, in a banner on every page, that its numbers are recorded real responses at default settings. Eleven views and seven engines.</sub></td>
</tr>
</table>

**Deep-learning labs.** Each runs a real training or benchmark job against real data and renders the
result with its verdict. In this demo recording the more complex model does not win in any of them.

<table>
<tr>
<td width="50%"><img src="./docs/images/web/lab-inflationcast.png" alt="INFLATIONCAST lab: mean absolute error by candidate"><br><sub><b>INFLATIONCAST.</b> CPI nowcasting on BLS CPI-U and Kaggle macro data. Verdict: classical better (naive persistence has the lowest error); the GRU's 90% intervals cover 10.7%.</sub></td>
<td width="50%"><img src="./docs/images/web/lab-recessionnet.png" alt="RECESSIONNET lab: Brier score by candidate"><br><sub><b>RECESSIONNET.</b> Recession classification on Kaggle-sourced US macro indicators. The base rate is the strongest classical candidate; the quantum interval [-0.005, 0.007] includes zero. Verdict: inconclusive.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/lab-qmacro.png" alt="Q-MACRO lab: MASE by candidate"><br><sub><b>Q-MACRO.</b> Market-factor regression on Kenneth French data. Every model beats persistence; the hybrid quantum regressor is level with AR(3). Verdict: inconclusive.</sub></td>
<td width="50%"><img src="./docs/images/web/lab-neural-sde.png" alt="Neural SDE lab: log score and CRPS by candidate"><br><sub><b>Neural SDE.</b> Proper scoring rules including a real out-of-distribution window (COVID, 2020). In this recorded run the neural SDE scores worse than the classical candidates on both log-score and CRPS.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/lab-pde-solver.png" alt="PDE solver lab: wall-clock cost and prices by method"><br><sub><b>PDE solvers.</b> Closed form, finite-difference grid, PINN and deep BSDE on the same option. At these recorded default settings the grid matches the closed form (10.4481 vs 10.4506) and the two neural solvers do not.</sub></td>
<td width="50%"><img src="./docs/images/web/lab-marl.png" alt="Multi-agent RL lab: household utility, single-agent versus co-learning"><br><sub><b>Multi-agent RL.</b> A PPO household policy trained alone versus co-learning. Verdict: single-agent better (mean household-utility difference −12.593).</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/lab-rl-hedge.png" alt="RL hedging lab: CVaR of the static baseline versus the RL policy"><br><sub><b>RL hedging.</b> A REINFORCE policy against a static delta-hedge baseline, judged on CVaR (lower is better): 8.476 static against 9.278 for RL. Verdict: static better.</sub></td>
<td width="50%"></td>
</tr>
</table>

**Model zoo.** The Atlas, the same web as the desktop page, read from a file the Python registry exports (a test fails if it goes stale), so it needs no backend.

<table>
<tr>
<td><img src="./docs/images/web/atlas.png" alt="Web Atlas page: the model web, the selected model's card and the counts"><br><sub><b>Atlas.</b> 106 models were requested; 28 are written in the zoo, 6 were already here, 72 are deliberately not built (a collapsed list gives each reason). The card shows what the selected model was judged against and its recorded verdicts.</sub></td>
</tr>
</table>

**Dashboard views.** Eleven views over the simulation and evidence subsystems.

<table>
<tr>
<td width="50%"><img src="./docs/images/web/economy.png" alt="Economy explorer"><br><sub><b>Economy explorer.</b> A household and firm economy stepped forward with real posted ledger transactions and drawn macro shocks.</sub></td>
<td width="50%"><img src="./docs/images/web/balance-sheets.png" alt="Balance sheets"><br><sub><b>Balance sheets.</b> A portfolio that only a token authorised for its owner can reach. Assets, liabilities, equity and whether the books reconcile.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/market-paths.png" alt="Market paths"><br><sub><b>Market paths.</b> Simulated GBM paths; 5th, 50th and 95th percentile of the terminal value.</sub></td>
<td width="50%"><img src="./docs/images/web/pricing.png" alt="Pricing diagnostics"><br><sub><b>Pricing diagnostics.</b> Closed-form Black–Scholes price and Greeks.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/hedge-actions.png" alt="Hedge actions"><br><sub><b>Hedge actions.</b> The delta-hedge ratio at each step of one simulated path, computed from information available at that step only.</sub></td>
<td width="50%"><img src="./docs/images/web/portfolio-risk.png" alt="Portfolio risk"><br><sub><b>Portfolio risk.</b> Historical VaR, Expected Shortfall and maximum drawdown over a P&amp;L series.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/experiments.png" alt="Experiment comparison"><br><sub><b>Experiments.</b> Every real comparison the project has run, including each null and negative result, with a verdict.</sub></td>
<td width="50%"><img src="./docs/images/web/audit-trail.png" alt="Audit trail"><br><sub><b>Audit trail.</b> A model registry's state transitions: who moved a model from evaluated to approved, and why.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/validation-issues.png" alt="Validation issues"><br><sub><b>Validation issues.</b> The tracked findings log, with severity, owner and disposition.</sub></td>
<td width="50%"><img src="./docs/images/web/model-usage.png" alt="Model usage"><br><sub><b>Model usage.</b> Check whether a model is authorised for a given application.</sub></td>
</tr>
</table>

### Make it yours

A command palette over every page, theme, switch and model; twelve themes in the spirit of the omarchy and
Hyprland rices (each one held to WCAG contrast in the tests); and an interactive 3D model web. Everything is
in the **Settings** page and keyboard-reachable. [docs/INTERFACE_AND_ACCESSIBILITY.md](./docs/INTERFACE_AND_ACCESSIBILITY.md)
says what is verified, and what is not (no screen reader was used, and nothing here is a conformance claim).

<table>
<tr>
<td width="50%"><img src="./docs/images/web/atlas-3d.png" alt="The 3D model web: spheres, the selected model highlighted, pipeline flows as moving dots"><br><sub><b>3D model web.</b> Drag to orbit (it coasts), scroll or pinch to zoom, click to select, arrow keys rotate, <code>[</code> and <code>]</code> step through models. Lines show what each model was judged against; dots flow along the pipelines. No dependency: a hand-written canvas engine.</sub></td>
<td width="50%"><img src="./docs/images/web/settings.png" alt="The Settings page with twelve theme cards and groups of switches"><br><sub><b>Settings.</b> Twelve themes with a palette preview, text size, typeface, line spacing, motion, panel transparency, contrast, colour-blind-safe charts, focus ring, 44 px targets, layout, 3D quality, export and import.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/palette.png" alt="The command palette open, filtered to a theme"><br><sub><b>Command palette</b> (<code>Ctrl K</code>). Pages, themes, accessibility switches and every model of the zoo, with fuzzy search.</sub></td>
<td width="50%"><img src="./docs/images/web/shortcuts.png" alt="The keyboard shortcuts dialog"><br><sub><b>Shortcuts</b> (<code>?</code>). <code>Alt 1</code> to <code>Alt 5</code> switch workspace, <code>Alt T</code> the theme, <code>Alt M</code> motion.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/theme-catppuccin-latte.png" alt="The Catppuccin Latte light theme"><br><sub><b>Light.</b> Catppuccin Latte. The glass panels tint with the ink on light themes.</sub></td>
<td width="50%"><img src="./docs/images/web/theme-gruvbox.png" alt="The Gruvbox theme"><br><sub><b>Gruvbox.</b> One of twelve; the others are Aurora, Tokyo Night, Catppuccin Mocha, Rosé Pine, Nord, Kanagawa, Everforest, Matte Black and two high-contrast sets.</sub></td>
</tr>
<tr>
<td width="50%"><img src="./docs/images/web/theme-tokyo-night.png" alt="The Tokyo Night theme"><br><sub><b>Tokyo Night.</b></sub></td>
<td width="50%"><img src="./docs/images/web/access-large-text.png" alt="Large text, the high-contrast light palette and a strong focus ring"><br><sub><b>Accessibility.</b> 130% text, the high-contrast palette, hard borders, large targets and a strong focus ring, all together.</sub></td>
</tr>
</table>

## Key findings

Five falsifiable hypotheses were frozen on 2026-11-11 against the evidence gathered through that date;
see [docs/FINAL_PROJECT_HYPOTHESES.md](./docs/FINAL_PROJECT_HYPOTHESES.md) for the full,
retrospectively-frozen record and its own honest caveat about what that means for evidentiary weight.
After that date the questions don't change; the evidence for or against them can, with every revision
disclosed. The pattern across all five, and across the newer findings: **the more complex method
winning was the exception, not the rule**, and the exceptions that did appear were earned by ruling out
confounds directly, not by re-running until a result looked good.

| ID | Question | Verdict |
|---|---|---|
| **H1** | Does a hybrid quantum-classical model beat classical baselines on recession classification / factor regression? | **Rejected.** Tested 3 independent ways (2 real datasets, 2 task families); every bootstrap CI includes zero. |
| **H2** | Does a neural SDE beat classical baselines in-distribution, and degrade less under a real shock? | **Not supported** (revised 2026-11-25; was "partially supported"). Not better in-distribution, and the one robustness result (+6.99 vs. a GBM baseline's +26.45 under COVID) is a single training seed: over 10 seeds the neural SDE degraded less in 4 of 10 under COVID, 0 of 10 in 2001 and 4 of 10 in 2008. |
| **H3** | Does a neural PDE solver (PINN/deep-BSDE) earn its cost over a classical grid at high dimension? | **Supported**, crossover measured not assumed. Revised 2026-11-13 once an undertrained baseline was caught and fixed (grid's accuracy edge over deep-BSDE: ~580x → ~2x; verdict unchanged). |
| **H4** | Can naive fixed-epoch training or an unaudited reward silently produce a false conclusion? | **Supported, twice**, independently (RECESSIONNET's early-stopping fix; MARL's reward-design fix). |
| **H5** | Does a REINFORCE hedging agent beat a well-specified static baseline? | **Rejected.** Still loses after fixing a real reward/metric mismatch and training 10–20x longer (gap narrowed ~2.5x → ~1.04–1.41x, still a loss). |

<details>
<summary><b>Two checks run after the freeze, and the newest findings (27 to 34)</b></summary>

<br>

Two further checks, run after the freeze (disclosed as such, not folded into H1 to H5): a textbook
recession predictor (the US Treasury 10Y-3M yield-curve spread) was added to RECESSIONNET as a real
feature and made things **worse**, not better (ROC-AUC 0.71–0.85 without it vs. 0.35–0.83 with it,
across the same 5 seeds), plausibly because an already data-starved model gained one more dimension to
fit. And a "train harder" pass across all seven deep-learning subsystems found two defaults were already
*correct*: the neural SDE's one clearly positive result collapses under more training, and the
Brier-score-vs-ROC-AUC trap on RECESSIONNET's Kaggle data is real (an inverted ranking at one seed that
only a second diagnostic exposes), but its first, 'seed 0' form turned out to be partly a data
look-ahead we then found and fixed (Finding 13).

The latest findings concern the simulated economy (`worldsim`) and how far it can be tied to real data:

- **Finding 27.** Closing the loops between households, banks, the state and the rest: the connected
  economy transmits shocks the unconnected one absorbs, a sovereign default is mostly a consequence of a
  banking crisis, and leaning against leverage backfired.
- **Finding 28.** Estimating the economy's parameters from real data instead of choosing them: the first
  attempt did worse than the chosen parameters out of sample, a revision that tied the output gap to real
  GDP did not, and the claim that connecting the sectors makes shocks travel survived both.
- **Finding 29.** Estimating the banks from real FDIC data: matching the level of bank earnings, capital
  and loan losses is easy, matching their behaviour is not, and a second attempt that changed the model's
  structure did worse. With the extensions switched on, the estimated banks all fail in most 20-year
  paths, which is a caveat on Findings 27 and 28.
- **Findings 30 to 34, the model zoo** (see [Model zoo](#model-zoo)): small neural operators, continuous-
  dynamics models and mesh-free PDE solvers; seven deep forecasters; deep equilibrium nets, a differentiable
  portfolio layer, a graph network, double ML, DeepIV and DeepSurv; quantum algorithms on an ideal simulator and
  tensor trains; and two pipelines in which one model feeds the next. 52 hypotheses, written before each run,
  judged against exact answers or classical methods.

</details>

See [docs/RESULTS_AND_LIMITATIONS.md](./docs/RESULTS_AND_LIMITATIONS.md) (34 numbered findings, each with
its own re-runnable test) and [docs/RESEARCH_CONTRIBUTIONS.md](./docs/RESEARCH_CONTRIBUTIONS.md) for the
full account behind every line above, or [docs/FINAL_PAPER.md](./docs/FINAL_PAPER.md) for all of it
assembled into one linear final-project paper, limitations and null/negative experiments included by name.

## The evidence discipline

**"Evidenced" means exactly one thing here: a passing automated test in this repository links to that
specific checklist item.** Not a design document, not a docstring, not a plan: a test that runs today,
cross-checked against a closed form, an independent numerical method, or real data wherever one exists,
with `ruff` and `mypy --strict` clean on every touched module. Nothing is marked done on the strength of
a specification alone, and every PR states plainly what it does *not* cover.

| | |
|---|---|
| Blueprint items evidenced | **361 / 374** (96.5%) across 29 categories |
| Categories at 100% | API, AUD, CIQ, DOC, DRI, ECO, EXP, GOV, HDG, LCH, LED, MAR, MLO, NSD, OPS, OPT, PDE, PRI, REL, RISK, SDE, UIX, VAL |
| Test suite | **5,490 passed, 16 skipped** (5,506 tests; the count in the green CI run of commit `35fe98e`, Python 3.11 to 3.14, `uv run pytest -q`; four of the skips need `desktop-file-utils` or the full git history, which the CI image lacks, and 12 more are skipped by design); **356 / 356** passing (`frontend/`'s separate Vitest suite, in the same commit's green frontend CI run) |
| Lint & types | `ruff` clean, `mypy --strict` clean |
| Pull requests | ledger entries through PR-231, each independently verified |

For the full per-category breakdown, see [CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md). For the detailed,
PR-by-PR account of what was built and how each claim was verified, see
[docs/PR_LEDGER.md](./docs/PR_LEDGER.md). For a shorter, human-curated summary of what changed and when,
see [CHANGELOG.md](./CHANGELOG.md). The project is built against two governing specifications, the
original [374-item master blueprint](./docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf)
and the [PROMETHEUS-X final-project addendum](./docs/PROMETHEUS_X_Final_Project_Integrated_Blueprint.md),
and tracks its own progress against both, in public.

**Live visual dashboards** (Claude Artifacts, kept in sync with each PR): the
[blueprint coverage dashboard](https://claude.ai/artifact/HChLfAPJQfvUasBbLP4fxj) tracks the 374-item
checklist by category, and the [simulation dashboard](https://claude.ai/artifact/Eit5ePvaZhWDgbSXSQhV5w)
charts real output from the economy, market-path, hedging and portfolio-risk subsystems. Both must be
shared from their Share menu before a link works for anyone other than the account that owns them. **The
deep-learning demo itself is a real app, not an Artifact**: the desktop application and the React
frontend run any of the deep-learning subsystems and render the real result.

## Get started

New here? The quickest way to see all of it is the [desktop application](#desktop-application).
[docs/PORTFOLIO_DEMO.md](./docs/PORTFOLIO_DEMO.md) is a 10-minute guide to running the real test suite,
starting the real research dashboard and spot-checking a real finding yourself.

### Two editions

The same engine, two front doors. Pick one; neither removes the other.

| | **Desktop software** | **Web app** |
|---|---|---|
| Start it | Linux: `bash install-linux.sh` (from the release; no root; adds an icon to the menu and the desktop; [offline install](./docs/release/OFFLINE_INSTALL.md) from a bundle). Any system: `pip install -e '.[desktop,quantum]'` from a checkout, then `econosim desktop` | `docker compose up`, or `python -m prometheus.webgateway serve --dist frontend/dist` |
| What it is | a native Qt window; no server, port or token | React frontend + API gateway in the browser |
| Needs | Linux for running jobs; `libxcb-cursor0` on X11 | Docker, or Python + a built `frontend/dist` |
| Details | [Desktop application](#desktop-application) | [Web app](#web-app), [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) |

A third, lighter way to look: the **demo edition** of the web app needs no install, no token and no
backend. It shows real responses recorded from the real backend (default settings only, clearly
labelled); see [frontend/README.md](./frontend/README.md#the-demo-edition-what-vercel-hosts-no-backend-no-token).
It is what the web screenshots above show.

<details>
<summary><b>Why the Linux installer uses the source archive and not the wheel, and what was not tested</b></summary>

<br>

The labs read the committed `data_cache/` next to the source tree and a wheel does not carry it, so a
wheel install opens but its data-driven labs cannot run (found by testing a clean install; the wheel is
still published for the API). The installer pins every dependency to `uv.lock`, so `econosim doctor`
agrees with the install, and was tested here from nothing to "desktop check: all clear" (real job run,
data files verified). **Not tested:** Windows and macOS (no installer, jobs need Linux there), and a
graphical launch from the menu entry on a machine other than this one.

Every tagged release (`v*`) is built by [`release.yml`](./.github/workflows/release.yml) and published as
GitHub Release files: the reproducibly built wheel (desktop and API), the web build as a tarball, the SBOM
and `SHA256SUMS`. The workflow can also be run by hand without publishing anything.

</details>

### Quickstart (from a checkout)

```bash
python3 -m pip install --require-hashes --only-binary=':all:' -r requirements/bootstrap.txt
uv sync --locked --all-extras --group build
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
  uv run --locked --all-extras pytest
uv run --locked --all-extras ruff check src tests tools
uv run --locked --all-extras mypy --strict src tools/reproducible_build.py
```

(Some tests are skipped by default; see "How to verify the evidence above yourself" in
[CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md) for the optional, own-machine-only way to run them.)

<details>
<summary><b>One-command smoke test: replay a recorded run and check its hash</b></summary>

<br>

This replays a recorded reference run and checks the result hash, rather than waiting on the full suite.
It is a genuine, repeatedly-confirmed reproducibility guarantee on one consistent machine (seed,
dependency versions and thread count all pinned). It is NOT a claim that any two different machines
compute an identical hash: confirmed directly when this project's own CI runner, matching every pinned
dependency version and thread setting, still diverged from this sandbox's recorded hash in the last bit
or two of an `exp`/`log` call (IEEE 754 does not require those bit-exact across different hardware, only
the four basic arithmetic operations).

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
  uv run --locked --all-extras python -m prometheus.orchestration.replay \
  evidence/api_reference.json --require-integrity --output dist/reference-replay.json
```

</details>

Requires Python 3.11+. Core dependencies are `numpy`, `scipy` and `torch`; optional extras add a local
service layer (`uvicorn`, `jsonschema`), encrypted local recovery (`cryptography`), the native desktop
application (`PySide6-Essentials`) and hybrid quantum-classical ML (`pennylane`, `pennylane-lightning`;
see [`src/prometheus/quantum/`](./src/prometheus/quantum/)). See [`pyproject.toml`](./pyproject.toml) for
the full dependency and extras list.

## Desktop application

The same research engine as software you open, instead of a service you browse to. A native window (Qt,
through `PySide6-Essentials`) over the very machinery the web stack uses (the allow-listed runners, the
transactional job queue, the isolated worker process and the hash-verified result store), called directly
by one local user. There is no HTTP listener, no token, no port and no browser. The web app and its
gateway still exist and are still tested; this is an additional front door, not a replacement.

```bash
uv sync --locked --extra desktop             # adds PySide6-Essentials, hash-locked like every other dependency
sudo apt install libxcb-cursor0              # Debian/Ubuntu: the one system library Qt 6.5+ needs on X11
econosim desktop                             # open the window
econosim desktop --install-launcher          # add ECONOSIM to your application menu (--uninstall-launcher removes it)
econosim desktop --check                     # self-test everything but the window, headlessly (~10 s)
econosim desktop --screenshots docs/shots    # render every page to PNG with no display at all
```

- **Labs** run any of the 16 runners (INFLATIONCAST, RECESSIONNET, Q-MACRO, the neural SDE, the PDE
  solvers, multi-agent RL, the RL hedging agent, the economy and monetary simulations and the hedging
  studies) as an isolated job. The parameter form is *generated from each runner's own config type*, so
  it cannot drift from what the runner accepts; what you enter is judged by the same typed decoding and
  resource limits a queued job faces, the result is re-verified against its hash every time it is
  opened, and a running job can be cancelled.
- **Explorers** are the dashboard's views (economy, market paths with the 5th/50th/95th percentile fan,
  option pricing and Greeks, hedge ratios, portfolio VaR/ES, shock transmission, experiment comparison,
  validation issues), each computed in a child process with the same parameter bounds as the web views.
- **Findings** shows `docs/RESULTS_AND_LIMITATIONS.md` as it is written (parsed, not copied): all 34
  findings, the negative ones exactly as prominent as the positive ones. **Atlas** shows the model zoo
  as a web (see [Model zoo](#model-zoo)).
- **History** lists every job, reopens a result, loads its settings back into the lab, exports it and
  recomputes the queue's hash-chained audit log. **System** states the NO-GO gate decision, the preflight
  checks, the 29 verified data files and where your work is kept (`$ECONOSIM_HOME`, else
  `~/.local/share/econosim`, created `0700`).
- **Menu bar and settings.** *File*: open the folder where your work is kept, Quit (Ctrl+Q). *View*: the
  pages (Ctrl+1 to Ctrl+8) and the colour theme: `system` follows your desktop's light/dark setting
  live, or choose dark or light. *Help*: About, which states the version, the gate decision and the
  disclaimer. Anything uncaught is written to `errors.log` in the state directory (a program started from
  a menu has no terminal), and the status bar says so.

Every chart is drawn by this project's own QPainter code (no charting dependency) with a categorical
palette that was run through a colour-vision-deficiency separation check in both themes, a legend for two
or more series, tooltips that also appear from the keyboard, and a table view behind it. Text that comes
from a result is always shown as text, never interpreted as markup.

**What it is not.** It is not a production system or an advice tool: the window says *research only* and
shows the NO-GO gate on every page. It is not a security boundary against whoever already runs as you. It
is not a packaged binary: you install it from this repository. Running a job needs Linux (the isolated
worker uses parent-death signalling and resource limits); on another platform the explorers and the
findings work and the lab says why it cannot run. Q-MACRO fetches its factor file from an allow-listed
host (and says so on its page); everything else runs offline. The Qt wheel is LGPL-3.0-licensed; see
[docs/LICENSE_INVENTORY.md](./docs/LICENSE_INVENTORY.md) for what that does and does not oblige you to do
if you ever redistribute a bundle.

**If the window does not open.** `econosim desktop` checks first and says so instead of aborting: on X11
Qt needs `libxcb-cursor` (found missing on the author's own desktop; the command printed the package to
install, sent a desktop notification and wrote `startup-error.txt` into the state directory, because a
menu entry has no terminal). `econosim desktop --check` reports the same in its `display` step.

## Web app

A Vite + React + TypeScript app (`frontend/`) over a real, authenticated research dashboard and a jobs
API, rendering live computed output from every subsystem, with owner-scoped portfolio access and real
HTTP authorization boundaries, not a mock-up.

```bash
./run_dev.sh                 # the whole stack with hot reload, for working on the frontend
docker compose up --build    # the already-built artifact, nothing installed locally but Docker
python -m prometheus.dashboard serve --demo   # only the research dashboard (or: econosim dashboard serve --demo)
```

- **`./run_dev.sh`** starts the whole stack with one command; see [frontend/README.md](./frontend/README.md).
- **`docker compose up --build`** runs the built artifact through a `prometheus.webgateway` reverse-proxy
  service, which is also the deployment's hardened edge: a closed request-target grammar, per-client rate
  limiting, bounded bodies, security headers and a Content-Security-Policy with no third-party origin (see
  [SECURITY.md](./SECURITY.md) and [docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md)). The container runs as an
  unprivileged user with a read-only root, no capabilities and health checks, bound to loopback by default,
  with a real TLS overlay. [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) is the operator's guide, including what
  the deployment does NOT give you.
- **Data integrity.** Every committed data snapshot is verified against `data_cache/MANIFEST.sha256.json`
  whenever a loader reads it, the parsers for third-party data are fuzzed, and a pre-commit hook plus a
  whole-repository test refuse secrets (see [SECURITY.md](./SECURITY.md)).
- `/dashboard/inflationcast` benchmarks five real CPI-nowcasting candidates live against real BLS and
  Kaggle data.
- **Interface.** A status bar with workspaces, a command palette (`Ctrl K`), twelve themes, a Settings page
  (text size, contrast, motion, colour-blind-safe charts, large targets, layout) and an interactive 3D model
  web, with no new dependency and nothing that the gateway's Content-Security-Policy would refuse; see
  [docs/INTERFACE_AND_ACCESSIBILITY.md](./docs/INTERFACE_AND_ACCESSIBILITY.md).

None of this changes the project's NO-GO gate for live trading.

## Model zoo

`prometheus.modelzoo` collects small, from-scratch reference implementations of the model families a
quantitative-economics programme is asked about, each judged against something with a known answer. It is
**not** a replication of any cited paper at that paper's scale. A registry says what became of every model
in the request (106 of them): **28 written here**, **6 already in this repository**, **72 deliberately not
built**, each with its reason (the theorem provers need Lean and a language model; the many-electron
wavefunctions need chemistry software; several need data this project does not hold). A graph links them and
every edge is checked against the code and the records by `econosim modelzoo validate`.

| Family | Written | Judged against | What was found (Findings 30 to 34) |
|---|---|---|---|
| Operators and dynamics | FNO, DeepONet, Neural ODE and CDE, HNN, SympNet | closed-form Black-Scholes, exact flows | structure kept what it promised (energy drift 0.0009 against 0.022 for the plain Neural ODE); a plain MLP matched the FNO |
| Mesh-free PDE solvers | DGM (European and American put), Deep Ritz, Deep Kolmogorov | closed form, binomial tree, finite differences, Monte Carlo | DGM within 1% and 4%; finite differences beat Deep Ritz; Monte Carlo beat Deep Kolmogorov |
| Forecasting | N-BEATS, N-HiTS, PatchTST, DeepAR, TFT-lite, S4D, Mamba-style SSM | Finding 18's ridge and base-effect rule on 277 test months | none distinguishable from the ridge; DeepAR's 80% interval covered 66% |
| Macro, portfolio, causal | deep equilibrium nets, a differentiable QP layer, a graph network, double ML, DeepIV, DeepSurv | exact growth policy, value-function iteration, Leontief inverse, OLS, linear Cox | the equilibrium net matched the exact policy; decision-focused learning matched predict-then-optimise; DeepIV lost to OLS on the metric used |
| Quantum and tensor | amplitude estimation, QAOA, VQE, a quantum reservoir, tensor trains | Monte Carlo, exact diagonalisation, an echo-state network | amplitude estimation beat Monte Carlo until 1% noise per call; a kinked payoff is not low-rank |
| Pipelines | operator surrogate to hedge to tail risk; simulated banks to quantum estimation to tail risk | `titan.risk_metrics` | both chains end at the number the classical tool gives (the surrogate hedge is 2.5 times noisier than the exact one) |

```mermaid
flowchart LR
    fno["Fourier Neural Operator"] ==> hedge["Delta hedge"] ==> titan["Tail risk (titan)"]
    banks["Simulated banks"] ==> qae["Amplitude estimation"] ==> titan
```

```bash
econosim modelzoo coverage      # what became of each requested model
econosim modelzoo validate      # check the registry against the code and the records
econosim modelzoo neighbours fno
```

The quantum part runs on a state-vector simulator written for this purpose: no hardware, and the
amplitude-estimation advantage is measured in calls to the state preparation on a noiseless machine. The
simulated inputs (production networks, causal and survival data, stock paths, the banking system) say
nothing about any real economy. Every hypothesis was written and committed before its run, and a test
recomputes each stored verdict from the numbers beside it.

## Architecture

```mermaid
flowchart LR
    DATA["data_cache/<br/>real snapshots<br/>+ SHA-256 manifest"]

    subgraph ENG["Engines"]
        E1["Economy and markets<br/>econosim · worldsim · marl<br/>stochastica · volterra"]
        E2["Learning<br/>neural_sde · pde_solvers · recessionnet<br/>inflationcast · macrocore · quantum"]
        E3["Risk and hedging<br/>titan · hedging · policylab"]
    end

    RUN["Allow-listed runners<br/>→ job queue → isolated worker<br/>→ hash-verified results"]
    DASH["Dashboard API<br/>(authenticated)"]
    JOBS["Jobs API<br/>(authenticated)"]
    GW["webgateway<br/>static files + reverse proxy"]
    WEB["Web app<br/>React"]
    DESK["Desktop app<br/>Qt, no port, no token"]
    EVID["Evidence layer<br/>tests · gate report (NO-GO)<br/>checklist register · PR ledger"]

    DATA --> ENG
    ENG --> RUN
    ENG --> DASH
    RUN --> JOBS
    JOBS --> GW
    DASH --> GW
    GW --> WEB
    RUN --> DESK
    ENG --> DESK
    ENG -.-> EVID
```

<details>
<summary><b>Project structure</b></summary>

```
src/prometheus/
  core/            money, double-entry ledger, business-day calendar, RNG seed hierarchy
  econosim/        household/firm/bank/government agents, Economy wiring, point-in-time
                   macro data, macro time engine, central bank, market clearing,
                   step-hooks orchestration, data quality monitoring
  modelzoo/        small reference implementations of operators, dynamics, mesh-free solvers, deep forecasters,
                   macro, portfolio, causal and quantum models, the registry and graph that link them, and
                   the pipelines in which one feeds the next (Findings 30 to 34)
  worldsim/        a reduced-form simulated world joining economy, asset markets, households and
                   banks; estimated against real data (Findings 27 to 29)
  stochastica/     GBM, Heston, Merton jump-diffusion, regime-switching, historical calibration
  neural_sde/      drift/diffusion network trained on real macro data, proper scoring rules,
                   multi-seed/multi-solver sensitivity, real-event OOD evaluation, model card
  volterra/        Black-Scholes, Heston & Merton pricers, barrier/Asian/American options, Greeks
  pde_solvers/     classical finite-difference, PINN and deep BSDE solvers for the Black-Scholes
                   PDE (and a correlated multi-asset basket generalization), cross-checked against
                   closed-form/Monte Carlo and each other
  marl/            PPO-trained household/firm policies and rule-based bank/central-bank policies
                   over the real econosim ledger environment, with welfare, nonstationarity and
                   OOD-shock diagnostics
  policylab/       a constrained PPO central-bank policy-rate agent in a small reduced-form macro environment
  titan/           VaR, Expected Shortfall, factor exposure, stress testing, portfolio optimization
  hedging/         delta/no-trade-band baselines, self-financing simulator, CVaR-trained MLP policy
  macrocore/       classical forecasting baselines (persistence/AR/VAR), rolling-origin backtests,
                   and a point-in-time-safe Q-MACRO regression benchmark (real Mkt-RF, h-months-ahead)
  recessionnet/    point-in-time-safe recession classification: real NBER labels, real factor
                   features, logistic/classical-MLP/hybrid-quantum model comparison
  inflationcast/   real monthly US CPI-U nowcasting with release-timing discipline
  quantum/         differentiable quantum circuit layer (PennyLane) and hybrid classifier/regressor
                   models shared by recessionnet and macrocore
  encoders/        shared-versus-independent encoder ablation
  experiments/     bootstrap CIs, manifests, holdout splits, leakage diagnostics, benchmarks
  evidence/        model cards, gate reports, model registry, champion/challenger comparison
  service/         authenticated HTTP API, pricing/risk reports, deploy manifests
  dashboard/       authenticated research dashboard: economy/market/pricing/hedging/risk views,
                   experiment comparison, audit trail, provenance labels, reproducible exports
  webgateway/      static-file server and reverse proxy in front of the two backends
  httpsec/         HTTP hardening shared by the ASGI apps: security headers, rate limiting, request limits
  jobs/            durable, bounded research-job queue and worker
  desktop/         the native desktop application (framework-free core; Qt only under ui/)
  recovery/        authenticated encrypted local job snapshots and verified recovery
  data_ingestion/  external data source connectors (point-in-time schema)
  orchestration/   demo, benchmark/study and replay runners
  confirmatory/    analysis code for the draft confirmatory protocol: reproduces Findings 8, 15 and 18 on
                   the old data, and refuses to read untouched data until the protocol is frozen
  trading_readiness/ mock-only mechanisms for the EXT checklist; no network, no broker SDK, never imported
                   by the service, dashboard or jobs (see Status & disclaimers)
tests/
  unit/            one behavior per test, no hidden randomness
  property/        Hypothesis-based invariant and extreme-input testing
docs/
  PR_LEDGER.md     the full PR-by-PR evidence log
  implementation/  the machine-readable checklist register
```

</details>

## CLI

Once installed (editable or otherwise), every subsystem is also reachable through one command,
`econosim`, instead of its own `python -m prometheus.<name>` invocation:

```bash
econosim --help                     # list subsystems
econosim dashboard serve --demo     # same as: python -m prometheus.dashboard serve --demo
econosim webgateway serve --dist frontend/dist
econosim desktop                    # the native desktop application (needs the `desktop` extra)
econosim desktop --check            # headless self-test of the desktop application's engine
econosim doctor                     # preflight: deps match uv.lock, data manifest, credentials mode
econosim data check                 # verify data_cache/ against its manifest
econosim modelzoo coverage         # the model registry: what became of each requested model
econosim recovery keygen --output recovery.key
econosim --version
```

`econosim` is a thin dispatcher (`src/prometheus/cli.py`) over each subsystem's own, already-tested
`main(argv)`; nothing is reimplemented. Each subsystem's import is lazy, so `econosim --help` and
subsystems that need no extra dependency still work on a base install that never opted into `recovery` or
`service`.

## Documentation

| If you want to... | Read |
|---|---|
| Evaluate the project in ten minutes | [docs/PORTFOLIO_DEMO.md](./docs/PORTFOLIO_DEMO.md) |
| See what was tested and what was found, including what did not hold up | [docs/RESEARCH_CONTRIBUTIONS.md](./docs/RESEARCH_CONTRIBUTIONS.md), [docs/RESULTS_AND_LIMITATIONS.md](./docs/RESULTS_AND_LIMITATIONS.md) |
| Read it as one paper | [docs/FINAL_PAPER.md](./docs/FINAL_PAPER.md) |
| See the frozen hypotheses | [docs/FINAL_PROJECT_HYPOTHESES.md](./docs/FINAL_PROJECT_HYPOTHESES.md) |
| Re-run the findings yourself and report what you got | [docs/REPLICATION_GUIDE.md](./docs/REPLICATION_GUIDE.md) |
| Test them on data this project has never used | [docs/CONFIRMATORY_PROTOCOL.md](./docs/CONFIRMATORY_PROTOCOL.md) (a draft; it binds nothing until frozen) |
| See an external technical audit answered item by item | [docs/audit/REGISTER.md](./docs/audit/REGISTER.md) |
| Know what comes next, and what will not | [docs/ROADMAP.md](./docs/ROADMAP.md) |
| Deploy the web stack | [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md), [docs/OPERATIONS_RUNBOOK.md](./docs/OPERATIONS_RUNBOOK.md) |
| See what can be changed in the interface, and what accessibility was and was not checked | [docs/INTERFACE_AND_ACCESSIBILITY.md](./docs/INTERFACE_AND_ACCESSIBILITY.md) |
| Understand the security posture | [SECURITY.md](./SECURITY.md), [docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md) |
| See the data and where it came from | [docs/DATA_DICTIONARY.md](./docs/DATA_DICTIONARY.md), [docs/LICENSE_INVENTORY.md](./docs/LICENSE_INVENTORY.md) |

## Status & disclaimers

- **This is research and simulation software.** It is not financial advice, not an investment product,
  and not permission or infrastructure for live trading. A separately gated, 12-item extension checklist
  (`EXT`) exists for what real trading access would require. The mechanism half of ten of those items
  exists as `prometheus.trading_readiness`, tested only against an in-memory mock broker: it makes no
  network call, has no broker SDK, and is never imported by the service, dashboard or jobs. The
  institutional half (a real broker agreement, named officers, real capital) is not met, and the other
  two items (`EXT-02`, `EXT-09`) ask for an external legal opinion and independent model validation that
  no code can produce.
- **"NO-GO for production"** is this project's own, unchanged internal gate decision; see
  [`evidence/gate_report_r0.json`](./evidence/gate_report_r0.json). Nothing in this repository moves that
  needle, nor is it meant to yet.
- Remaining work is almost entirely governance, compliance and security controls that need real
  organizational authority this single-maintainer repository does not have (independent review, legal
  sign-off, a penetration test), plus two data-ingestion connectors (`DAT-02`/`DAT-03`) blocked on
  `stlouisfed.org` being unreachable from this environment, not on missing code. See
  [CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md) for exactly which items remain and why.
- No independent review of any claim in this repository has happened. "Evidenced" means covered by a
  passing automated test here, not peer-reviewed, regulator-approved, or production-ready.

## Contributing

This is presently a single-maintainer research repository. Issues and discussion are welcome; the
standing bar for any change is the same one every PR here already meets: a passing test, `ruff`/`mypy
--strict` clean, and an honest, specific statement of what the change does and does not cover. See
[CONTRIBUTING.md](./CONTRIBUTING.md) for the full workflow, [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md),
and [SECURITY.md](./SECURITY.md) for how to report a vulnerability.

## Citing

[`CITATION.cff`](./CITATION.cff) holds the citation metadata (GitHub's "Cite this repository" button
reads it). Cite the version you ran. There is no DOI and no peer-reviewed paper yet, so the citation is to
the software and its repository, and the findings in
[docs/RESULTS_AND_LIMITATIONS.md](./docs/RESULTS_AND_LIMITATIONS.md) are the author's own, not
independently replicated.

## License

MIT, see [LICENSE](./LICENSE).
