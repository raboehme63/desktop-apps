"""Horizontal strip of travel-section cards over the map."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from travelcore.maps.groups import MapTimelineCard, parse_group_key
from travelcore.timeline.journal import calendar_key
from travelcore.timeline.sections import KIND_DAY, KIND_MOVEMENT, insert_dates_between
from traveljournal.widgets.join_plus import MapSpine

CARD_WIDTH = 248
CARD_HEIGHT = 148
CARD_RADIUS = 22
CARD_IDLE_SCALE = 0.70
HEXAGON_CUT_RATIO = 0.28
_FOCUS_DELAY_MS = 180
COVER_FOCUS_ZOOM = 14


def section_card_menu_items(card: MapTimelineCard) -> tuple[tuple[str, bool], ...]:
    """Right-click actions for a saved section card: place, move, or zoom to the cover."""

    kind, raw = parse_group_key(card.group_key)
    if kind != "section" or not isinstance(raw, int) or raw <= 0:
        return ()
    placed = not card.needs_pin
    return (
        ("Platzieren", not placed),
        ("Verschieben", placed),
        ("Zentrieren", placed),
    )


def cover_dest_rect(target: QRectF, pixmap_width: float, pixmap_height: float) -> QRectF:
    """Scale pixmap to cover ``target`` (crop overflow, no letterbox)."""

    if pixmap_width <= 0 or pixmap_height <= 0 or target.width() <= 0 or target.height() <= 0:
        return QRectF(target)
    scale = max(target.width() / pixmap_width, target.height() / pixmap_height)
    width = pixmap_width * scale
    height = pixmap_height * scale
    return QRectF(
        target.x() + (target.width() - width) / 2,
        target.y() + (target.height() - height) / 2,
        width,
        height,
    )


def nearest_card_index(centers: list[int], viewport_center: int) -> int | None:
    """Index of the card whose center is closest to the viewport midpoint."""

    if not centers:
        return None
    return min(range(len(centers)), key=lambda index: abs(centers[index] - viewport_center))


def hexagon_cut(rect: QRectF) -> float:
    """Horizontal inset of the left/right points of a lying hexagon."""

    if rect.width() <= 0 or rect.height() <= 0:
        return 0.0
    return min(rect.height() * HEXAGON_CUT_RATIO, rect.width() * 0.22)


def transfer_hexagon_path(rect: QRectF) -> QPainterPath:
    """Lying hexagon: flat top and bottom, points left and right."""

    cut = hexagon_cut(rect)
    mid_y = rect.center().y()
    path = QPainterPath()
    path.moveTo(rect.left(), mid_y)
    path.lineTo(rect.left() + cut, rect.top())
    path.lineTo(rect.right() - cut, rect.top())
    path.lineTo(rect.right(), mid_y)
    path.lineTo(rect.right() - cut, rect.bottom())
    path.lineTo(rect.left() + cut, rect.bottom())
    path.closeSubpath()
    return path


class _CardWidget(QFrame):
    clicked = Signal(str)
    open_requested = Signal(str)
    place_requested = Signal(str)
    zoom_requested = Signal(str)

    def __init__(self, card: MapTimelineCard, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.card = card
        self.setObjectName("mapTimelineCard")
        width, height = _card_size(focused=False)
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("focused", False)
        self.setProperty("cardKind", card.card_kind)
        self._focused = False
        self._pixmap = QPixmap()
        path = card.cover_path
        if path is not None and path.is_file():
            loaded = QPixmap(str(path))
            if not loaded.isNull():
                self._pixmap = loaded
        self._press: QPoint | None = None
        self._dragged = False

    def set_focused(self, focused: bool) -> None:
        self._focused = focused
        self.setProperty("focused", focused)
        width, height = _card_size(focused=focused)
        if self.width() != width or self.height() != height:
            self.setFixedSize(width, height)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        hexagon = self.card.card_kind == KIND_MOVEMENT
        radius = CARD_RADIUS if self._focused else CARD_RADIUS * CARD_IDLE_SCALE
        clip = transfer_hexagon_path(rect) if hexagon else QPainterPath()
        if not hexagon:
            clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        if self._pixmap.isNull():
            painter.fillRect(rect, QColor("#243044"))
        else:
            dest = cover_dest_rect(rect, float(self._pixmap.width()), float(self._pixmap.height()))
            painter.drawPixmap(dest, self._pixmap, QRectF(self._pixmap.rect()))
        fade_h = rect.height() * 0.58
        fade = QLinearGradient(rect.left(), rect.bottom() - fade_h, rect.left(), rect.bottom())
        fade.setColorAt(0.0, QColor(8, 12, 18, 0))
        fade.setColorAt(0.35, QColor(8, 12, 18, 70))
        fade.setColorAt(1.0, QColor(8, 12, 18, 190))
        painter.fillRect(rect, fade)
        scale = 1.0 if self._focused else CARD_IDLE_SCALE
        side_pad = hexagon_cut(rect) if hexagon else 0.0
        inset = max(8, int(side_pad + (8 if hexagon else 12) * scale))
        text_h = max(22, int(40 * scale))
        when_h = max(12, int(16 * scale))
        text = QRect(
            int(rect.left()) + inset,
            int(rect.bottom()) - (text_h + when_h + 4),
            int(rect.width()) - 2 * inset,
            text_h,
        )
        when = QRect(
            int(rect.left()) + inset,
            int(rect.bottom()) - (when_h + 4),
            int(rect.width()) - 2 * inset,
            when_h,
        )
        title_font = QFont(self.font())
        if hexagon:
            title_font.setPixelSize(14 if self._focused else 12)
        else:
            title_font.setPixelSize(16 if self._focused else 14)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            text,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap),
            self.card.title,
        )
        when_font = QFont(self.font())
        if hexagon:
            when_font.setPixelSize(10 if self._focused else 9)
        else:
            when_font.setPixelSize(11 if self._focused else 10)
        painter.setFont(when_font)
        painter.setPen(QColor("#e8edf5"))
        painter.drawText(
            when,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.card.time_label,
        )
        _paint_count_chips(
            painter,
            rect,
            self.card,
            focused=self._focused,
            hexagon=hexagon,
            show_reserve=self._include_reserve(),
        )
        if self.card.card_kind == KIND_DAY:
            _paint_calendar_badge(painter, rect)
        painter.setClipping(False)
        if self.card.needs_pin:
            border = QColor("#e23d3d")
            width = 2.6 if self._focused else 2.0
        else:
            border = QColor("#2eb8a0") if self._focused else QColor("#f4f7fb")
            width = 2.0 if self._focused else 1.4
        painter.setPen(QPen(border, width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(clip)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._show_card_menu(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._dragged = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        strip = self._strip()
        if self._press is None or strip is None:
            super().mouseMoveEvent(event)
            return
        current = event.globalPosition().toPoint()
        delta = current.x() - self._press.x()
        if abs(delta) > 6:
            self._dragged = True
        if self._dragged:
            bar = strip.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            self._press = current
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            dragged = self._dragged
            self._press = None
            self._dragged = False
            if not dragged:
                self.clicked.emit(self.card.group_key)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.card.group_key)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _show_card_menu(self, global_pos: QPoint) -> None:
        items = section_card_menu_items(self.card)
        if not items:
            return
        menu = QMenu(self)
        for label, enabled in items:
            action = menu.addAction(label)
            action.setEnabled(enabled)
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        label = chosen.text()
        if label in {"Platzieren", "Verschieben"}:
            self.place_requested.emit(self.card.group_key)
            return
        if label == "Zentrieren":
            self.zoom_requested.emit(self.card.group_key)

    def _include_reserve(self) -> bool:
        strip = self._strip()
        return strip is not None and strip.show_reserve()

    def _strip(self) -> MapTimelineStrip | None:
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, MapTimelineStrip):
                return parent
            parent = parent.parent()
        return None


class MapTimelineStrip(QScrollArea):
    focus_changed = Signal(str)
    open_in_timeline = Signal(str)
    place_requested = Signal(str)
    zoom_requested = Signal(str)
    add_between = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mapTimelineStrip")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(164)
        self.setMaximumHeight(176)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.viewport().setAutoFillBackground(False)
        self._cards: tuple[MapTimelineCard, ...] = ()
        self._widgets: list[_CardWidget] = []
        self._focused_key = ""
        self._show_reserve = False
        self._inner = QWidget()
        self._inner.setAutoFillBackground(False)
        self._row = QHBoxLayout(self._inner)
        self._row.setContentsMargins(0, 4, 0, 4)
        self._row.setSpacing(0)
        self._row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._left_pad = QWidget(self._inner)
        self._right_pad = QWidget(self._inner)
        self._empty = QLabel("Keine Reiseabschnitte.", self._inner)
        self._empty.setObjectName("pageSubtitle")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._row.addWidget(self._left_pad)
        self._row.addWidget(self._empty, 1)
        self._row.addWidget(self._right_pad)
        self.setWidget(self._inner)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_FOCUS_DELAY_MS)
        self._timer.timeout.connect(self._emit_center)
        self.horizontalScrollBar().valueChanged.connect(self._schedule_focus)

    def cards(self) -> tuple[MapTimelineCard, ...]:
        return self._cards

    def card(self, group_key: str) -> MapTimelineCard | None:
        return next((item for item in self._cards if item.group_key == group_key), None)

    def update_card_notes(self, group_key: str, notes: str) -> None:
        self._cards = tuple(
            replace(item, notes=notes) if item.group_key == group_key else item for item in self._cards
        )

    def focused_key(self) -> str:
        return self._focused_key

    def show_reserve(self) -> bool:
        return self._show_reserve

    def set_show_reserve(self, show: bool) -> None:
        flag = bool(show)
        if flag == self._show_reserve:
            return
        self._show_reserve = flag
        for widget in self._widgets:
            widget.update()

    def set_cards(self, cards: tuple[MapTimelineCard, ...] | list[MapTimelineCard]) -> None:
        self._timer.stop()
        self._cards = tuple(cards)
        self._widgets = []
        self._focused_key = ""
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in {self._left_pad, self._right_pad, self._empty}:
                widget.deleteLater()
        self._row.addWidget(self._left_pad)
        if not self._cards:
            self._empty.setVisible(True)
            self._row.addWidget(self._empty, 1)
            self._row.addWidget(self._right_pad)
            self._update_end_padding()
            return
        self._empty.setVisible(False)
        self._empty.setParent(self._inner)
        for index, card in enumerate(self._cards):
            if index:
                previous = self._cards[index - 1]
                start, end = insert_dates_between(
                    calendar_key(previous.ended_at) or calendar_key(previous.started_at),
                    calendar_key(card.started_at),
                )
                line = MapSpine(self._inner)
                line.add_requested.connect(
                    lambda start=start, end=end: self.add_between.emit((start, end))
                )
                self._row.addWidget(line, 0, Qt.AlignmentFlag.AlignVCenter)
            widget = _CardWidget(card, self._inner)
            widget.clicked.connect(self.center_on)
            widget.open_requested.connect(self.open_in_timeline.emit)
            widget.place_requested.connect(self.place_requested.emit)
            widget.zoom_requested.connect(self.zoom_requested.emit)
            self._widgets.append(widget)
            self._row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self._row.addWidget(self._right_pad)
        self._update_end_padding()
        QTimer.singleShot(0, self._center_first)

    def center_on(self, group_key: str, *, emit: bool = True) -> None:
        widget = next((item for item in self._widgets if item.card.group_key == group_key), None)
        if widget is None:
            return
        self._apply_focus(group_key, force=True, emit=emit)
        self._scroll_widget_to_center(widget)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, 164)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_end_padding()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - int(delta))
            event.accept()
            return
        super().wheelEvent(event)

    def _center_first(self) -> None:
        if not self._widgets:
            return
        self.center_on(self._widgets[0].card.group_key)

    def _update_end_padding(self) -> None:
        pad = max(12, (self.viewport().width() - CARD_WIDTH) // 2)
        self._left_pad.setFixedWidth(pad)
        self._right_pad.setFixedWidth(pad)

    def _schedule_focus(self) -> None:
        if not self._widgets:
            return
        self._timer.start()

    def _emit_center(self) -> None:
        index = nearest_card_index(self._card_centers(), self._viewport_center())
        if index is None:
            return
        self._apply_focus(self._widgets[index].card.group_key)

    def _apply_focus(self, group_key: str, *, force: bool = False, emit: bool = True) -> None:
        for widget in self._widgets:
            widget.set_focused(widget.card.group_key == group_key)
        self._update_end_padding()
        if group_key == self._focused_key and not force:
            return
        self._focused_key = group_key
        if emit:
            self.focus_changed.emit(group_key)

    def _viewport_center(self) -> int:
        return self.horizontalScrollBar().value() + self.viewport().width() // 2

    def _card_centers(self) -> list[int]:
        centers: list[int] = []
        for widget in self._widgets:
            pos = widget.mapTo(self._inner, QPoint(widget.width() // 2, 0))
            centers.append(pos.x())
        return centers

    def _scroll_widget_to_center(self, widget: _CardWidget) -> None:
        center = widget.mapTo(self._inner, QPoint(widget.width() // 2, 0)).x()
        self.horizontalScrollBar().setValue(center - self.viewport().width() // 2)


def _card_size(*, focused: bool) -> tuple[int, int]:
    scale = 1.0 if focused else CARD_IDLE_SCALE
    return max(1, round(CARD_WIDTH * scale)), max(1, round(CARD_HEIGHT * scale))


def _paint_calendar_badge(painter: QPainter, rect: QRectF) -> None:
    size = max(16.0, rect.height() * 22.0 / CARD_HEIGHT)
    inset = max(6.0, rect.height() * 8.0 / CARD_HEIGHT)
    box = QRectF(rect.right() - size - inset, rect.top() + inset, size, size)
    painter.setPen(QPen(QColor("#f4f7fb"), 1.2))
    painter.setBrush(QColor(8, 12, 18, 175))
    painter.drawRoundedRect(box, 4, 4)
    painter.fillRect(QRectF(box.left(), box.top(), box.width(), 6), QColor("#e8edf5"))
    painter.setPen(QPen(QColor("#243044"), 1.6))
    painter.drawLine(int(box.left() + 6), int(box.top() - 1), int(box.left() + 6), int(box.top() + 5))
    painter.drawLine(int(box.right() - 6), int(box.top() - 1), int(box.right() - 6), int(box.top() + 5))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#f4f7fb"))
    for column in range(3):
        for row in range(2):
            painter.drawEllipse(QRectF(box.left() + 5 + column * 5.2, box.top() + 10 + row * 5.2, 2.4, 2.4))


def _paint_count_chips(
    painter: QPainter,
    rect: QRectF,
    card: MapTimelineCard,
    *,
    focused: bool,
    hexagon: bool,
    show_reserve: bool,
) -> None:
    photos, tracks, igc, youtube = card.visible_counts(show_reserve=show_reserve)
    chips: list[tuple[str, int]] = []
    if photos:
        chips.append(("photo", photos))
    if tracks:
        chips.append(("track", tracks))
    if igc:
        chips.append(("igc", igc))
    if youtube:
        chips.append(("youtube", youtube))
    if not chips:
        return
    scale = 1.0 if focused else CARD_IDLE_SCALE
    icon = max(10.0, 12.0 * scale)
    font_px = max(9, int(11 * scale))
    gap = max(4.0, 6.0 * scale)
    pad_x = max(4.0, 5.0 * scale)
    pad_y = max(2.0, 3.0 * scale)
    side = hexagon_cut(rect) if hexagon else 0.0
    inset = max(6.0, 8.0 * scale)
    x = rect.left() + side + inset
    y = rect.top() + inset
    limit = rect.right() - side - inset
    if card.card_kind == KIND_DAY:
        badge = max(16.0, rect.height() * 22.0 / CARD_HEIGHT)
        limit = min(limit, rect.right() - badge - inset - 6.0)
    font = QFont(painter.font())
    font.setPixelSize(font_px)
    font.setWeight(QFont.Weight.DemiBold)
    metrics = QFontMetrics(font)
    chip_h = pad_y * 2 + max(icon, float(font_px))
    for kind, number in chips:
        text = str(number)
        text_w = metrics.horizontalAdvance(text)
        icon_w = icon * (4.0 / 3.0) if kind == "youtube" else icon
        chip_w = pad_x * 2 + icon_w + 3.0 + text_w
        if x + chip_w > limit:
            break
        box = QRectF(x, y, chip_w, chip_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 12, 18, 185))
        painter.drawRoundedRect(box, 4, 4)
        icon_box = QRectF(box.left() + pad_x, box.center().y() - icon / 2, icon_w, icon)
        _paint_count_icon(painter, kind, icon_box)
        painter.setFont(font)
        painter.setPen(QColor("#f4f7fb"))
        text_box = QRect(
            int(icon_box.right()) + 3,
            int(box.top()),
            text_w + 2,
            int(box.height()),
        )
        painter.drawText(text_box, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
        x += chip_w + gap


def _paint_count_icon(painter: QPainter, kind: str, box: QRectF) -> None:
    painter.setPen(QPen(QColor("#f4f7fb"), 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "photo":
        painter.drawRoundedRect(box.adjusted(0.6, 0.8, -0.6, -0.4), 1.6, 1.6)
        peak = QPainterPath()
        peak.moveTo(box.left() + 1.4, box.bottom() - 1.4)
        peak.lineTo(box.left() + box.width() * 0.38, box.top() + box.height() * 0.42)
        peak.lineTo(box.left() + box.width() * 0.58, box.top() + box.height() * 0.62)
        peak.lineTo(box.right() - 1.4, box.bottom() - 1.4)
        painter.setBrush(QColor("#f4f7fb"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(peak)
        painter.setBrush(QColor("#f4f7fb"))
        painter.drawEllipse(QRectF(box.left() + box.width() * 0.55, box.top() + 2.0, 2.4, 2.4))
        return
    if kind == "track":
        path = QPainterPath()
        path.moveTo(box.left() + 1.2, box.bottom() - 2.0)
        path.lineTo(box.left() + box.width() * 0.38, box.top() + 2.2)
        path.lineTo(box.left() + box.width() * 0.62, box.bottom() - 2.4)
        path.lineTo(box.right() - 1.2, box.top() + 2.0)
        painter.drawPath(path)
        painter.setBrush(QColor("#f4f7fb"))
        painter.setPen(Qt.PenStyle.NoPen)
        r = 1.7
        painter.drawEllipse(QRectF(box.left() + 0.4, box.bottom() - 3.6, r * 2, r * 2))
        painter.drawEllipse(QRectF(box.right() - 3.8, box.top() + 0.6, r * 2, r * 2))
        return
    if kind == "igc":
        color = QColor("#f4f7fb")
        left = box.left() + 0.7
        right = box.right() - 0.7
        mid = box.center().x()
        rim = box.top() + box.height() * 0.40
        peak = box.top() + 0.55
        canopy = QPainterPath()
        canopy.moveTo(left, rim)
        canopy.quadTo(mid, peak, right, rim)
        wing = max(2.05, box.height() * 0.20)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(color, wing, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPath(canopy)
        harness = QPointF(mid, box.bottom() - box.height() * 0.16)
        line_w = max(1.15, box.height() * 0.10)
        inset = (right - left) * 0.16
        painter.setPen(QPen(color, line_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(left + inset, rim), harness)
        painter.drawLine(QPointF(right - inset, rim), harness)
        r = max(1.45, box.height() * 0.13)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(harness, r, r)
        return
    if kind != "youtube":
        return
    height = box.height()
    width = height * (4.0 / 3.0)
    if width > box.width():
        width = box.width()
        height = width * 0.75
    tube = QRectF(
        box.center().x() - width / 2,
        box.center().y() - height / 2,
        width,
        height,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ff0000"))
    painter.drawRoundedRect(tube, height * 0.26, height * 0.26)
    play = QPainterPath()
    cx = tube.center().x() - height * 0.04
    cy = tube.center().y()
    play.moveTo(cx - height * 0.14, cy - height * 0.20)
    play.lineTo(cx + height * 0.24, cy)
    play.lineTo(cx - height * 0.14, cy + height * 0.20)
    play.closeSubpath()
    painter.setBrush(QColor("#ffffff"))
    painter.drawPath(play)
