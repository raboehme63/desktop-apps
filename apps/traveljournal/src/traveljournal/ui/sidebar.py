"""Left-hand navigation."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QLabel, QPushButton, QVBoxLayout, QWidget

NAV_ITEMS = (
    ("project", "Projekt"),
    ("import", "Import"),
    ("timeline", "Timeline"),
    ("map", "Karte"),
    ("photos", "Fotos"),
    ("export", "Export"),
)


class Sidebar(QWidget):
    page_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(6)

        brand = QLabel("Reisetagebuch")
        brand.setObjectName("brand")
        sub = QLabel("Lokal · Phase 7")
        sub.setObjectName("brandSub")
        layout.addWidget(brand)
        layout.addWidget(sub)
        layout.addSpacing(18)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for key, label in NAV_ITEMS:
            button = QPushButton(label)
            button.setObjectName("sidebarButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, page=key: self.page_changed.emit(page))
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self._buttons["project"].setChecked(True)

    def current_key(self) -> str:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return "project"

    def set_current(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)
