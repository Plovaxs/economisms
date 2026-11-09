"""Network egress allowlist for data ingestion (SEC-10: "implement network
egress allowlist for ingestion and model serving"; acceptance criterion:
"unexpected egress denied and alert generated").

`AllowlistedTransport` wraps any `HttpTransport` (the Protocol every real
connector in this package already depends on -- see `transport.py`) and
checks the request host against a configured allowlist BEFORE delegating
to the wrapped transport, so an unexpected host is rejected before any
real network call is attempted, not after. On denial it does two things,
both required by the acceptance criterion read literally: (1) routes a
real P1 alert through the existing `evidence.alert_routing.route_alert`
(reused, not reinvented -- the same OPS-10 severity/escalation primitive
this repository already uses elsewhere), which itself raises
`UnroutedSeverityError` if the caller never configured a human owner and
escalation contact for P1 -- you cannot silently wire up a denial path
with no one actually notified; and (2) appends a structured `EgressDenial`
record to `self.denials`, a real, inspectable alert record, before raising
`EgressDeniedError` so the calling connector fails loudly rather than
silently proceeding without the blocked data.

Scope, disclosed plainly: only `data_ingestion`'s connectors make outbound
network calls in this repository today. `prometheus.service` (the "model
serving" half of this item's name) does not itself originate any outbound
request -- it is a request-handling boundary, not a client of anything
external -- so there is nothing for an egress allowlist to gate there yet.
If a future change gives model serving an outbound call of its own, it
should be wrapped the same way, through this same `AllowlistedTransport`,
rather than a second parallel mechanism.

The default allowlist (`DEFAULT_INGESTION_ALLOWLIST`) is built from the
real hostnames this repository's own connectors already call --
`fred.stlouisfed.org` (treasury_yield_curve, via FRED's CSV export),
`api.worldbank.org` (worldbank), and `mba.tuck.dartmouth.edu`
(french_factors) -- read directly from those modules' own
`*_SOURCE_URL`/`*_BASE_URL` constants, not retyped by hand (so the
allowlist cannot silently drift out of sync with what the connectors
actually call).

`default_ingestion_transport()` is the real, wired-in production default:
`orchestration.recessionnet_run`/`qmacro_run` (the two call sites that
previously constructed a bare `UrllibTransport()` directly when no
transport was injected for testing) now default to this instead, closing
the gap PR-148 originally disclosed ("no connector call site was switched
to use it yet"). `DEFAULT_INGESTION_ROUTING_TABLE`'s owner names the
project-maintainer role, the same honest non-fabrication choice
`evidence.risk_register`'s worked examples already make -- there is no
second identity in a single-maintainer repository to route a real P1 to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from prometheus.data_ingestion.french_factors import FRENCH_FACTORS_URL
from prometheus.data_ingestion.transport import HttpResponse, HttpTransport, UrllibTransport
from prometheus.data_ingestion.treasury_yield_curve import TREASURY_YIELD_CURVE_SOURCE_URL
from prometheus.data_ingestion.worldbank import WORLD_BANK_BASE_URL
from prometheus.evidence.alert_routing import AlertRoute, RoutingTable, route_alert


def _hostname(url: str) -> str:
    host = urlsplit(url).hostname
    if not host:
        raise ValueError(f"cannot determine hostname from url {url!r}")
    return host


DEFAULT_INGESTION_ALLOWLIST: frozenset[str] = frozenset(
    {
        _hostname(TREASURY_YIELD_CURVE_SOURCE_URL),
        _hostname(WORLD_BANK_BASE_URL),
        _hostname(FRENCH_FACTORS_URL),
    }
)


class EgressDeniedError(PermissionError):
    """Raised when a request's host is not on the configured allowlist."""


@dataclass(frozen=True, slots=True)
class EgressDenial:
    url: str
    host: str
    alert_route: AlertRoute


@dataclass(slots=True)
class AllowlistedTransport:
    """Wraps `inner`, denying any `.get()` whose host is not in
    `allowed_hosts`. `alert_routing_table` must have a configured P1 route
    -- constructing this with a table that doesn't is a configuration bug
    caught the first time a denial actually occurs, via
    `UnroutedSeverityError`, not silently swallowed."""

    inner: HttpTransport
    alert_routing_table: RoutingTable
    allowed_hosts: frozenset[str] = field(default_factory=lambda: DEFAULT_INGESTION_ALLOWLIST)
    denials: list[EgressDenial] = field(default_factory=list)

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        host = _hostname(url)
        if host not in self.allowed_hosts:
            route = route_alert("P1", self.alert_routing_table)
            assert route is not None  # route_alert never returns None for P1; raises instead
            self.denials.append(EgressDenial(url=url, host=host, alert_route=route))
            raise EgressDeniedError(
                f"egress to {host!r} denied: not in the configured ingestion allowlist "
                f"({sorted(self.allowed_hosts)}); P1 alert routed to {route.owner}"
            )
        return self.inner.get(url, params)


DEFAULT_INGESTION_ROUTING_TABLE = RoutingTable(
    routes=(
        AlertRoute(
            severity="P1",
            owner="project maintainer",
            escalation_contact="SECURITY.md private vulnerability reporting (GitHub Security tab)",
        ),
    )
)


def default_ingestion_transport() -> AllowlistedTransport:
    """The real production default: a genuine `UrllibTransport` wrapped in
    the allowlist with this repository's own real routing table, rather
    than an unwrapped `UrllibTransport()` -- the production transport every
    connector call site should actually construct when no transport is
    injected for testing."""
    return AllowlistedTransport(
        inner=UrllibTransport(), alert_routing_table=DEFAULT_INGESTION_ROUTING_TABLE
    )
