from __future__ import annotations

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


def test_content_type_is_guessed_per_extension(dist_root) -> None:
    js = resolve_static_file(dist_root, "/assets/app.js")
    css = resolve_static_file(dist_root, "/assets/app.css")
    html = resolve_static_file(dist_root, "/index.html")
    assert "javascript" in js.content_type
    assert css.content_type == "text/css"
    assert html.content_type == "text/html"


def test_unmatched_path_falls_back_to_the_spa_shell(dist_root) -> None:
    result = resolve_static_file(dist_root, "/lab/pde-solver")
    assert result.body == b"<html>spa shell</html>"


def test_root_path_falls_back_to_the_spa_shell(dist_root) -> None:
    result = resolve_static_file(dist_root, "/")
    assert result.body == b"<html>spa shell</html>"


def test_path_traversal_falls_back_rather_than_escaping_the_dist_root(tmp_path, dist_root) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("outside the dist root")
    result = resolve_static_file(dist_root, "/../secret.txt")
    assert result.body == b"<html>spa shell</html>"
    assert b"outside the dist root" not in result.body


def test_raises_a_clear_error_when_the_build_has_never_been_produced(tmp_path) -> None:
    empty_root = tmp_path / "never-built"
    empty_root.mkdir()
    with pytest.raises(StaticFileNotFoundError, match="npm run build"):
        resolve_static_file(empty_root, "/anything")
