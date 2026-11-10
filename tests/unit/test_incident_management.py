from __future__ import annotations

from datetime import date

import pytest

from prometheus.evidence.alert_routing import AlertRoute, RoutingTable
from prometheus.evidence.incident_management import (
    PR_141_POSTMORTEM,
    STAKEHOLDER_TEMPLATES,
    CorrectiveAction,
    IncidentRota,
    NoActiveRotaError,
    OutageCommunicationTemplate,
    PostmortemRecord,
    page,
)


def test_a_template_requires_all_three_acceptance_fields() -> None:
    with pytest.raises(ValueError, match="impact_statement"):
        OutageCommunicationTemplate(
            audience="x", impact_statement="  ",
            detection_time_placeholder="y", next_steps_placeholder="z",
        )


def test_real_stakeholder_templates_render_with_all_three_fields_present() -> None:
    assert len(STAKEHOLDER_TEMPLATES) >= 2
    for template in STAKEHOLDER_TEMPLATES:
        rendered = template.render()
        assert "Impact:" in rendered
        assert "Detected at:" in rendered
        assert "Next steps:" in rendered


def test_rota_rejects_a_window_ending_before_it_starts() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        IncidentRota(
            window_start=date(2026, 2, 1), window_end=date(2026, 1, 1),
            commander="a", scribe="b", escalation_contact="pager",
        )


def test_rota_rejects_the_same_person_as_commander_and_scribe() -> None:
    with pytest.raises(ValueError, match="distinct roles"):
        IncidentRota(
            window_start=date(2026, 1, 1), window_end=date(2026, 1, 7),
            commander="same-person", scribe="same-person", escalation_contact="pager",
        )


def _configured_table() -> RoutingTable:
    return RoutingTable(
        routes=(
            AlertRoute(severity="P0", owner="commander", escalation_contact="pager"),
            AlertRoute(severity="P1", owner="commander", escalation_contact="pager"),
        )
    )


def test_a_realistic_page_during_an_active_rota_succeeds() -> None:
    """DRI-06's own acceptance wording: "on-call process tested with
    realistic page" -- an active rota, a real severity, a real table."""
    rota = IncidentRota(
        window_start=date(2026, 1, 1), window_end=date(2026, 1, 7),
        commander="alice", scribe="bob", escalation_contact="pager-alice",
    )
    result = page((rota,), date(2026, 1, 3), "P0", _configured_table())
    assert result.rota.commander == "alice"
    assert result.alert_route.severity == "P0"


def test_paging_outside_any_rota_window_fails_loudly() -> None:
    rota = IncidentRota(
        window_start=date(2026, 1, 1), window_end=date(2026, 1, 7),
        commander="alice", scribe="bob", escalation_contact="pager-alice",
    )
    with pytest.raises(NoActiveRotaError):
        page((rota,), date(2026, 2, 1), "P0", _configured_table())


def test_a_postmortem_requires_at_least_one_corrective_action() -> None:
    with pytest.raises(ValueError, match="corrective_actions"):
        PostmortemRecord(
            incident_id="x", occurred_at=date(2026, 1, 1),
            root_cause="r", blameless_statement="b", corrective_actions=(),
        )


def test_a_corrective_action_requires_an_owner() -> None:
    with pytest.raises(ValueError, match="owner"):
        CorrectiveAction(description="fix it", owner="", due_date=date(2026, 1, 1))


def test_the_real_pr_141_postmortem_is_blameless_and_has_a_completed_corrective_action() -> None:
    """Demonstrated against a real past incident already in this
    repository's own history, not an invented example."""
    assert "no individual or process failure" in PR_141_POSTMORTEM.blameless_statement
    assert len(PR_141_POSTMORTEM.corrective_actions) == 1
    assert PR_141_POSTMORTEM.corrective_actions[0].completed is True
    assert PR_141_POSTMORTEM.open_actions() == ()


def test_open_actions_excludes_completed_ones() -> None:
    record = PostmortemRecord(
        incident_id="x",
        occurred_at=date(2026, 1, 1),
        root_cause="r",
        blameless_statement="b",
        corrective_actions=(
            CorrectiveAction(
                description="done", owner="o", due_date=date(2026, 1, 1), completed=True
            ),
            CorrectiveAction(description="pending", owner="o", due_date=date(2026, 2, 1)),
        ),
    )
    assert [a.description for a in record.open_actions()] == ["pending"]
