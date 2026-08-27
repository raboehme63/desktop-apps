"""Shared Alle / Favoriten / Reserve / Aussortiert register (click-only)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QTabBar, QWidget

from travelcore.media.gallery import SORT_FAVORITE, SORT_REJECTED, SORT_RESERVE

MEDIA_TABS = (
    ("Alle", None),
    ("Favoriten", SORT_FAVORITE),
    ("Reserve", SORT_RESERVE),
    ("Aussortiert", SORT_REJECTED),
)


def media_tab_key(index: int) -> str:
    if 0 <= index < len(MEDIA_TABS):
        return MEDIA_TABS[index][1] or "all"
    return "all"


def media_tab_index(key: str) -> int:
    for index, (_, status) in enumerate(MEDIA_TABS):
        if (status or "all") == key:
            return index
    return 0


class ClickTabBar(QTabBar):
    """Tabs change only on click. Wheel events pass through to the page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setChangeCurrentOnDrag(False)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()
