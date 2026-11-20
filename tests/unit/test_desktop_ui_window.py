# ruff: noqa: E402
"""PR-205: the whole window, driven like a person would, over a real session and a real worker.

Nothing here fakes the engine: Run submits a real job to the real queue, the real isolated worker
runs it, and the page shows the result read back through its hash verification. What is stubbed is
only the operating system's file dialogs and the "really close?" question.
"""

from __future__ import annotations

import json
import os
import types
from pathlib import Path
from typing import Any

import pytest

from tests.unit import desktop_ui_support as support

support.require_qt()

from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QTreeWidget,
    QWidget,
)

from prometheus.desktop import findings as findings_module
from prometheus.desktop.findings import FindingsDocument
from prometheus.desktop.runner import WorkerLoop
from prometheus.desktop.ui import app as app_module
from prometheus.desktop.ui import theme
from prometheus.desktop.ui.main_window import PAGES, MainWindow
from prometheus.desktop.ui.pages.findings import FindingsPage

# ------------------------------------------------------------------ helpers


def child_pids() -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            parent = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
            command = (entry / "cmdline").read_bytes()
        except (OSError, ValueError, IndexError):
            continue
        if parent == os.getpid() and b"prometheus.jobs.child" in command:
            found.append(int(entry.name))
    return found


def wait(window: MainWindow, until: Any, *, timeout: float = 90.0) -> bool:
    """Run the event loop, taking a look at the queue each turn, until `until()` holds."""

    def check() -> bool:
        window.tick()
        return bool(until())

    return support.pump(check, timeout=timeout)


def run_small_inflationcast(window: MainWindow) -> str:
    window.show_page("labs")
    window.labs.select_kind("inflationcast")
    form = window.labs.form()
    form.set_values({("max_epochs",): "3", ("bootstrap_resamples",): "20", ("seed",): "5"})
    job_id = window.labs.run()
    assert job_id is not None
    assert wait(window, lambda: window.labs.result.view is not None), "the result never appeared"
    return job_id


# ------------------------------------------------------------------ the chrome


def test_the_statement_of_what_this_is_is_on_screen_on_every_page(window: MainWindow) -> None:
    assert (
        "research only"
        in window.findChildren(QWidget, "banner")[0]
        .findChildren(type(window.gate_badge))[0]
        .text()
        .lower()
    )
    assert "Simulated data" in window.banner_text.text()
    assert "NO-GO" in window.gate_badge.text() and "✕" in window.gate_badge.text()
    for key, _ in PAGES:
        window.show_page(key)
        assert window.gate_badge.isVisible() and window.banner_text.isVisible(), key


def test_every_page_can_be_reached_from_the_sidebar_and_the_keyboard(window: MainWindow) -> None:
    assert [window.nav.item(i).text() for i in range(window.nav.count())] == [t for _, t in PAGES]
    for row, (key, title) in enumerate(PAGES):
        window.nav.setCurrentRow(row)
        assert window.current_page == key and title in window.windowTitle()
    shortcuts = {s.key().toString(): s for s in window.findChildren(QShortcut)}
    assert sorted(shortcuts) == [f"Ctrl+{n}" for n in range(1, len(PAGES) + 1)]
    shortcuts["Ctrl+3"].activated.emit()
    assert window.current_page == "explorers"
    shortcuts["Ctrl+1"].activated.emit()
    assert window.current_page == "overview"


def test_the_status_bar_is_idle_until_a_job_runs(window: MainWindow) -> None:
    window.tick()
    assert window.job_label.text() == "No job running"
    assert window.job_progress.isHidden() and window.job_cancel.isHidden()
    assert window.worker_error.text() == ""


def test_every_interactive_widget_has_an_accessible_name_and_can_take_focus(
    window: MainWindow,
) -> None:
    named = (
        QLineEdit,
        QComboBox,
        QDateEdit,
        QPlainTextEdit,
        QTableWidget,
        QTreeWidget,
        QListWidget,
        QTabWidget,
        QTextBrowser,
    )
    offenders: list[str] = []
    for key, _ in PAGES:
        window.show_page(key)
        support.settle(0.1)
        if key == "labs":
            for kind in window.labs.kinds():
                window.labs.select_kind(kind)  # every form, not only the first
        for widget in window.pages[key].findChildren(QWidget):
            if widget.objectName().startswith("qt_") or widget.isHidden():
                continue  # Qt's own internals (a table's corner button) and what is not shown
            where = f"{key}:{type(widget).__name__}:{widget.objectName() or widget.toolTip()[:30]}"
            if isinstance(widget, QAbstractButton | QToolButton):
                if not (widget.text() or widget.accessibleName()):
                    offenders.append(where + " (button without text or name)")
                if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
                    offenders.append(where + " (button that cannot be focused)")
            elif isinstance(widget, named) and not widget.accessibleName():
                offenders.append(where)
            elif isinstance(widget, QLineEdit | QComboBox | QDateEdit | QPlainTextEdit) and (
                widget.focusPolicy() == Qt.FocusPolicy.NoFocus
            ):
                offenders.append(where + " (input that cannot be focused)")
    # a QLineEdit that is a spin box's or combo box's internal editor is not a separate control
    offenders = [o for o in offenders if "qt_spinbox_lineedit" not in o and "lineEdit" not in o]
    assert offenders == [], offenders[:12]


# ------------------------------------------------------------------ a lab, end to end


def test_a_lab_runs_for_real_and_its_result_is_shown_verified(window: MainWindow) -> None:
    job_id = run_small_inflationcast(window)
    labs = window.labs
    assert window.session.get(job_id).status == "succeeded"
    assert labs.status_badge.status == "succeeded" and "took" in labs.status_text.text()
    assert labs.tabs.currentIndex() == 1, "the page moved to the result"
    view = labs.result.view
    assert view is not None and view.kind == "inflationcast"
    assert dict(view.provenance)["Job"] == job_id
    assert labs.result.verdict.text().endswith(view.verdict.replace("_", " "))  # type: ignore[union-attr]
    comparison_cards = [c for c in labs.result.chart_cards if c.title == "Models"]
    assert comparison_cards and comparison_cards[0].table.rowCount() == 5
    assert "SIMULATED DATA" in labs.result._disclaimer.text()
    assert (
        labs.result.rerun_button.isHidden() is False
        and labs.result.export_button.isHidden() is False
    )
    assert wait(window, lambda: window.job_label.text() == "No job running")
    assert child_pids() == []


def test_the_overview_and_history_follow_the_job(window: MainWindow) -> None:
    job_id = run_small_inflationcast(window)
    window.show_page("history")
    assert window.history.job_ids() == [job_id]
    window.history.select(job_id)
    assert not window.history.open_button.isHidden() and window.history.open_button.isEnabled()
    assert window.history.cancel_button.isEnabled() is False, "it is finished"
    assert "succeeded" in window.history.detail_badge.text()
    window.show_page("overview")
    assert window.overview.jobs_tile.value_text.startswith("1")
    opens = [b for b in window.overview.findChildren(QAbstractButton) if b.text() == "Open result"]
    assert len(opens) == 1
    window.show_page("explorers")
    opens[0].click()
    assert window.current_page == "labs" and window.labs.result.view is not None


def test_a_mistake_in_a_field_stops_the_run_and_points_at_the_field(window: MainWindow) -> None:
    window.show_page("labs")
    window.labs.select_kind("inflationcast")
    window.labs.tabs.setCurrentIndex(1)
    form = window.labs.form()
    form.set_values({("seed",): "abc"})
    assert window.labs.run() is None
    assert window.labs.tabs.currentIndex() == 0, "back to the parameters, where the error is"
    assert ("seed",) in form.error_texts() and "whole number" in form.error_texts()[("seed",)]
    assert "attention" in window.labs.admission.text()
    assert window.session.jobs() == ()


def test_a_recipe_beyond_the_limits_is_refused_with_the_limit_named(window: MainWindow) -> None:
    window.show_page("labs")
    window.labs.select_kind("inflationcast")
    window.labs.form().set_values({("max_epochs",): "10000000"})
    assert window.labs.validate_now() is False
    assert "max_epochs" in window.labs.admission.text() and window.labs.admission.text().startswith(
        "✕"
    )
    assert window.labs.run() is None and window.session.jobs() == ()


def test_the_admission_line_says_how_close_a_recipe_is_to_a_limit(window: MainWindow) -> None:
    window.show_page("labs")
    window.labs.select_kind("inflationcast")
    window.labs.form().reset()
    assert window.labs.validate_now() is True
    assert window.labs.admission.text().startswith("✓  Admitted. Closest to a limit:")


def test_each_labs_form_is_judged_and_admitted_from_its_defaults(window: MainWindow) -> None:
    window.show_page("labs")
    for kind in window.labs.kinds():
        window.labs.select_kind(kind)
        assert window.labs.validate_now() is True, (kind, window.labs.admission.text())


def test_cancelling_a_running_job_stops_it_and_leaves_no_process(window: MainWindow) -> None:
    window.show_page("labs")
    window.labs.select_kind("rl_hedge")
    window.labs.form().set_values({("n_epochs",): "400", ("n_paths",): "800", ("n_steps",): "60"})
    job_id = window.labs.run()
    assert job_id is not None
    assert wait(window, lambda: window.session.get(job_id).status == "running")
    assert "running" in window.job_label.text() and not window.job_cancel.isHidden()
    assert not window.labs.cancel_button.isHidden()
    window.labs.cancel_button.click()
    assert wait(window, lambda: window.session.get(job_id).status == "cancelled", timeout=30)
    assert wait(window, lambda: window.labs.status_badge.status == "cancelled")
    assert window.labs.result.isHidden()
    assert window.labs.result_empty.text() == "This job ended: cancelled."
    assert wait(window, lambda: child_pids() == [], timeout=15)
    assert wait(window, lambda: window.job_label.text() == "No job running")


def test_the_status_bar_can_cancel_the_running_job_too(window: MainWindow) -> None:
    window.show_page("labs")
    window.labs.select_kind("rl_hedge")
    window.labs.form().set_values({("n_epochs",): "400", ("n_paths",): "800", ("n_steps",): "60"})
    job_id = window.labs.run()
    assert job_id is not None
    assert wait(window, lambda: window.session.get(job_id).status == "running")
    window.job_cancel.click()
    assert wait(window, lambda: window.session.get(job_id).status == "cancelled", timeout=30)


def test_a_past_jobs_settings_come_back_into_the_form_and_the_result_can_be_exported(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = run_small_inflationcast(window)  # seed 5, 3 epochs, 20 resamples
    window.labs.form().set_values({("seed",): "99", ("max_epochs",): "7"})
    window.show_page("history")
    window.history.select(job_id)
    window.history.rerun_button.click()
    assert window.current_page == "labs" and window.labs.tabs.currentIndex() == 0
    values = window.labs.form().values()
    assert values[("seed",)] == "5" and values[("max_epochs",)] == "3"
    assert values[("bootstrap_resamples",)] == "20"

    target = tmp_path / "exported.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window.show_page("history")
    window.history.select(job_id)
    window.history.export_button.click()
    body = json.loads(target.read_text())
    assert body["job_context"]["job_id"] == job_id and "inflationcast" in body
    assert window.history.audit_text.text().startswith("✓  Exported")


def test_the_audit_chain_can_be_verified_from_the_history(window: MainWindow) -> None:
    run_small_inflationcast(window)
    window.show_page("history")
    assert window.history.verify_audit() is True
    assert (
        window.history.audit_text.text().startswith("✓")
        and "verifies" in window.history.audit_text.text()
    )


def test_a_finished_job_can_be_reopened_from_the_history_row(window: MainWindow) -> None:
    job_id = run_small_inflationcast(window)
    window.labs.result.clear()
    window.show_page("history")
    window.history.select(job_id)
    window.history.open_button.click()
    assert window.current_page == "labs" and window.labs.result.view is not None
    assert dict(window.labs.result.view.provenance)["Job"] == job_id


# ------------------------------------------------------------------ the explorers


def test_an_explorer_computes_in_a_child_process_and_draws_its_picture(window: MainWindow) -> None:
    window.show_page("explorers")
    window.explorers.select("market_paths")
    assert wait(
        window, lambda: window.explorers.result.view is not None and not window.explorers.busy()
    )
    view = window.explorers.result.view
    assert view is not None and view.title == "Market paths"
    assert window.explorers.result.tabs.currentIndex() == 1, (
        "a picture-first result opens on its chart"
    )
    fan = window.explorers.result.chart_cards[0]
    assert [line.name for line in fan.line_chart.lines] == [
        "5th percentile",
        "Median",
        "95th percentile",
    ]
    assert fan.legend.isHidden(), "a band is one series: no legend"
    assert "Computed in" in window.explorers.status.text()
    assert "SIMULATED DATA" in window.explorers.result._disclaimer.text()


def test_the_pricing_explorer_draws_two_curves_with_a_legend(window: MainWindow) -> None:
    window.show_page("explorers")
    window.explorers.select("pricing")
    assert wait(
        window, lambda: window.explorers.result.view is not None and not window.explorers.busy()
    )
    cards = {c.title: c for c in window.explorers.result.chart_cards}
    value = cards["Value curve"]
    assert [n for n, _ in value.legend.entries] == ["Option value", "Payoff at expiry"]
    assert not value.legend.isHidden() and value.table.rowCount() == 41


def test_an_explorer_refuses_a_value_outside_its_range(window: MainWindow) -> None:
    window.show_page("explorers")
    window.explorers.select("economy")
    assert wait(window, lambda: not window.explorers.busy())
    form = window.explorers.form("economy")
    form.set_values({("n_steps",): "500"})
    assert window.explorers.compute() is False
    assert (
        "n_steps" not in window.explorers.status.text()
        and "attention" in window.explorers.status.text()
    )
    assert "must be at most 120" in form.error_texts()[("n_steps",)]
    assert window.explorers.busy() is False


def test_two_parameters_that_are_too_much_together_are_refused(window: MainWindow) -> None:
    window.show_page("explorers")
    window.explorers.select("market_paths")
    assert wait(window, lambda: not window.explorers.busy())
    window.explorers.form("market_paths").set_values({("n_steps",): "365", ("n_paths",): "20000"})
    assert window.explorers.compute() is False
    assert "2,000,000" in window.explorers.form("market_paths")._general_error.text()


def test_moving_to_another_explorer_while_one_computes_does_not_show_the_wrong_result(
    window: MainWindow,
) -> None:
    window.show_page("explorers")
    window.explorers.select("market_paths")
    window.explorers.select("hedge_actions")
    assert wait(
        window,
        lambda: window.explorers.result.view is not None and not window.explorers.busy(),
    )
    assert window.explorers.result.view.title == "Hedge ratios"  # type: ignore[union-attr]
    assert window.explorers.names()[0] == "economy" and len(window.explorers.names()) == 7


def test_an_explorer_calculation_can_be_cancelled(window: MainWindow) -> None:
    window.show_page("explorers")
    window.explorers.select("portfolio_risk")
    assert wait(window, lambda: not window.explorers.busy())
    window.explorers.form("portfolio_risk").set_values({("n",): "100000"})
    assert window.explorers.compute() is True
    window.explorers.cancel_button.click()
    assert wait(window, lambda: not window.explorers.busy(), timeout=20)
    assert child_pids() == []


def test_the_static_explorers_have_no_form_and_show_their_rows(window: MainWindow) -> None:
    window.show_page("explorers")
    window.explorers.select("validation_issues")
    assert wait(
        window, lambda: window.explorers.result.view is not None and not window.explorers.busy()
    )
    assert window.explorers.reset_button.isHidden() and window.explorers.synthetic.isHidden()
    assert window.explorers.result.tables and window.explorers.result.tables[0].rowCount() == 2


# ------------------------------------------------------------------ the findings


def test_the_findings_page_lists_the_whole_document(window: MainWindow) -> None:
    page = window.findings
    entries = page.entries()
    assert entries[0] == "gate" and entries[-1] == "limitations"
    assert [e for e in entries if e.startswith("finding:")] == [
        f"finding:{n}" for n in range(1, 19)
    ]
    page.select("finding:13")
    text = page.browser.toPlainText()
    assert "Finding 13 (PR-197)" in text and "look-ahead" in text
    page.select("gate")
    assert "NO-GO" in page.browser.toPlainText()
    page.select("limitations")
    assert "No independent human review" in page.browser.toPlainText()


def test_searching_the_findings_filters_the_list(window: MainWindow) -> None:
    page = window.findings
    page.search.setText("GARCH")
    hits = page.visible_entries()
    assert "finding:15" in hits and "finding:17" in hits and "finding:1" not in hits
    assert "match" in page.count.text()
    page.search.setText("zzz-no-such-text-anywhere")
    assert page.visible_entries() == []
    page.search.setText("")
    assert len(page.visible_entries()) == len(page.entries())
    assert page.count.text() == "18 findings recorded"


def test_without_the_document_the_page_says_so_and_invents_nothing(
    qapp: Any, theme_dark: Any
) -> None:
    page = FindingsPage(FindingsDocument(False, "", "", (), ""))
    assert page.entries() == [] and not page.search.isEnabled()
    assert (
        "not found" in page.unavailable.text() and "Nothing is invented" in page.unavailable.text()
    )
    assert page.browser.isHidden()
    assert findings_module.load(Path("/nonexistent/file.md")).available is False


def test_a_link_in_a_finding_is_never_followed(window: MainWindow) -> None:
    browser = window.findings.browser
    assert browser.openLinks() is False and browser.openExternalLinks() is False


def test_a_finding_is_prose_only_raw_html_is_text_and_nothing_is_loaded(
    qapp: Any, theme_dark: Any
) -> None:
    from PySide6.QtCore import QUrl

    from prometheus.desktop.findings import parse

    document = parse(
        "## Finding 1 (PR-1): a title\n\n"
        "Text with <img src='file:///etc/hostname'> and <b>raw</b> and "
        "<a href='http://example.invalid/'>a link</a>.\n\n![pic](file:///etc/hostname)\n"
    )
    page = FindingsPage(document)
    page.select("finding:1")
    shown = page.browser.toPlainText()
    assert "<img src='file:///etc/hostname'>" in shown and "<b>raw</b>" in shown
    assert page.browser.loadResource(2, QUrl("file:///etc/hostname")) is None
    assert page.browser.loadResource(1, QUrl("http://example.invalid/x.css")) is None
    assert "<img" not in page.list.item(0).toolTip()


# ------------------------------------------------------------------ the system page


def test_the_system_page_states_the_gate_the_checks_and_the_data(window: MainWindow) -> None:
    window.show_page("system")
    page = window.system
    assert "NO-GO" in page.gate_badge.text()
    assert set(page.cards) == {"gate", "checks", "data", "storage", "settings"}
    assert page.report is not None and page.report.ok
    assert page.data_table.rowCount() == len(page.report.data_files) == 24
    assert {page.data_table.cell(r, 2) for r in range(24)} == {"ok"}
    labels = " ".join(label.text() for label in page.cards["checks"].findChildren(QLabel))
    assert "python" in labels and "data integrity" in labels and "locked dependencies" in labels
    assert "SIMULATED DATA" in " ".join(
        lab.text() for lab in page.cards["gate"].findChildren(type(window.banner_text))
    )


def test_the_colour_theme_can_be_changed_from_the_system_page(window: MainWindow) -> None:
    window.show_page("system")
    dark = support.grab_pixels(window)
    window.system.theme_box.setCurrentText("Light")
    assert window.theme_mode == "light" and theme.current() is theme.LIGHT
    assert support.grab_pixels(window) != dark
    window.show_page("explorers")
    assert wait(
        window, lambda: window.explorers.result.view is not None and not window.explorers.busy()
    )
    card = window.explorers.result.chart_cards[0]
    assert card.line_chart.legend_entries() == [] or card.line_chart.legend_entries()[0][
        1
    ].name().lower() in (theme.LIGHT.series[0].lower(),)
    window.set_theme("dark")
    assert theme.current() is theme.DARK


def test_the_launcher_can_be_added_and_removed_from_the_system_page(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    window.show_page("system")
    page = window.system
    page.install_button.click()
    entry = tmp_path / "data" / "applications" / "econosim.desktop"
    assert entry.is_file() and page.launcher_text.text().startswith("✓  Added")
    page.remove_button.click()
    assert not entry.exists() and page.launcher_text.text().startswith("✓  Removed")
    page.remove_button.click()
    assert page.launcher_text.text() == "Nothing to remove."


def test_the_storage_card_says_where_the_work_is_kept(window: MainWindow) -> None:
    window.show_page("system")
    table = [
        t
        for t in window.system.cards["storage"].findChildren(type(window.system.data_table))
        if t.rowCount() == 5
    ][0]
    cells = {table.cell(r, 0): table.cell(r, 1) for r in range(table.rowCount())}
    assert cells["State directory"] == str(window.session.root)
    assert cells["Isolated job worker"] == "available" and cells["Jobs"] == "none yet"


def test_the_overview_leads_with_the_standing_and_offers_the_next_steps(window: MainWindow) -> None:
    page = window.overview
    assert "NO-GO" in page.gate_badge.text()
    assert page.health_tile.value_text == "All clear"
    assert (
        page.data_tile.value_text == "24 of 24 verified" and page.findings_tile.value_text == "18"
    )
    assert page.jobs_tile.value_text == "0"
    for key in ("labs", "explorers", "findings"):
        window.show_page("overview")
        page.action_buttons[key].click()
        assert window.current_page == key


# ------------------------------------------------------------------ closing


def test_closing_with_a_job_running_asks_first_and_cancels_it_on_yes(
    qapp: Any, ui_session: Any, theme_dark: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = WorkerLoop(ui_session, idle_seconds=0.05)
    runner.start()
    shown = MainWindow(ui_session, state_dir=tmp_path / "state", runner=runner, theme_mode="dark")
    shown.show()
    shown.labs.select_kind("rl_hedge")
    shown.labs.form().set_values({("n_epochs",): "400", ("n_paths",): "800", ("n_steps",): "60"})
    job_id = shown.labs.run()
    assert job_id is not None
    assert wait(shown, lambda: ui_session.get(job_id).status == "running")

    asked: list[str] = []

    def answer(parent: Any, title: str, text: str, *rest: Any) -> Any:
        asked.append(text)
        return QMessageBox.StandardButton.No if len(asked) == 1 else QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)
    assert shown.close() is False and shown.isVisible(), "answering No keeps the window"
    assert ui_session.get(job_id).status == "running"
    assert shown.close() is True
    assert len(asked) == 2 and "cancel the job that is running" in asked[0]
    # closing stops the worker thread, and stopping it cancels the job it was running and waits
    # for the child process to go: both are already true when close() returns
    assert not runner.alive
    assert ui_session.get(job_id).status == "cancelled"
    assert child_pids() == []
    shown.deleteLater()


def test_closing_when_idle_does_not_ask(
    qapp: Any, ui_session: Any, theme_dark: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("asked while idle"))
    shown = MainWindow(ui_session, state_dir=tmp_path / "state", theme_mode="dark")
    shown.show()
    assert shown.close() is True
    shown.deleteLater()


def test_a_window_with_no_worker_still_opens(
    qapp: Any, ui_session: Any, theme_dark: Any, tmp_path: Path
) -> None:
    shown = MainWindow(
        ui_session,
        state_dir=tmp_path / "state",
        runner=None,
        theme_mode="dark",
        confirm_close=False,
    )
    shown.show()
    shown.tick()
    assert shown.worker_error.text() == ""
    shown.shutdown()
    shown.shutdown()  # safe to repeat
    shown.close()
    shown.deleteLater()


def test_a_platform_that_cannot_run_jobs_says_so_on_the_lab(
    qapp: Any, theme_dark: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prometheus.desktop import session as session_module

    monkeypatch.setattr(session_module, "sys", types.SimpleNamespace(platform="darwin"))
    elsewhere = session_module.LocalSession(tmp_path / "elsewhere")
    shown = MainWindow(
        elsewhere, state_dir=tmp_path / "elsewhere", theme_mode="dark", confirm_close=False
    )
    shown.show()
    assert shown.labs.run_button.isEnabled() is False
    assert "needs Linux" in shown.labs.admission.text()
    shown.shutdown()
    shown.close()
    shown.deleteLater()


# ------------------------------------------------------------------ the application as a whole


def test_the_screenshot_command_renders_every_page_for_real(qapp: Any, tmp_path: Path) -> None:
    out = tmp_path / "shots"
    assert app_module.screenshots(out, theme="dark") == 0
    images = sorted(out.glob("*.png"))
    names = [p.stem.split("-", 1)[1] for p in images]
    assert names == [
        "overview",
        "labs-parameters",
        "labs-result",
        "explorers-market-paths",
        "explorers-pricing",
        "findings",
        "history",
        "system",
    ]
    from PySide6.QtGui import QImage

    for path in images:
        image = QImage(str(path))
        assert (image.width(), image.height()) == app_module.WINDOW_SIZE, path.name
        assert support.distinct_colors(image, step=8) > 40, f"{path.name} looks blank"
    # the lab result screenshot shows a real, verified run
    result = QImage(str(out / "03-labs-result.png"))
    parameters = QImage(str(out / "02-labs-parameters.png"))
    assert result != parameters


def test_run_opens_the_window_and_returns_when_it_is_closed(
    qapp: Any, tmp_path: Path, theme_dark: Any
) -> None:
    from PySide6.QtCore import QTimer

    state = tmp_path / "state-for-run"
    state.mkdir(mode=0o700)
    QTimer.singleShot(1200, qapp.quit)
    assert app_module.run(state, theme="dark") == 0
    assert (state / "jobs.sqlite3").is_file()
    assert child_pids() == []


def test_the_app_icon_is_a_real_icon_at_several_sizes(qapp: Any) -> None:
    icon = app_module.app_icon()
    assert not icon.isNull()
    sizes = {size.width() for size in icon.availableSizes()}
    assert {16, 32, 64, 256} <= sizes
    assert app_module.preferred_size(qapp)[0] <= 1500


def test_a_second_application_object_is_not_created(qapp: Any) -> None:
    assert app_module.create_application() is qapp
