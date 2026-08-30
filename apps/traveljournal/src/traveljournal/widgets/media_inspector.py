"""Standalone media viewer. Originals are read-only; extra panel reserved for duplicates."""

from __future__ import annotations

import io
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRect,
    QRectF,
    QRunnable,
    QSize,
    QSizeF,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QHoverEvent,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
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
from travelcore.media.gallery import (
    SORT_FAVORITE,
    SORT_REJECTED,
    SORT_RESERVE,
    GalleryItem,
    effective_sort_status,
)
from travelcore.media.heic_win import decode_windows_full, decode_windows_thumbnail
from travelcore.media.heif_items import extract_heif_jpeg_item
from travelcore.media.orientation import can_rotate_media, normalize_rotation_degrees, orient_image
from travelcore.media.types import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS
from traveljournal.services.workspace import Workspace

_MAX_EDGE = 1920
_INSPECTOR_EDGE = 6000
_DISPLAY_BUCKETS = (1280, 1600, 1920, 2560)
_CACHE_LIMIT = 8
_DIRECT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
_RATING_BUTTONS = (
    (SORT_FAVORITE, "★ Favorit"),
    (SORT_RESERVE, "R Reserve"),
    (SORT_REJECTED, "× Aussortiert"),
)
_MIN_ZOOM = 1.0
_MAX_ZOOM = 8.0
_ZOOM_STEP = 1.15
_NAV_RATIO = 0.18
_NAV_MIN = 64
_NAV_MAX = 140
_MIN_IMAGE = QSize(240, 180)
INSPECTOR_DEFAULT_SIZE = (960, 720)
INSPECTOR_MIN_SIZE = (520, 400)
INSPECTOR_MAX_SIZE = (8000, 8000)


class _PixmapCache:
    """Small LRU of decoded inspector images, keyed by file, rotation, and decode edge."""

    def __init__(self, limit: int = _CACHE_LIMIT) -> None:
        self._items: OrderedDict[tuple[int, int, int], QPixmap] = OrderedDict()
        self._limit = limit

    def get(self, key: tuple[int, int, int]) -> QPixmap | None:
        pixmap = self._items.get(key)
        if pixmap is None:
            return None
        self._items.move_to_end(key)
        return pixmap

    def covering(self, source_file_id: int, rotation: int, edge: int) -> QPixmap | None:
        enough = [
            (key[2], pixmap)
            for key, pixmap in self._items.items()
            if key[0] == source_file_id and key[1] == rotation and key[2] >= edge
        ]
        if not enough:
            return None
        found_edge, pixmap = min(enough, key=lambda item: item[0])
        self.get((source_file_id, rotation, found_edge))
        return pixmap

    def nearest(self, source_file_id: int, rotation: int) -> QPixmap | None:
        matches = [
            (key[2], pixmap)
            for key, pixmap in self._items.items()
            if key[0] == source_file_id and key[1] == rotation
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item[0])[1]

    def put(self, key: tuple[int, int, int], pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        self._items[key] = pixmap
        self._items.move_to_end(key)
        while len(self._items) > self._limit:
            self._items.popitem(last=False)


class _DecodeSignals(QObject):
    finished = Signal(int, int, int, object)
    failed = Signal(int, int, int)


class _DecodeRunnable(QRunnable):
    def __init__(self, item: GalleryItem, max_edge: int, host: QObject) -> None:
        super().__init__()
        self._item = item
        self._max_edge = max_edge
        self.signals = _DecodeSignals(host)
        self.setAutoDelete(True)

    def run(self) -> None:
        rotation = normalize_rotation_degrees(self._item.rotation_degrees)
        try:
            image = load_media_qimage(self._item, max_edge=self._max_edge)
        except Exception:  # noqa: BLE001 - decode failures must not kill the pool thread
            self.signals.failed.emit(self._item.source_file_id, rotation, self._max_edge)
            return
        self.signals.finished.emit(self._item.source_file_id, rotation, self._max_edge, image)


class PhotoCanvas(QWidget):
    """Fitted photo with hover arrows, wheel-zoom, and double-click to reset."""

    side_clicked = Signal(int)
    double_activated = Signal()
    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source = QPixmap()
        self._zoom = _MIN_ZOOM
        self._offset = QPointF()
        self._hover_side = 0
        self._browse = False
        self._drag_last: QPointF | None = None
        self._moved = False
        self._nav_clicked = False
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def source(self) -> QPixmap:
        return self._source

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_browse_enabled(self, enabled: bool) -> None:
        self._browse = enabled
        if not enabled:
            self._hover_side = 0
        self.update()

    def set_source(self, pixmap: QPixmap, *, keep_view: bool = False) -> None:
        self._source = pixmap
        if keep_view:
            self._clamp_offset()
            self.update()
            return
        self.reset_view()

    def reset_view(self) -> None:
        self._zoom = _MIN_ZOOM
        self._offset = QPointF()
        self._drag_last = None
        self._moved = False
        self._refresh_cursor()
        self.update()

    def zoom_at(self, factor: float, origin: QPointF) -> None:
        if self._source.isNull() or factor <= 0:
            return
        old = self._zoom
        new = min(_MAX_ZOOM, max(_MIN_ZOOM, old * factor))
        if abs(new - old) < 1e-4:
            return
        center = QPointF(self.width() / 2, self.height() / 2)
        relative = origin - (center + self._offset)
        ratio = new / old
        self._zoom = new
        self._offset = origin - center - relative * ratio
        self._clamp_offset()
        self._refresh_cursor()
        self.update()
        self.zoom_changed.emit(self._zoom)

    def nav_side_at(self, x: float) -> int:
        if not self._browse:
            return 0
        band = _nav_band_width(self.width())
        if x < band:
            return -1
        if x > self.width() - band:
            return 1
        return 0

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        if self._hover_side:
            self._hover_side = 0
            self.update()
        self._refresh_cursor()
        super().leaveEvent(event)

    def hoverMoveEvent(self, event: QHoverEvent) -> None:  # noqa: N802
        self._update_hover(event.position().x())
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._moved = False
        self._nav_clicked = False
        side = self.nav_side_at(event.position().x())
        if side:
            self._nav_clicked = True
            self.side_clicked.emit(side)
            event.accept()
            return
        if self._zoom > 1.01:
            self._drag_last = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self._drag_last = None
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._update_hover(event.position().x())
        if self._drag_last is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position() - self._drag_last
            if delta.manhattanLength() >= 2:
                self._moved = True
            self._offset += delta
            self._drag_last = event.position()
            self._clamp_offset()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        dragging = self._drag_last is not None
        clicked_nav = self._nav_clicked
        self._drag_last = None
        self._nav_clicked = False
        self._refresh_cursor()
        if clicked_nav or (dragging and self._moved):
            event.accept()
            return
        side = self.nav_side_at(event.position().x())
        if side:
            self.side_clicked.emit(side)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.nav_side_at(event.position().x()) == 0:
            self.double_activated.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120
        if steps == 0:
            pixel = event.pixelDelta().y()
            steps = pixel / 80 if pixel else 0
        if steps == 0 or self._source.isNull():
            super().wheelEvent(event)
            return
        self.zoom_at(_ZOOM_STEP**steps, event.position())
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._clamp_offset()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#000000"))
        if not self._source.isNull():
            target = self._draw_rect()
            painter.drawPixmap(target.toRect(), self._source)
        if self._browse:
            _draw_nav_arrow(painter, self.rect(), -1, strong=self._hover_side == -1)
            _draw_nav_arrow(painter, self.rect(), 1, strong=self._hover_side == 1)

    def _draw_rect(self) -> QRectF:
        fit = _fit_rect(self.size(), self._source.size())
        size = QSizeF(fit.width() * self._zoom, fit.height() * self._zoom)
        center = fit.center() + self._offset
        return QRectF(
            center.x() - size.width() / 2,
            center.y() - size.height() / 2,
            size.width(),
            size.height(),
        )

    def _clamp_offset(self) -> None:
        if self._zoom <= 1.01:
            self._offset = QPointF()
            return
        fit = _fit_rect(self.size(), self._source.size())
        max_x = max(0.0, (fit.width() * self._zoom - self.width()) / 2)
        max_y = max(0.0, (fit.height() * self._zoom - self.height()) / 2)
        self._offset.setX(min(max_x, max(-max_x, self._offset.x())))
        self._offset.setY(min(max_y, max(-max_y, self._offset.y())))

    def _update_hover(self, x: float) -> None:
        side = self.nav_side_at(x)
        if side != self._hover_side:
            self._hover_side = side
            self.update()
        if self._drag_last is None:
            self._refresh_cursor()

    def _refresh_cursor(self) -> None:
        if self._drag_last is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._hover_side:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._zoom > 1.01:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)


class _CornerGrip(QWidget):
    """Visible bottom-right handle that resizes the inspector while keeping photo aspect."""

    def __init__(self, host: MediaInspectorWindow) -> None:
        super().__init__(host)
        self._host = host
        self._origin = QPointF()
        self._start = QSize()
        self.setObjectName("inspectorSizeGrip")
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("Ecke ziehen: proportional. Fensterränder: frei breiter oder höher.")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#9aa6b8"), 1.6))
        for index in range(3):
            inset = 3 + index * 4
            painter.drawLine(inset, 15, 15, inset)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._origin = event.globalPosition()
        self._start = self._host.size()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        delta = event.globalPosition() - self._origin
        wanted = QSize(self._start.width() + round(delta.x()), self._start.height() + round(delta.y()))
        self._host.resize_to_aspect(wanted, old=self._start)
        event.accept()


def cascade_inspector(window: QWidget, host: QWidget | None) -> None:
    """Offset a new inspector so several originals stay visible at once."""

    if host is None:
        return
    others = [child for child in host.findChildren(MediaInspectorWindow) if child is not window]
    if not others:
        return
    last = others[-1]
    window.move(last.x() + 28, last.y() + 28)


class MediaInspectorWindow(QWidget):
    """Shows the original (or best preview) and ratings. ``extra_host`` is for later duplicate tools."""

    rating_changed = Signal(object)
    rotation_changed = Signal(object)
    park_changed = Signal(object)
    open_media_on_map = Signal(str, int)

    def __init__(
        self,
        item: GalleryItem,
        *,
        items: list[GalleryItem] | None = None,
        workspace: Workspace | None = None,
        parent: QWidget | None = None,
        thumbnail_first: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(*INSPECTOR_MIN_SIZE)
        self.workspace = workspace
        self._thumbnail_first = thumbnail_first
        self._showing_original = not thumbnail_first
        self._items = _sequence_for(item, items)
        self._index = next(
            (index for index, entry in enumerate(self._items) if entry.source_file_id == item.source_file_id),
            0,
        )
        width, height = INSPECTOR_DEFAULT_SIZE
        self._restore_maximized = False
        if workspace is not None:
            width, height = workspace.inspector_size()
            self._restore_maximized = workspace.inspector_maximized()
        self.resize(width, height)
        self._closed = False
        self._cache = _PixmapCache()
        self._inflight: set[tuple[int, int, int]] = set()
        self._pool = QThreadPool.globalInstance()
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(250)
        self._persist_timer.timeout.connect(self._persist_geometry)
        self._decode_timer = QTimer(self)
        self._decode_timer.setSingleShot(True)
        self._decode_timer.setInterval(150)
        self._decode_timer.timeout.connect(self._refresh_display_decode)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        self._image = PhotoCanvas(self)
        self._image.side_clicked.connect(lambda side: self.step(int(side)))
        self._image.double_activated.connect(self._on_photo_double_click)
        self._image.zoom_changed.connect(self._on_zoom_changed)
        split.addWidget(self._image)
        self.extra_host = QWidget(self)
        self.extra_host.setObjectName("inspectorExtra")
        extra_layout = QVBoxLayout(self.extra_host)
        extra_layout.setContentsMargins(0, 0, 0, 0)
        extra_hint = QLabel("Platz für Dublettenbearbeitung", self.extra_host)
        extra_hint.setObjectName("pageSubtitle")
        extra_hint.setWordWrap(True)
        extra_layout.addWidget(extra_hint)
        extra_layout.addStretch(1)
        self.extra_host.hide()
        split.addWidget(self.extra_host)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        root.addWidget(split, 1)

        self._meta = QLabel(self)
        self._meta.setObjectName("pageSubtitle")
        self._meta.setWordWrap(True)
        self._meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self._meta)

        self._rating_row = QHBoxLayout()
        self._rotate_left = QPushButton("↺", self)
        self._rotate_left.setObjectName("rotateChip")
        self._rotate_left.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._rotate_left.setToolTip("90° gegen den Uhrzeigersinn (L)")
        self._rotate_left.clicked.connect(lambda: self._rotate(-90))
        self._rotate_right = QPushButton("↻", self)
        self._rotate_right.setObjectName("rotateChip")
        self._rotate_right.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._rotate_right.setToolTip("90° im Uhrzeigersinn (R)")
        self._rotate_right.clicked.connect(lambda: self._rotate(90))
        self._rating_row.addWidget(self._rotate_left)
        self._rating_row.addWidget(self._rotate_right)
        self._rating_buttons: dict[str, QPushButton] = {}
        for status, label in _RATING_BUTTONS:
            button = QPushButton(label, self)
            button.setObjectName("ratingChip")
            button.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, value=status: self._choose_rating(value))
            self._rating_buttons[status] = button
            self._rating_row.addWidget(button)
        self._pool_button = QPushButton("In den Pool", self)
        self._pool_button.setObjectName("ratingChip")
        self._pool_button.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._pool_button.clicked.connect(self._toggle_pool)
        self._rating_row.addWidget(self._pool_button)
        self._to_map_button = QPushButton("Zur Karte", self)
        self._to_map_button.setObjectName("inspectorToMap")
        self._to_map_button.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._to_map_button.clicked.connect(self._request_open_on_map)
        self._rating_row.addWidget(self._to_map_button)
        self._rating_row.addStretch(1)
        for widget in (
            self,
            self._image,
            self._meta,
            self._rotate_left,
            self._rotate_right,
            self._pool_button,
            self._to_map_button,
            *self._rating_buttons.values(),
        ):
            widget.installEventFilter(self)
        self._size_grip = _CornerGrip(self)
        self._rating_row.addWidget(
            self._size_grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight
        )
        root.addLayout(self._rating_row)
        self._show_current()

    def item(self) -> GalleryItem:
        return self._items[self._index]

    def showing_original(self) -> bool:
        return self._showing_original

    def _on_photo_double_click(self) -> None:
        if self._thumbnail_first and not self._showing_original:
            self._showing_original = True
            self._show_current()
            return
        self._image.reset_view()

    def step(self, delta: int, *, keep_view: bool = False) -> None:
        if len(self._items) < 2 or delta == 0:
            return
        self._index = (self._index + delta) % len(self._items)
        if self._thumbnail_first and not keep_view:
            self._showing_original = False
        self._image.reset_view()
        self._show_current()

    def resize_to_aspect(self, wanted: QSize, *, old: QSize | None = None) -> None:
        target = size_keeping_photo_aspect(
            old or self.size(),
            wanted,
            self._image.source().size(),
            self._chrome_size(),
        )
        if abs(target.width() - self.width()) <= 2 and abs(target.height() - self.height()) <= 2:
            return
        self.resize(target)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self._restore_maximized:
            self._restore_maximized = False
            self.showMaximized()
        self.activateWindow()
        self._image.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.isVisible() and self._wants_original():
            self._decode_timer.start()
        if self.workspace is None or not self.isVisible():
            return
        if self.isMaximized() or self.isFullScreen():
            return
        self._persist_timer.start()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._closed = True
        self._persist_timer.stop()
        self._decode_timer.stop()
        self._persist_geometry()
        super().closeEvent(event)

    def _persist_geometry(self) -> None:
        if self.workspace is None:
            return
        maximized = self.isMaximized() or self.isFullScreen()
        if maximized:
            geo = self.normalGeometry()
            self.workspace.set_inspector_geometry(geo.width(), geo.height(), maximized=True)
            return
        self.workspace.set_inspector_geometry(self.width(), self.height(), maximized=False)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange:
            return
        filled = self.isMaximized() or self.isFullScreen()
        self._size_grip.setVisible(not filled)
        if filled:
            self._image.reset_view()
        self._persist_geometry()

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if isinstance(event, QKeyEvent) and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if event.type() == QEvent.Type.KeyPress:
                self.step(-1 if event.key() == Qt.Key.Key_Left else 1)
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Left:
            self.step(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self.step(1)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_L, Qt.Key.Key_BracketLeft):
            self._rotate(-90)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_R, Qt.Key.Key_BracketRight):
            self._rotate(90)
            event.accept()
            return
        if event.key() == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def sync_from_item(self, item: GalleryItem) -> None:
        for index, existing in enumerate(self._items):
            if existing.source_file_id != item.source_file_id:
                continue
            self._items[index] = item
            if index == self._index:
                self._show_current()
            return

    def _chrome_size(self) -> QSize:
        return QSize(max(0, self.width() - self._image.width()), max(0, self.height() - self._image.height()))

    def _choose_rating(self, status: str) -> None:
        current_item = self.item()
        if self.workspace is None or not _can_rate(current_item):
            self._sync_rating_buttons()
            return
        current = effective_sort_status(current_item.sort_status, current_item.is_favorite)
        next_status = None if current == status else status
        try:
            self.workspace.set_sort_status(current_item.source_file_id, next_status)
        except ProjectError:
            self._sync_rating_buttons()
            return
        favorite = next_status == SORT_FAVORITE
        updated = replace(current_item, sort_status=next_status, is_favorite=favorite)
        self._items[self._index] = updated
        self.rating_changed.emit(updated)
        self._advance_to_next()

    def _advance_to_next(self) -> None:
        if self._index + 1 < len(self._items):
            self.step(1, keep_view=True)
            return
        self._show_current()

    def _rotate(self, delta: int) -> None:
        current_item = self.item()
        if not can_rotate_media(current_item.extension):
            return
        if self.workspace is not None:
            try:
                degrees, thumb = self.workspace.add_rotation(current_item.source_file_id, delta)
            except ProjectError:
                return
            updated = replace(current_item, rotation_degrees=degrees, thumbnail_path=thumb)
        else:
            degrees = normalize_rotation_degrees(current_item.rotation_degrees + delta)
            updated = replace(current_item, rotation_degrees=degrees)
        self._items[self._index] = updated
        self._show_current()
        self.rotation_changed.emit(updated)

    def _toggle_pool(self) -> None:
        if self.workspace is None:
            return
        current_item = self.item()
        try:
            if current_item.parked:
                self.workspace.unpark_media([current_item.source_file_id])
            else:
                self.workspace.park_media([current_item.source_file_id])
        except ProjectError as exc:
            QMessageBox.warning(self, "Medien", str(exc))
            return
        updated = replace(current_item, parked=not current_item.parked)
        self._items[self._index] = updated
        self.park_changed.emit(updated)
        if updated.parked:
            self._advance_to_next()
            return
        self._sync_pool_button()
        self._sync_map_button()

    def _show_current(self) -> None:
        item = self.item()
        title = _window_title(item, self._index, len(self._items))
        if self._thumbnail_first and not self._showing_original:
            title = f"{title} · Vorschau"
        self.setWindowTitle(title)
        self._image.set_browse_enabled(len(self._items) >= 2)
        if self._wants_original():
            self._present_original(item)
        else:
            self._image.set_source(load_thumbnail_pixmap(item))
        meta = media_meta_text(item)
        if self._thumbnail_first and not self._showing_original:
            hint = "Vorschau · Doppelklick für Original"
            meta = f"{meta} · {hint}" if meta else hint
        self._meta.setText(meta)
        can_rate = _can_rate(item)
        can_rotate = can_rotate_media(item.extension)
        self._rotate_left.setVisible(can_rotate)
        self._rotate_right.setVisible(can_rotate)
        self._rotate_left.setEnabled(can_rotate)
        self._rotate_right.setEnabled(can_rotate)
        for button in self._rating_buttons.values():
            button.setVisible(can_rate)
            button.setEnabled(can_rate and self.workspace is not None)
        self._sync_rating_buttons()
        self._sync_pool_button()
        self._sync_map_button()

    def _wants_original(self) -> bool:
        return not (self._thumbnail_first and not self._showing_original)

    def _rotation_key(self, item: GalleryItem) -> int:
        return normalize_rotation_degrees(item.rotation_degrees)

    def _display_edge(self) -> int:
        width = self._image.width() or self.width() or INSPECTOR_DEFAULT_SIZE[0]
        height = self._image.height() or self.height() or INSPECTOR_DEFAULT_SIZE[1]
        return inspector_display_edge(width, height, self.devicePixelRatioF())

    def _wanted_edge(self) -> int:
        if self._image.zoom > 1.01:
            return _INSPECTOR_EDGE
        return self._display_edge()

    def _keep_zoom(self) -> bool:
        return self._image.zoom > 1.01

    def _cache_key(self, item: GalleryItem, max_edge: int) -> tuple[int, int, int]:
        return (item.source_file_id, self._rotation_key(item), max_edge)

    def _present_original(self, item: GalleryItem) -> None:
        edge = self._wanted_edge()
        rotation = self._rotation_key(item)
        covering = self._cache.covering(item.source_file_id, rotation, edge)
        if covering is not None:
            self._image.set_source(covering)
            self._prefetch_neighbors()
            return
        placeholder = self._cache.nearest(item.source_file_id, rotation)
        if placeholder is None or placeholder.isNull():
            placeholder = try_thumbnail_pixmap(item)
        if placeholder.isNull():
            pixmap = load_media_pixmap(item, max_edge=edge)
            if not pixmap.isNull():
                self._cache.put(self._cache_key(item, edge), pixmap)
            self._image.set_source(pixmap)
        else:
            self._image.set_source(placeholder)
            self._request_decode(item, edge)
        self._prefetch_neighbors()

    def _refresh_display_decode(self) -> None:
        if self._closed or not self._wants_original():
            return
        self._request_decode(self.item(), self._wanted_edge())

    def _on_zoom_changed(self, zoom: float) -> None:
        if self._closed or not self._wants_original() or zoom <= 1.01:
            return
        self._apply_or_request_full(self.item())

    def _apply_or_request_full(self, item: GalleryItem) -> None:
        cached = self._cache.covering(item.source_file_id, self._rotation_key(item), _INSPECTOR_EDGE)
        if cached is not None:
            self._image.set_source(cached, keep_view=True)
            return
        self._request_decode(item, _INSPECTOR_EDGE)

    def _prefetch_neighbors(self) -> None:
        if len(self._items) < 2:
            return
        edge = self._display_edge()
        for delta in (-1, 1):
            self._request_decode(self._items[(self._index + delta) % len(self._items)], edge)

    def _request_decode(self, item: GalleryItem, max_edge: int) -> None:
        if self._closed:
            return
        key = self._cache_key(item, max_edge)
        if self._cache.covering(item.source_file_id, key[1], max_edge) is not None:
            return
        if key in self._inflight:
            return
        self._inflight.add(key)
        job = _DecodeRunnable(item, max_edge, self)
        job.signals.finished.connect(self._on_decoded)
        job.signals.failed.connect(self._on_decode_failed)
        self._pool.start(job)

    def _on_decoded(self, source_file_id: int, rotation: int, max_edge: int, image: object) -> None:
        self._inflight.discard((source_file_id, rotation, max_edge))
        if self._closed or not isinstance(image, QImage) or image.isNull():
            return
        pixmap = QPixmap.fromImage(image.copy())
        self._cache.put((source_file_id, rotation, max_edge), pixmap)
        if not self._wants_original():
            return
        current = self.item()
        if current.source_file_id != source_file_id or self._rotation_key(current) != rotation:
            return
        full = max_edge >= _INSPECTOR_EDGE
        if not full and self._keep_zoom():
            if self._cache.covering(source_file_id, rotation, _INSPECTOR_EDGE) is not None:
                return
            if (source_file_id, rotation, _INSPECTOR_EDGE) in self._inflight:
                return
        shown = self._image.source()
        if not full and not shown.isNull():
            if max(pixmap.width(), pixmap.height()) < max(shown.width(), shown.height()):
                return
        self._image.set_source(pixmap, keep_view=self._keep_zoom())

    def _on_decode_failed(self, source_file_id: int, rotation: int, max_edge: int) -> None:
        self._inflight.discard((source_file_id, rotation, max_edge))

    def _sync_rating_buttons(self) -> None:
        current_item = self.item()
        current = effective_sort_status(current_item.sort_status, current_item.is_favorite)
        for status, button in self._rating_buttons.items():
            button.blockSignals(True)
            button.setChecked(current == status)
            button.blockSignals(False)

    def _sync_pool_button(self) -> None:
        has_workspace = self.workspace is not None
        self._pool_button.setVisible(has_workspace)
        self._pool_button.setEnabled(has_workspace)
        parked = self.item().parked
        self._pool_button.setText("Zurückholen" if parked else "In den Pool")
        self._pool_button.setToolTip(
            "Medium wieder der Timeline und der Galerie zuordnen"
            if parked
            else "Medium aus dem Tagebuch nehmen und in den Medienpool legen"
        )

    def _item_has_map_position(self, item: GalleryItem) -> bool:
        if item.display_latitude is not None and item.display_longitude is not None:
            return True
        return item.gps_latitude is not None and item.gps_longitude is not None

    def _map_group_key(self) -> str | None:
        if self.workspace is None:
            return None
        item = self.item()
        if item.parked or not self._item_has_map_position(item):
            return None
        lookup = getattr(self.workspace, "map_group_key_for_source", None)
        if lookup is None:
            return None
        try:
            key = lookup(item.source_file_id)
        except ProjectError:
            return None
        return key if isinstance(key, str) and key.strip() else None

    def _sync_map_button(self) -> None:
        has_workspace = self.workspace is not None
        self._to_map_button.setVisible(has_workspace)
        if not has_workspace:
            return
        item = self.item()
        if item.parked:
            self._to_map_button.setEnabled(False)
            self._to_map_button.setToolTip("Nur Medien im Tagebuch erscheinen auf der Karte")
            return
        if not self._item_has_map_position(item):
            self._to_map_button.setEnabled(False)
            self._to_map_button.setToolTip("Nur mit Kartenposition")
            return
        key = self._map_group_key()
        self._to_map_button.setEnabled(key is not None)
        self._to_map_button.setToolTip(
            "Medium auf der Karte zeigen" if key else "Nach dem Speichern auf der Karte sichtbar"
        )

    def _request_open_on_map(self) -> None:
        key = self._map_group_key()
        if key is None:
            return
        self.open_media_on_map.emit(key, self.item().source_file_id)


def clamp_inspector_size(width: object, height: object) -> tuple[int, int]:
    """Keep a stored inspector size within the window minimum and a safe maximum."""

    def axis(value: object, default: int, lo: int, hi: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            number = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
        return max(lo, min(number, hi))

    return (
        axis(width, INSPECTOR_DEFAULT_SIZE[0], INSPECTOR_MIN_SIZE[0], INSPECTOR_MAX_SIZE[0]),
        axis(height, INSPECTOR_DEFAULT_SIZE[1], INSPECTOR_MIN_SIZE[1], INSPECTOR_MAX_SIZE[1]),
    )


def size_keeping_photo_aspect(
    old: QSize,
    new: QSize,
    photo: QSize,
    chrome: QSize,
    *,
    min_image: QSize = _MIN_IMAGE,
) -> QSize:
    """Choose a window size that keeps the photo area at the photo's aspect ratio."""

    if photo.width() < 1 or photo.height() < 1:
        return new
    aspect = photo.width() / photo.height()
    dw = new.width() - old.width()
    dh = new.height() - old.height()
    if abs(dw) >= abs(dh):
        image_w = max(min_image.width(), new.width() - chrome.width())
        image_h = max(min_image.height(), round(image_w / aspect))
        return QSize(image_w + chrome.width(), image_h + chrome.height())
    image_h = max(min_image.height(), new.height() - chrome.height())
    image_w = max(min_image.width(), round(image_h * aspect))
    return QSize(image_w + chrome.width(), image_h + chrome.height())


def _nav_band_width(width: int) -> int:
    return max(_NAV_MIN, min(_NAV_MAX, round(width * _NAV_RATIO)))


def _fit_rect(area: QSize, photo: QSize) -> QRectF:
    if photo.width() < 1 or photo.height() < 1 or area.width() < 1 or area.height() < 1:
        return QRectF(0, 0, max(0, area.width()), max(0, area.height()))
    scale = min(area.width() / photo.width(), area.height() / photo.height())
    width = photo.width() * scale
    height = photo.height() * scale
    return QRectF((area.width() - width) / 2, (area.height() - height) / 2, width, height)


def _draw_nav_arrow(painter: QPainter, bounds: QRect | QRectF, side: int, *, strong: bool = True) -> None:
    band = _nav_band_width(int(bounds.width()))
    cx = bounds.left() + band / 2 if side < 0 else bounds.right() - band / 2
    cy = bounds.center().y()
    size = 28.0
    path = QPainterPath()
    if side < 0:
        path.moveTo(cx + size * 0.28, cy - size)
        path.lineTo(cx - size * 0.45, cy)
        path.lineTo(cx + size * 0.28, cy + size)
    else:
        path.moveTo(cx - size * 0.28, cy - size)
        path.lineTo(cx + size * 0.45, cy)
        path.lineTo(cx - size * 0.28, cy + size)
    outline = 200 if strong else 110
    fill = 235 if strong else 150
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(
        QPen(
            QColor(0, 0, 0, outline),
            7,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.drawPath(path)
    painter.setPen(
        QPen(
            QColor(255, 255, 255, fill),
            4,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.drawPath(path)


def _sequence_for(item: GalleryItem, items: list[GalleryItem] | None) -> list[GalleryItem]:
    sequence = list(items) if items else []
    if not any(entry.source_file_id == item.source_file_id for entry in sequence):
        sequence.insert(0, item)
    return sequence or [item]


def _window_title(item: GalleryItem, index: int, total: int) -> str:
    if total <= 1:
        return item.filename
    return f"{item.filename} · {index + 1} von {total}"


def inspector_display_edge(width: int, height: int, device_pixel_ratio: float = 1.0) -> int:
    """Snap the on-screen decode size so resize does not thrash the cache."""

    raw = max(int(max(width, height) * max(device_pixel_ratio, 1.0)), _DISPLAY_BUCKETS[0])
    for bucket in _DISPLAY_BUCKETS:
        if raw <= bucket:
            return bucket
    return _DISPLAY_BUCKETS[-1]


def wait_inspector_decodes(*, timeout_ms: int = 3000) -> None:
    """Block until queued inspector decodes finish. Used by tests."""

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    pool = QThreadPool.globalInstance()
    remaining = max(timeout_ms, 0)
    while remaining >= 0:
        if app is not None:
            app.processEvents()
        if pool.waitForDone(50):
            if app is not None:
                app.processEvents()
            if pool.activeThreadCount() == 0:
                return
        remaining -= 50


def try_thumbnail_pixmap(item: GalleryItem) -> QPixmap:
    """Cached thumbnail file only. Does not open the original."""

    path = item.thumbnail_path
    if path.is_file():
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            return pixmap
    return QPixmap()


def load_thumbnail_pixmap(item: GalleryItem) -> QPixmap:
    """Cached thumbnail only; never opens the original file."""

    pixmap = try_thumbnail_pixmap(item)
    if not pixmap.isNull():
        return pixmap
    return load_media_pixmap(item, max_edge=_MAX_EDGE)


def load_media_pixmap(item: GalleryItem, *, max_edge: int = _MAX_EDGE) -> QPixmap:
    """Best available preview of the original. Never writes the source file."""

    return QPixmap.fromImage(load_media_qimage(item, max_edge=max_edge))


def load_media_qimage(item: GalleryItem, *, max_edge: int = _MAX_EDGE) -> QImage:
    """Decode a display image on any thread. Never writes the source file."""

    source = Path(item.path)
    suffix = source.suffix.lower()
    full = max_edge >= _INSPECTOR_EDGE
    image = QImage()
    rotated = False
    if suffix in _DIRECT and source.is_file():
        try:
            with Image.open(source) as opened:
                if not full:
                    _apply_draft(opened, max_edge)
                working = orient_image(opened, rotation_degrees=item.rotation_degrees)
                image = _qimage_from_pil(working)
                rotated = True
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            image = QImage()
    if image.isNull() and source.is_file() and suffix in PHOTO_EXTENSIONS | VIDEO_EXTENSIONS:
        decoded = _decode_non_direct(source, max_edge=max_edge, full=full)
        if decoded is not None:
            image = _qimage_from_pil(orient_image(decoded, rotation_degrees=item.rotation_degrees))
            rotated = True
    if image.isNull() and item.thumbnail_path.is_file():
        image = QImage(str(item.thumbnail_path))
        rotated = True
    if image.isNull():
        empty = QImage(320, 240, QImage.Format.Format_RGB32)
        empty.fill(QColor(Qt.GlobalColor.darkGray))
        return empty
    if not rotated:
        image = _rotate_qimage(image, item.rotation_degrees)
    if max_edge and (image.width() > max_edge or image.height() > max_edge):
        image = image.scaled(
            max_edge,
            max_edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return image


def _decode_non_direct(source: Path, *, max_edge: int, full: bool) -> Image.Image | None:
    if full:
        jpeg = _embedded_heif_jpeg(source)
        if jpeg is not None:
            return jpeg
        decoded = decode_windows_full(source)
        if decoded is not None:
            return decoded
    return decode_windows_thumbnail(source, size=max_edge)


def _embedded_heif_jpeg(source: Path) -> Image.Image | None:
    if source.suffix.lower() not in {".heic", ".heif"}:
        return None
    try:
        payload = extract_heif_jpeg_item(source.read_bytes())
    except OSError:
        return None
    if payload is None:
        return None
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            return opened.convert("RGB").copy()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def media_meta_text(item: GalleryItem) -> str:
    parts = [item.path]
    if item.captured_at is not None:
        stamp = item.captured_at.strftime("%Y-%m-%d %H:%M:%S")
        if item.timezone_unknown:
            stamp += " (TZ unbekannt)"
        parts.append(f"Aufnahme {stamp}")
    if item.journal_at is not None and item.journal_at != item.captured_at:
        parts.append(f"Tagebuch {item.journal_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if item.gps_latitude is not None and item.gps_longitude is not None:
        parts.append(f"{item.gps_latitude:.5f}, {item.gps_longitude:.5f}")
    if item.camera:
        parts.append(item.camera)
    degrees = normalize_rotation_degrees(item.rotation_degrees)
    if degrees:
        parts.append(f"Drehung {degrees}°")
    status = effective_sort_status(item.sort_status, item.is_favorite)
    if status == SORT_FAVORITE:
        parts.append("Favorit")
    elif status == SORT_RESERVE:
        parts.append("Reserve")
    elif status == SORT_REJECTED:
        parts.append("Aussortiert")
    return " · ".join(parts)


def _can_rate(_item: GalleryItem) -> bool:
    return True


def _apply_draft(opened: Image.Image, max_edge: int) -> None:
    if max_edge <= 0:
        return
    try:
        opened.draft("RGB", (max_edge, max_edge))
    except (ValueError, OSError, AttributeError):
        return


def _rotate_qimage(image: QImage, degrees: int | None) -> QImage:
    snapped = normalize_rotation_degrees(degrees)
    if not snapped or image.isNull():
        return image
    return image.transformed(
        QTransform().rotate(snapped),
        Qt.TransformationMode.SmoothTransformation,
    )


def _qimage_from_pil(image: Image.Image) -> QImage:
    rgb = image.convert("RGB")
    width, height = rgb.size
    qimage = QImage(rgb.tobytes(), width, height, width * 3, QImage.Format.Format_RGB888)
    return qimage.copy()
