"""Combo boxes that change only after a click, never on hover or wheel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox, QListWidget, QWidget


class ClickCombo(QComboBox):
    """Ignore hover-wheel so a parent scroll area can keep scrolling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, False)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        view = self.view()
        if view is not None and view.isVisible():
            super().wheelEvent(event)
            return
        event.ignore()


class ClickListWidget(QListWidget):
    """List that does not consume the wheel while the timeline scrolls past it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, False)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()
