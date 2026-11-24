"""Fetch a CPI series from the BLS public API and lock it as a `month,level` CSV.

This is how the confirmatory protocol's E2 data are acquired BEFORE the freeze without being looked
at: the tool prints only the series id, the number of months, the first and last month LABELS and
two SHA-256 digests (the raw API response and the CSV), never a value. The CSV and a sidecar
`.meta.json` (source, request, retrieval time, both digests, the vintage caveat) are written once
and never overwritten, so the digest the protocol records stays the digest of the bytes that are
analysed.

Network policy: https only, the host pinned to `api.bls.gov`, redirects refused, a timeout and a
size cap. The BLS v1 endpoint needs no key and allows a few dozen requests a day; a POST body is
the only way to ask it for an explicit range of years (a GET returns the latest three).

Vintage: BLS revises the seasonally adjusted indexes every February for the previous five years,
so a download made now is a different VINTAGE from the Kaggle copy committed in `data_cache/`. The
sidecar says so, and `e2_inflation.vintage_overlap` measures the difference.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

_NOT_PUBLISHED = {"-", ""}
BLS_HOST = "api.bls.gov"
BLS_URL = f"https://{BLS_HOST}/publicAPI/v1/timeseries/data/"
MAX_RESPONSE_BYTES = 1_048_576
LICENSE = "U.S. government work -- public domain"
VINTAGE_NOTE = (
    "Seasonally adjusted indexes are revised each February for the previous five years: this file "
    "is the vintage published on the retrieval date, not the real-time vintage a forecaster had."
)


class BlsFetchError(ValueError):
    """The BLS response, or the request for it, cannot be trusted."""


class Poster(Protocol):
    def post_json(self, url: str, payload: dict[str, Any]) -> bytes: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class UrllibPoster:
    """The real poster. Not exercised by the test suite (which must stay hermetic)."""

    def __init__(self, timeout: float = 30.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout

    def post_json(self, url: str, payload: dict[str, Any]) -> bytes:  # pragma: no cover
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname != BLS_HOST:
            raise BlsFetchError(f"only https://{BLS_HOST}/ is fetched, not {url!r}")
        request = urllib.request.Request(  # noqa: S310  (scheme and host verified above)
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "econosim-research"},
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=self.timeout) as response:  # noqa: S310
                body: bytes = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, OSError) as exc:
            raise BlsFetchError(f"could not fetch {url}: {exc}") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise BlsFetchError("the BLS response is larger than the size cap")
        return body


@dataclass(frozen=True, slots=True)
class FetchedSeries:
    series_id: str
    months: tuple[str, ...]
    """`YYYY-MM`, ascending, consecutive."""
    levels: tuple[str, ...]
    """The index levels as the API wrote them (strings: no float round trip); an empty string
    marks a month BLS published no value for."""
    raw_sha256: str
    request: dict[str, Any]

    @property
    def missing_months(self) -> tuple[str, ...]:
        return tuple(m for m, v in zip(self.months, self.levels, strict=True) if v == "")


def _parse(series_id: str, raw: bytes) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise BlsFetchError("the BLS response is not JSON") from exc
    if not isinstance(document, dict) or document.get("status") != "REQUEST_SUCCEEDED":
        message = document.get("message") if isinstance(document, dict) else None
        raise BlsFetchError(f"the BLS request did not succeed: {message!r}")
    try:
        series = document["Results"]["series"]
        found = next(s for s in series if s["seriesID"] == series_id)
        data = found["data"]
    except (KeyError, TypeError, StopIteration) as exc:
        raise BlsFetchError(f"the response holds no data for series {series_id}") from exc
    points: dict[str, str] = {}
    for item in data:
        period = item.get("period", "")
        if not (period.startswith("M") and period != "M13"):
            continue  # annual averages and half-year values are not monthly levels
        month = f"{int(item['year']):04d}-{int(period[1:]):02d}"
        value = str(item["value"]).strip()
        if month in points:
            raise BlsFetchError(f"the response lists {month} twice")
        if value in _NOT_PUBLISHED:
            points[month] = ""  # BLS published no value (e.g. October 2025): kept as a gap
            continue
        try:
            level = float(value)
        except ValueError as exc:
            raise BlsFetchError(f"the level for {month} is not a number") from exc
        if not math.isfinite(level) or level <= 0.0:
            raise BlsFetchError(f"a level for {month} is not a positive finite number")
        points[month] = value
    if not any(points.values()):
        raise BlsFetchError("the response holds no monthly levels")
    months = tuple(sorted(points))
    indices = [int(m[:4]) * 12 + int(m[5:]) for m in months]
    if any(b - a != 1 for a, b in zip(indices, indices[1:], strict=False)):
        raise BlsFetchError("the monthly levels are not consecutive")
    return months, tuple(points[m] for m in months)


def fetch_series(series_id: str, start_year: int, end_year: int, poster: Poster) -> FetchedSeries:
    if not series_id.isalnum():
        raise BlsFetchError("a BLS series id is letters and digits only")
    if not 1947 <= start_year <= end_year <= 2100 or end_year - start_year > 9:
        raise BlsFetchError("the BLS v1 endpoint serves at most ten calendar years per request")
    request = {"seriesid": [series_id], "startyear": str(start_year), "endyear": str(end_year)}
    raw = poster.post_json(BLS_URL, request)
    months, levels = _parse(series_id, raw)
    return FetchedSeries(series_id, months, levels, hashlib.sha256(raw).hexdigest(), request)


def render_csv(series: FetchedSeries) -> bytes:
    rows = ["month,level"] + [f"{m},{v}" for m, v in zip(series.months, series.levels, strict=True)]
    return ("\n".join(rows) + "\n").encode()


def write_locked(
    series: FetchedSeries,
    out: Path,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Write `out` and `out.with_suffix('.meta.json')`, refusing to overwrite either, and return
    the metadata. Only labels and digests are in the returned dictionary: no level."""
    meta_path = out.with_suffix(".meta.json")
    if out.exists() or meta_path.exists():
        raise BlsFetchError(f"{out} or its metadata already exists: a locked file is write-once")
    content = render_csv(series)
    meta = {
        "source": "U.S. Bureau of Labor Statistics, Public Data API v1 (no key)",
        "request_url": BLS_URL,
        "request": series.request,
        "series_id": series.series_id,
        "retrieved_at_utc": now().isoformat(timespec="seconds"),
        "first_month": series.months[0],
        "last_month": series.months[-1],
        "n_months": len(series.months),
        "missing_months": list(series.missing_months),
        "missing_note": "BLS published no index level for the months listed (a blank in the CSV); "
        "analyses must exclude or declare an imputation for every month that needs them.",
        "raw_response_sha256": series.raw_sha256,
        "csv_sha256": hashlib.sha256(content).hexdigest(),
        "license": LICENSE,
        "vintage_note": VINTAGE_NOTE,
        "columns": {"month": "YYYY-MM of the month measured", "level": "index level, as published"},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta
