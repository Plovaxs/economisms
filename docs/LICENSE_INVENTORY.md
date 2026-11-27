# Third-party license inventory

Generated from this repository's real, installed dependency metadata —
not hand-typed, not guessed. Regenerate with:

```bash
.venv/bin/python -c "
from pathlib import Path
from prometheus.evidence.license_inventory import direct_dependency_names, collect_license_inventory
for d in collect_license_inventory(direct_dependency_names(Path('pyproject.toml'))):
    print(d)
"
```

See [`prometheus.evidence.license_inventory`](../src/prometheus/evidence/license_inventory.py)
for how each value below was actually obtained: `License-Expression` is
the modern PEP 639 SPDX identifier reported by the installed package's
own metadata; `Classifiers` is the legacy `License :: ...` trove
classifier fallback. `tests/unit/test_license_inventory.py` additionally
asserts, as a real passing check and not just a reviewed table, that no
direct dependency carries a GPL/AGPL-family license incompatible with
this project's own MIT license.

## Direct code dependencies, as resolved in this environment

| Package | Installed version | License |
|---|---|---|
| numpy | 2.5.4 | `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` |
| scipy | 1.18.1 | BSD License (classifier; no `License-Expression` published) |
| torch | 2.15.0+cpu | `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND ISC AND MIT AND Zlib` |
| uvicorn (service extra) | 0.54.0 | `BSD-3-Clause` |
| jsonschema (service extra) | 4.26.0 | `MIT` |
| cryptography (recovery extra) | 50.0.2 | `Apache-2.0 OR BSD-3-Clause` |
| PySide6-Essentials (desktop extra) | 6.12.0 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` (read from the legacy `License:` header; this project relies on the LGPL alternative) |
| pennylane (quantum extra) | 0.45.1 | `Apache-2.0` |
| pennylane-lightning (quantum extra) | 0.45.0 | `Apache-2.0` |
| pytest (dev) | 9.2.0 | `MIT` |
| hypothesis (dev) | 6.170.14 | `MPL-2.0` |
| pytest-cov (dev) | 7.1.0 | `MIT` |
| ruff (dev) | 0.17.3 | `MIT` |
| mypy (dev) | 2.4.1 | `MIT` |
| scipy-stubs (dev) | 1.18.1.1 | `BSD-3-Clause` |
| scikit-learn (dev) | 1.9.1 | `BSD-3-Clause` |
| types-jsonschema (dev) | 4.26.0.20261006 | `Apache-2.0` |

Every direct dependency above is permissively licensed (BSD/MIT/Apache-2.0/
Zlib/0BSD/CC0) or weak-copyleft at the file level only (MPL-2.0, which
`hypothesis` — a `dev`-only test dependency never distributed as part of
this project's own package — carries). None requires this project's own
MIT-licensed code to be relicensed, confirmed by the real test named
above, not asserted from memory.

**The one exception to "permissive" is Qt.** `PySide6-Essentials` (the Qt for Python bindings, with
its transitive `shiboken6`) is offered under `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, and this
project relies on the LGPL alternative. That is judged by a real SPDX evaluator
(`evidence.license_inventory.allows_mit_project`: `OR` is the licensee's choice, `AND` needs every part),
not by a substring match -- `LGPL` contains `GPL`, which is why the previous check could not have
told them apart. What it means in practice: the Qt wheels are an *optional* extra that this repository
neither vendors nor redistributes, imported only inside `prometheus.desktop.ui`, so the MIT-licensed
code here is not relicensed by it. If you ever redistribute a **bundle that contains Qt** (an AppImage,
a PyInstaller folder, a `.deb`), the LGPL's obligations for Qt attach to that bundle -- notices, the
text of the license, and the ability for a user to replace the Qt libraries -- and nothing in this
repository does or claims any of that: no bundle is built. Dynamic linking against a separately
installed Qt, as `uv sync --extra desktop` does, is the case the LGPL is designed for. The software
bill of materials (`docs/release/dependency-sbom.cdx.json`) covers the service and recovery runtime;
the `desktop` extra is optional and separate, and appears in `uv.lock` and in the weekly
`pip-audit`, which exports every locked requirement.

## External data source / vendor-entitlement register (PRV-01)

Already recorded per-connector (see
[docs/DATA_DICTIONARY.md § MacroObservation](./DATA_DICTIONARY.md#macroobservation--point-in-time-macro-data)'s
`source_license` field, populated on every real ingested observation), collected here for one-stop review, with the explicit permitted-use/redistribution terms PRV-01's acceptance wording asks for:

| Source | License | Permitted use | Retention | Redistribution |
|---|---|---|---|---|
| U.S. Treasury CMT yields, via FRED (`data_ingestion.treasury_yield_curve`) | Public Domain (U.S. government work) | Unrestricted | Indefinite (public domain) | Unrestricted |
| World Bank Open Data (`data_ingestion.worldbank`) | World Bank Open Data license | Unrestricted, with attribution | Indefinite | Permitted, with attribution |
| Kenneth French Data Library (`data_ingestion.french_factors`) | Free for academic research use | Academic/research use | Indefinite | Permitted for research/academic redistribution |
| Kaggle-republished FRED macro series, `mikoajfish99/us-recession-and-financial-indicators` (`data_ingestion.kaggle_macro`) | ODbL-1.0 | Unrestricted, share-alike | Indefinite | Permitted under ODbL-1.0 share-alike terms (this project's own derived CSVs, `data_cache/kaggle_us_macro_monthly.csv` and `data_cache/kaggle_us_macro_extended_monthly.csv`, are committed and redistributed under those same terms; PR-203 adds `data_cache/kaggle_cpi_index_monthly.csv`, the CPI-U index levels, under the same ODbL-1.0 share-alike terms) |
| Kaggle S&P 500 index history, `henryhan117/sp-500-historical-data` (`data_ingestion.kaggle_sp500`) | ODbL-1.0 (database), contents under the dataset's "Database Contents" licence | Unrestricted, share-alike | Indefinite | Permitted under ODbL-1.0 share-alike terms (the derived `data_cache/kaggle_sp500_daily_close.csv` is committed under the same terms; PR-202's `data_cache/kaggle_sp500_spliced_daily_close.csv` continues it with the backbone dataset's SPX500 series, and `data_cache/kaggle_nasdaq_daily_close.csv` is derived from the backbone dataset's NASDAQ table -- both ODbL-1.0 and share-alike) |
| Kaggle Federal Reserve interest rates, `federalreserve/interest-rates` (`data_ingestion.kaggle_fed_policy`) | CC0-1.0 | Unrestricted | Indefinite | Unrestricted |
| Kaggle US Treasury yields, `guillemservera/us-treasury-yields-daily` (`data_ingestion.kaggle_term_spread`) | CC BY-NC 4.0 | **Non-commercial** use, with attribution | Indefinite | Permitted for NON-COMMERCIAL use with attribution only; the derived `data_cache/kaggle_term_spread_monthly.csv` inherits that restriction and is NOT covered by any more permissive licence this repository's other files carry |
| FDIC BankFind Suite API, annual national bank totals and failures (`data_ingestion.fdic_banks`) | US Government work, public domain | Unrestricted | Indefinite (public domain) | Unrestricted; the derived `data_cache/fdic_bank_annual.csv` and `fdic_bank_failures_annual.csv` are committed |

These terms are read directly from each source's own published license
(linked at each connector's `source_url`/license page), the same
evidence-discipline bar as everything else in this repository — "checked"
means read against the actual license text, not inferred from the
source's reputation. **Not independently (second-party) checked** — this
is a single-maintainer repository; see `CONTRIBUTING.md`.

`prometheus.evidence.security_scan.license_scan` (DAT-13, SEC-adjacent)
independently sweeps this repository's tracked source tree for
restricted-redistribution vendor names (Bloomberg, Refinitiv, FactSet,
S&P Capital IQ, LSEG, Morningstar Direct) and confirms zero matches — see
[docs/SECURITY_AND_DATA_HANDLING.md § Data licensing / provenance](./SECURITY_AND_DATA_HANDLING.md#data-licensing--provenance).

## Source code, model weights, and benchmark licensing (PRV-07)

- **Source code**: MIT, see [LICENSE](../LICENSE) — covers every connector,
  model, pricer, and the `neural_sde`/`pde_solvers`-class subsystems alike.
- **Model weights**: this repository does **not** commit trained model
  weights as artifacts — every model (RECESSIONNET, Q-MACRO, the neural
  SDE, the hedging MLP) is trained fresh from committed, licensed input
  data each run, under the MIT-licensed training code above. There is no
  separate weights license to track because there is no separate weights
  file.
- **Benchmark results**: generated outputs (JSON reports, model cards)
  are covered by the same MIT code license and the input data's licenses
  above; none are published under a separate restrictive license.

## Approval

Published and reviewed by the project maintainer as part of this PR — see
[CONTRIBUTING.md](../CONTRIBUTING.md) for this repository's single-
maintainer status and what "approved" means in that context (there is no
separate second-party approver to name; see `CHECKLIST_STATUS.md`'s GOV
category for the items that honestly remain open because they require
one).
