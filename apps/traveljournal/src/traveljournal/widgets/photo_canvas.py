"""Photo page canvas: free-form frames with crop, z-order, and edit gestures."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QImage,
    QKeyEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QStyleOptionGraphicsItem,
    QWidget,
)

from travelcore.export.document import (
    PhotoElement,
    add_photo_element,
    bring_to_front,
    remove_element,
    replace_source,
    send_to_back,
    sorted_by_z,
    update_element,
)
from travelcore.export.geometry import (
    Crop,
    clamp_angle,
    clamp_crop,
    clamp_scale,
    contain_fit,
    frame_pixels,
    image_rect_in_rotated_frame,
    pan_from_delta,
    pixels_to_frame,
    zoom_keeping_point,
)
from traveljournal.widgets.gallery import source_ids_from_mime

_PAGE_BG = "#f7f4ee"
_HANDLE = 8.0
_ZOOM_STEP = 1.08
_ROTATE_R = 6.0
_ROTATE_GAP = 18.0
# Square thumbs (thumbnails._fit_square) pad with this fill. JPEG-safe tolerance.
_THUMB_FILL = (18, 21, 28)
_THUMB_FILL_TOL = 22
_Handle = str  # nw n ne e se s sw w | rotate


def _wheel_steps(event: object) -> int:
    """Vertical wheel notches from a view ``QWheelEvent`` or item scene wheel event."""

    angle = getattr(event, "angleDelta", None)
    if callable(angle):
        vector = angle()
        value = vector.y() if vector.y() != 0 else vector.x()
        if value:
            return int(value)
    legacy = getattr(event, "delta", None)
    if callable(legacy):
        return int(legacy())
    return 0


def _near_fill(color: QColor) -> bool:
    return (
        abs(color.red() - _THUMB_FILL[0]) <= _THUMB_FILL_TOL
        and abs(color.green() - _THUMB_FILL[1]) <= _THUMB_FILL_TOL
        and abs(color.blue() - _THUMB_FILL[2]) <= _THUMB_FILL_TOL
    )


def _letterbox_axis(pixmap: QPixmap) -> str | None:
    """``y`` = bars top/bottom (landscape), ``x`` = bars left/right (portrait)."""

    if pixmap.isNull() or pixmap.width() < 8 or pixmap.height() < 8:
        return None
    if pixmap.width() != pixmap.height():
        return None
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    width, height = image.width(), image.height()
    top = all(_near_fill(image.pixelColor(x, 1)) for x in (1, width // 2, width - 2))
    left = all(_near_fill(image.pixelColor(1, y)) for y in (1, height // 2, height - 2))
    if top and not left:
        return "y"
    if left and not top:
        return "x"
    return None


def _preview_image_size(pixmap: QPixmap, media: BookMedia | None) -> tuple[float, float]:
    """Pixel size of the photo as displayed (after EXIF / rotation), not the square thumb."""

    pw = float(max(pixmap.width(), 1))
    ph = float(max(pixmap.height(), 1))
    if media is None:
        return pw, ph
    width = float(media.width)
    height = float(media.height)
    if width <= 0 or height <= 0:
        return pw, ph
    axis = _letterbox_axis(pixmap)
    if axis == "y":
        return (max(width, height), min(width, height))
    if axis == "x":
        return (min(width, height), max(width, height))
    return width, height


@dataclass(frozen=True, slots=True)
class BookMedia:
    source_file_id: int
    thumbnail_path: Path
    width: int = 0
    height: int = 0


class _PhotoItem(QGraphicsObject):
    def __init__(
        self,
        element: PhotoElement,
        pixmap: QPixmap,
        image_width: float,
        image_height: float,
        page_width: float,
        page_height: float,
        *,
        editable: bool,
        gutter_side: str | None = None,
    ) -> None:
        super().__init__()
        self.element = element
        self._pixmap = pixmap
        self._image_w = image_width if image_width > 0 else max(pixmap.width(), 1)
        self._image_h = image_height if image_height > 0 else max(pixmap.height(), 1)
        self._page_w = page_width
        self._page_h = page_height
        self._editable = editable
        self._gutter_side = gutter_side
        self._handle: _Handle | None = None
        self._press = QPointF()
        self._press_item = QPointF()
        self._start_frame = element.frame
        self._start_crop = element.crop
        self._panning = False
        self.setZValue(element.z)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, editable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(editable)
        self._place()

    def _place(self) -> None:
        left, top, width, height = frame_pixels(self._page_w, self._page_h, self.element.frame)
        self.setPos(left, top)
        self._fw = max(width, 1.0)
        self._fh = max(height, 1.0)
        self.prepareGeometryChange()

    def _rotate_handle_center(self) -> QPointF:
        return QPointF(self._fw / 2.0, -_ROTATE_GAP)

    def boundingRect(self) -> QRectF:  # noqa: N802
        if not self._editable:
            return QRectF(0, 0, self._fw, self._fh)
        pad = _HANDLE
        top = _ROTATE_GAP + _ROTATE_R
        return QRectF(-pad, -top, self._fw + pad * 2, self._fh + top + pad)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        dest = QRectF(0, 0, self._fw, self._fh)
        painter.save()
        painter.setClipRect(dest)
        if self._pixmap.isNull():
            painter.fillRect(dest, QColor("#d9d3c7"))
        else:
            painter.translate(self._fw / 2.0, self._fh / 2.0)
            painter.rotate(self.element.crop.angle)
            left, top, width, height = image_rect_in_rotated_frame(
                self._image_w, self._image_h, self._fw, self._fh, self.element.crop
            )
            ox, oy, cw, ch = contain_fit(
                self._image_w,
                self._image_h,
                float(max(self._pixmap.width(), 1)),
                float(max(self._pixmap.height(), 1)),
            )
            painter.drawPixmap(
                QRectF(left, top, width, height),
                self._pixmap,
                QRectF(ox, oy, cw, ch),
            )
        painter.restore()
        if self._editable and self.isSelected():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#2c9a8f"), 1.5))
            painter.drawRect(dest)
            hinge = QPointF(self._fw / 2.0, 0.0)
            knob = self._rotate_handle_center()
            painter.drawLine(hinge, knob)
            painter.setBrush(QBrush(QColor("#2c9a8f")))
            painter.setPen(Qt.PenStyle.NoPen)
            for rect in self._handle_rects().values():
                painter.drawRect(rect)
            painter.drawEllipse(knob, _ROTATE_R, _ROTATE_R)

    def _handle_rects(self) -> dict[str, QRectF]:
        s = _HANDLE
        w, h = self._fw, self._fh
        return {
            "nw": QRectF(-s / 2, -s / 2, s, s),
            "n": QRectF(w / 2 - s / 2, -s / 2, s, s),
            "ne": QRectF(w - s / 2, -s / 2, s, s),
            "e": QRectF(w - s / 2, h / 2 - s / 2, s, s),
            "se": QRectF(w - s / 2, h - s / 2, s, s),
            "s": QRectF(w / 2 - s / 2, h - s / 2, s, s),
            "sw": QRectF(-s / 2, h - s / 2, s, s),
            "w": QRectF(-s / 2, h / 2 - s / 2, s, s),
        }

    def _hit_handle(self, pos: QPointF) -> _Handle | None:
        if not self._editable:
            return None
        knob = self._rotate_handle_center()
        if (pos - knob).manhattanLength() <= _ROTATE_R + 3:
            return "rotate"
        for name, rect in self._handle_rects().items():
            if rect.contains(pos):
                return name
        return None

    def hoverMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        handle = self._hit_handle(event.pos())
        cursors = {
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
            "n": Qt.CursorShape.SizeVerCursor,
            "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor,
            "w": Qt.CursorShape.SizeHorCursor,
            "rotate": Qt.CursorShape.CrossCursor,
        }
        if handle is not None:
            self.setCursor(QCursor(cursors[handle]))
        elif event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self._editable:
            event.ignore()
            return
        self._handle = self._hit_handle(event.pos())
        pan_mod = bool(
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        )
        self._panning = self._handle is None and pan_mod
        self._press = event.scenePos()
        self._press_item = event.pos()
        self._start_frame = self.element.frame
        self._start_crop = self.element.crop
        self.setSelected(True)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self._editable:
            return
        delta = event.scenePos() - self._press
        if self._handle == "rotate":
            self._rotate_to(event.pos(), bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            return
        if self._handle is not None:
            self._resize_by(delta.x(), delta.y(), event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            return
        if self._panning:
            self._set_crop(
                pan_from_delta(
                    self._image_w,
                    self._image_h,
                    self._fw,
                    self._fh,
                    self._start_crop,
                    delta.x(),
                    delta.y(),
                )
            )
            return
        left, top, width, height = frame_pixels(self._page_w, self._page_h, self._start_frame)
        self.element = replace(
            self.element,
            frame=pixels_to_frame(
                self._page_w,
                self._page_h,
                left + delta.x(),
                top + delta.y(),
                width,
                height,
                gutter_side=self._gutter_side,
            ),
        )
        self._place()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._handle = None
        self._panning = False
        scene = self.scene()
        view = scene.views()[0] if scene is not None and scene.views() else None
        if isinstance(view, PhotoPageCanvas):
            view._commit_item(self)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self._editable:
            event.ignore()
            return
        delta = _wheel_steps(event)
        if delta == 0:
            event.ignore()
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._nudge_angle(1.0 if delta > 0 else -1.0)
        else:
            factor = _ZOOM_STEP if delta > 0 else 1.0 / _ZOOM_STEP
            new_scale = clamp_scale(self.element.crop.scale * factor)
            pos = event.pos()
            self._set_crop(
                zoom_keeping_point(
                    self._image_w,
                    self._image_h,
                    self._fw,
                    self._fh,
                    self.element.crop,
                    new_scale,
                    pos.x(),
                    pos.y(),
                )
            )
        scene = self.scene()
        view = scene.views()[0] if scene is not None and scene.views() else None
        if isinstance(view, PhotoPageCanvas):
            view._commit_item(self)
        event.accept()

    def _set_crop(self, crop: Crop) -> None:
        self.element = replace(self.element, crop=clamp_crop(crop))
        self.update()

    def _nudge_angle(self, degrees: float) -> None:
        angle = clamp_angle(round(self.element.crop.angle + degrees))
        self._set_crop(replace(self.element.crop, angle=angle))

    def _nudge_scale(self, direction: int) -> None:
        factor = _ZOOM_STEP if direction > 0 else 1.0 / _ZOOM_STEP
        self._set_crop(replace(self.element.crop, scale=clamp_scale(self.element.crop.scale * factor)))

    def _rotate_to(self, pos: QPointF, snap_coarse: bool) -> None:
        center = QPointF(self._fw / 2.0, self._fh / 2.0)
        start = self._press_item - center
        now = pos - center
        if start.manhattanLength() < 1 or now.manhattanLength() < 1:
            return
        delta = math.degrees(math.atan2(now.y(), now.x()) - math.atan2(start.y(), start.x()))
        angle = self._start_crop.angle + delta
        step = 15.0 if snap_coarse else 1.0
        angle = clamp_angle(round(angle / step) * step)
        self._set_crop(replace(self._start_crop, angle=angle))

    def _resize_by(self, dx: float, dy: float, keep_aspect: bool) -> None:
        left, top, width, height = frame_pixels(self._page_w, self._page_h, self._start_frame)
        right = left + width
        bottom = top + height
        handle = self._handle or ""
        if "w" in handle:
            left += dx
        if "e" in handle:
            right += dx
        if "n" in handle:
            top += dy
        if "s" in handle:
            bottom += dy
        if keep_aspect and width > 0 and height > 0:
            aspect = width / height
            new_w = max(right - left, 1.0)
            new_h = max(bottom - top, 1.0)
            if abs(new_w / max(new_h, 1.0) - aspect) > abs(new_h * aspect - new_w) / max(new_w, 1.0):
                new_h = new_w / aspect
            else:
                new_w = new_h * aspect
            if "w" in handle:
                left = right - new_w
            else:
                right = left + new_w
            if "n" in handle:
                top = bottom - new_h
            else:
                bottom = top + new_h
        self.element = replace(
            self.element,
            frame=pixels_to_frame(
                self._page_w,
                self._page_h,
                left,
                top,
                right - left,
                bottom - top,
                gutter_side=self._gutter_side,
            ),
        )
        self._place()
        self.update()


class PhotoPageCanvas(QGraphicsView):
    """One book page of photo elements. Preview uses thumbnails; export uses originals."""

    elementsChanged = Signal()
    keyForward = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bookPhotoCanvas")
        self.setBackgroundBrush(QBrush(QColor(_PAGE_BG)))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setAcceptDrops(True)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._elements: tuple[PhotoElement, ...] = ()
        self._visitors: tuple[PhotoElement, ...] = ()
        self._gutter_side: str | None = None
        self._media: dict[int, BookMedia] = {}
        self._editable = False
        self._pixmaps: dict[int, QPixmap] = {}

    def elements(self) -> tuple[PhotoElement, ...]:
        return self._elements

    def set_editable(self, editable: bool) -> None:
        if self._editable == editable:
            return
        self._editable = editable
        self._rebuild()

    def set_page(
        self,
        elements: tuple[PhotoElement, ...],
        media: tuple[BookMedia, ...],
        *,
        gutter_side: str | None = None,
        visitors: tuple[PhotoElement, ...] = (),
    ) -> None:
        self._elements = sorted_by_z(elements)
        self._visitors = visitors
        self._gutter_side = gutter_side
        self._media = {item.source_file_id: item for item in media}
        self._rebuild()

    def set_visitors(self, visitors: tuple[PhotoElement, ...]) -> None:
        self._visitors = visitors
        self._rebuild()

    def clear_page(self) -> None:
        self._elements = ()
        self._media = {}
        self._scene.clear()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._rebuild()

    def _rebuild(self) -> None:
        selected = {item.element.id for item in self._items() if item.isSelected()}
        self._scene.clear()
        width = max(self.viewport().width(), 1)
        height = max(self.viewport().height(), 1)
        self.resetTransform()
        self._scene.setSceneRect(0, 0, width, height)
        own_ids = {item.id for item in self._elements}
        for element, editable in (
            *((item, self._editable) for item in sorted_by_z(self._elements)),
            *((item, False) for item in self._visitors if item.id not in own_ids),
        ):
            media = self._media.get(element.source_file_id)
            pixmap = self._pixmap_for(media)
            image_w, image_h = _preview_image_size(pixmap, media)
            item = _PhotoItem(
                element,
                pixmap,
                image_w,
                image_h,
                float(width),
                float(height),
                editable=editable,
                gutter_side=self._gutter_side if editable else None,
            )
            self._scene.addItem(item)
            if editable and element.id in selected:
                item.setSelected(True)

    def _pixmap_for(self, media: BookMedia | None) -> QPixmap:
        if media is None:
            return QPixmap()
        cached = self._pixmaps.get(media.source_file_id)
        if cached is not None:
            return cached
        path = media.thumbnail_path
        pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()
        self._pixmaps[media.source_file_id] = pixmap
        return pixmap

    def _items(self) -> list[_PhotoItem]:
        return [item for item in self._scene.items() if isinstance(item, _PhotoItem)]

    def _selected(self) -> _PhotoItem | None:
        for item in self._items():
            if item.isSelected():
                return item
        return None

    def _commit_item(self, item: _PhotoItem) -> None:
        previous = next((element for element in self._elements if element.id == item.element.id), None)
        if previous is None or previous == item.element:
            return
        self._elements = update_element(self._elements, item.element)
        self.elementsChanged.emit()

    def _set_elements(self, elements: tuple[PhotoElement, ...]) -> None:
        self._elements = sorted_by_z(elements)
        self._rebuild()
        self.elementsChanged.emit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._editable and source_ids_from_mime(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        self.dragEnterEvent(event)  # type: ignore[arg-type]

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        ids = source_ids_from_mime(event.mimeData())
        if not self._editable or not ids:
            event.ignore()
            return
        source_id = ids[0]
        scene_pos = self.mapToScene(event.position().toPoint())
        hit = self._scene.itemAt(scene_pos, self.transform())
        own_hit = isinstance(hit, _PhotoItem) and any(
            element.id == hit.element.id for element in self._elements
        )
        if own_hit:
            self._set_elements(replace_source(self._elements, hit.element.id, source_id))
        else:
            page_w = max(self.viewport().width(), 1)
            page_h = max(self.viewport().height(), 1)
            frame = pixels_to_frame(
                page_w,
                page_h,
                scene_pos.x() - page_w * 0.18,
                scene_pos.y() - page_h * 0.16,
                page_w * 0.36,
                page_h * 0.32,
                gutter_side=self._gutter_side,
            )
            self._set_elements(add_photo_element(self._elements, source_id, frame=frame))
        event.acceptProposedAction()

    def contextMenuEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self._editable:
            return
        item = self._selected()
        if item is None:
            scene_pos = self.mapToScene(event.pos())
            hit = self._scene.itemAt(scene_pos, self.transform())
            if isinstance(hit, _PhotoItem):
                hit.setSelected(True)
                item = hit
        if item is None:
            return
        menu = QMenu(self)
        front = menu.addAction("Nach vorn")
        back = menu.addAction("Nach hinten")
        menu.addSeparator()
        rot_ccw = menu.addAction("Drehen −1°")
        rot_cw = menu.addAction("Drehen +1°")
        rot_90_ccw = menu.addAction("Drehen −90°")
        rot_90_cw = menu.addAction("Drehen +90°")
        rot_reset = menu.addAction("Drehung zurücksetzen")
        menu.addSeparator()
        delete = menu.addAction("Löschen")
        chosen = menu.exec(event.globalPos())
        if chosen is front:
            self._set_elements(bring_to_front(self._elements, item.element.id))
        elif chosen is back:
            self._set_elements(send_to_back(self._elements, item.element.id))
        elif chosen is rot_ccw:
            item._nudge_angle(-1)
            self._commit_item(item)
        elif chosen is rot_cw:
            item._nudge_angle(1)
            self._commit_item(item)
        elif chosen is rot_90_ccw:
            item._nudge_angle(-90)
            self._commit_item(item)
        elif chosen is rot_90_cw:
            item._nudge_angle(90)
            self._commit_item(item)
        elif chosen is rot_reset:
            item._set_crop(replace(item.element.crop, angle=0.0))
            self._commit_item(item)
        elif chosen is delete:
            self._set_elements(remove_element(self._elements, item.element.id))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        item = self._selected() if self._editable else None
        if item is not None:
            key = event.key()
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if key == Qt.Key.Key_Delete:
                self._set_elements(remove_element(self._elements, item.element.id))
                return
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                item._nudge_scale(1)
                self._commit_item(item)
                return
            if key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                item._nudge_scale(-1)
                self._commit_item(item)
                return
            if key in (Qt.Key.Key_Comma, Qt.Key.Key_BracketLeft):
                item._nudge_angle(-15 if shift else -1)
                self._commit_item(item)
                return
            if key in (Qt.Key.Key_Period, Qt.Key.Key_BracketRight):
                item._nudge_angle(15 if shift else 1)
                self._commit_item(item)
                return
        self.keyForward.emit(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        if self._editable and isinstance(item, _PhotoItem):
            super().wheelEvent(event)
            return
        event.ignore()
