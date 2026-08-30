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
from travelcore.similarity.types import ClusterStatus
from travelcore.timeline.sections import format_scroll_date
from traveljournal.widgets.scroll_date import ScrollDateChip
from traveljournal.widgets.thumb_zoom import (
    DEFAULT_THUMB_ZOOM,
    clamp_thumb_zoom,
    gallery_cell_size,
    gallery_chip_size,
    gallery_icon_size,
)

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
_STACK_CHIP = QColor("#d4a017")
_GROUP_CHIP_READY = QColor("#2eb8a0")
_GROUP_CHIP_PALETTE = (
    QColor("#6b8cce"),
    QColor("#c47ac0"),
    QColor("#e07a4a"),
    QColor("#3cb8c9"),
    QColor("#8b6fc7"),
    QColor("#e07090"),
    QColor("#4a9fd4"),
    QColor("#d48a5a"),
)
_GROUP_TEXT_DARK = QColor("#0e1628")
_GROUP_TEXT_READY = QColor("#06231e")


def rating_hotspots(
    cell: QRect, *, icon: int | None = None, chip: int | None = None
) -> dict[str, QRect]:
    """Hit targets for ★ / R / × on the thumbnail, right-aligned above the filename."""

    icon_px = gallery_icon_size(DEFAULT_THUMB_ZOOM) if icon is None else icon
    chip_px = _CHIP if chip is None else chip
    count = len(_RATING_CHIPS)
    total = count * chip_px + (count - 1) * _CHIP_GAP
    y = cell.y() + 8 + icon_px - chip_px - 2
    x = cell.x() + cell.width() - 10 - total
    return {
        status: QRect(x + index * (chip_px + _CHIP_GAP), y, chip_px, chip_px)
        for index, (status, _label) in enumerate(_RATING_CHIPS)
    }


def hit_rating(
    cell: QRect, pos: QPoint, *, icon: int | None = None, chip: int | None = None
) -> str | None:
    for status, rect in rating_hotspots(cell, icon=icon, chip=chip).items():
        if rect.contains(pos):
            return status
    return None


def cover_hotspot(cell: QRect, *, chip: int | None = None) -> QRect:
    """Hit target for the title-image chip, top-left on the thumbnail."""

    chip_px = _CHIP if chip is None else chip
    return QRect(cell.x() + 10, cell.y() + 10, chip_px, chip_px)


def hit_cover(cell: QRect, pos: QPoint, *, chip: int | None = None) -> bool:
    return cover_hotspot(cell, chip=chip).contains(pos)


def shows_stack_badge(item: GalleryItem) -> bool:
    return item.stack_id is not None and item.stack_size >= 2


def group_badge_color(item: GalleryItem) -> QColor:
    if item.group_status == ClusterStatus.ACCEPTED:
        return _GROUP_CHIP_READY
    if item.group_id is None:
        return _GROUP_CHIP_PALETTE[0]
    return _GROUP_CHIP_PALETTE[item.group_id % len(_GROUP_CHIP_PALETTE)]


def group_badge_text_color(item: GalleryItem) -> QColor:
    if item.group_status == ClusterStatus.ACCEPTED:
        return _GROUP_TEXT_READY
    return _GROUP_TEXT_DARK


def shows_group_badge(item: GalleryItem) -> bool:
    if item.group_id is None or item.group_size < 2:
        return False
    if item.group_status == ClusterStatus.DISMISSED:
        return False
    if item.group_status == ClusterStatus.ACCEPTED:
        return item.is_group_key
    return True


def cluster_hotspots(
    cell: QRect,
    item: GalleryItem,
    *,
    chip: int | None = None,
) -> dict[str, QRect]:
    """Hit targets for stack/group badges at the top-right of the thumbnail."""

    chip_px = _CHIP if chip is None else chip
    kinds: list[str] = []
    if shows_group_badge(item):
        kinds.append("group")
    if shows_stack_badge(item):
        kinds.append("stack")
    spots: dict[str, QRect] = {}
    x = cell.x() + cell.width() - 10
    y = cell.y() + 10
    for kind in reversed(kinds):
        width = chip_px + (10 if kind == "stack" else 0)
        x -= width
        spots[kind] = QRect(x, y, width, chip_px)
        x -= _CHIP_GAP
    return spots


def hit_cluster(
    cell: QRect,
    item: GalleryItem,
    pos: QPoint,
    *,
    chip: int | None = None,
) -> str | None:
    for kind, rect in cluster_hotspots(cell, item, chip=chip).items():
        if rect.contains(pos):
            return kind
    return None


def _is_photo_item(item: GalleryItem) -> bool:
    return item.extension.lower() in PHOTO_EXTENSIONS


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
        self._icon = gallery_icon_size(DEFAULT_THUMB_ZOOM)
        self._cell = gallery_cell_size(DEFAULT_THUMB_ZOOM)
        self._chip = gallery_chip_size(DEFAULT_THUMB_ZOOM)

    def set_thumb_zoom(self, percent: int) -> None:
        self._icon = gallery_icon_size(percent)
        self._cell = gallery_cell_size(percent)
        self._chip = gallery_chip_size(percent)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        _ = option, index
        return self._cell

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
        thumb = self._cache.get(item.thumbnail_path, self._icon)
        x = rect.x() + (rect.width() - thumb.width()) // 2
        painter.drawPixmap(x, rect.y() + 8, thumb)
        if current == SORT_REJECTED:
            painter.fillRect(
                QRect(x, rect.y() + 8, thumb.width(), thumb.height()),
                QColor(18, 21, 28, 140),
            )
        clusters = cluster_hotspots(rect, item, chip=self._chip)
        if clusters:
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            if "stack" in clusters:
                chip = clusters["stack"]
                painter.setBrush(_STACK_CHIP)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(chip, 6, 6)
                painter.setPen(QColor("#2a2108"))
                painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, f"×{item.stack_size}")
            if "group" in clusters:
                chip = clusters["group"]
                painter.setBrush(group_badge_color(item))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(chip, 6, 6)
                painter.setPen(group_badge_text_color(item))
                painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, "G")
        if self.show_cover and can_be_cover(item):
            chip = cover_hotspot(rect, chip=self._chip)
            active = item.is_entry_cover
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            painter.setBrush(_COVER_ACTIVE if active else QColor("#2a3144"))
            painter.setPen(QColor("#3a4458") if not active else Qt.PenStyle.NoPen)
            painter.drawRoundedRect(chip, 6, 6)
            painter.setPen(QColor("#06231e") if active else QColor("#c5cddb"))
            painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, "T")
        if self.show_ratings:
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            spots = rating_hotspots(rect, icon=self._icon, chip=self._chip)
            for status, label in _RATING_CHIPS:
                chip = spots[status]
                active = current == status
                painter.setBrush(_CHIP_ACTIVE[status] if active else QColor("#2a3144"))
                painter.setPen(QColor("#3a4458") if not active else Qt.PenStyle.NoPen)
                painter.drawRoundedRect(chip, 6, 6)
                painter.setPen(QColor("#06231e") if active else QColor("#c5cddb"))
                painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(QColor("#c5cddb"))
        painter.setFont(QFont("Segoe UI", 8))
        label = rect.adjusted(8, 8 + self._icon, -8, -6)
        painter.drawText(label, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, item.filename)
        painter.restore()


class GalleryView(QListView):
    item_activated = Signal(object)
    rating_chosen = Signal(object, str)
    cover_chosen = Signal(object)
    items_dropped = Signal(list)
    drop_hover = Signal(bool)
    map_requested = Signal(object)
    stack_requested = Signal(object)
    group_requested = Signal(object)
    group_create_requested = Signal()
    group_dissolve_requested = Signal(object)
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
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.doubleClicked.connect(self._emit_item)
        self._expand_to_fit = False
        self._show_ratings = show_ratings
        self._show_cover = show_cover
        self._accept_pool_drop = False
        self._scroll_date: ScrollDateChip | None = None
        self._to_map_enabled = None
        self._show_map_action = False
        self._thumb_zoom = DEFAULT_THUMB_ZOOM
        self._apply_thumb_zoom()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

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
        """Include ``Zur Karte…`` in the thumbnail context menu (Timeline)."""

        self._to_map_enabled = enabled_for
        self._show_map_action = True

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.indexAt(pos)
        item = self._model.item_at(index)
        if item is None:
            return
        selected_ids = {row.source_file_id for row in self.selected_items()}
        if item.source_file_id not in selected_ids:
            self.clearSelection()
            self.select_by_source_ids({item.source_file_id})
        menu, group_act, dissolve_act, map_act = self._build_context_menu(item)
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is group_act and group_act.isEnabled():
            self.group_create_requested.emit()
            return
        if chosen is dissolve_act and dissolve_act.isEnabled():
            self.group_dissolve_requested.emit(item)
            return
        if map_act is not None and chosen is map_act and map_act.isEnabled():
            self.map_requested.emit(item)

    def _build_context_menu(self, item: GalleryItem) -> tuple[QMenu, object, object, object]:
        menu = QMenu(self)
        photos = [row for row in self.selected_items() if _is_photo_item(row)]
        group_act = menu.addAction("Gruppieren")
        group_act.setEnabled(len(photos) >= 2)
        dissolve_act = menu.addAction("Gruppe auflösen")
        dissolve_act.setEnabled(item.group_id is not None and item.group_status != ClusterStatus.DISMISSED)
        map_act = None
        if self._show_map_action:
            menu.addSeparator()
            map_act = menu.addAction("Zur Karte…")
            if self._to_map_enabled is not None:
                map_act.setEnabled(bool(self._to_map_enabled(item)))
        return menu, group_act, dissolve_act, map_act

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

    def set_thumb_zoom(self, percent: int) -> None:
        zoom = clamp_thumb_zoom(percent)
        if zoom == self._thumb_zoom:
            return
        self._thumb_zoom = zoom
        self._apply_thumb_zoom()
        self.viewport().update()
        self._update_expanded_height()

    def _apply_thumb_zoom(self) -> None:
        cell = gallery_cell_size(self._thumb_zoom)
        delegate = self.itemDelegate()
        if isinstance(delegate, GalleryDelegate):
            delegate.set_thumb_zoom(self._thumb_zoom)
        self.setGridSize(QSize(cell.width() + 8, cell.height() + 8))

    def _thumb_metrics(self) -> tuple[int, int]:
        return gallery_icon_size(self._thumb_zoom), gallery_chip_size(self._thumb_zoom)

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
                icon, chip = self._thumb_metrics()
                if self._show_cover and can_be_cover(item) and hit_cover(cell, pos, chip=chip):
                    self.cover_chosen.emit(item)
                    event.accept()
                    return
                cluster = hit_cluster(cell, item, pos, chip=chip)
                if cluster == "stack":
                    self.stack_requested.emit(item)
                    event.accept()
                    return
                if cluster == "group":
                    self.group_requested.emit(item)
                    event.accept()
                    return
                if self._show_ratings:
                    status = hit_rating(cell, pos, icon=icon, chip=chip)
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
                icon, chip = self._thumb_metrics()
                if self._show_cover and can_be_cover(item) and hit_cover(cell, pos, chip=chip):
                    event.accept()
                    return
                if hit_cluster(cell, item, pos, chip=chip):
                    event.accept()
                    return
                if self._show_ratings and hit_rating(cell, pos, icon=icon, chip=chip):
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
        cell = gallery_cell_size(self._thumb_zoom)
        available = max(self.viewport().width(), self.width() - 16, cell.width())
        step = cell.width() + self.spacing()
        columns = max(1, available // step)
        rows = (count + columns - 1) // columns
        self.setFixedHeight(rows * (cell.height() + self.spacing()) + 8)

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
