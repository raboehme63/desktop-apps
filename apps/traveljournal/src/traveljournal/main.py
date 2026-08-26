"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from travelcore.logging_config import setup_logging
from traveljournal.__about__ import APP_NAME, __version__
from traveljournal.ui.main_window import MainWindow
from traveljournal.ui.theme import apply_theme


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("TravelJournal")
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
