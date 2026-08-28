"""Date chip next to a vertical scrollbar handle, as on the Timeline."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QAbstractScrollArea, QLabel, QScrollBar, QStyle, QStyleOptionSlider


def scrollbar_slider_rect(bar: QScrollBar) -> QRect:
    opt = QStyleOptionSlider()
    bar.initStyleOption(opt)
    return bar.style().subControlRect(
        QStyle.ComplexControl.CC_ScrollBar,
        opt,
        QStyle.SubControl.SC_ScrollBarSlider,
        bar,
    )


class ScrollDateChip(QObject):
    """Shows ``date_at_mid()`` beside the scrollbar while the user scrolls."""

    def __init__(self, host: QAbstractScrollArea, date_at_mid: Callable[[], str | None]) -> None:
        super().__init__(host)
        self._host = host
        self._date_at_mid = date_at_mid
        self._slider_down = False
        self.label = QLabel(host)
        self.label.setObjectName("timelineScrollDate")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.label.hide()
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.setInterval(900)
        self._hide.timeout.connect(self.label.hide)
        bar = host.verticalScrollBar()
        bar.valueChanged.connect(self._on_scroll)
        bar.sliderPressed.connect(self._on_pressed)
        bar.sliderReleased.connect(self._on_released)
        bar.rangeChanged.connect(self._on_range)
        host.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self.place()
        return super().eventFilter(watched, event)

    def sync(self, *, show: bool) -> None:
        if not show:
            self.label.hide()
            return
        bar = self._host.verticalScrollBar()
        text = self._date_at_mid() if bar.maximum() > 0 else None
        if not text:
            self.label.hide()
            return
        self.label.setText(text)
        self.label.adjustSize()
        self.label.show()
        self.place()

    def place(self) -> None:
        if self.label.isHidden():
            return
        bar = self._host.verticalScrollBar()
        handle = scrollbar_slider_rect(bar)
        if not handle.isValid() or handle.height() <= 0:
            return
        label = self.label
        label.adjustSize()
        bar_origin = bar.mapTo(self._host, QPoint(0, 0))
        handle_center = bar.mapTo(self._host, handle.center())
        anchor_x = bar_origin.x()
        if anchor_x <= 0:
            anchor_x = self._host.viewport().width()
        x = anchor_x - label.width()
        y = handle_center.y() - label.height() // 2
        y = max(0, min(y, self._host.height() - label.height()))
        x = max(0, min(x, self._host.width() - label.width()))
        label.move(x, y)
        label.raise_()

    def _on_pressed(self) -> None:
        self._slider_down = True
        self._hide.stop()
        self.sync(show=True)

    def _on_released(self) -> None:
        self._slider_down = False
        self._hide.start()

    def _on_scroll(self, _value: int = 0) -> None:
        self.sync(show=True)
        if not self._slider_down:
            self._hide.start()

    def _on_range(self, *_args: int) -> None:
        if not self.label.isHidden():
            self.place()
