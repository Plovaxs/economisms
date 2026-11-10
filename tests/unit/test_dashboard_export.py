from __future__ import annotations

import pytest

from prometheus.dashboard.export import build_export, export_to_json, render_printable_html


def test_build_export_rejects_empty_fields() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_export("", "method", "<p>content</p>")


def test_run_hash_is_deterministic_for_identical_content() -> None:
    a = build_export("pricing", "Black-Scholes closed-form", "<p>same</p>")
    b = build_export("pricing", "Black-Scholes closed-form", "<p>same</p>")
    assert a.run_hash == b.run_hash


def test_run_hash_changes_when_rendered_content_changes_by_one_character() -> None:
    a = build_export("pricing", "method", "<p>content A</p>")
    b = build_export("pricing", "method", "<p>content B</p>")
    assert a.run_hash != b.run_hash


def test_json_export_embeds_the_run_hash_and_method_summary() -> None:
    export = build_export("pricing", "Black-Scholes closed-form", "<p>content</p>")
    payload = export_to_json(export)
    assert payload["run_hash"] == export.run_hash
    assert payload["method_summary"] == "Black-Scholes closed-form"
    assert "rendered_content" not in payload  # not re-embedded wholesale in the JSON summary


def test_printable_html_embeds_the_same_run_hash() -> None:
    export = build_export("pricing", "Black-Scholes closed-form", "<p>content</p>")
    html = render_printable_html(export)
    assert export.run_hash in html
    assert "Black-Scholes closed-form" in html
