"""Icon gallery with lazy-loaded cached thumbnails."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QListView,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from travelcore.media.gallery import GalleryItem

_ICON = 168
_CELL = QSize(184, 214)
_PLACEHOLDER = QColor("#243044")
_STAR = QColor("#7eebcf")


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


class GalleryDelegate(QStyledItemDelegate):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cache = _PixmapCache()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        _ = option, index
        return _CELL

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(item, GalleryItem):
            return
        rect: QRect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(rect.adjusted(4, 4, -4, -4), QColor("#1a2030"))
        if selected:
            painter.setPen(QColor("#2eb8a0"))
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 8, 8)
        thumb = self._cache.get(item.thumbnail_path, _ICON)
        x = rect.x() + (rect.width() - thumb.width()) // 2
        painter.drawPixmap(x, rect.y() + 8, thumb)
        if item.is_favorite:
            painter.setPen(_STAR)
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(
                rect.adjusted(10, 8, -8, 0),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                "★",
            )
        painter.setPen(QColor("#c5cddb"))
        painter.setFont(QFont("Segoe UI", 8))
        label = rect.adjusted(8, 8 + _ICON, -8, -6)
        painter.drawText(label, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, item.filename)
        painter.restore()


class GalleryView(QListView):
    item_activated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = GalleryModel(self)
        self.setModel(self._model)
        self.setItemDelegate(GalleryDelegate(self))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.doubleClicked.connect(self._emit_item)
        self._expand_to_fit = False

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
        indexes = self.selectedIndexes()
        if not indexes:
            return None
        return self._model.item_at(indexes[0])

    def _emit_item(self, index: QModelIndex) -> None:
        item = self._model.item_at(index)
        if item is not None:
            self.item_activated.emit(item)
