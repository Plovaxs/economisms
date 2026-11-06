from pathlib import Path

import pytest

from prometheus.evidence.requirements import (
    build_requirement_register,
    link_repository_notes,
    parse_blueprint_checklists,
)


def minimal_text():
    header = (
        " ID / status        Required capability or control"
        + " " * 28
        + "Acceptance evidence / pass condition"
    )
    acceptance = header.index("Acceptance")

    def row(identifier, requirement, evidence):
        return (
            (" " + identifier).ljust(20)
            + requirement.ljust(acceptance - 20)
            + evidence
            + "\n [ ] NOT VERIFIED\n"
        )

    return (
        header
        + "\n"
        + row("GOV-01", "Define scope", "Signed charter")
        + row("EXT-01", "Define gated extension", "Independent approval")
    )


def test_extracts_source_text_pages_and_acceptance_without_promoting_status():
    items = parse_blueprint_checklists(minimal_text(), expected_count=2)
    assert [item["id"] for item in items] == ["GOV-01", "EXT-01"]
    assert items[0]["requirement"] == "Define scope"
    assert items[0]["acceptance_criterion"] == "Signed charter"
    assert items[0]["source_pdf_page"] == 1
    assert all(
        item["acceptance_status"] == "NOT VERIFIED" and item["owner"] is None for item in items
    )
    assert items[1]["track"] == "separately_gated_live_extension"
    linked = link_repository_notes(
        items, "| GOV-01 (partial) | Scope | test_scope.py |\n| R-03 | risk register | other |"
    )
    assert linked[0]["implementation_evidence_status"] == "repository_notes_present"
    assert linked[1]["implementation_evidence_status"] == "not_evidenced"
    assert linked[0]["repository_notes"][0]["checklist_line"] == 1
    assert linked[0]["acceptance_status"] == "NOT VERIFIED"


def test_duplicate_missing_and_empty_extractions_fail_explicitly():
    with pytest.raises(ValueError, match="expected 374"):
        parse_blueprint_checklists(minimal_text())
    with pytest.raises(ValueError, match="duplicate"):
        parse_blueprint_checklists(minimal_text().replace("EXT-01", "GOV-01"), expected_count=2)
    with pytest.raises(ValueError, match="unexpected"):
        parse_blueprint_checklists(minimal_text().replace("[ ] NOT VERIFIED", ""), expected_count=2)


def test_full_repository_pdf_reconstructs_all_374_requirements_in_29_categories():
    root = Path(__file__).resolve().parents[2]
    register = build_requirement_register(
        root / "docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf",
        root / "CHECKLIST_STATUS.md",
    )
    summary = register["summary"]
    assert summary["requirements"] == 374 and summary["categories"] == 29
    assert (
        summary["research_enterprise"] == 362 and summary["separately_gated_live_extension"] == 12
    )
    assert summary["independently_verified"] == 0
    assert len({item["id"] for item in register["items"]}) == 374
    assert all(
        item["requirement"] and item["acceptance_criterion"] and item["source_rows"]
        for item in register["items"]
    )
    assert (
        register["blueprint_sha256"]
        == "6745f7dd2b027378fbafbd9a870b84d86489932d2068fa10abf0d604ef3bac75"
    )


def test_tracked_register_matches_current_pdf_and_checklist():
    from prometheus.evidence.contracts import read_evidence_bundle

    root = Path(__file__).resolve().parents[2]
    tracked = read_evidence_bundle(
        root / "docs/implementation/blueprint_register.json", require_integrity=True
    )
    rebuilt = build_requirement_register(
        root / "docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf",
        root / "CHECKLIST_STATUS.md",
    )
    # Poppler formatting/version can change its raw text digest; compare the
    # actual parsed inventory and input hashes instead of that diagnostic.
    tracked.pop("artifact_integrity")
    tracked.pop("extracted_text_sha256")
    rebuilt.pop("extracted_text_sha256")
    assert tracked == rebuilt
