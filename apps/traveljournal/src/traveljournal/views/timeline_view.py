"""Chronological trip overview. Originals are never written."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.timeline.types import TimelineDay, TimelineSnapshot
from traveljournal.services.workspace import Workspace


class TimelineView(QWidget):
    status_message = Signal(str)
    timeline_changed = Signal()

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._snapshot: TimelineSnapshot | None = None
        self._selected_day_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Timeline")
        title.setObjectName("pageTitle")
        self._subtitle = QLabel(
            "Tage entstehen automatisch aus der Aufnahmezeit. "
            "Orte und Übernachtungen setzt du im Tagebuch; "
            "Foto-, Video- und Trackpositionen bekommen keinen Ortsnamen. "
            "Manuelle Texte überschreibt die Automatik nicht."
        )
        self._subtitle.setObjectName("pageSubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(self._subtitle)

        toolbar = QHBoxLayout()
        refresh = QPushButton("Timeline aktualisieren")
        refresh.clicked.connect(self.rebuild)
        toolbar.addWidget(refresh)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.days = QListWidget()
        self.days.currentItemChanged.connect(self._on_day_changed)
        splitter.addWidget(self.days)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        self._detail_title = QLabel("Kein Tag gewählt")
        self._detail_title.setObjectName("pageTitle")
        self._detail_notes = QLabel("")
        self._detail_notes.setObjectName("pageSubtitle")
        self._detail_notes.setWordWrap(True)
        self.events = QListWidget()
        self.photos = QListWidget()
        self.photos.setIconSize(QSize(56, 56))
        self.places = QListWidget()
        self.stays = QListWidget()
        detail_layout.addWidget(self._detail_title)
        detail_layout.addWidget(self._detail_notes)
        detail_layout.addWidget(QLabel("Ereignisse"))
        detail_layout.addWidget(self.events)
        detail_layout.addWidget(QLabel("Medien"))
        detail_layout.addWidget(self.photos, 1)
        detail_layout.addWidget(QLabel("Orte"))
        detail_layout.addWidget(self.places)
        place_row = QHBoxLayout()
        confirm = QPushButton("Ort bestätigen…")
        confirm.clicked.connect(self._confirm_place)
        delete_place = QPushButton("Ort löschen")
        delete_place.clicked.connect(self._delete_place)
        place_row.addWidget(confirm)
        place_row.addWidget(delete_place)
        place_row.addStretch(1)
        detail_layout.addLayout(place_row)
        detail_layout.addWidget(QLabel("Übernachtungen"))
        detail_layout.addWidget(self.stays)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

    def rebuild(self) -> None:
        self.refresh(rebuild=True)
        self.timeline_changed.emit()

    def refresh(self, rebuild: bool = False) -> None:
        if self.workspace.current is None:
            self._snapshot = None
            self.days.clear()
            self._show_day(None)
            self._subtitle.setText("Bitte ein Projekt öffnen.")
            return
        try:
            if rebuild:
                snapshot = self.workspace.sync_timeline()
            else:
                snapshot = self.workspace.load_timeline()
                if snapshot is None:
                    snapshot = self.workspace.sync_timeline()
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self._snapshot = snapshot
        self._subtitle.setText(
            f"{snapshot.title}: {snapshot.day_count} Tage. Übernachtungen und Orte setzt du im Tagebuch."
        )
        self._fill_days()
        self.status_message.emit(f"Timeline: {snapshot.day_count} Tage")

    def _fill_days(self) -> None:
        self.days.blockSignals(True)
        self.days.clear()
        selected: QListWidgetItem | None = None
        for day in self._snapshot.days if self._snapshot is not None else ():
            item = QListWidgetItem(_day_summary(day))
            item.setData(Qt.ItemDataRole.UserRole, day.id)
            self.days.addItem(item)
            if self._selected_day_id == day.id:
                selected = item
        self.days.blockSignals(False)
        if selected is not None:
            self.days.setCurrentItem(selected)
        elif self.days.count():
            self.days.setCurrentRow(0)
        else:
            self._show_day(None)

    def _on_day_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None or self._snapshot is None:
            self._show_day(None)
            return
        day_id = current.data(Qt.ItemDataRole.UserRole)
        self._selected_day_id = int(day_id) if day_id is not None else None
        day = next((item for item in self._snapshot.days if item.id == self._selected_day_id), None)
        self._show_day(day)

    def _show_day(self, day: TimelineDay | None) -> None:
        self.events.clear()
        self.photos.clear()
        self.places.clear()
        self.stays.clear()
        if day is None:
            self._detail_title.setText("Kein Tag gewählt")
            self._detail_notes.setText("")
            return
        origin = "manuell" if day.origin == "manual" else "automatisch"
        title = day.title or "Ohne Titel"
        self._detail_title.setText(f"{title} ({origin})")
        notes = (day.notes or "").strip() or "Kein Text — Texte schreibst du im Tagebuch."
        self._detail_notes.setText(notes)
        for event in day.events:
            mark = "auto" if event.origin == "auto" else "manuell"
            self.events.addItem(f"{event.title} ({mark})")
        for photo in day.photos:
            text = photo.filename
            extras: list[str] = []
            if photo.used_in_journal:
                extras.append("Tagebuch")
            if photo.is_cover:
                extras.append("Titelbild")
            if extras:
                text = f"{text} · {' · '.join(extras)}"
            item = QListWidgetItem(text)
            if photo.thumbnail_path.is_file():
                pixmap = QPixmap(str(photo.thumbnail_path))
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap))
            self.photos.addItem(item)
        for place in day.places:
            state = "bestätigt" if place.confirmed else "Vorschlag"
            self.places.addItem(QListWidgetItem(f"{place.name} ({state})"))
            self.places.item(self.places.count() - 1).setData(Qt.ItemDataRole.UserRole, place.id)
        for stay in day.stays:
            where = f" · {stay.location_name}" if stay.location_name else ""
            self.stays.addItem(f"{stay.name}{where}")

    def _selected_place_id(self) -> int | None:
        item = self.places.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _confirm_place(self) -> None:
        place_id = self._selected_place_id()
        if place_id is None:
            QMessageBox.information(self, "Timeline", "Bitte einen Ort auswählen.")
            return
        current = self.places.currentItem()
        suggestion = current.text().rsplit(" (", 1)[0] if current is not None else ""
        name, accepted = QInputDialog.getText(self, "Ort bestätigen", "Name", text=suggestion)
        if not accepted:
            return
        try:
            self.workspace.confirm_place(place_id, name)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()

    def _delete_place(self) -> None:
        place_id = self._selected_place_id()
        if place_id is None:
            QMessageBox.information(self, "Timeline", "Bitte einen Ort auswählen.")
            return
        if (
            QMessageBox.question(self, "Ort löschen", "Diesen Ort wirklich löschen?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.workspace.delete_place(place_id)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()


def _day_summary(day: TimelineDay) -> str:
    date_text = day.date.strftime("%d.%m.%Y") if day.date is not None else "Ohne Datum"
    title = day.title or date_text
    bits = [f"{len(day.photos)} Medien"]
    if day.places:
        bits.append(f"{len(day.places)} Orte")
    if day.stays:
        bits.append(f"{len(day.stays)} Übernachtungen")
    return f"{title}\n{date_text} · {' · '.join(bits)}"
