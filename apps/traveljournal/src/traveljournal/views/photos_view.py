"""Chronological thumbnail gallery with filters. Originals are only read."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from travelcore.media.gallery import GalleryItem
from traveljournal.services.workers import ThumbnailRunnable
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.gallery import GalleryView

_JPEG = {".jpg", ".jpeg"}
_HEIC = {".heic", ".heif"}
_RAW = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2"}


class PhotosView(QWidget):
    status_message = Signal(str)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._items: list[GalleryItem] = []
        self._pool = QThreadPool.globalInstance()
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Fotos")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Chronologische Galerie aus gecachten Vorschaubildern. Originale bleiben unverändert. "
            "Qualität und Dubletten folgen in späteren Phasen."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Dateiname suchen")
        self.search.textChanged.connect(self._apply_filters)
        self.place = QComboBox()
        self.place.addItems(["Alle Orte", "Mit Ort", "Ohne Ort"])
        self.place.currentIndexChanged.connect(self._apply_filters)
        self.kind = QComboBox()
        self.kind.addItems(["Alle Typen", "JPEG", "HEIC", "PNG", "RAW", "Sonstiges"])
        self.kind.currentIndexChanged.connect(self._apply_filters)
        self.year = QComboBox()
        self.year.addItem("Alle Jahre")
        self.year.currentIndexChanged.connect(self._apply_filters)
        self.favorites = QCheckBox("Nur Favoriten")
        self.favorites.toggled.connect(self._apply_filters)
        self.unused = QCheckBox("Nicht im Tagebuch")
        self.unused.toggled.connect(self._apply_filters)
        refresh = QPushButton("Vorschauen aktualisieren")
        refresh.clicked.connect(self._refresh_thumbs)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.year)
        filters.addWidget(self.place)
        filters.addWidget(self.kind)
        filters.addWidget(self.favorites)
        filters.addWidget(self.unused)
        filters.addWidget(refresh)
        root.addLayout(filters)

        self.gallery = GalleryView()
        self.gallery.item_activated.connect(self._preview)
        root.addWidget(self.gallery, 1)

        actions = QHBoxLayout()
        favorite_btn = QPushButton("Favorit umschalten")
        favorite_btn.clicked.connect(self._toggle_favorite)
        self.summary = QLabel("Kein Projekt geöffnet")
        self.summary.setObjectName("pageSubtitle")
        actions.addWidget(favorite_btn)
        actions.addStretch(1)
        actions.addWidget(self.summary)
        root.addLayout(actions)

    def refresh(self) -> None:
        if self.workspace.current is None:
            self._items = []
            self.gallery.set_items([])
            self.summary.setText("Kein Projekt geöffnet")
            return
        self._items = self.workspace.gallery_items()
        years = sorted({item.captured_at.year for item in self._items if item.captured_at is not None})
        current = self.year.currentText()
        self.year.blockSignals(True)
        self.year.clear()
        self.year.addItem("Alle Jahre")
        for year in years:
            self.year.addItem(str(year))
        index = self.year.findText(current)
        self.year.setCurrentIndex(max(index, 0))
        self.year.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self.search.text().strip().lower()
        place = self.place.currentIndex()
        kind = self.kind.currentText()
        year_text = self.year.currentText()
        only_fav = self.favorites.isChecked()
        unused = self.unused.isChecked()
        shown: list[GalleryItem] = []
        for item in self._items:
            if query and query not in item.filename.lower():
                continue
            if place == 1 and item.gps_latitude is None:
                continue
            if place == 2 and item.gps_latitude is not None:
                continue
            if only_fav and not item.is_favorite:
                continue
            if unused and item.used_in_journal:
                continue
            if year_text != "Alle Jahre" and (
                item.captured_at is None or str(item.captured_at.year) != year_text
            ):
                continue
            if kind != "Alle Typen" and not _matches_kind(item.extension, kind):
                continue
            shown.append(item)
        self.gallery.set_items(shown)
        self.summary.setText(f"{len(shown)} von {len(self._items)} Fotos")

    def clear(self) -> None:
        self._items = []
        self.gallery.set_items([])
        if self.workspace.current is None:
            self.summary.setText("Kein Projekt geöffnet")
            return
        self.summary.setText("Index wird geladen…")

    def _toggle_favorite(self) -> None:
        item = self.gallery.selected_item()
        if item is None:
            QMessageBox.information(self, "Fotos", "Bitte ein Foto auswählen.")
            return
        try:
            self.workspace.set_favorite(item.source_file_id, not item.is_favorite)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Fotos", str(exc))
            return
        self.refresh()

    def _preview(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        dialog = PreviewDialog(item, self)
        dialog.exec()

    def _refresh_thumbs(self) -> None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Fotos", "Bitte zuerst ein Projekt öffnen.")
            return
        if self._busy:
            return
        self._busy = True
        self.status_message.emit("Vorschaubilder werden erzeugt…")
        worker = ThumbnailRunnable(self.workspace.current)
        worker.signals.finished.connect(self._on_thumbs_done)
        worker.signals.failed.connect(self._on_thumbs_failed)
        self._pool.start(worker)

    def _on_thumbs_done(self, written: int) -> None:
        self._busy = False
        self.refresh()
        self.status_message.emit(f"{written} neue Vorschaubilder")

    def _on_thumbs_failed(self, message: str) -> None:
        self._busy = False
        QMessageBox.warning(self, "Fotos", message)


class PreviewDialog(QDialog):
    def __init__(self, item: GalleryItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(item.filename)
        self.resize(720, 640)
        layout = QVBoxLayout(self)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = _preview_pixmap(item)
        image.setPixmap(pixmap)
        layout.addWidget(image, 1)
        meta = QLabel(_preview_text(item))
        meta.setWordWrap(True)
        meta.setObjectName("pageSubtitle")
        layout.addWidget(meta)
        close = QPushButton("Schließen")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


def _matches_kind(extension: str, kind: str) -> bool:
    suffix = extension.lower()
    if kind == "JPEG":
        return suffix in _JPEG
    if kind == "HEIC":
        return suffix in _HEIC
    if kind == "PNG":
        return suffix == ".png"
    if kind == "RAW":
        return suffix in _RAW
    if kind == "Sonstiges":
        return suffix not in _JPEG | _HEIC | _RAW | {".png", ".webp", ".tif", ".tiff"}
    return True


def _preview_pixmap(item: GalleryItem) -> QPixmap:
    source = Path(item.path)
    if source.suffix.lower() in _JPEG | {".png", ".webp"} and source.is_file():
        pixmap = QPixmap(str(source))
        if not pixmap.isNull():
            return pixmap.scaled(
                QSize(680, 480),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    if item.thumbnail_path.is_file():
        pixmap = QPixmap(str(item.thumbnail_path))
        if not pixmap.isNull():
            return pixmap.scaled(
                QSize(512, 512),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    empty = QPixmap(320, 240)
    empty.fill(Qt.GlobalColor.darkGray)
    return empty


def _preview_text(item: GalleryItem) -> str:
    parts = [item.path]
    if item.captured_at is not None:
        stamp = item.captured_at.strftime("%Y-%m-%d %H:%M:%S")
        if item.timezone_unknown:
            stamp += " (TZ unbekannt)"
        parts.append(stamp)
    if item.gps_latitude is not None and item.gps_longitude is not None:
        parts.append(f"{item.gps_latitude:.5f}, {item.gps_longitude:.5f}")
    if item.camera:
        parts.append(item.camera)
    if item.is_favorite:
        parts.append("Favorit")
    return " · ".join(parts)
