"""Medien filter panel: quality, date range, rating (multi-select)."""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from travelcore.image_analysis.quality import QUALITY_GREEN, QUALITY_RED, QUALITY_YELLOW
from travelcore.media.gallery import (
    SORT_FAVORITE,
    SORT_REJECTED,
    SORT_RESERVE,
    GalleryItem,
    effective_sort_status,
)

QUALITY_NONE = "none"
RATING_NONE = "none"

QUALITY_CHOICES = (
    (QUALITY_GREEN, "Grün"),
    (QUALITY_YELLOW, "Gelb"),
    (QUALITY_RED, "Rot"),
    (QUALITY_NONE, "Ohne Ampel"),
)
RATING_CHOICES = (
    (SORT_FAVORITE, "Favorit"),
    (SORT_RESERVE, "Reserve"),
    (SORT_REJECTED, "Aussortiert"),
    (RATING_NONE, "Ohne Bewertung"),
)


def quality_key(item: GalleryItem) -> str:
    return item.quality_light or QUALITY_NONE


def rating_key(item: GalleryItem) -> str:
    return effective_sort_status(item.sort_status, item.is_favorite) or RATING_NONE


def matches_quality_filter(item: GalleryItem, selected: frozenset[str]) -> bool:
    return not selected or quality_key(item) in selected


def matches_rating_filter(item: GalleryItem, selected: frozenset[str]) -> bool:
    return not selected or rating_key(item) in selected


def matches_date_range(
    item: GalleryItem,
    start: date | None,
    end: date | None,
) -> bool:
    if start is None and end is None:
        return True
    captured = item.captured_at
    if captured is None:
        return False
    day = captured.date() if isinstance(captured, datetime) else captured
    if start is not None and day < start:
        return False
    return end is None or day <= end


class MediaFilterPanel(QWidget):
    changed = Signal()
    range_opened = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mediaFilterPanel")
        self._quality: dict[str, QCheckBox] = {}
        self._ratings: dict[str, QCheckBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 8)
        root.setSpacing(10)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._quality_box(), 1)
        columns.addWidget(self._date_box(), 1)
        columns.addWidget(self._rating_box(), 1)
        root.addLayout(columns)
        actions = QHBoxLayout()
        actions.addStretch(1)
        reset = QPushButton("Filter zurücksetzen")
        reset.clicked.connect(self.reset)
        actions.addWidget(reset)
        root.addLayout(actions)

    def quality_selected(self) -> frozenset[str]:
        return frozenset(key for key, box in self._quality.items() if box.isChecked())

    def rating_selected(self) -> frozenset[str]:
        return frozenset(key for key, box in self._ratings.items() if box.isChecked())

    def date_range(self) -> tuple[date | None, date | None]:
        if not self._range.isChecked():
            return None, None
        start = _date_from_edit(self._from)
        end = _date_from_edit(self._until)
        if start > end:
            start, end = end, start
        return start, end

    def is_active(self) -> bool:
        start, end = self.date_range()
        return bool(self.quality_selected() or self.rating_selected() or start or end)

    def button_label(self) -> str:
        parts: list[str] = []
        if self.quality_selected():
            parts.append("Qualität")
        if self.date_range()[0] is not None:
            parts.append("Datum")
        if self.rating_selected():
            parts.append("Bewertung")
        if not parts:
            return "Filtern"
        return "Filtern · " + ", ".join(parts)

    def set_span(self, start: date, end: date) -> None:
        self._from.blockSignals(True)
        self._until.blockSignals(True)
        self._from.setDate(QDate(start.year, start.month, start.day))
        self._until.setDate(QDate(end.year, end.month, end.day))
        self._from.blockSignals(False)
        self._until.blockSignals(False)

    def reset(self) -> None:
        for box in (*self._quality.values(), *self._ratings.values()):
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self._range.blockSignals(True)
        self._range.setChecked(False)
        self._range.blockSignals(False)
        self._sync_dates()
        self.changed.emit()

    def _quality_box(self) -> QGroupBox:
        box = QGroupBox("Qualität")
        grid = QGridLayout(box)
        for index, (key, label) in enumerate(QUALITY_CHOICES):
            check = QCheckBox(label)
            check.toggled.connect(self._emit_changed)
            self._quality[key] = check
            grid.addWidget(check, index // 2, index % 2)
        return box

    def _date_box(self) -> QGroupBox:
        box = QGroupBox("Datum")
        layout = QVBoxLayout(box)
        self._range = QCheckBox("Zeitraum")
        self._range.toggled.connect(self._on_range_toggled)
        layout.addWidget(self._range)
        row = QHBoxLayout()
        row.addWidget(QLabel("Von"))
        self._from = QDateEdit()
        _configure_date_edit(self._from)
        self._from.dateChanged.connect(self._emit_changed)
        row.addWidget(self._from, 1)
        row.addWidget(QLabel("Bis"))
        self._until = QDateEdit()
        _configure_date_edit(self._until)
        self._until.dateChanged.connect(self._emit_changed)
        row.addWidget(self._until, 1)
        layout.addLayout(row)
        self._sync_dates()
        return box

    def _rating_box(self) -> QGroupBox:
        box = QGroupBox("Bewertung")
        grid = QGridLayout(box)
        for index, (key, label) in enumerate(RATING_CHOICES):
            check = QCheckBox(label)
            check.toggled.connect(self._emit_changed)
            self._ratings[key] = check
            grid.addWidget(check, index // 2, index % 2)
        return box

    def _emit_changed(self, *_args: object) -> None:
        self.changed.emit()

    def _on_range_toggled(self, checked: bool) -> None:
        self._sync_dates()
        if checked:
            self.range_opened.emit()
        self.changed.emit()

    def _sync_dates(self) -> None:
        enabled = self._range.isChecked()
        self._from.setEnabled(enabled)
        self._until.setEnabled(enabled)


def _date_from_edit(edit: QDateEdit) -> date:
    chosen = edit.date()
    return date(chosen.year(), chosen.month(), chosen.day())


def _configure_date_edit(edit: QDateEdit) -> None:
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy")
    today = QDate.currentDate()
    edit.setDate(today)
    edit.setMinimumWidth(140)
    edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
