"""Shared plus-on-a-line control for Timeline and map card joins."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QEnterEvent, QMouseEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from travelcore.project_settings import DEFAULT_STAY_LINK_COLOR

JOIN_PLUS_SIZE = 22
JOIN_LINE_WIDTH = 2.0
_JOIN_FILL = QColor("#12151c")
_JOIN_HOVER = QColor("#1c2230")


def join_color(value: str) -> QColor:
    color = QColor(value)
    if color.isValid():
        return color
    return QColor(DEFAULT_STAY_LINK_COLOR)


def paint_plus_circle(
    painter: QPainter,
    center: QPointF,
    radius: float,
    color: QColor,
    *,
    fill: QColor,
) -> None:
    """Antialiased ring with a stroked plus — no font, no filled triangle."""

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(fill)
    painter.drawEllipse(center, radius, radius)
    arm = radius * 0.40
    painter.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(center.x() - arm, center.y()), QPointF(center.x() + arm, center.y()))
    painter.drawLine(QPointF(center.x(), center.y() - arm), QPointF(center.x(), center.y() + arm))


class JoinPlus(QWidget):
    """Circular + that sits on a timeline or map join line."""

    clicked = Signal()

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("joinPlus")
        self._color = join_color(color)
        self._hover = False
        self.setFixedSize(JOIN_PLUS_SIZE, JOIN_PLUS_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Reiseabschnitt hier einfügen")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._hit(event.position()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        radius = (JOIN_PLUS_SIZE - 3) / 2
        center = QPointF(self.width() / 2, self.height() / 2)
        fill = _JOIN_HOVER if self._hover else _JOIN_FILL
        paint_plus_circle(painter, center, radius, self._color, fill=fill)

    def _hit(self, pos: QPointF) -> bool:
        center = QPointF(self.width() / 2, self.height() / 2)
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        radius = JOIN_PLUS_SIZE / 2
        return dx * dx + dy * dy <= radius * radius


class TimelineSpine(QWidget):
    """Vertical line with a plus between timeline cards."""

    add_requested = Signal()

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timelineJoin")
        self._color = join_color(color)
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._plus = JoinPlus(color, self)
        self._plus.clicked.connect(self.add_requested.emit)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._plus.move(
            (self.width() - self._plus.width()) // 2,
            (self.height() - self._plus.height()) // 2,
        )
        self._plus.raise_()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        gap = JOIN_PLUS_SIZE / 2 + 3
        painter.setPen(QPen(self._color, JOIN_LINE_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx, 3.0), QPointF(cx, cy - gap))
        painter.drawLine(QPointF(cx, cy + gap), QPointF(cx, self.height() - 3.0))


class MapSpine(QWidget):
    """Horizontal line with a plus between map-strip cards."""

    add_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mapTimelineJoin")
        self._color = QColor("#c5cedb")
        self.setFixedSize(40, JOIN_PLUS_SIZE + 6)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plus = JoinPlus("#c5cedb", self)
        self._plus.clicked.connect(self.add_requested.emit)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._plus.move(
            (self.width() - self._plus.width()) // 2,
            (self.height() - self._plus.height()) // 2,
        )
        self._plus.raise_()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        gap = JOIN_PLUS_SIZE / 2 + 3
        cx = self.width() / 2
        painter.setPen(QPen(self._color, JOIN_LINE_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(1.0, cy), QPointF(cx - gap, cy))
        painter.drawLine(QPointF(cx + gap, cy), QPointF(self.width() - 1.0, cy))
