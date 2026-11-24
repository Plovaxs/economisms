# Extension points and compatibility

Where the code is meant to be extended, what must stay true when it is, and what is and is not promised to people
who depend on it. The project is pre-1.0 research software with one maintainer: nothing here is a stability
guarantee beyond what a test enforces.

## Adding a runner (a lab / a recipe kind)

1. Write the study module under `src/prometheus/orchestration/` with a frozen config dataclass that has
   `from_dict` (it must accept exactly the complete set of fields) and a function returning a result with a
   `manifest` and an `evidence_bundle`.
2. Register it in `RUNNERS` in `src/prometheus/orchestration/recipes.py`, and give it an entry in
   `evidence.contracts.CONVENTIONS`: the module refuses to import if the two key sets differ.
3. The desktop forms (derived from the config dataclass), the job engine and the web API pick it up from the
   registry. Add a test that its default recipe runs, and one for each guard in its config.
4. Say in the study's docstring what it does **not** show, and add it to `docs/RESULTS_AND_LIMITATIONS.md` only
   if it produced a finding.

## Adding a data snapshot

Put the CSV and its `.meta.json` (source, source URL, licence, download date, raw-file digests, derivation) in
`data_cache/`, then `python -m prometheus.data_ingestion.snapshot_integrity write` (the integrity manifest) and
`python -m prometheus.data_ingestion.dataset_registry write` (the registry and the QA report). A test fails if
either is stale, and the QA report's pinned list of known warnings fails if the new file raises one you have not
read.

## Adding a confirmatory endpoint

A new module in `src/prometheus/confirmatory/` that takes its data or seeds as arguments, a power note, a line in
the protocol's open items, and a test that it reproduces the old finding it extends. Untouched data must go through
the freeze guard (`freeze.require_frozen`).

## Compatibility: what is promised

| Thing | Promise |
| --- | --- |
| The `econosim` subcommands and `python -m prometheus.orchestration.<runner>` flags | Documented in `--help`; pre-1.0, so a change is allowed but goes in the changelog. |
| Evidence payloads and recipes | Evidence payloads carry `schema_version: 1`; a recipe's hash covers its full config, so changing a default changes the default recipe's hash. |
| The job store (SQLite) | `PRAGMA user_version = 1`; **there are no migrations**: a store of any other version is refused. A schema change needs a migration written first. |
| Python | 3.11 to 3.14.7, tested in CI on every push; the lock is the reference. |
| Operating systems | Linux for jobs and the installer; see [SUPPORT_MATRIX.md](./SUPPORT_MATRIX.md). |
| Numerical results | Reproducible to the locked versions on one machine; across machines, to the printed digits and the same conclusions ([REPLICATION_GUIDE.md](./REPLICATION_GUIDE.md)). |

## Known gaps (not hidden)

No schema migrations; no deprecation policy; no complexity or hotspot review of the code; no stable Python API
beyond what the tests import.
