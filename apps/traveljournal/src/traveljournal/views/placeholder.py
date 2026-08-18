"""Shared placeholder page for later phases."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class PlaceholderView(QWidget):
    def __init__(self, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        subtitle = QLabel("Folgt in einer späteren Phase")
        subtitle.setObjectName("pageSubtitle")
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        text = QLabel(body)
        text.setWordWrap(True)
        card_layout.addWidget(text)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addWidget(card)
        layout.addStretch(1)
