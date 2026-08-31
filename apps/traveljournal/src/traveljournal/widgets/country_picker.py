"""Searchable multi-select for bundled ISO countries (flag + silhouette)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from travelcore.geo.catalog import Country, get_country, list_countries, resolve_countries, search_countries
from traveljournal.widgets.svg_pixmaps import svg_pixmap

_FLAG = QSize(28, 21)
_SHAPE = QSize(22, 18)
_INK = "#e8edf5"


class CountryPicker(QWidget):
    codes_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("countryPicker")
        self._codes: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("countrySearch")
        self.search.setPlaceholderText("Land suchen, z. B. Italien")
        names = [item.name_de for item in list_countries()]
        completer = QCompleter(names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.search.setCompleter(completer)
        add_btn = QPushButton("Hinzufügen")
        add_btn.setObjectName("countryAdd")
        add_btn.clicked.connect(self._add_from_field)
        self.search.returnPressed.connect(self._add_from_field)
        completer.activated.connect(self._add_named)
        row.addWidget(self.search, 1)
        row.addWidget(add_btn)
        root.addLayout(row)

        scroll = QScrollArea()
        scroll.setObjectName("countryList")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(96)
        scroll.setMaximumHeight(168)
        inner = QWidget()
        inner.setObjectName("countryListInner")
        self._list = QVBoxLayout(inner)
        self._list.setContentsMargins(8, 8, 8, 8)
        self._list.setSpacing(6)
        self._empty = QLabel("Noch keine Länder ausgewählt.")
        self._empty.setObjectName("pageSubtitle")
        self._empty.setWordWrap(True)
        self._list.addWidget(self._empty)
        self._list.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll)

    def codes(self) -> tuple[str, ...]:
        return tuple(self._codes)

    def set_codes(self, tokens: Sequence[str]) -> None:
        self._codes = [item.iso2 for item in resolve_countries(tokens)]
        self._rebuild()

    def _add_named(self, name: str) -> None:
        self._add_query(str(name))

    def _add_from_field(self) -> None:
        self._add_query(self.search.text())

    def _add_query(self, query: str) -> None:
        if not self.isEnabled():
            return
        matches = search_countries(query, limit=1)
        if not matches:
            return
        iso = matches[0].iso2
        if iso in self._codes:
            self.search.clear()
            return
        self._codes.append(iso)
        self.search.clear()
        self._rebuild()
        self.codes_changed.emit()

    def _remove(self, iso2: str) -> None:
        if iso2 not in self._codes:
            return
        self._codes = [item for item in self._codes if item != iso2]
        self._rebuild()
        self.codes_changed.emit()

    def _rebuild(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._codes:
            self._empty = QLabel("Noch keine Länder ausgewählt.")
            self._empty.setObjectName("pageSubtitle")
            self._empty.setWordWrap(True)
            self._list.addWidget(self._empty)
            self._list.addStretch(1)
            return
        for iso2 in self._codes:
            country = get_country(iso2)
            if country is None:
                continue
            self._list.addWidget(_SelectedRow(country, on_remove=self._remove))
        self._list.addStretch(1)


class _SelectedRow(QWidget):
    def __init__(self, country: Country, *, on_remove: Callable[[str], None]) -> None:
        super().__init__()
        self.setObjectName("countryRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        flag = QLabel()
        flag.setPixmap(svg_pixmap(country.flag_svg, _FLAG))
        flag.setFixedSize(_FLAG)
        shape = QLabel()
        shape.setPixmap(svg_pixmap(country.shape_svg, _SHAPE, fill=_INK))
        shape.setFixedSize(_SHAPE)
        name = QLabel(country.name_de)
        name.setObjectName("countryRowName")
        remove = QPushButton("Entfernen")
        remove.setObjectName("countryRemove")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda: on_remove(country.iso2))
        layout.addWidget(flag)
        layout.addWidget(shape)
        layout.addWidget(name, 1)
        layout.addWidget(remove)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
