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

## External data source licenses

Already recorded per-connector (see
[docs/DATA_DICTIONARY.md § MacroObservation](./DATA_DICTIONARY.md#macroobservation--point-in-time-macro-data)'s
`source_license` field, populated on every real ingested observation), collected here for one-stop review:

| Source | License |
|---|---|
| U.S. Treasury CMT yields, via FRED (`data_ingestion.treasury_yield_curve`) | Public Domain (U.S. government work) |
| World Bank Open Data (`data_ingestion.worldbank`) | World Bank Open Data license (free redistribution with attribution) |
| Kenneth French Data Library (`data_ingestion.french_factors`) | Free for academic research use |
| Kaggle-republished FRED macro series, `mikoajfish99/us-recession-and-financial-indicators` (`data_ingestion.kaggle_macro`) | ODbL-1.0 |

`prometheus.evidence.security_scan.license_scan` (DAT-13, SEC-adjacent)
independently sweeps this repository's tracked source tree for
restricted-redistribution vendor names (Bloomberg, Refinitiv, FactSet,
S&P Capital IQ, LSEG, Morningstar Direct) and confirms zero matches — see
[docs/SECURITY_AND_DATA_HANDLING.md § Data licensing / provenance](./SECURITY_AND_DATA_HANDLING.md#data-licensing--provenance).

## Approval

Published and reviewed by the project maintainer as part of this PR — see
[CONTRIBUTING.md](../CONTRIBUTING.md) for this repository's single-
maintainer status and what "approved" means in that context (there is no
separate second-party approver to name; see `CHECKLIST_STATUS.md`'s GOV
category for the items that honestly remain open because they require
one).
