"""Horizontal strip of travel-section cards over the map."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
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
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from travelcore.maps.groups import MapTimelineCard

CARD_WIDTH = 248
CARD_HEIGHT = 148
CARD_RADIUS = 22
LINE_WIDTH = 36
_FOCUS_DELAY_MS = 180


def nearest_card_index(centers: list[int], viewport_center: int) -> int | None:
    """Index of the card whose center is closest to the viewport midpoint."""

    if not centers:
        return None
    return min(range(len(centers)), key=lambda index: abs(centers[index] - viewport_center))


class _LineWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mapTimelineLine")
        self.setFixedSize(LINE_WIDTH, 8)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        y = self.height() // 2
        painter.setPen(QPen(QColor("#e8edf5"), 2.0))
        painter.drawLine(0, y, self.width(), y)


class _CardWidget(QFrame):
    clicked = Signal(str)
    fit_all_requested = Signal()

    def __init__(self, card: MapTimelineCard, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.card = card
        self.setObjectName("mapTimelineCard")
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("focused", False)
        self._focused = False
        self._pixmap = QPixmap()
        path = card.cover_path
        if path is not None and path.is_file():
            loaded = QPixmap(str(path))
            if not loaded.isNull():
                self._pixmap = loaded.scaled(
                    CARD_WIDTH,
                    CARD_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
        self._press: QPoint | None = None
        self._dragged = False

    def set_focused(self, focused: bool) -> None:
        self._focused = focused
        self.setProperty("focused", focused)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
        painter.setClipPath(clip)
        if self._pixmap.isNull():
            painter.fillRect(rect, QColor("#243044"))
        else:
            x = rect.x() + (rect.width() - self._pixmap.width()) / 2
            y = rect.y() + (rect.height() - self._pixmap.height()) / 2
            painter.drawPixmap(int(x), int(y), self._pixmap)
        fade = QLinearGradient(rect.left(), rect.bottom() - 86, rect.left(), rect.bottom())
        fade.setColorAt(0.0, QColor(8, 12, 18, 0))
        fade.setColorAt(0.35, QColor(8, 12, 18, 70))
        fade.setColorAt(1.0, QColor(8, 12, 18, 190))
        painter.fillRect(rect, fade)
        text = QRect(int(rect.left()) + 12, int(rect.bottom()) - 70, int(rect.width()) - 24, 40)
        when = QRect(int(rect.left()) + 12, int(rect.bottom()) - 28, int(rect.width()) - 24, 16)
        title_font = QFont(self.font())
        title_font.setPixelSize(16)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            text,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap),
            self.card.title,
        )
        when_font = QFont(self.font())
        when_font.setPixelSize(11)
        painter.setFont(when_font)
        painter.setPen(QColor("#e8edf5"))
        painter.drawText(
            when,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.card.time_label,
        )
        painter.setClipping(False)
        border = QColor("#2eb8a0") if self._focused else QColor("#f4f7fb")
        painter.setPen(QPen(border, 2.0 if self._focused else 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
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
            self.fit_all_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _strip(self) -> MapTimelineStrip | None:
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, MapTimelineStrip):
                return parent
            parent = parent.parent()
        return None


class MapTimelineStrip(QScrollArea):
    focus_changed = Signal(str)
    fit_all_requested = Signal()

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

    def focused_key(self) -> str:
        return self._focused_key

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
                line = _LineWidget(self._inner)
                self._row.addWidget(line, 0, Qt.AlignmentFlag.AlignVCenter)
            widget = _CardWidget(card, self._inner)
            widget.clicked.connect(self.center_on)
            widget.fit_all_requested.connect(self.fit_all_requested.emit)
            self._widgets.append(widget)
            self._row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self._row.addWidget(self._right_pad)
        self._update_end_padding()
        QTimer.singleShot(0, self._center_first)

    def center_on(self, group_key: str) -> None:
        widget = next((item for item in self._widgets if item.card.group_key == group_key), None)
        if widget is None:
            return
        self._scroll_widget_to_center(widget)
        self._apply_focus(group_key, force=True)

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

    def _apply_focus(self, group_key: str, *, force: bool = False) -> None:
        for widget in self._widgets:
            widget.set_focused(widget.card.group_key == group_key)
        if group_key == self._focused_key and not force:
            return
        self._focused_key = group_key
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
