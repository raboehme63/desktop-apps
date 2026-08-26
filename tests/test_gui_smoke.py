"""GUI smoke test. Requires an offscreen Qt platform plugin."""

from __future__ import annotations

import os
from pathlib import Path


def test_main_window_starts() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QScrollArea

    from traveljournal.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Reisetagebuch"
    assert window.stack.count() == 7
    titles = [action.text() for action in window.menuBar().actions()]
    assert "Projekt" in titles
    assert window._settings_action is not None
    assert not window._settings_action.isEnabled()
    headers = [
        window.import_view.table.horizontalHeaderItem(index).text()
        for index in range(window.import_view.table.columnCount())
    ]
    assert headers == ["Datei", "Typ", "Aufnahmezeit", "GPS", "Kamera / Pilot"]
    assert "matched" in window.import_view._stat_labels
    assert window.import_view._stat_labels["matched"].text() == "0"
    assert window.import_view._stat_labels["unlocated"].text() == "0"
    assert window.import_view._preview_image is not None
    assert "Mouseover" in window.import_view._preview_meta.text()
    assert window.project_view.name_label.text() == "–"
    assert not window.project_view.name_edit.isEnabled()
    assert window.project_view.load_progress.format() == "Bereit"
    assert window._load_progress.isHidden()
    assert not window.import_view.is_loading_index
    assert isinstance(window.timeline_view._scroll, QScrollArea)
    _ = app


def test_new_project_dialog_preview_and_values(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from travelcore.exceptions import ProjectError
    from traveljournal.views.project_view import NewProjectDialog

    app = QApplication.instance() or QApplication([])
    dialog = NewProjectDialog(initial_parent=tmp_path)
    assert dialog.dir_edit.text() == str(tmp_path)
    dialog.name_edit.setText("Italien: 2025")
    parent, name = dialog.values()
    assert name == "Italien: 2025"
    assert parent == tmp_path
    assert dialog.preview_label.text() == str(tmp_path / "Italien 2025")
    dialog.name_edit.setText("")
    try:
        dialog.values()
    except ProjectError as exc:
        assert "Projektnamen" in str(exc)
    else:
        raise AssertionError("expected ProjectError")
    _ = app


def test_format_local_datetime_uses_local_time_not_utc() -> None:
    from datetime import UTC, datetime

    from traveljournal.views.project_view import format_local_datetime

    utc = datetime(2026, 8, 26, 14, 49, 0, tzinfo=UTC)
    naive = datetime(2026, 8, 26, 14, 49, 0)
    expected = utc.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert format_local_datetime(utc) == expected
    assert format_local_datetime(naive) == expected


def test_format_import_status() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from traveljournal.views.import_view import format_import_status

    assert format_import_status(0, 0, "Verzeichnis wird durchsucht…") == "Verzeichnis wird durchsucht…"
    assert format_import_status(0, 12, "12 Dateien gefunden") == "12 Dateien gefunden"
    assert (
        format_import_status(3, 12, "Analysiere DSC_0123.jpg") == "Analysiere DSC_0123.jpg · 3 von 12 (25 %)"
    )
    assert format_import_status(2, 4, "", r"C:\fotos\flug.igc") == "flug.igc · 2 von 4 (50 %)"


def test_progress_bar_format_uses_qt_percent_placeholder() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from traveljournal.views.import_view import progress_bar_format

    assert progress_bar_format("Analysiere spur.GPX") == "Analysiere spur.GPX  %v von %m (%p %)"
    assert "%%" not in progress_bar_format("Datei 100% fertig")


def test_file_preview_text_includes_heading_and_35mm() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import UTC, datetime

    from travelcore.database.models import SourceFile
    from traveljournal.views.import_view import file_preview_text

    row = SourceFile(
        id=1,
        project_id=1,
        path=r"C:\media\foto.jpg",
        filename="foto.jpg",
        file_kind="photo",
        extension=".jpg",
        size_bytes=2048,
        imported_at=datetime(2025, 5, 15, 12, 0, tzinfo=UTC),
        status="ok",
        timezone_unknown=True,
        camera="Canon EOS R6",
        heading_degrees=123.5,
        heading_ref="T",
        focal_length_35mm=24.0,
    )
    text = file_preview_text(row, dhv_url="https://example.test/flight")
    assert "foto.jpg" in text
    assert "123.5" in text
    assert "geografisch Nord" in text
    assert "24" in text
    assert "Canon EOS R6" in text
    assert "https://example.test/flight" in text
