from __future__ import annotations

import pytest

from prometheus.data_ingestion.egress_allowlist import (
    DEFAULT_INGESTION_ALLOWLIST,
    DEFAULT_INGESTION_ROUTING_TABLE,
    AllowlistedTransport,
    EgressDeniedError,
    default_ingestion_transport,
)
from prometheus.data_ingestion.transport import HttpResponse, UrllibTransport
from prometheus.evidence.alert_routing import AlertRoute, RoutingTable, UnroutedSeverityError


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        self.calls.append((url, params))
        return HttpResponse(status_code=200, body=b"ok")


def _configured_table() -> RoutingTable:
    return RoutingTable(
        routes=(AlertRoute(severity="P1", owner="data-eng-oncall", escalation_contact="pager"),)
    )


def test_default_allowlist_is_built_from_the_real_connectors_own_urls() -> None:
    assert DEFAULT_INGESTION_ALLOWLIST == frozenset(
        {"fred.stlouisfed.org", "api.worldbank.org", "mba.tuck.dartmouth.edu"}
    )


def test_an_allowlisted_host_passes_through_to_the_real_call() -> None:
    inner = _FakeTransport()
    wrapped = AllowlistedTransport(inner=inner, alert_routing_table=_configured_table())
    response = wrapped.get("https://fred.stlouisfed.org/graph/fredgraph.csv", {"id": "DGS10"})
    assert response.status_code == 200
    assert inner.calls == [("https://fred.stlouisfed.org/graph/fredgraph.csv", {"id": "DGS10"})]
    assert wrapped.denials == []


def test_an_unexpected_host_is_denied_before_any_real_call_is_attempted() -> None:
    inner = _FakeTransport()
    wrapped = AllowlistedTransport(inner=inner, alert_routing_table=_configured_table())
    with pytest.raises(EgressDeniedError, match="evil.example.com"):
        wrapped.get("https://evil.example.com/exfiltrate", {})
    assert inner.calls == []  # denied before delegating to the wrapped transport


def test_a_denial_generates_a_real_inspectable_alert_record() -> None:
    inner = _FakeTransport()
    wrapped = AllowlistedTransport(inner=inner, alert_routing_table=_configured_table())
    with pytest.raises(EgressDeniedError):
        wrapped.get("https://evil.example.com/exfiltrate", {})
    assert len(wrapped.denials) == 1
    denial = wrapped.denials[0]
    assert denial.host == "evil.example.com"
    assert denial.url == "https://evil.example.com/exfiltrate"
    assert denial.alert_route.owner == "data-eng-oncall"
    assert denial.alert_route.severity == "P1"


def test_denying_with_no_configured_p1_route_fails_loudly_rather_than_denying_silently() -> None:
    inner = _FakeTransport()
    unconfigured_table = RoutingTable(routes=())
    wrapped = AllowlistedTransport(inner=inner, alert_routing_table=unconfigured_table)
    with pytest.raises(UnroutedSeverityError):
        wrapped.get("https://evil.example.com/exfiltrate", {})
    assert wrapped.denials == []  # never got far enough to record a denial


def test_a_custom_allowlist_overrides_the_default() -> None:
    inner = _FakeTransport()
    wrapped = AllowlistedTransport(
        inner=inner,
        alert_routing_table=_configured_table(),
        allowed_hosts=frozenset({"internal.example.com"}),
    )
    with pytest.raises(EgressDeniedError):
        wrapped.get("https://fred.stlouisfed.org/graph/fredgraph.csv", {})
    response = wrapped.get("https://internal.example.com/data", {})
    assert response.status_code == 200


def test_default_routing_table_has_a_real_configured_p1_route_not_a_fabricated_name() -> None:
    routes = DEFAULT_INGESTION_ROUTING_TABLE.routes
    assert len(routes) == 1
    assert routes[0].severity == "P1"
    assert routes[0].owner == "project maintainer"
    assert routes[0].escalation_contact  # non-empty, enforced by AlertRoute.__post_init__


def test_default_ingestion_transport_is_a_real_allowlisted_wrapper_around_urllib() -> None:
    transport = default_ingestion_transport()
    assert isinstance(transport, AllowlistedTransport)
    assert isinstance(transport.inner, UrllibTransport)
    assert transport.allowed_hosts == DEFAULT_INGESTION_ALLOWLIST
    assert transport.alert_routing_table == DEFAULT_INGESTION_ROUTING_TABLE
