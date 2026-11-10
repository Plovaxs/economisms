from __future__ import annotations

from datetime import date

from prometheus.dashboard.accessibility import check_accessibility
from prometheus.dashboard.audit_trail import render_audit_trail
from prometheus.evidence.model_registry import ModelRegistryEntry


def _real_promoted_entry() -> ModelRegistryEntry:
    entry = ModelRegistryEntry("dashboard-demo-model")
    entry.transition(
        "evaluated", "ci-pipeline", date(2026, 1, 1), "automated eval pass", approved_by="n/a"
    )
    entry.transition(
        "approved",
        "reviewer",
        date(2026, 1, 2),
        "passed validation gate",
        approved_by="project maintainer",
        content_hash="a" * 64,
    )
    return entry


def test_audit_trail_renders_every_real_transition_in_order() -> None:
    entry = _real_promoted_entry()
    html = render_audit_trail(entry)
    assert "automated eval pass" in html
    assert "passed validation gate" in html
    assert "project maintainer" in html
    assert "a" * 64 in html
    # row order: the first real transition's own reason text must precede the second's.
    assert html.index("automated eval pass") < html.index("passed validation gate")


def test_audit_trail_names_its_current_real_state() -> None:
    entry = _real_promoted_entry()
    html = render_audit_trail(entry)
    assert "current state: <strong>approved</strong>" in html


def test_audit_trail_page_passes_the_real_accessibility_checks() -> None:
    html = render_audit_trail(_real_promoted_entry())
    assert check_accessibility(html).passes()
