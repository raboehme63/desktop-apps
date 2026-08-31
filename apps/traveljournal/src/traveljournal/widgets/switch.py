"""On/off switch for timeline section cards."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QCheckBox, QSizePolicy, QWidget

_TRACK_W = 46
_TRACK_H = 24
_KNOB = 18
_TRACK_OFF = QColor("#1a2030")
_TRACK_ON = QColor("#2eb8a0")
_TRACK_BORDER = QColor("#8fa0bb")
_KNOB_OFF = QColor("#e8edf5")
_KNOB_ON = QColor("#06231e")


class SwitchToggle(QCheckBox):
    """Compact pill switch without label or chrome. Checked is on."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("")
        self.setAccessibleName("Auf Karte sichtbar")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def sizeHint(self) -> QSize:
        return QSize(_TRACK_W, _TRACK_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802
        return self.contentsRect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QRectF(0.5, (self.height() - _TRACK_H) / 2 + 0.5, _TRACK_W - 1, _TRACK_H - 1)
        fill = QColor(_TRACK_ON if on else _TRACK_OFF)
        if self.underMouse():
            fill = fill.lighter(118)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(track, _TRACK_H / 2, _TRACK_H / 2)
        if not on:
            painter.setPen(QPen(_TRACK_BORDER, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track, _TRACK_H / 2, _TRACK_H / 2)
        inset = (_TRACK_H - _KNOB) / 2
        knob_x = track.right() - inset - _KNOB if on else track.left() + inset
        knob = QRectF(knob_x, track.top() + inset, _KNOB, _KNOB)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_KNOB_ON if on else _KNOB_OFF)
        painter.drawEllipse(knob)
        painter.end()
