from __future__ import annotations

import os

import pytest

from prometheus.webgateway.static_files import (
    StaticFileNotFoundError,
    resolve_static_file,
)


@pytest.fixture
def dist_root(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>spa shell</html>")
    (root / "assets" / "app.js").write_bytes(b"console.log('hi');")
    (root / "assets" / "app.css").write_text("body { color: red; }")
    return root


def test_serves_an_existing_file_with_its_real_bytes(dist_root) -> None:
    result = resolve_static_file(dist_root, "/assets/app.js")
    assert result.body == b"console.log('hi');"
    assert result.relative_path == "assets/app.js"
    assert result.is_spa_fallback is False


def test_content_types_come_from_a_fixed_table_not_the_host_mime_database(dist_root) -> None:
    (dist_root / "assets" / "font.woff2").write_bytes(b"wOF2")
    (dist_root / "assets" / "blob.unknownext").write_bytes(b"?")
    assert resolve_static_file(dist_root, "/assets/app.js").content_type == (
        "text/javascript; charset=utf-8"
    )
    assert resolve_static_file(dist_root, "/assets/app.css").content_type == (
        "text/css; charset=utf-8"
    )
    assert resolve_static_file(dist_root, "/index.html").content_type == (
        "text/html; charset=utf-8"
    )
    assert resolve_static_file(dist_root, "/assets/font.woff2").content_type == "font/woff2"
    assert resolve_static_file(dist_root, "/assets/blob.unknownext").content_type == (
        "application/octet-stream"
    )


def test_unmatched_extensionless_path_falls_back_to_the_spa_shell(dist_root) -> None:
    result = resolve_static_file(dist_root, "/lab/pde-solver")
    assert result.body == b"<html>spa shell</html>"
    assert result.is_spa_fallback is True
    assert result.is_html is True


def test_root_path_falls_back_to_the_spa_shell(dist_root) -> None:
    result = resolve_static_file(dist_root, "/")
    assert result.body == b"<html>spa shell</html>"


def test_a_missing_file_with_an_extension_is_a_404_not_the_html_shell(dist_root) -> None:
    for path in ("/assets/missing.js", "/robots.txt", "/assets/app.js.map"):
        with pytest.raises(StaticFileNotFoundError):
            resolve_static_file(dist_root, path)


def test_traversal_is_refused_outright_not_served_as_the_shell(tmp_path, dist_root) -> None:
    (tmp_path / "secret.txt").write_text("outside the dist root")
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/.."):
        with pytest.raises(StaticFileNotFoundError):
            resolve_static_file(dist_root, path)


def test_a_symlink_pointing_outside_the_dist_root_is_never_served(tmp_path, dist_root) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("outside the dist root")
    os.symlink(secret, dist_root / "assets" / "leak.txt")
    with pytest.raises(StaticFileNotFoundError):
        resolve_static_file(dist_root, "/assets/leak.txt")


def test_hidden_files_and_directories_are_refused(dist_root) -> None:
    (dist_root / ".env").write_text("SECRET=1")
    (dist_root / ".git").mkdir()
    (dist_root / ".git" / "config").write_text("[core]")
    for path in ("/.env", "/.git/config", "/assets/.hidden"):
        with pytest.raises(StaticFileNotFoundError):
            resolve_static_file(dist_root, path)


def test_well_known_is_the_one_hidden_directory_that_is_served(dist_root) -> None:
    (dist_root / ".well-known").mkdir()
    (dist_root / ".well-known" / "security.txt").write_text("Contact: nobody")
    assert resolve_static_file(dist_root, "/.well-known/security.txt").body == b"Contact: nobody"


def test_an_embedded_nul_is_a_clean_not_found_not_an_unhandled_error(dist_root) -> None:
    with pytest.raises(StaticFileNotFoundError):
        resolve_static_file(dist_root, "/assets/app\x00.js")


def test_raises_a_clear_error_when_the_build_has_never_been_produced(tmp_path) -> None:
    empty_root = tmp_path / "never-built"
    empty_root.mkdir()
    with pytest.raises(StaticFileNotFoundError, match="npm run build"):
        resolve_static_file(empty_root, "/anything")
