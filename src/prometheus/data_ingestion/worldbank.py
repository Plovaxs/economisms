"""World Bank Open Data connector (DAT-02 extension): the first external
macroeconomic data source in this repository that has actually been
exercised against a real, live API, not just coded against documentation
-- World Bank's indicator API needs no API key, unlike FRED/ALFRED (see
`fred.py`'s own docstring for why those remain untested against the live
service). A full round trip (real HTTP fetch -> JSON parse ->
`MacroObservation` construction -> `econosim.pit.PointInTimeStore`
eligibility query) was run against the live API before any production
code here was written, confirming the response shape, pagination
("page"/"pages" in the metadata object) and the missing-value convention
(a `null` JSON value, not a magic string) all behave as expected.

Response shape (confirmed live, not assumed from documentation alone):
a two-element JSON array `[metadata, rows]`. `metadata` carries
pagination (`page`, `pages`, `per_page`, `total`) and a dataset-level
`lastupdated` date -- NOT a per-observation vintage the way ALFRED
provides. Using `lastupdated` as every observation's `published_at` is a
deliberate, documented approximation: it is the best available signal
World Bank's bulk indicator API gives for "when could this number have
been known," and erring toward a LATER published_at (treating data as
newly published every time the dataset itself was last touched) is the
safe direction for a leakage-prevention gate -- it can only make data
LESS available than it truly was, never falsely available early.

`rows` is `null` (not an empty list) when the query matches no data at
all; an individual row's `value` is JSON `null` (not a magic string)
when that specific observation is missing -- skipped here, never
forward-filled or fabricated (DAT-08).

Scope: annual indicators only (`observation_at` = 31 December of the
given year) -- the indicators this connector's own docstring and the
project's dataset plan both focus on (GDP, inflation, unemployment,
population) are annual in World Bank's bulk API; monthly/quarterly World
Bank series are out of scope here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from prometheus.data_ingestion.transport import HttpTransport
from prometheus.econosim.pit import MacroObservation

WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"
WORLD_BANK_SOURCE_LICENSE = "CC-BY-4.0 (World Bank Open Data)"
_MAX_PAGES = 1000
"""A defensive cap against an API response that never reports `pages`
shrinking to something already fetched (e.g. a malformed or adversarial
response) -- without this, a bug could spin the pagination loop forever."""


class WorldBankResponseError(ValueError):
    """Raised when the World Bank API's response does not match the
    confirmed-live response shape this parser expects."""


@dataclass(frozen=True, slots=True)
class WorldBankFetchResult:
    observations: tuple[MacroObservation, ...]
    raw_hash: str
    """SHA256 of the CONCATENATION of every page's raw response body
    fetched in this call, in fetch order -- a fetch-level hash, not a
    true per-row hash (the bulk API returns many rows per HTTP response,
    so there is no natural per-row raw document to hash separately).
    Every observation in `observations` from the same fetch shares this
    same value."""
    pages_fetched: int


def fetch_world_bank_indicator(
    transport: HttpTransport,
    country_codes: list[str],
    indicator_code: str,
    *,
    per_page: int = 1000,
    date_range: str | None = None,
) -> WorldBankFetchResult:
    if not country_codes:
        raise ValueError("country_codes must be non-empty")
    if not indicator_code:
        raise ValueError("indicator_code must be non-empty")
    if per_page < 1:
        raise ValueError("per_page must be a positive integer")

    url = WORLD_BANK_BASE_URL.format(countries=";".join(country_codes), indicator=indicator_code)
    raw_rows: list[tuple[dict[str, Any], date]] = []
    hasher = hashlib.sha256()
    page = 1
    total_pages = 1

    while page <= total_pages:
        if page > _MAX_PAGES:
            raise WorldBankResponseError(
                f"exceeded the {_MAX_PAGES}-page safety cap fetching {url!r}; "
                "the API's reported 'pages' value may be malformed"
            )
        params = {"format": "json", "per_page": str(per_page), "page": str(page)}
        if date_range is not None:
            params["date"] = date_range
        response = transport.get(url, params)
        hasher.update(response.body)

        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise WorldBankResponseError(f"response body is not valid JSON: {exc}") from exc
        if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[0], dict):
            raise WorldBankResponseError(f"unexpected World Bank response shape: {payload!r}"[:500])

        metadata, rows = payload
        total_pages = int(metadata.get("pages", 1))
        last_updated_raw = metadata.get("lastupdated")
        if last_updated_raw is None:
            raise WorldBankResponseError("World Bank response metadata is missing 'lastupdated'")
        published_at = date.fromisoformat(last_updated_raw)

        for row in rows or []:
            if row.get("value") is None:
                continue
            raw_rows.append((row, published_at))
        page += 1

    raw_hash = hasher.hexdigest()
    observations = tuple(
        MacroObservation(
            series_id=f"{indicator_code}:{row['countryiso3code']}",
            observation_at=date(int(row["date"]), 12, 31),
            published_at=published_at,
            value=float(row["value"]),
            source_url=url,
            source_license=WORLD_BANK_SOURCE_LICENSE,
            raw_hash=raw_hash,
            frequency="A",
        )
        for row, published_at in raw_rows
    )
    return WorldBankFetchResult(
        observations=observations, raw_hash=raw_hash, pages_fetched=page - 1
    )
