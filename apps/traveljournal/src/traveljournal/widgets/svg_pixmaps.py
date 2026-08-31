"""Render bundled SVG files to pixmaps."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_SHAPE_FILL = 'fill="#000000"'


def svg_renderer(path: Path, *, fill: str | None = None) -> QSvgRenderer:
    if fill is None:
        return QSvgRenderer(str(path))
    text = path.read_text(encoding="utf-8").replace(_SHAPE_FILL, f'fill="{fill}"')
    return QSvgRenderer(QByteArray(text.encode("utf-8")))


def svg_pixmap(path: Path, size: QSize, *, fill: str | None = None) -> QPixmap:
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if size.width() < 1 or size.height() < 1 or not path.is_file():
        return pixmap
    renderer = svg_renderer(path, fill=fill)
    if not renderer.isValid():
        return pixmap
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap
