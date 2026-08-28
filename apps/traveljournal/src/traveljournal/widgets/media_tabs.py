"""Rating register Alle / Favoriten / Reserve / Aussortiert (click-only)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QCheckBox, QTabBar, QWidget

from travelcore.media.gallery import (
    SORT_FAVORITE,
    SORT_REJECTED,
    SORT_RESERVE,
    GalleryItem,
    effective_sort_status,
)

RATING_TABS = (
    ("Alle", None),
    ("Favoriten", SORT_FAVORITE),
    ("Reserve", SORT_RESERVE),
    ("Aussortiert", SORT_REJECTED),
)


def media_tab_key(index: int, tabs: tuple[tuple[str, str | None], ...] = RATING_TABS) -> str:
    if 0 <= index < len(tabs):
        return tabs[index][1] or "all"
    return "all"


def media_tab_index(key: str, tabs: tuple[tuple[str, str | None], ...] = RATING_TABS) -> int:
    for index, (_, status) in enumerate(tabs):
        if (status or "all") == key:
            return index
    return 0


def rating_status_at(index: int) -> str | None:
    if 0 <= index < len(RATING_TABS):
        return RATING_TABS[index][1]
    return None


def matches_rating(
    item: GalleryItem,
    wanted: str | None,
    *,
    include_rejected: bool = False,
) -> bool:
    status = effective_sort_status(item.sort_status, item.is_favorite)
    if wanted is None:
        return include_rejected or status != SORT_REJECTED
    return status == wanted


def sync_show_rejected_check(checkbox: QCheckBox, tabs: QTabBar, *, checked: bool) -> None:
    checkbox.blockSignals(True)
    checkbox.setChecked(checked)
    checkbox.blockSignals(False)
    checkbox.setVisible(rating_status_at(tabs.currentIndex()) is None)


class ShowRejectedCheck(QCheckBox):
    """Visible next to Alle: include rejected media in that register."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Aussortierte anzeigen", parent)
        self.setObjectName("showRejectedInAll")
        self.setToolTip("Im Register Alle auch als Aussortiert markierte Medien zeigen")
        self.setVisible(False)


class ClickTabBar(QTabBar):
    """Tabs change only on click. Wheel events pass through to the page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setChangeCurrentOnDrag(False)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()
