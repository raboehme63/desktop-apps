"""Medienpool container: parked media with their own rating register."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.media.gallery import SORT_FAVORITE, GalleryItem, effective_sort_status
from traveljournal.services.workspace import Workspace
from traveljournal.ui.sidebar import _CHEVRON_PX, _COLLAPSE_H, _COLLAPSE_W, _chevron_icon
from traveljournal.widgets.gallery import GalleryView, source_ids_from_mime
from traveljournal.widgets.media_tabs import (
    RATING_TABS,
    ClickTabBar,
    ShowRejectedCheck,
    matches_rating,
    media_tab_index,
    media_tab_key,
    rating_status_at,
    sync_show_rejected_check,
)


class PoolPane(QFrame):
    """Full-height Medienpool, independent of Tag / Transfer / Aufenthalt."""

    unpark_requested = Signal()
    items_dropped = Signal(list)
    item_rating_changed = Signal(object)
    item_activated = Signal(object)
    show_rejected_changed = Signal(bool)

    def __init__(
        self,
        *,
        workspace: Workspace | None = None,
        unpark_label: str = "Zurück in die Timeline",
        accept_drops: bool = False,
        gallery_drag_hint: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("timelinePool")
        self.setMinimumWidth(220)
        self.setAcceptDrops(accept_drops)
        self._accept_drops = accept_drops
        self.workspace = workspace
        self._items: list[GalleryItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._heading = QLabel("Medienpool", self)
        self._heading.setObjectName("pageSubtitle")
        self._heading.setWordWrap(True)
        self._unpark_button = QPushButton(unpark_label, self)
        self._unpark_button.setEnabled(False)
        self._unpark_button.clicked.connect(self.unpark_requested.emit)
        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 0)
        heading_row.setSpacing(8)
        heading_row.addWidget(self._heading, 1)
        heading_row.addWidget(self._unpark_button, 0, Qt.AlignmentFlag.AlignTop)

        self._tabs = ClickTabBar(self)
        self._tabs.setObjectName("mediaSortTabs")
        self._tabs.setExpanding(False)
        for label, _status in RATING_TABS:
            self._tabs.addTab(label)
        if workspace is not None:
            self._tabs.setCurrentIndex(media_tab_index(workspace.pool_media_tab()))
        self._tabs.currentChanged.connect(self._on_rating_tab)
        self._show_rejected = ShowRejectedCheck(self)
        if workspace is not None:
            self._show_rejected.setChecked(workspace.show_rejected_in_all())
        self._show_rejected.toggled.connect(self._on_show_rejected)
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(0, 0, 0, 0)
        tabs_row.setSpacing(8)
        tab_label = QLabel("Register", self)
        tab_label.setObjectName("pageSubtitle")
        tabs_row.addWidget(tab_label)
        tabs_row.addWidget(self._tabs)
        tabs_row.addWidget(self._show_rejected)
        tabs_row.addStretch(1)

        self._empty = QLabel("Keine Medien im Pool.", self)
        self._empty.setObjectName("pageSubtitle")
        self._empty.setWordWrap(True)
        self.gallery = GalleryView(self)
        self.gallery.set_multi_select(True)
        self.gallery.set_drag_enabled(True)
        self.gallery.set_accept_pool_drop(accept_drops)
        self.gallery.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.gallery.enable_scroll_date()
        self.gallery.setToolTip(
            gallery_drag_hint
            or (
                "Auf die Reise-Galerie ziehen"
                if accept_drops
                else "Auf einen Tag, Transfer oder Aufenthalt ziehen"
            )
        )
        self.gallery.rating_chosen.connect(self._on_rating)
        self.gallery.item_activated.connect(self.item_activated.emit)
        if accept_drops:
            self.gallery.items_dropped.connect(self.items_dropped.emit)
            self.gallery.drop_hover.connect(self._set_drop_highlight)
        model = self.gallery.selectionModel()
        if model is not None:
            model.selectionChanged.connect(self._on_selection)

        layout.addLayout(heading_row)
        layout.addLayout(tabs_row)
        layout.addWidget(self._empty)
        layout.addWidget(self.gallery, 1)
        self._sync_show_rejected()
        self._refresh_empty()

    def set_items(self, items: list[GalleryItem]) -> None:
        selected = set(self.selected_source_ids())
        self._items = list(items)
        self.sync_tab_from_workspace()
        self._sync_show_rejected()
        self._apply_rating_tab()
        self.gallery.select_by_source_ids(selected)

    def sync_tab_from_workspace(self) -> None:
        if self.workspace is None:
            return
        index = media_tab_index(self.workspace.pool_media_tab())
        if self._tabs.currentIndex() == index:
            return
        self._tabs.blockSignals(True)
        self._tabs.setCurrentIndex(index)
        self._tabs.blockSignals(False)
        self._sync_show_rejected()
        self._apply_rating_tab()

    def contains(self, source_file_id: int) -> bool:
        return any(item.source_file_id == source_file_id for item in self._items)

    def selected_source_ids(self) -> list[int]:
        return [item.source_file_id for item in self.gallery.selected_items()]

    def shown_items(self) -> list[GalleryItem]:
        return self.gallery.items()

    def refresh_rating_filter(self) -> None:
        self._sync_show_rejected()
        self._apply_rating_tab()

    def sync_rating(self, item: GalleryItem) -> None:
        self._items = [
            item if existing.source_file_id == item.source_file_id else existing
            for existing in self._items
        ]
        selected = set(self.selected_source_ids())
        self._apply_rating_tab()
        self.gallery.select_by_source_ids(selected)

    def _shown_for_tab(self) -> list[GalleryItem]:
        wanted = rating_status_at(self._tabs.currentIndex())
        include_rejected = self.workspace is not None and self.workspace.show_rejected_in_all()
        return [
            item for item in self._items if matches_rating(item, wanted, include_rejected=include_rejected)
        ]

    def _apply_rating_tab(self) -> None:
        self.gallery.set_items(self._shown_for_tab())
        self._refresh_empty()

    def _sync_show_rejected(self) -> None:
        checked = self.workspace.show_rejected_in_all() if self.workspace is not None else False
        sync_show_rejected_check(self._show_rejected, self._tabs, checked=checked)

    def _on_rating_tab(self, index: int) -> None:
        if self.workspace is not None:
            self.workspace.set_pool_media_tab(media_tab_key(index))
        self._sync_show_rejected()
        self._apply_rating_tab()

    def _on_show_rejected(self, checked: bool) -> None:
        if self.workspace is not None:
            self.workspace.set_show_rejected_in_all(checked)
        self._apply_rating_tab()
        self.show_rejected_changed.emit(checked)

    def _refresh_empty(self) -> None:
        count = len(self._items)
        self._heading.setText(f"Medienpool ({count})" if count else "Medienpool")
        shown = self.gallery.items()
        if not self._items:
            self._empty.setText("Keine Medien im Pool.")
            self._empty.setVisible(True)
            self.gallery.setVisible(False)
            return
        self.gallery.setVisible(True)
        if not shown:
            self._empty.setText("Keine Medien in diesem Register.")
            self._empty.setVisible(True)
            return
        self._empty.setVisible(False)

    def _on_selection(self, *_args: object) -> None:
        self._unpark_button.setEnabled(bool(self.gallery.selected_items()))

    def _on_rating(self, item: object, status: str) -> None:
        if not isinstance(item, GalleryItem):
            return
        current = effective_sort_status(item.sort_status, item.is_favorite)
        next_status = None if current == status else status
        if self.workspace is not None:
            try:
                self.workspace.set_sort_status(item.source_file_id, next_status)
            except ProjectError as exc:
                QMessageBox.warning(self, "Bewertung", str(exc))
                return
        favorite = next_status == SORT_FAVORITE
        updated = replace(item, sort_status=next_status, is_favorite=favorite)
        self.sync_rating(updated)
        self.item_rating_changed.emit(updated)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._accept_drops and source_ids_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self._set_drop_highlight(True)
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._accept_drops and source_ids_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_drop_highlight(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_drop_highlight(False)
        ids = source_ids_from_mime(event.mimeData())
        if not self._accept_drops or not ids:
            event.ignore()
            return
        event.acceptProposedAction()
        self.items_dropped.emit(ids)

    def _set_drop_highlight(self, active: bool) -> None:
        self.setProperty("dropTarget", "true" if active else "false")
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)


POOL_WIDTH_DEFAULT = 280
POOL_WIDTH_MIN = 220


def clamp_pool_width(value: object) -> int:
    if isinstance(value, bool):
        return POOL_WIDTH_DEFAULT
    try:
        width = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return POOL_WIDTH_DEFAULT
    return max(POOL_WIDTH_MIN, min(width, 2000))


class PoolCollapse:
    """Right-edge chevron that hides the pool and restores its last width."""

    def __init__(
        self,
        host: QWidget,
        split: QSplitter,
        pane: QWidget,
        workspace: Workspace,
    ) -> None:
        self._host = host
        self._split = split
        self._pane = pane
        self._workspace = workspace
        self._applying = False
        self.toggle = QPushButton(host)
        self.toggle.setObjectName("poolCollapse")
        self.toggle.setCheckable(True)
        self.toggle.setIcon(_chevron_icon(expand=False))
        self.toggle.setIconSize(QSize(_CHEVRON_PX, _CHEVRON_PX))
        self.toggle.setFixedSize(_COLLAPSE_W, _COLLAPSE_H)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        visible = workspace.timeline_pool_visible()
        self.toggle.setChecked(visible)
        self.toggle.toggled.connect(self._on_toggled)
        split.splitterMoved.connect(self._on_splitter_moved)
        self.apply(visible)

    def _on_toggled(self, visible: bool) -> None:
        self.apply(visible)
        self._workspace.set_timeline_pool_visible(visible)

    def set_visible(self, visible: bool) -> None:
        if self.toggle.isChecked() != visible:
            self.toggle.setChecked(visible)
            return
        self.apply(visible)
        self._workspace.set_timeline_pool_visible(visible)

    def apply(self, visible: bool) -> None:
        self._applying = True
        try:
            if not visible:
                self._remember_width()
            self._pane.setVisible(visible)
            self.toggle.setIcon(_chevron_icon(expand=visible))
            self.toggle.setToolTip("Medienpool einklappen" if visible else "Medienpool ausklappen")
            if visible:
                self._restore_width()
            self.place()
        finally:
            self._applying = False

    def sync_from_workspace(self) -> None:
        visible = self._workspace.timeline_pool_visible()
        if self.toggle.isChecked() != visible:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(visible)
            self.toggle.blockSignals(False)
            self.apply(visible)
            return
        if visible:
            self._restore_width()
        self.place()

    def place(self) -> None:
        btn = self.toggle
        split = self._split
        y = split.y() + max(0, (split.height() - btn.height()) // 2)
        btn.move(self._host.width() - btn.width(), y)
        btn.raise_()

    def _on_splitter_moved(self, *_args: object) -> None:
        if not self._applying and self._pane.isVisible():
            self._remember_width()
        self.place()

    def _remember_width(self) -> None:
        sizes = self._split.sizes()
        if len(sizes) < 2 or sizes[1] < POOL_WIDTH_MIN:
            return
        self._workspace.set_pool_width(sizes[1])

    def _restore_width(self) -> None:
        width = self._workspace.pool_width()
        sizes = self._split.sizes()
        total = max(sum(sizes), self._split.width(), 800)
        self._split.setSizes([max(total - width, 1), width])

