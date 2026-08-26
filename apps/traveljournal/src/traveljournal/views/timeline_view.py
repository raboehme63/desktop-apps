"""Chronological trip overview. Originals are never written."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent, QTextOption
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.media.gallery import GalleryItem
from travelcore.timeline.types import TimelineDay, TimelinePhoto, TimelineSnapshot
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.gallery import GalleryView


class TimelineView(QWidget):
    status_message = Signal(str)
    timeline_changed = Signal()

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._snapshot: TimelineSnapshot | None = None
        self._blocks: list[DayEntryWidget] = []
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Timeline")
        title.setObjectName("pageTitle")
        self._subtitle = QLabel(
            "Alle Tage untereinander. Titel und Tagebucheintrag sind bearbeitbar "
            "und werden aus importierten Texten vorbefüllt. "
            "Manuelle Änderungen überschreibt die Automatik nicht."
        )
        self._subtitle.setObjectName("pageSubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(self._subtitle)

        toolbar = QHBoxLayout()
        refresh = QPushButton("Timeline aktualisieren")
        refresh.clicked.connect(self.rebuild)
        self._save_button = QPushButton("Speichern")
        self._save_button.setObjectName("primary")
        self._save_button.clicked.connect(self._on_save_clicked)
        toolbar.addWidget(refresh)
        toolbar.addStretch(1)
        toolbar.addWidget(self._save_button)
        root.addLayout(toolbar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 8, 0)
        self._host_layout.setSpacing(16)
        self._empty = QLabel("Bitte ein Projekt öffnen.")
        self._empty.setObjectName("pageSubtitle")
        self._empty.setWordWrap(True)
        self._host_layout.addWidget(self._empty)
        self._host_layout.addStretch(1)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, 1)
        self._save_button.setEnabled(False)

    def rebuild(self) -> None:
        self.refresh(rebuild=True)
        self.timeline_changed.emit()

    def refresh(self, rebuild: bool = False) -> None:
        self._commit_if_dirty()
        if self.workspace.current is None:
            self._snapshot = None
            self._fill_days()
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
            f"{snapshot.title}: {snapshot.day_count} Tage untereinander. "
            "Titel und Text aus Notizen vorbefüllt, Medien als Vorschau."
        )
        self._fill_days()
        self.status_message.emit(f"Timeline: {snapshot.day_count} Tage")

    def clear(self) -> None:
        self._snapshot = None
        self._fill_days()
        self._subtitle.setText(
            "Index wird geladen…" if self.workspace.current is not None else "Bitte ein Projekt öffnen."
        )

    def _fill_days(self) -> None:
        self._loading = True
        scroll = self._scroll.verticalScrollBar().value()
        for block in self._blocks:
            self._host_layout.removeWidget(block)
            block.deleteLater()
        self._blocks.clear()
        days = self._snapshot.days if self._snapshot is not None else ()
        if not days:
            self._empty.setVisible(True)
            if self.workspace.current is None:
                self._empty.setText("Bitte ein Projekt öffnen.")
            elif self._snapshot is None:
                self._empty.setText("Index wird geladen…")
            else:
                self._empty.setText("Keine Tage in der Timeline.")
            self._save_button.setEnabled(False)
            self._loading = False
            return
        self._empty.setVisible(False)
        insert_at = max(self._host_layout.count() - 1, 0)
        for day in days:
            block = DayEntryWidget(day)
            self._blocks.append(block)
            self._host_layout.insertWidget(insert_at, block)
            insert_at += 1
        self._save_button.setEnabled(True)
        self._loading = False
        self._scroll.verticalScrollBar().setValue(scroll)

    def _commit_if_dirty(self) -> bool:
        if self._loading:
            return True
        dirty = [block for block in self._blocks if block.is_dirty()]
        if not dirty:
            return True
        try:
            for block in dirty:
                day_id, title, notes = block.values()
                self.workspace.save_day_text(day_id, title=title, notes=notes)
                block.mark_clean()
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return False
        return True

    def _on_save_clicked(self) -> None:
        if not self._blocks:
            QMessageBox.information(self, "Timeline", "Keine Tage zum Speichern.")
            return
        if not self._commit_if_dirty():
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Tagebuch gespeichert.")


class DayEntryWidget(QFrame):
    def __init__(self, day: TimelineDay, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._day_id = day.id
        self._loaded_title = day.title or ""
        self._loaded_notes = day.notes or ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        date_text = day.date.strftime("%d.%m.%Y") if day.date is not None else "Ohne Datum"
        origin = "manuell" if day.origin == "manual" else "automatisch"
        heading = QLabel(f"{date_text} · {origin}")
        heading.setObjectName("pageSubtitle")
        self.title_edit = QLineEdit(self._loaded_title)
        self.title_edit.setPlaceholderText("Titel des Tages")
        self.notes_edit = QPlainTextEdit(self._loaded_notes)
        self.notes_edit.setPlaceholderText("Tagebucheintrag — aus importierten Texten vorbefüllt")
        self.notes_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.notes_edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.notes_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.notes_edit.textChanged.connect(self._fit_notes)
        media_count = len(day.photos)
        media_label = QLabel("Keine Medien" if media_count == 0 else f"Medien ({media_count})")
        media_label.setObjectName("pageSubtitle")
        self.gallery = GalleryView()
        self.gallery.set_expand_to_fit(True)
        self.gallery.set_items([_gallery_item(photo) for photo in day.photos])
        self.gallery.setVisible(media_count > 0)

        layout.addWidget(heading)
        layout.addWidget(QLabel("Titel des Tages"))
        layout.addWidget(self.title_edit)
        layout.addWidget(QLabel("Tagebucheintrag"))
        layout.addWidget(self.notes_edit)
        layout.addWidget(media_label)
        if media_count:
            layout.addWidget(self.gallery)
        self._fit_notes()

    def values(self) -> tuple[int, str, str]:
        return self._day_id, self.title_edit.text(), self.notes_edit.toPlainText()

    def is_dirty(self) -> bool:
        return (
            self.title_edit.text() != self._loaded_title
            or self.notes_edit.toPlainText() != self._loaded_notes
        )

    def mark_clean(self) -> None:
        self._loaded_title = self.title_edit.text()
        self._loaded_notes = self.notes_edit.toPlainText()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_notes()

    def _fit_notes(self) -> None:
        document = self.notes_edit.document()
        document.setTextWidth(max(self.notes_edit.viewport().width(), 100))
        margins = self.notes_edit.contentsMargins()
        height = int(document.size().height()) + margins.top() + margins.bottom() + 16
        self.notes_edit.setFixedHeight(max(88, height))


def _gallery_item(photo: TimelinePhoto) -> GalleryItem:
    return GalleryItem(
        source_file_id=photo.source_file_id,
        path=photo.path,
        filename=photo.filename,
        extension=Path(photo.filename).suffix,
        captured_at=photo.captured_at,
        timezone_unknown=True,
        gps_latitude=photo.gps_latitude,
        gps_longitude=photo.gps_longitude,
        camera=None,
        is_favorite=photo.is_favorite,
        used_in_journal=photo.used_in_journal,
        thumbnail_path=photo.thumbnail_path,
    )
