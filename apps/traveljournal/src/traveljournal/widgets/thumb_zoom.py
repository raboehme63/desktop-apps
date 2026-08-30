"""Thumbnail zoom slider with a painted mark at the default value."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QStyle, QStyleOptionSlider, QWidget

MIN_THUMB_ZOOM = 50
DEFAULT_THUMB_ZOOM = 100
MAX_THUMB_ZOOM = 200
DEFAULT_GALLERY_ICON = 168
DEFAULT_GALLERY_CELL = QSize(184, 214)


def clamp_thumb_zoom(value: object) -> int:
    try:
        percent = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_THUMB_ZOOM
    snapped = int(round(percent / 5) * 5)
    return max(MIN_THUMB_ZOOM, min(MAX_THUMB_ZOOM, snapped))


def gallery_icon_size(percent: int) -> int:
    return max(48, round(DEFAULT_GALLERY_ICON * clamp_thumb_zoom(percent) / 100))


def gallery_cell_size(percent: int) -> QSize:
    icon = gallery_icon_size(percent)
    extra_w = DEFAULT_GALLERY_CELL.width() - DEFAULT_GALLERY_ICON
    extra_h = DEFAULT_GALLERY_CELL.height() - DEFAULT_GALLERY_ICON
    return QSize(icon + extra_w, icon + extra_h)


def gallery_chip_size(percent: int) -> int:
    return max(16, min(28, round(22 * clamp_thumb_zoom(percent) / 100)))


class DefaultMarkSlider(QSlider):
    """Horizontal slider that paints a tick at the default zoom."""

    def __init__(self, default: int, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._default = default
        self.setObjectName("thumbZoomSlider")
        self.setRange(MIN_THUMB_ZOOM, MAX_THUMB_ZOOM)
        self.setSingleStep(5)
        self.setPageStep(10)
        self.setTickInterval(0)
        self.setFixedHeight(22)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mark_x = self._mark_x()
        mid = self.rect().center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2eb8a0"))
        painter.drawRoundedRect(mark_x - 1, mid - 11, 3, 8, 1, 1)
        handle = self._handle_rect()
        hover = bool(self.underMouse())
        painter.setBrush(QColor("#2eb8a0") if hover else QColor("#e8edf5"))
        painter.setPen(QPen(QColor("#2eb8a0"), 2))
        painter.drawEllipse(handle.center(), 8, 8)

    def _handle_rect(self) -> QRect:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )

    def _mark_x(self) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        span = max(1, groove.width() - handle.width())
        ratio = (self._default - self.minimum()) / max(1, self.maximum() - self.minimum())
        return groove.x() + handle.width() // 2 + round(span * ratio)


class ThumbZoomSlider(QWidget):
    """Compact toolbar control: label, slider with default mark, percent."""

    zoom_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None, *, value: int = DEFAULT_THUMB_ZOOM) -> None:
        super().__init__(parent)
        self.setObjectName("thumbZoom")
        zoom = clamp_thumb_zoom(value)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel("Zoom", self)
        label.setObjectName("pageSubtitle")
        self._slider = DefaultMarkSlider(DEFAULT_THUMB_ZOOM, self)
        self._slider.setValue(zoom)
        self._slider.setFixedWidth(140)
        self._slider.setToolTip("Thumbnail-Größe. Markierung = Standard")
        self._value = QLabel(self)
        self._value.setObjectName("pageSubtitle")
        self._value.setMinimumWidth(40)
        self._slider.valueChanged.connect(self._on_slider)
        layout.addWidget(label)
        layout.addWidget(self._slider)
        layout.addWidget(self._value)
        self._sync_label(zoom)

    def value(self) -> int:
        return clamp_thumb_zoom(self._slider.value())

    def set_value(self, percent: int) -> None:
        zoom = clamp_thumb_zoom(percent)
        if self._slider.value() == zoom:
            self._sync_label(zoom)
            return
        self._slider.blockSignals(True)
        self._slider.setValue(zoom)
        self._slider.blockSignals(False)
        self._sync_label(zoom)

    def _on_slider(self, value: int) -> None:
        zoom = clamp_thumb_zoom(value)
        if value != zoom:
            self._slider.blockSignals(True)
            self._slider.setValue(zoom)
            self._slider.blockSignals(False)
        self._sync_label(zoom)
        self.zoom_changed.emit(zoom)

    def _sync_label(self, zoom: int) -> None:
        self._value.setText(f"{zoom} %")
        mark = "Standard" if zoom == DEFAULT_THUMB_ZOOM else f"Standard {DEFAULT_THUMB_ZOOM} %"
        self._slider.setToolTip(f"Thumbnail-Größe {zoom} %. Markierung = {mark}")
