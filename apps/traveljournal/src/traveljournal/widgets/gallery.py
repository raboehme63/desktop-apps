"""Icon gallery with lazy-loaded cached thumbnails."""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QMenu,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from travelcore.media.gallery import (
    SORT_FAVORITE,
    SORT_REJECTED,
    SORT_RESERVE,
    GalleryItem,
    effective_sort_status,
)
from travelcore.media.types import GPS_EXTENSIONS, PHOTO_EXTENSIONS
from travelcore.timeline.sections import format_scroll_date
from traveljournal.widgets.scroll_date import ScrollDateChip

_ICON = 168
_CELL = QSize(184, 214)
_PLACEHOLDER = QColor("#243044")
POOL_MIME = "application/x-traveljournal-source-ids"
_CHIP = 22
_CHIP_GAP = 3
_COVER_ACTIVE = QColor("#e0b85a")
_RATING_CHIPS = (
    (SORT_FAVORITE, "★"),
    (SORT_RESERVE, "R"),
    (SORT_REJECTED, "×"),
)
_CHIP_ACTIVE = {
    SORT_FAVORITE: QColor("#2eb8a0"),
    SORT_RESERVE: QColor("#5b8def"),
    SORT_REJECTED: QColor("#c45c6a"),
}


def rating_hotspots(cell: QRect) -> dict[str, QRect]:
    """Hit targets for ★ / R / × on the thumbnail, right-aligned above the filename."""

    count = len(_RATING_CHIPS)
    total = count * _CHIP + (count - 1) * _CHIP_GAP
    y = cell.y() + 8 + _ICON - _CHIP - 2
    x = cell.x() + cell.width() - 10 - total
    return {
        status: QRect(x + index * (_CHIP + _CHIP_GAP), y, _CHIP, _CHIP)
        for index, (status, _label) in enumerate(_RATING_CHIPS)
    }


def hit_rating(cell: QRect, pos: QPoint) -> str | None:
    for status, rect in rating_hotspots(cell).items():
        if rect.contains(pos):
            return status
    return None


def cover_hotspot(cell: QRect) -> QRect:
    """Hit target for the title-image chip, top-left on the thumbnail."""

    return QRect(cell.x() + 10, cell.y() + 10, _CHIP, _CHIP)


def hit_cover(cell: QRect, pos: QPoint) -> bool:
    return cover_hotspot(cell).contains(pos)


def can_be_cover(item: GalleryItem) -> bool:
    suffix = item.extension.lower()
    return suffix in PHOTO_EXTENSIONS or suffix in GPS_EXTENSIONS


def encode_pool_source_ids(source_ids: list[int]) -> bytes:
    unique = list(dict.fromkeys(int(item) for item in source_ids))
    return json.dumps(unique).encode("utf-8")


def decode_pool_source_ids(payload: bytes) -> list[int]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    ids: list[int] = []
    seen: set[int] = set()
    for item in data:
        if not isinstance(item, int):
            continue
        if item in seen:
            continue
        seen.add(item)
        ids.append(item)
    return ids


def source_ids_from_mime(mime: QMimeData | None) -> list[int]:
    if mime is None or not mime.hasFormat(POOL_MIME):
        return []
    return decode_pool_source_ids(bytes(mime.data(POOL_MIME)))


class _PixmapCache:
    def __init__(self, limit: int = 280) -> None:
        self._limit = limit
        self._items: OrderedDict[str, QPixmap] = OrderedDict()

    def get(self, path: Path, size: int) -> QPixmap:
        key = f"{path}:{size}"
        cached = self._items.get(key)
        if cached is not None:
            self._items.move_to_end(key)
            return cached
        pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()
        if pixmap.isNull():
            pixmap = QPixmap(size, size)
            pixmap.fill(_PLACEHOLDER)
        elif pixmap.width() != size or pixmap.height() != size:
            pixmap = pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._items[key] = pixmap
        if len(self._items) > self._limit:
            self._items.popitem(last=False)
        return pixmap


class GalleryModel(QAbstractListModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[GalleryItem] = []

    def set_items(self, items: list[GalleryItem]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: ANN201
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.filename
        if role == Qt.ItemDataRole.UserRole:
            return item
        return None

    def item_at(self, index: QModelIndex) -> GalleryItem | None:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        return self._items[index.row()]

    def items(self) -> list[GalleryItem]:
        return list(self._items)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [POOL_MIME]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:  # noqa: N802
        ids: list[int] = []
        seen: set[int] = set()
        for index in indexes:
            item = self.item_at(index)
            if item is None or item.source_file_id in seen:
                continue
            seen.add(item.source_file_id)
            ids.append(item.source_file_id)
        mime = QMimeData()
        mime.setData(POOL_MIME, QByteArray(encode_pool_source_ids(ids)))
        return mime

    def supportedDragActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.CopyAction


class GalleryDelegate(QStyledItemDelegate):
    def __init__(
        self, parent: QWidget | None = None, *, show_ratings: bool = True, show_cover: bool = False
    ) -> None:
        super().__init__(parent)
        self._cache = _PixmapCache()
        self.show_ratings = show_ratings
        self.show_cover = show_cover

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        _ = option, index
        return _CELL

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(item, GalleryItem):
            return
        rect: QRect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        current = effective_sort_status(item.sort_status, item.is_favorite)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(rect.adjusted(4, 4, -4, -4), QColor("#1a2030"))
        if selected:
            painter.setPen(QColor("#2eb8a0"))
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 8, 8)
        thumb = self._cache.get(item.thumbnail_path, _ICON)
        x = rect.x() + (rect.width() - thumb.width()) // 2
        painter.drawPixmap(x, rect.y() + 8, thumb)
        if current == SORT_REJECTED:
            painter.fillRect(
                QRect(x, rect.y() + 8, thumb.width(), thumb.height()),
                QColor(18, 21, 28, 140),
            )
        if self.show_cover and can_be_cover(item):
            chip = cover_hotspot(rect)
            active = item.is_entry_cover
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            painter.setBrush(_COVER_ACTIVE if active else QColor("#2a3144"))
            painter.setPen(QColor("#3a4458") if not active else Qt.PenStyle.NoPen)
            painter.drawRoundedRect(chip, 6, 6)
            painter.setPen(QColor("#06231e") if active else QColor("#c5cddb"))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, "T")
        if self.show_ratings:
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            for status, label in _RATING_CHIPS:
                chip = rating_hotspots(rect)[status]
                active = current == status
                painter.setBrush(_CHIP_ACTIVE[status] if active else QColor("#2a3144"))
                painter.setPen(QColor("#3a4458") if not active else Qt.PenStyle.NoPen)
                painter.drawRoundedRect(chip, 6, 6)
                painter.setPen(QColor("#06231e") if active else QColor("#c5cddb"))
                painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(QColor("#c5cddb"))
        painter.setFont(QFont("Segoe UI", 8))
        label = rect.adjusted(8, 8 + _ICON, -8, -6)
        painter.drawText(label, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, item.filename)
        painter.restore()


class GalleryView(QListView):
    item_activated = Signal(object)
    rating_chosen = Signal(object, str)
    cover_chosen = Signal(object)
    items_dropped = Signal(list)
    drop_hover = Signal(bool)
    map_requested = Signal(object)
    drag_started = Signal()
    drag_finished = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, show_ratings: bool = True, show_cover: bool = False
    ) -> None:
        super().__init__(parent)
        self._model = GalleryModel(self)
        self.setModel(self._model)
        self.setItemDelegate(GalleryDelegate(self, show_ratings=show_ratings, show_cover=show_cover))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setGridSize(QSize(_CELL.width() + 8, _CELL.height() + 8))
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.doubleClicked.connect(self._emit_item)
        self._expand_to_fit = False
        self._show_ratings = show_ratings
        self._show_cover = show_cover
        self._accept_pool_drop = False
        self._scroll_date: ScrollDateChip | None = None
        self._to_map_enabled = None

    def set_multi_select(self, enabled: bool) -> None:
        mode = QListView.SelectionMode.MultiSelection if enabled else QListView.SelectionMode.SingleSelection
        self.setSelectionMode(mode)

    def set_drag_enabled(self, enabled: bool) -> None:
        self.setDragEnabled(enabled)
        if enabled:
            self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self._sync_drag_drop_mode()

    def set_accept_pool_drop(self, enabled: bool) -> None:
        self._accept_pool_drop = enabled
        self._sync_drag_drop_mode()

    def _sync_drag_drop_mode(self) -> None:
        dragging = self.dragEnabled()
        dropping = self._accept_pool_drop
        self.setAcceptDrops(dropping)
        if dragging and dropping:
            self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        elif dragging:
            self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        elif dropping:
            self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._accept_pool_drop and source_ids_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self.drop_hover.emit(True)
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._accept_pool_drop and source_ids_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._accept_pool_drop:
            self.drop_hover.emit(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        ids = source_ids_from_mime(event.mimeData())
        self.drop_hover.emit(False)
        if not self._accept_pool_drop or not ids:
            event.ignore()
            return
        event.acceptProposedAction()
        self.items_dropped.emit(ids)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:  # noqa: N802
        if not self.dragEnabled():
            return
        self.drag_started.emit()
        try:
            super().startDrag(supportedActions)
        finally:
            self.drag_finished.emit()

    def enable_to_map_menu(self, enabled_for=None) -> None:  # noqa: ANN001
        """Right-click a thumbnail to emit ``map_requested`` (Timeline only)."""

        self._to_map_enabled = enabled_for
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_to_map_menu)

    def _show_to_map_menu(self, pos: QPoint) -> None:
        index = self.indexAt(pos)
        item = self._model.item_at(index)
        if item is None:
            return
        self.setCurrentIndex(index)
        menu = QMenu(self)
        action = menu.addAction("Zur Karte…")
        if self._to_map_enabled is not None:
            action.setEnabled(bool(self._to_map_enabled(item)))
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is action and action.isEnabled():
            self.map_requested.emit(item)

    def enable_scroll_date(self) -> None:
        if self._scroll_date is not None:
            return
        self._scroll_date = ScrollDateChip(self, self.date_at_viewport_mid)

    def date_at_viewport_mid(self) -> str | None:
        if not self.items():
            return None
        viewport = self.viewport()
        mid_x = max(8, viewport.width() // 2)
        for mid_y in (viewport.height() // 2, 12, max(12, viewport.height() - 12)):
            item = self._model.item_at(self.indexAt(QPoint(mid_x, mid_y)))
            if item is not None:
                return format_scroll_date(item.captured_at, item.captured_at)
        return None

    def set_expand_to_fit(self, enabled: bool) -> None:
        """Grow with the item count so a parent scroll area can own scrolling."""

        self._expand_to_fit = enabled
        if enabled:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._update_expanded_height()

    def set_items(self, items: list[GalleryItem]) -> None:
        self._model.set_items(items)
        self._update_expanded_height()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            item = self._model.item_at(index)
            if item is not None:
                cell = self.visualRect(index)
                if self._show_cover and can_be_cover(item) and hit_cover(cell, pos):
                    self.cover_chosen.emit(item)
                    event.accept()
                    return
                if self._show_ratings:
                    status = hit_rating(cell, pos)
                    if status is not None:
                        self.rating_chosen.emit(item, status)
                        event.accept()
                        return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            item = self._model.item_at(index)
            if item is not None:
                cell = self.visualRect(index)
                if self._show_cover and can_be_cover(item) and hit_cover(cell, pos):
                    event.accept()
                    return
                if self._show_ratings and hit_rating(cell, pos):
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self._update_expanded_height()

    def wheelEvent(self, event) -> None:  # noqa: ANN001, N802
        if self._expand_to_fit:
            event.ignore()
            return
        super().wheelEvent(event)

    def _update_expanded_height(self) -> None:
        if not self._expand_to_fit:
            return
        count = self._model.rowCount()
        if count == 0:
            self.setFixedHeight(8)
            return
        available = max(self.viewport().width(), self.width() - 16, _CELL.width())
        cell = _CELL.width() + self.spacing()
        columns = max(1, available // cell)
        rows = (count + columns - 1) // columns
        self.setFixedHeight(rows * (_CELL.height() + self.spacing()) + 8)

    def selected_item(self) -> GalleryItem | None:
        items = self.selected_items()
        return items[0] if items else None

    def selected_items(self) -> list[GalleryItem]:
        found: list[GalleryItem] = []
        seen: set[int] = set()
        for index in self.selectedIndexes():
            item = self._model.item_at(index)
            if item is None or item.source_file_id in seen:
                continue
            seen.add(item.source_file_id)
            found.append(item)
        return found

    def items(self) -> list[GalleryItem]:
        return self._model.items()

    def select_by_source_ids(self, wanted: set[int]) -> None:
        model = self.selectionModel()
        if model is None:
            return
        selection = QItemSelection()
        for row in range(self._model.rowCount()):
            index = self._model.index(row, 0)
            item = self._model.item_at(index)
            if item is not None and item.source_file_id in wanted:
                selection.select(index, index)
        model.clearSelection()
        if not selection.indexes():
            return
        model.select(selection, QItemSelectionModel.SelectionFlag.Select)

    def _emit_item(self, index: QModelIndex) -> None:
        item = self._model.item_at(index)
        if item is not None:
            self.item_activated.emit(item)
