"""Mechanical checks on the container deployment itself: the Dockerfile and the
compose files. They exist so the hardening cannot erode silently -- a base image
pinned by tag, a service that quietly regains a writable root filesystem or a
capability, a second published port, or a TLS overlay that re-enables cleartext
fails here, in the same run that would have shipped it.

There is no Docker daemon in this test environment, so these check the
DECLARED posture; `.github/workflows/docker-build.yml` then checks the REAL
containers (uid, read-only rootfs, dropped capabilities, health, TLS) on a
runner that has one."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
LONG_RUNNING = ("webgateway", "worker", "jobs-api", "dashboard")


class _ComposeLoader(yaml.SafeLoader):
    pass


def _tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("!", _tag)


def _load(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / name).read_text(), Loader=_ComposeLoader)  # noqa: S506


COMPOSE = _load("docker-compose.yml")
OVERLAY = _load("docker-compose.prod.yml")
SERVICES = COMPOSE["services"]


def test_every_base_image_is_pinned_by_digest() -> None:
    froms = re.findall(r"^FROM\s+(\S+)", DOCKERFILE, re.M)
    assert len(froms) >= 2
    for image in froms:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", image), (
            f"{image!r}: a tag can be moved to different contents after review; a digest cannot"
        )


def test_the_image_runs_as_an_unprivileged_user() -> None:
    users = re.findall(r"^USER\s+(\S+)", DOCKERFILE, re.M)
    assert users, "no USER instruction: the image would run as root"
    assert users[-1] not in ("root", "0", "0:0"), users
    assert re.search(r"useradd .*--uid 10001", DOCKERFILE)
    assert "chown econosim:econosim /data" in DOCKERFILE, (
        "/data must exist in the image, owned by the user: that is what makes a fresh "
        "named volume inherit that ownership"
    )


def test_the_build_toolchain_is_not_installed_into_the_runtime_image() -> None:
    assert "--group build" not in DOCKERFILE
    assert "--no-install-project" in DOCKERFILE and "--no-build" in DOCKERFILE
    assert "--all-extras" not in DOCKERFILE, "the dev extra must not reach the runtime image"
    assert "--extra dev" not in DOCKERFILE
    assert "PYTHONPATH=/app/src" in DOCKERFILE


def test_frontend_dependencies_are_installed_without_running_package_scripts() -> None:
    assert re.search(r"^RUN npm ci --ignore-scripts$", DOCKERFILE, re.M)


def test_no_floating_latest_tag_anywhere() -> None:
    assert ":latest" not in DOCKERFILE
    assert ":latest" not in (ROOT / "docker-compose.yml").read_text()


def test_the_node_base_is_a_supported_release_line() -> None:
    match = re.search(r"^FROM node:(\d+)-", DOCKERFILE, re.M)
    assert match is not None
    assert int(match.group(1)) >= 22, "Node 20 is end-of-life: no security fixes are published"


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_service_is_hardened(name: str) -> None:
    service = SERVICES[name]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["init"] is True
    assert service["pids_limit"] >= 1
    assert service["tmpfs"], "a read-only rootfs needs a tmpfs /tmp"
    assert service["logging"]["options"]["max-size"] and service["logging"]["options"]["max-file"]
    assert "mem_limit" in service, "an unbounded container can take the whole host"


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_no_service_asks_for_more_privilege(name: str) -> None:
    service = SERVICES[name]
    assert not service.get("privileged")
    assert service.get("network_mode") in (None, "service:webgateway")
    assert str(service.get("user", "")) not in ("root", "0", "0:0")
    assert not service.get("cap_add")
    assert not service.get("pid") and not service.get("ipc")
    for volume in service.get("volumes", []):
        assert "docker.sock" not in str(volume), "the Docker socket is root on the host"
        assert str(volume).startswith("econosim-data:"), f"unexpected mount {volume!r}"


def test_only_the_gateway_publishes_a_port_and_only_on_loopback() -> None:
    published = {n: s["ports"] for n, s in SERVICES.items() if s.get("ports")}
    assert set(published) == {"webgateway"}
    for mapping in published["webgateway"]:
        assert str(mapping).startswith("127.0.0.1:"), (
            "cleartext HTTP must not be reachable from the network; use the TLS overlay"
        )


def test_long_running_services_report_health_and_restart() -> None:
    for name in ("webgateway", "jobs-api", "dashboard"):
        health = SERVICES[name]["healthcheck"]
        assert health["test"][0] == "CMD"
        assert health["interval"] and health["retries"] >= 1 and health["start_period"]
    for name in LONG_RUNNING:
        assert SERVICES[name]["restart"] == "unless-stopped"
    assert SERVICES["init-auth"]["restart"] == "no"


def test_the_backends_share_the_gateways_network_and_bind_loopback() -> None:
    for name in ("worker", "jobs-api", "dashboard"):
        assert SERVICES[name]["network_mode"] == "service:webgateway"
    for name in ("jobs-api", "dashboard"):
        command = SERVICES[name]["command"]
        assert command[command.index("--host") + 1] == "127.0.0.1"


def test_the_tls_overlay_requires_a_certificate_and_never_allows_cleartext() -> None:
    gateway = OVERLAY["services"]["webgateway"]
    command = gateway["command"]
    assert "--tls-cert" in command and "--tls-key" in command
    assert "--allow-non-loopback-without-tls" not in command
    assert gateway["ports"] == ["127.0.0.1:8443:8443"]
    assert set(gateway["secrets"]) == {"tls_cert", "tls_key"}
    assert all("file" in secret for secret in OVERLAY["secrets"].values())
    assert "https://" in gateway["healthcheck"]["test"][-1]


def test_the_default_command_still_needs_its_explicit_cleartext_opt_in() -> None:
    command = re.search(r"^CMD (\[.*\])$", DOCKERFILE, re.M)
    assert command is not None
    assert "--allow-non-loopback-without-tls" in command.group(1)
