"""User-facing error dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from travelcore.exceptions import ReadOnlyProjectError


def report_exception(parent: QWidget | None, title: str, exc: BaseException) -> None:
    """Show a warning, or the read-only hint when the project cannot be saved."""

    if isinstance(exc, ReadOnlyProjectError):
        QMessageBox.information(parent, ReadOnlyProjectError.TITLE, str(exc))
        return
    QMessageBox.warning(parent, title, str(exc))
