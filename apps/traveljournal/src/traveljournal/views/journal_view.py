"""Editable journal: day texts, photo inclusion, overnight stays."""

from __future__ import annotations

from typing import TypedDict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.media.types import FileKind
from travelcore.timeline.links import normalize_leonardo_url, parse_youtube_urls, serialize_youtube_urls
from travelcore.timeline.types import TimelineDay, TimelineSnapshot
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.entry_links import (
    LeonardoLinksDialog,
    YouTubeLinksDialog,
    YouTubeThumbsRow,
    igc_flights,
    links_html,
)


class OvernightStayValues(TypedDict):
    name: str
    location_name: str | None
    latitude: float | None
    longitude: float | None
    description: str | None


class JournalView(QWidget):
    status_message = Signal(str)
    timeline_changed = Signal()

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._snapshot: TimelineSnapshot | None = None
        self._selected_day_id: int | None = None
        self._pending_youtube: dict[int, list[str]] = {}
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Tagebuch")
        title.setObjectName("pageTitle")
        self._subtitle = QLabel(
            "Texte und Titelbilder gelten als manuell. Die Automatik überschreibt sie nicht. "
            "Fotos gehören über die Aufnahmezeit zu einem Kalendertag; "
            "Häkchen steuern nur die Tagebuch-Nutzung."
        )
        self._subtitle.setObjectName("pageSubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(self._subtitle)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.days = QListWidget()
        self.days.currentItemChanged.connect(self._on_day_changed)
        splitter.addWidget(self.days)

        editor = QWidget()
        layout = QVBoxLayout(editor)
        layout.setContentsMargins(8, 0, 0, 0)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Titel des Tages")
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Tagebuchtext für diesen Tag")
        save = QPushButton("Tag speichern")
        save.clicked.connect(self._save_day)
        layout.addWidget(QLabel("Titel"))
        layout.addWidget(self.title_edit)
        text_row = QHBoxLayout()
        text_row.addWidget(QLabel("Text"), 1)
        self._menu_button = QToolButton()
        self._menu_button.setObjectName("entryMenu")
        self._menu_button.setText("⋯")
        self._entry_menu = QMenu(self)
        youtube_action = self._entry_menu.addAction("YouTube-Links…")
        youtube_action.triggered.connect(self._edit_youtube)
        self._leonardo_action = self._entry_menu.addAction("DHV-Leonardo…")
        self._leonardo_action.triggered.connect(self._edit_leonardo)
        self._menu_button.clicked.connect(self._popup_entry_menu)
        text_row.addWidget(self._menu_button)
        layout.addLayout(text_row)
        layout.addWidget(self.notes_edit, 1)
        self.youtube_thumbs = YouTubeThumbsRow()
        layout.addWidget(self.youtube_thumbs)
        self.links_label = QLabel()
        self.links_label.setObjectName("pageSubtitle")
        self.links_label.setWordWrap(True)
        self.links_label.setOpenExternalLinks(True)
        self.links_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.links_label)
        layout.addWidget(save)

        layout.addWidget(QLabel("Fotos in diesem Tag"))
        self.photos = QListWidget()
        self.photos.itemChanged.connect(self._on_photo_toggled)
        layout.addWidget(self.photos, 1)
        photo_row = QHBoxLayout()
        include = QPushButton("Alle ins Tagebuch")
        include.clicked.connect(lambda: self._set_day_photos(True))
        exclude = QPushButton("Alle entfernen")
        exclude.clicked.connect(lambda: self._set_day_photos(False))
        cover = QPushButton("Als Titelbild")
        cover.clicked.connect(self._set_cover)
        photo_row.addWidget(include)
        photo_row.addWidget(exclude)
        photo_row.addWidget(cover)
        photo_row.addStretch(1)
        layout.addLayout(photo_row)

        self._tracks_label = QLabel("Tracks")
        self.tracks = QListWidget()
        layout.addWidget(self._tracks_label)
        layout.addWidget(self.tracks)

        layout.addWidget(QLabel("Übernachtungen"))
        self.stays = QListWidget()
        layout.addWidget(self.stays)
        stay_row = QHBoxLayout()
        add_stay = QPushButton("Übernachtung hinzufügen…")
        add_stay.clicked.connect(self._add_stay)
        delete_stay = QPushButton("Übernachtung löschen")
        delete_stay.clicked.connect(self._delete_stay)
        stay_row.addWidget(add_stay)
        stay_row.addWidget(delete_stay)
        stay_row.addStretch(1)
        layout.addLayout(stay_row)

        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

    def rebuild(self) -> None:
        self.refresh(rebuild=True)
        self.timeline_changed.emit()

    def refresh(self, rebuild: bool = False) -> None:
        if self.workspace.current is None:
            self._snapshot = None
            self._pending_youtube.clear()
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
            QMessageBox.warning(self, "Tagebuch", str(exc))
            return
        self._snapshot = snapshot
        used = sum(1 for day in snapshot.days for photo in day.photos if photo.used_in_journal)
        self._subtitle.setText(
            f"{snapshot.day_count} Tage, {used} Fotos im Tagebuch. Speichern setzt origin=manual."
        )
        self._fill_days()
        self.status_message.emit(f"Tagebuch: {snapshot.day_count} Tage")

    def clear(self) -> None:
        self._snapshot = None
        self._selected_day_id = None
        self._pending_youtube.clear()
        self.days.clear()
        self._show_day(None)
        self._subtitle.setText(
            "Index wird geladen…" if self.workspace.current is not None else "Bitte ein Projekt öffnen."
        )

    def _fill_days(self) -> None:
        self.days.blockSignals(True)
        self.days.clear()
        selected: QListWidgetItem | None = None
        for day in self._snapshot.days if self._snapshot is not None else ():
            item = QListWidgetItem(_day_label(day))
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

    def _current_day(self) -> TimelineDay | None:
        if self._snapshot is None or self._selected_day_id is None:
            return None
        return next((item for item in self._snapshot.days if item.id == self._selected_day_id), None)

    def _show_day(self, day: TimelineDay | None) -> None:
        self._loading = True
        self.photos.blockSignals(True)
        self.photos.clear()
        self.tracks.clear()
        self.stays.clear()
        if day is None:
            self.title_edit.clear()
            self.notes_edit.clear()
            self.title_edit.setEnabled(False)
            self.notes_edit.setEnabled(False)
            self._menu_button.setEnabled(False)
            self._leonardo_action.setEnabled(False)
            self.youtube_thumbs.set_urls(())
            self.links_label.clear()
            self.links_label.hide()
            self._tracks_label.hide()
            self.tracks.hide()
            self.photos.blockSignals(False)
            self._loading = False
            return
        self.title_edit.setEnabled(True)
        self.notes_edit.setEnabled(True)
        self._menu_button.setEnabled(True)
        self._leonardo_action.setEnabled(True)
        self.title_edit.setText(day.title or "")
        self.notes_edit.setPlainText(day.notes or "")
        self._refresh_links(day)
        for photo in day.photos:
            if photo.file_kind == FileKind.GPS.value:
                self.tracks.addItem(photo.filename)
                continue
            text = photo.filename
            if photo.is_cover:
                text += " · Titelbild"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, photo.source_file_id)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Checked if photo.used_in_journal else Qt.CheckState.Unchecked)
            self.photos.addItem(item)
        has_tracks = self.tracks.count() > 0
        self._tracks_label.setVisible(has_tracks)
        self.tracks.setVisible(has_tracks)
        for stay in day.stays:
            where = f" · {stay.location_name}" if stay.location_name else ""
            item = QListWidgetItem(f"{stay.name}{where}")
            item.setData(Qt.ItemDataRole.UserRole, stay.id)
            self.stays.addItem(item)
        self.photos.blockSignals(False)
        self._loading = False

    def _youtube_for_day(self, day: TimelineDay) -> list[str]:
        if day.id in self._pending_youtube:
            return list(self._pending_youtube[day.id])
        return list(day.youtube_urls)

    def _refresh_links(self, day: TimelineDay) -> None:
        youtube = self._youtube_for_day(day)
        self.youtube_thumbs.set_urls(youtube)
        text = links_html((), igc_flights(day.photos), day.leonardo_urls)
        self.links_label.setText(text)
        self.links_label.setVisible(bool(text))

    def _popup_entry_menu(self) -> None:
        self._entry_menu.exec(self._menu_button.mapToGlobal(self._menu_button.rect().bottomLeft()))

    def _edit_youtube(self) -> None:
        day = self._current_day()
        if day is None:
            return
        dialog = YouTubeLinksDialog(self._youtube_for_day(day), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            stored = serialize_youtube_urls(dialog.urls())
        except ProjectError as exc:
            QMessageBox.warning(self, "YouTube-Links", str(exc))
            return
        self._pending_youtube[day.id] = list(parse_youtube_urls(stored))
        self._refresh_links(day)

    def _edit_leonardo(self) -> None:
        day = self._current_day()
        if day is None:
            return
        flights = igc_flights(day.photos)
        dialog = LeonardoLinksDialog(flights, day.leonardo_urls, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            igc_urls = {
                source_id: (normalize_leonardo_url(url) if url else "")
                for source_id, url in dialog.values().items()
            }
            for source_id, url in igc_urls.items():
                self.workspace.set_gps_track_url(source_id, url or None)
            self.workspace.save_leonardo_urls("day", day.id, dialog.extra_urls())
        except (ProjectError, ValueError) as exc:
            QMessageBox.warning(self, "DHV-Leonardo", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()

    def _save_day(self) -> None:
        if self._selected_day_id is None:
            QMessageBox.information(self, "Tagebuch", "Bitte zuerst einen Tag wählen.")
            return
        try:
            self.workspace.save_day_text(
                self._selected_day_id,
                title=self.title_edit.text(),
                notes=self.notes_edit.toPlainText(),
            )
            pending = self._pending_youtube.get(self._selected_day_id)
            if pending is not None:
                self.workspace.save_youtube_urls("day", self._selected_day_id, pending)
                del self._pending_youtube[self._selected_day_id]
        except ProjectError as exc:
            QMessageBox.warning(self, "Tagebuch", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Tag gespeichert (origin=manual).")

    def _on_photo_toggled(self, item: QListWidgetItem) -> None:
        if self._loading:
            return
        source_id = item.data(Qt.ItemDataRole.UserRole)
        if source_id is None:
            return
        used = item.checkState() == Qt.CheckState.Checked
        try:
            self.workspace.set_photo_in_journal(int(source_id), used)
        except ProjectError as exc:
            QMessageBox.warning(self, "Tagebuch", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()

    def _set_day_photos(self, used: bool) -> None:
        day = self._current_day()
        if day is None:
            return
        try:
            for photo in day.photos:
                if photo.file_kind == FileKind.GPS.value:
                    continue
                self.workspace.set_photo_in_journal(photo.source_file_id, used)
        except ProjectError as exc:
            QMessageBox.warning(self, "Tagebuch", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()

    def _set_cover(self) -> None:
        item = self.photos.currentItem()
        if item is None:
            QMessageBox.information(self, "Tagebuch", "Bitte ein Foto auswählen.")
            return
        source_id = item.data(Qt.ItemDataRole.UserRole)
        if source_id is None:
            return
        try:
            self.workspace.set_cover_photo(int(source_id))
        except ProjectError as exc:
            QMessageBox.warning(self, "Tagebuch", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()

    def _add_stay(self) -> None:
        if self._selected_day_id is None:
            QMessageBox.information(self, "Tagebuch", "Bitte zuerst einen Tag wählen.")
            return
        dialog = OvernightStayDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dialog.values()
        if payload is None:
            QMessageBox.warning(self, "Tagebuch", "Koordinaten müssen Zahlen sein.")
            return
        try:
            self.workspace.add_overnight_stay(
                self._selected_day_id,
                name=payload["name"],
                location_name=payload["location_name"],
                latitude=payload["latitude"],
                longitude=payload["longitude"],
                description=payload["description"],
            )
        except ProjectError as exc:
            QMessageBox.warning(self, "Tagebuch", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()

    def _delete_stay(self) -> None:
        item = self.stays.currentItem()
        if item is None:
            QMessageBox.information(self, "Tagebuch", "Bitte eine Übernachtung auswählen.")
            return
        stay_id = item.data(Qt.ItemDataRole.UserRole)
        if stay_id is None:
            return
        if (
            QMessageBox.question(self, "Übernachtung löschen", "Diese Übernachtung wirklich löschen?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.workspace.delete_overnight_stay(int(stay_id))
        except ProjectError as exc:
            QMessageBox.warning(self, "Tagebuch", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()


class OvernightStayDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Übernachtung")
        layout = QFormLayout(self)
        self.name = QLineEdit("Übernachtung")
        self.location = QLineEdit()
        self.latitude = QLineEdit()
        self.longitude = QLineEdit()
        self.description = QPlainTextEdit()
        self.latitude.setPlaceholderText("z. B. 46.5")
        self.longitude.setPlaceholderText("z. B. 11.35")
        layout.addRow("Name", self.name)
        layout.addRow("Ort", self.location)
        layout.addRow("Breite", self.latitude)
        layout.addRow("Länge", self.longitude)
        layout.addRow("Beschreibung", self.description)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> OvernightStayValues | None:
        try:
            latitude = _parse_coord(self.latitude.text())
            longitude = _parse_coord(self.longitude.text())
        except ValueError:
            return None
        return OvernightStayValues(
            name=self.name.text(),
            location_name=self.location.text() or None,
            latitude=latitude,
            longitude=longitude,
            description=self.description.toPlainText() or None,
        )


def _parse_coord(text: str) -> float | None:
    raw = text.strip().replace(",", ".")
    if not raw:
        return None
    return float(raw)


def _day_label(day: TimelineDay) -> str:
    date_text = day.date.strftime("%d.%m.%Y") if day.date is not None else "Ohne Datum"
    title = day.title or date_text
    used = sum(1 for photo in day.photos if photo.used_in_journal)
    return f"{title}\n{date_text} · {used}/{len(day.photos)} im Tagebuch"
