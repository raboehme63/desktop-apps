"""Icon gallery with lazy-loaded cached thumbnails."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QListView,
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

_ICON = 168
_CELL = QSize(184, 214)
_PLACEHOLDER = QColor("#243044")
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

    def __init__(
        self, parent: QWidget | None = None, *, show_ratings: bool = True, show_cover: bool = False
    ) -> None:
        super().__init__(parent)
        self._model = GalleryModel(self)
        self.setModel(self._model)
        self.setItemDelegate(GalleryDelegate(self, show_ratings=show_ratings, show_cover=show_cover))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.doubleClicked.connect(self._emit_item)
        self._expand_to_fit = False
        self._show_ratings = show_ratings
        self._show_cover = show_cover

    def set_multi_select(self, enabled: bool) -> None:
        mode = (
            QListView.SelectionMode.MultiSelection if enabled else QListView.SelectionMode.SingleSelection
        )
        self.setSelectionMode(mode)

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
