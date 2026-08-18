"""GUI smoke test. Requires an offscreen Qt platform plugin."""

from __future__ import annotations

import os


def test_main_window_starts() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from traveljournal.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Reisetagebuch"
    assert window.stack.count() == 7
    titles = [action.text() for action in window.menuBar().actions()]
    assert "Projekt" in titles
    assert window._settings_action is not None
    assert not window._settings_action.isEnabled()
    _ = app


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
