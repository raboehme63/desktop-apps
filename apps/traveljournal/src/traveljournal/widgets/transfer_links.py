"""Ordered connection-line editor on a Transfer timeline card."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from travelcore.timeline.symbols import TRANSPORT_SYMBOLS
from travelcore.timeline.transfer_links import (
    LINK_DASH_SOLID,
    LINK_GEOMETRY_ARC,
    LINK_GEOMETRY_LINE,
    LINK_GEOMETRY_ROUTE,
    LINK_GEOMETRY_TRACK,
)
from travelcore.timeline.types import TimelineLink

_GEOMETRY_LABELS = (
    (LINK_GEOMETRY_LINE, "Linie"),
    (LINK_GEOMETRY_TRACK, "Track"),
    (LINK_GEOMETRY_ARC, "Bogenlinie"),
    (LINK_GEOMETRY_ROUTE, "Route"),
)
_SYMBOL_LABELS = (("", "Symbol"),) + tuple((item.key, item.label) for item in TRANSPORT_SYMBOLS)


class TransferLinkStrip(QWidget):
    """List of connection lines. Drag reorders. Track combo uses section GPX only."""

    links_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transferLinkStrip")
        self._tracks: list[tuple[int, str]] = []
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        caption = QLabel("Verbindungslinien", self)
        caption.setObjectName("fieldCaption")
        self._list = QListWidget(self)
        self._list.setObjectName("transferLinkList")
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setAcceptDrops(True)
        model = self._list.model()
        if model is not None:
            model.rowsMoved.connect(self._on_rows_moved)
        add = QPushButton("Linie hinzufügen", self)
        add.setObjectName("transferLinkAdd")
        add.clicked.connect(self._add_row)
        layout.addWidget(caption)
        layout.addWidget(self._list)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)

    def set_tracks(self, tracks: list[tuple[int, str]]) -> None:
        self._tracks = list(tracks)
        for row in self._rows():
            row.set_tracks(self._tracks, self._claimed_tracks(except_row=row))

    def set_links(self, links: tuple[TimelineLink, ...] | list[TimelineLink]) -> None:
        self._loading = True
        self._list.clear()
        for link in links:
            self._insert_row(link)
        if self._list.count() == 0:
            self._insert_row(
                TimelineLink(id=0, sort_index=0, geometry=LINK_GEOMETRY_LINE, dash=LINK_DASH_SOLID)
            )
        self._loading = False
        self._refresh_joints()
        self._fit_list()

    def links(self) -> list[TimelineLink]:
        return [row.to_link(index) for index, row in enumerate(self._rows())]

    def _rows(self) -> list[TransferLinkRow]:
        found: list[TransferLinkRow] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            widget = self._list.itemWidget(item) if item is not None else None
            if isinstance(widget, TransferLinkRow):
                found.append(widget)
        return found

    def _insert_row(self, link: TimelineLink) -> TransferLinkRow:
        item = QListWidgetItem(self._list)
        row = TransferLinkRow(link, self._tracks, self)
        row.changed.connect(self._on_row_changed)
        row.remove_requested.connect(lambda widget=row: self._remove_row(widget))
        item.setSizeHint(row.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, row)
        return row

    def _add_row(self) -> None:
        self._insert_row(
            TimelineLink(
                id=0,
                sort_index=self._list.count(),
                geometry=LINK_GEOMETRY_LINE,
                dash=LINK_DASH_SOLID,
            )
        )
        self._refresh_joints()
        self._fit_list()
        self._emit_changed()

    def _remove_row(self, row: TransferLinkRow) -> None:
        if self._list.count() <= 1:
            row.reset_empty()
            self._emit_changed()
            return
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is not None and self._list.itemWidget(item) is row:
                self._list.takeItem(index)
                break
        self._refresh_joints()
        self._fit_list()
        self._emit_changed()

    def _on_rows_moved(self, *_args: object) -> None:
        self._refresh_joints()
        self._emit_changed()

    def _on_row_changed(self) -> None:
        for row in self._rows():
            row.set_tracks(self._tracks, self._claimed_tracks(except_row=row))
        self._refresh_joints()
        self._emit_changed()

    def _claimed_tracks(self, *, except_row: TransferLinkRow | None) -> set[int]:
        claimed: set[int] = set()
        for row in self._rows():
            if row is except_row:
                continue
            track_id = row.track_id()
            if track_id is not None:
                claimed.add(track_id)
        return claimed

    def _refresh_joints(self) -> None:
        rows = self._rows()
        for index, row in enumerate(rows):
            row.set_joint_visible(index < len(rows) - 1 and row.needs_joint())
            item = self._list.item(index)
            if item is not None:
                item.setSizeHint(row.sizeHint())

    def _fit_list(self) -> None:
        height = 4
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is not None:
                height += item.sizeHint().height() + 2
        self._list.setFixedHeight(max(height, 36))

    def _emit_changed(self) -> None:
        if not self._loading:
            self.links_changed.emit()


class TransferLinkRow(QWidget):
    changed = Signal()
    remove_requested = Signal()

    def __init__(
        self,
        link: TimelineLink,
        tracks: list[tuple[int, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._loading = True
        self._link_id = link.id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        handle = QLabel("⋮⋮", self)
        handle.setToolTip("Ziehen, um die Reihenfolge zu ändern")
        self.geometry = QComboBox(self)
        for value, label in _GEOMETRY_LABELS:
            self.geometry.addItem(label, value)
        self._disable_route()
        self.symbol = QComboBox(self)
        for value, label in _SYMBOL_LABELS:
            self.symbol.addItem(label, value)
        self.track = QComboBox(self)
        self.track.setMinimumWidth(140)
        remove = QToolButton(self)
        remove.setText("–")
        remove.setToolTip("Linie entfernen")
        remove.clicked.connect(self.remove_requested.emit)
        top.addWidget(handle, 0)
        top.addWidget(self.geometry, 0)
        top.addWidget(self.symbol, 0)
        top.addWidget(self.track, 1)
        top.addWidget(remove, 0)
        joint = QHBoxLayout()
        joint.setContentsMargins(18, 0, 0, 0)
        joint.setSpacing(6)
        self._joint_label = QLabel("Gelenk", self)
        self.end_lat = QLineEdit(self)
        self.end_lat.setPlaceholderText("Breite")
        self.end_lon = QLineEdit(self)
        self.end_lon.setPlaceholderText("Länge")
        joint.addWidget(self._joint_label)
        joint.addWidget(self.end_lat, 1)
        joint.addWidget(self.end_lon, 1)
        layout.addLayout(top)
        layout.addLayout(joint)
        self.set_tracks(tracks, set())
        self._apply_link(link)
        self.geometry.currentIndexChanged.connect(self._on_geometry)
        self.symbol.currentIndexChanged.connect(self._emit)
        self.track.currentIndexChanged.connect(self._emit)
        self.end_lat.editingFinished.connect(self._emit)
        self.end_lon.editingFinished.connect(self._emit)
        self._loading = False
        self._on_geometry()

    def _disable_route(self) -> None:
        index = self.geometry.findData(LINK_GEOMETRY_ROUTE)
        model = self.geometry.model()
        if index < 0 or model is None or not hasattr(model, "item"):
            return
        item = model.item(index)
        if item is not None:
            item.setEnabled(False)
            item.setToolTip("Route kommt später")

    def _apply_link(self, link: TimelineLink) -> None:
        geometry = link.geometry if link.geometry != LINK_GEOMETRY_ROUTE else LINK_GEOMETRY_LINE
        self.geometry.setCurrentIndex(max(0, self.geometry.findData(geometry)))
        self.symbol.setCurrentIndex(max(0, self.symbol.findData(link.symbol or "")))
        if link.track_source_file_id is not None:
            self.track.setCurrentIndex(max(0, self.track.findData(link.track_source_file_id)))
        if link.end_latitude is not None:
            self.end_lat.setText(f"{link.end_latitude:.5f}")
        if link.end_longitude is not None:
            self.end_lon.setText(f"{link.end_longitude:.5f}")

    def reset_empty(self) -> None:
        self._loading = True
        self.geometry.setCurrentIndex(self.geometry.findData(LINK_GEOMETRY_LINE))
        self.symbol.setCurrentIndex(0)
        self.track.setCurrentIndex(0)
        self.end_lat.clear()
        self.end_lon.clear()
        self._link_id = 0
        self._loading = False
        self._on_geometry()

    def set_tracks(self, tracks: list[tuple[int, str]], claimed: set[int]) -> None:
        current = self.track.currentData()
        self.track.blockSignals(True)
        self.track.clear()
        self.track.addItem("Spur wählen", None)
        for source_id, name in tracks:
            self.track.addItem(name, source_id)
            index = self.track.count() - 1
            if source_id in claimed and source_id != current:
                model = self.track.model()
                if model is not None and hasattr(model, "item"):
                    item = model.item(index)
                    if item is not None:
                        item.setEnabled(False)
        if current is not None:
            self.track.setCurrentIndex(max(0, self.track.findData(current)))
        self.track.blockSignals(False)

    def set_joint_visible(self, visible: bool) -> None:
        self._joint_label.setVisible(visible)
        self.end_lat.setVisible(visible)
        self.end_lon.setVisible(visible)

    def needs_joint(self) -> bool:
        geometry = str(self.geometry.currentData() or LINK_GEOMETRY_LINE)
        return geometry in {LINK_GEOMETRY_LINE, LINK_GEOMETRY_ARC, LINK_GEOMETRY_ROUTE}

    def track_id(self) -> int | None:
        if str(self.geometry.currentData()) != LINK_GEOMETRY_TRACK:
            return None
        value = self.track.currentData()
        return int(value) if isinstance(value, int) else None

    def to_link(self, sort_index: int) -> TimelineLink:
        lat = _parse_coord(self.end_lat.text(), 90.0)
        lon = _parse_coord(self.end_lon.text(), 180.0)
        symbol = str(self.symbol.currentData() or "") or None
        geometry = str(self.geometry.currentData() or LINK_GEOMETRY_LINE)
        return TimelineLink(
            id=self._link_id,
            sort_index=sort_index,
            geometry=geometry,
            dash=LINK_DASH_SOLID,
            symbol=symbol,
            end_latitude=lat,
            end_longitude=lon,
            track_source_file_id=self.track_id(),
        )

    def _on_geometry(self) -> None:
        track = str(self.geometry.currentData()) == LINK_GEOMETRY_TRACK
        self.track.setVisible(track)
        self._emit()

    def _emit(self) -> None:
        if not self._loading:
            self.changed.emit()


def _parse_coord(raw: str, limit: float) -> float | None:
    text = raw.strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if abs(value) > limit:
        return None
    return value
