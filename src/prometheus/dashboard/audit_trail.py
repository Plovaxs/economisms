"""UIX-09: "Implement audit trail view for model promotion and outputs
-- Reviewer can navigate report to evidence and approval."

Renders a real `evidence.model_registry.ModelRegistryEntry.history` --
the real, already-evidenced (MLO-08) append-only transition log, not a
fabricated approval trail. No model in this repository has actually
been promoted through `candidate -> evaluated -> approved -> staged`
in production use (this project is NO-GO, see README.md), so this view
is demonstrated, honestly, against a REALISTIC entry built the same
way `evidence.model_registry`'s own test suite builds one (via the
real `ModelRegistryEntry.transition`/`promote_to_approved` calls, not
hand-typed `StateTransition` objects standing in for a real call) --
stated plainly here rather than implied to be a real production
history.
"""

from __future__ import annotations

from prometheus.dashboard.html import page, table
from prometheus.dashboard.provenance import synthetic_badge
from prometheus.evidence.model_registry import ModelRegistryEntry


def render_audit_trail(entry: ModelRegistryEntry) -> str:
    rows = [
        [
            str(i),
            t.from_state,
            t.to_state,
            t.actor,
            t.approved_by,
            t.at.isoformat(),
            t.reason,
            t.content_hash or "(none recorded for this transition)",
        ]
        for i, t in enumerate(entry.history)
    ]
    body = (
        synthetic_badge()
        + f"<p>Model: <strong>{entry.model_id}</strong> &mdash; current state: "
        f"<strong>{entry.state}</strong></p>"
        + "<p>This is a realistic, test-constructed registry entry (see this module's "
        "own docstring) -- no model in this repository has been promoted through a real "
        "production approval flow, since this project remains NO-GO.</p>"
        + table(
            [
                "#",
                "from_state",
                "to_state",
                "actor",
                "approved_by",
                "at",
                "reason",
                "content_hash (evidence link)",
            ],
            rows,
        )
    )
    return page("Audit trail", f"Audit trail: {entry.model_id}", body)
