# Data dictionary

Every field below is read directly from the dataclass that defines it, not
re-described from memory — if this document and the code ever disagree, the
code is correct and this document is stale (open an issue). This is not an
exhaustive field-by-field listing of every type in the codebase; it covers
the core cross-cutting schemas that most other modules build on.

## `MacroObservation` — point-in-time macro data

[`prometheus.econosim.pit.MacroObservation`](../src/prometheus/econosim/pit.py)
is the schema every real data connector in `prometheus.data_ingestion`
(`treasury_yield_curve`, `kaggle_macro`, `french_factors`, `worldbank`)
produces, and the only way time-series data enters any point-in-time-safe
pipeline in this repository.

| Field | Type | Meaning |
|---|---|---|
| `series_id` | `str` | Which series this value belongs to (e.g. `"UST_10Y"`, a FRED/World Bank code). |
| `observation_at` | `date` | The period this value **describes** (e.g. the month CPI covers, or the trading date a yield applies to). |
| `published_at` | `date` | The date this specific vintage became public **from the source**. Must not precede `observation_at`. |
| `value` | `float` | The observed value. |
| `revision_id` | `str` | Defaults to `"r0"`; distinguishes later restatements of the same `(series_id, observation_at)`. |
| `vintage_at` | `date \| None` | A separately tracked source snapshot label (e.g. an ALFRED realtime-period), if the source distinguishes it from `published_at`. Must not precede `published_at`. |
| `asof_eligible_at` | `date \| None` | When **this system's own ingestion pipeline** made the value usable internally — distinct from, and allowed to lag, `published_at`. `None` means no extra ingestion lag. |
| `ingested_at` | `date \| None` | Pure provenance: when this system actually pulled the value. Not used by any eligibility predicate. |
| `unit` / `frequency` | `str` | E.g. `"percent"` / `"D"`. |
| `source_url` / `source_license` | `str` | Exactly where the value came from and under what license. |
| `raw_hash` | `str \| None` | SHA-256 hex digest of the raw source payload the value was parsed from, when recorded. |
| `transformation_id` | `str` | Identifies any transform applied between the raw source and this value. |
| `timezone` | `str` | Defaults to `"UTC"`. |
| `quality_flags` | `tuple[str, ...]` | Any quality annotations attached during ingestion. |

**The point-in-time rule** (`PointInTimeStore.as_of`,
[`econosim/pit.py`](../src/prometheus/econosim/pit.py)): a caller querying
`(series_id, observation_at)` "as of" decision time `t` only ever sees a
vintage whose `effective_eligible_at` — the later of `published_at` and
`asof_eligible_at` — is `<= t`. There is deliberately no "give me the latest
value regardless of date" accessor on this store, so a caller cannot
accidentally bypass the rule. `FutureDataError` is the fail-closed
counterpart for code paths that must actively reject a not-yet-eligible
request rather than silently receive `None`.

## `Money` — ledger currency values

[`prometheus.core.money.Money`](../src/prometheus/core/money.py):
`minor_units: int` (e.g. integer cents), `currency: str` (default `"USD"`).
Deliberately integer, never `float` — LED-02's acceptance criterion is "no
floating-cent drift in production ledger fixtures." Arithmetic or
comparison across two different currencies raises `CurrencyMismatchError`
rather than silently producing a number that looks plausible but means
nothing (there is no implicit FX conversion).

## `ModelCard` — the mandatory model documentation record

[`prometheus.evidence.model_card.ModelCard`](../src/prometheus/evidence/model_card.py)
(MLO-09 / DOC-06). Every field below is **required**; the dataclass raises
at construction if any is empty, so a card cannot ship with a silently
missing section:

`model_id`, `model_type`, `framework`, `version`, `license`, `content_hash`,
`intended_use`, `prohibited_use`, `input_schema_summary`,
`training_data_summary`, `primary_metrics` (`Mapping[str, float]`, must be
non-empty and every value finite — `NaN`/`inf` are rejected),
`metric_uncertainty_note`, `failure_modes` (`tuple[str, ...]`, must list at
least one known limitation — a model card with zero disclosed limitations
is rejected outright), `independent_reviewer` (`str | None` — `None` is
allowed and means exactly what it says: not reviewed), `approval_status`
(one of `NOT REVIEWED` / `APPROVED` / `REJECTED` / `CONDITIONAL`),
`created_at`.

## The service API wire schema

[`prometheus.service.schema`](../src/prometheus/service/schema.py)
derives its OpenAPI 3.1 JSON Schema **directly from the same dataclasses
the runtime decoders use** (`_schema()` walks dataclass fields via
`get_type_hints`), rather than hand-maintaining a second, parallel
description that could drift from the real wire format — JSON Schema
validates wire *shape*; the original decoders remain authoritative for
financial semantics and cross-field constraints. The generated schema is
published at [`docs/api/openapi-v1.json`](./api/openapi-v1.json); see
[`docs/RESEARCH_API.md`](./RESEARCH_API.md) for the running service and
[`prometheus.service.client`](../src/prometheus/service/client.py) for a
complete typed example client (DOC-10).

## Holdout / experiment splits

[`prometheus.experiments.holdout_manifest.DataSplit`](../src/prometheus/experiments/holdout_manifest.py):
`split_id: str`, `regime: Literal["train", "validation", "test"]`,
`start: date`, `end: date`. A `HoldoutManifest` assembled from a set of
non-overlapping splits is content-addressed (`manifest_id` is a
`compute_result_hash` over every split's fields) — two manifests built from
bit-identical cutoffs always carry the same id, and changing even one
cutoff changes it. See
[docs/EXPERIMENT_GUIDE.md](./EXPERIMENT_GUIDE.md) for how this is actually
used.
