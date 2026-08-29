"""Transport-symbol pixmaps and combo icons. Same badge as the map and Help."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QComboBox

from travelcore.timeline.symbols import symbol_badge_svg

COMBO_ICON_PX = 20


def transport_badge_pixmap(key: str, size: int = 48) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(symbol_badge_svg(key, size=size).encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap


def transport_badge_icon(key: str, size: int = COMBO_ICON_PX) -> QIcon:
    return QIcon(transport_badge_pixmap(key, size))


def fill_transport_combo(combo: QComboBox, items: tuple[tuple[str, str], ...]) -> None:
    """Add catalog rows with the badge before the label. Empty keys stay text-only."""

    combo.setIconSize(QSize(COMBO_ICON_PX, COMBO_ICON_PX))
    for value, label in items:
        if value:
            combo.addItem(transport_badge_icon(value), label, value)
        else:
            combo.addItem(label, value)
