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
