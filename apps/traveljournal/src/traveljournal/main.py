"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from travelcore.logging_config import setup_logging
from traveljournal.ui.main_window import MainWindow
from traveljournal.ui.theme import apply_theme


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Reisetagebuch")
    app.setOrganizationName("TravelJournal")
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
