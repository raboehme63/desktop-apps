"""Left-hand navigation."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap, QResizeEvent, QShowEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QButtonGroup, QPushButton, QSizePolicy, QVBoxLayout, QWidget

NAV_ITEMS = (
    ("project", "Projekt"),
    ("import", "Import"),
    ("photos", "Medien"),
    ("timeline", "Timeline"),
    ("map", "Karte"),
    ("export", "Export"),
)
_ICON_PX = 18
_CHEVRON_PX = 12
_COLLAPSE_W = 14
_COLLAPSE_H = 56
_ICON_WRAP = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
    'fill="none" stroke="{stroke}" stroke-width="{width}" stroke-linecap="round" '
    'stroke-linejoin="round">{paths}</svg>'
)
_NAV_ICON_PATHS = {
    "project": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "import": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/>'
        '<line x1="12" y1="15" x2="12" y2="3"/>'
    ),
    "photos": (
        '<rect x="3" y="3" width="18" height="18" rx="2"/>'
        '<circle cx="8.5" cy="8.5" r="1.5"/>'
        '<polyline points="21 15 16 10 5 21"/>'
    ),
    "timeline": (
        '<line x1="8" y1="6" x2="21" y2="6"/>'
        '<line x1="8" y1="12" x2="21" y2="12"/>'
        '<line x1="8" y1="18" x2="21" y2="18"/>'
        '<circle cx="4" cy="6" r="1.2"/>'
        '<circle cx="4" cy="12" r="1.2"/>'
        '<circle cx="4" cy="18" r="1.2"/>'
    ),
    "map": (
        '<polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/>'
        '<line x1="9" y1="3" x2="9" y2="18"/>'
        '<line x1="15" y1="6" x2="15" y2="21"/>'
    ),
    "export": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="17 8 12 3 7 8"/>'
        '<line x1="12" y1="3" x2="12" y2="15"/>'
    ),
}


def _svg_icon(paths: str, *, size: int, stroke: str = "#c5cddb", width: str = "2") -> QIcon:
    svg = _ICON_WRAP.format(paths=paths, stroke=stroke, width=width)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def _nav_icon(key: str) -> QIcon:
    return _svg_icon(_NAV_ICON_PATHS[key], size=_ICON_PX)


def _chevron_icon(*, expand: bool) -> QIcon:
    paths = '<polyline points="9 18 15 12 9 6"/>' if expand else '<polyline points="15 18 9 12 15 6"/>'
    return _svg_icon(paths, size=_CHEVRON_PX, stroke="#e8edf5", width="2.5")


class Sidebar(QWidget):
    page_changed = Signal(str)
    collapsed_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._collapsed = False

        layout = QVBoxLayout(self)
        self._root = layout
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(6)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for key, label in NAV_ITEMS:
            button = QPushButton(label)
            button.setObjectName("sidebarButton")
            button.setCheckable(True)
            button.setToolTip(label)
            button.setIcon(_nav_icon(key))
            button.setIconSize(QSize(_ICON_PX, _ICON_PX))
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, page=key: self.page_changed.emit(page))
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self._collapse = QPushButton(self)
        self._collapse.setObjectName("sidebarCollapse")
        self._collapse.setIcon(_chevron_icon(expand=False))
        self._collapse.setIconSize(QSize(_CHEVRON_PX, _CHEVRON_PX))
        self._collapse.setFixedSize(_COLLAPSE_W, _COLLAPSE_H)
        self._collapse.setToolTip("Navigation einklappen")
        self._collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse.clicked.connect(self._toggle_collapsed)
        self._buttons["project"].setChecked(True)
        self._apply_collapsed()

    def current_key(self) -> str:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return "project"

    def set_current(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        flag = bool(collapsed)
        if flag == self._collapsed:
            return
        self._collapsed = flag
        self._apply_collapsed()
        self.collapsed_changed.emit(flag)

    def _toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def _apply_collapsed(self) -> None:
        collapsed = self._collapsed
        self.setProperty("collapsed", collapsed)
        self.style().unpolish(self)
        self.style().polish(self)
        self._root.setContentsMargins(*(8, 12, 8, 12) if collapsed else (12, 16, 12, 16))
        self._collapse.setIcon(_chevron_icon(expand=collapsed))
        self._collapse.setToolTip("Navigation ausklappen" if collapsed else "Navigation einklappen")
        for key, label in NAV_ITEMS:
            button = self._buttons[key]
            button.setText("" if collapsed else label)
            button.setToolTip(label)
            button.style().unpolish(button)
            button.style().polish(button)
        self._fit_width()

    def _fit_width(self) -> None:
        if self._collapsed:
            self.setFixedWidth(52)
            self.updateGeometry()
            self._place_collapse()
            return
        hint = 0
        for widget in self._buttons.values():
            if widget.isHidden():
                continue
            hint = max(hint, widget.sizeHint().width())
        margins = self._root.contentsMargins()
        width = max(hint + margins.left() + margins.right(), 96)
        self.setFixedWidth(width)
        self.updateGeometry()
        self._place_collapse()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_collapse()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._place_collapse()

    def _place_collapse(self) -> None:
        x = self.width() - self._collapse.width()
        y = max(0, (self.height() - self._collapse.height()) // 2)
        self._collapse.move(x, y)
        self._collapse.raise_()
