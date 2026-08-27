"""Chronological thumbnail gallery with filters. Originals are only read."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from travelcore.media.gallery import SORT_FAVORITE, GalleryItem, effective_sort_status
from traveljournal.services.workers import ThumbnailRunnable
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.gallery import GalleryView
from traveljournal.widgets.media_inspector import MediaInspectorWindow
from traveljournal.widgets.media_tabs import (
    MEDIA_TABS,
    ClickTabBar,
    media_tab_index,
    media_tab_key,
)

_JPEG = {".jpg", ".jpeg"}
_HEIC = {".heic", ".heif"}
_RAW = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2"}
_VIDEO = {".mp4", ".mov", ".avi", ".mkv"}
_TRACK = {".gpx", ".igc", ".kml", ".geojson"}


class PhotosView(QWidget):
    status_message = Signal(str)
    rating_changed = Signal(object)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._items: list[GalleryItem] = []
        self._pool = QThreadPool.globalInstance()
        self._busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Medien")
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
        self.kind.addItems(["Alle Typen", "JPEG", "HEIC", "PNG", "RAW", "Video", "Tracks", "Sonstiges"])
        self.kind.currentIndexChanged.connect(self._apply_filters)
        self.year = QComboBox()
        self.year.addItem("Alle Jahre")
        self.year.currentIndexChanged.connect(self._apply_filters)
        self.unused = QCheckBox("Nicht im Tagebuch")
        self.unused.toggled.connect(self._apply_filters)
        refresh = QPushButton("Vorschauen aktualisieren")
        refresh.clicked.connect(self._refresh_thumbs)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.year)
        filters.addWidget(self.place)
        filters.addWidget(self.kind)
        filters.addWidget(self.unused)
        filters.addWidget(refresh)
        root.addLayout(filters)

        tabs = QHBoxLayout()
        tab_label = QLabel("Register")
        tab_label.setObjectName("pageSubtitle")
        self._media_tabs = ClickTabBar(self)
        self._media_tabs.setObjectName("mediaSortTabs")
        self._media_tabs.setExpanding(False)
        for label, _status in MEDIA_TABS:
            self._media_tabs.addTab(label)
        self._media_tabs.setCurrentIndex(media_tab_index(self.workspace.timeline_media_tab()))
        self._media_tabs.currentChanged.connect(self._on_media_tab)
        tabs.addWidget(tab_label)
        tabs.addWidget(self._media_tabs)
        tabs.addStretch(1)
        root.addLayout(tabs)

        self.gallery = GalleryView()
        self.gallery.item_activated.connect(self._preview)
        self.gallery.rating_chosen.connect(self._on_rating)
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
        self._sync_media_tab()
        self._apply_filters()

    def _sync_media_tab(self) -> None:
        index = media_tab_index(self.workspace.timeline_media_tab())
        if self._media_tabs.currentIndex() == index:
            return
        self._media_tabs.blockSignals(True)
        self._media_tabs.setCurrentIndex(index)
        self._media_tabs.blockSignals(False)

    def _on_media_tab(self, index: int) -> None:
        self.workspace.set_timeline_media_tab(media_tab_key(index))
        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self.search.text().strip().lower()
        place = self.place.currentIndex()
        kind = self.kind.currentText()
        year_text = self.year.currentText()
        unused = self.unused.isChecked()
        wanted = (
            MEDIA_TABS[self._media_tabs.currentIndex()][1]
            if 0 <= self._media_tabs.currentIndex() < len(MEDIA_TABS)
            else None
        )
        shown: list[GalleryItem] = []
        for item in self._items:
            if query and query not in item.filename.lower():
                continue
            if place == 1 and item.gps_latitude is None:
                continue
            if place == 2 and item.gps_latitude is not None:
                continue
            if wanted is not None and effective_sort_status(item.sort_status, item.is_favorite) != wanted:
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
        self.summary.setText(f"{len(shown)} von {len(self._items)} Medien")

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
            QMessageBox.information(self, "Medien", "Bitte ein Medium auswählen.")
            return
        current = effective_sort_status(item.sort_status, item.is_favorite)
        next_status = None if current == SORT_FAVORITE else SORT_FAVORITE
        try:
            self.workspace.set_sort_status(item.source_file_id, next_status)
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "Medien", str(error))
            return
        self._apply_item_rating(
            replace(item, sort_status=next_status, is_favorite=next_status == SORT_FAVORITE)
        )

    def _on_rating(self, item: object, status: str) -> None:
        if not isinstance(item, GalleryItem):
            return
        current = effective_sort_status(item.sort_status, item.is_favorite)
        next_status = None if current == status else status
        try:
            self.workspace.set_sort_status(item.source_file_id, next_status)
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "Medien", str(error))
            return
        self._apply_item_rating(
            replace(item, sort_status=next_status, is_favorite=next_status == SORT_FAVORITE)
        )

    def _preview(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        window = MediaInspectorWindow(
            item, items=self.gallery.items(), workspace=self.workspace, parent=self.window()
        )
        window.rating_changed.connect(self._on_inspector_rating)
        window.rotation_changed.connect(self._on_inspector_rating)
        window.show()
        window.raise_()
        window.activateWindow()

    def _on_inspector_rating(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        self._apply_item_rating(item)

    def _apply_item_rating(self, item: GalleryItem) -> None:
        self._items = [
            item if existing.source_file_id == item.source_file_id else existing for existing in self._items
        ]
        self._apply_filters()
        self.rating_changed.emit(item)

    def apply_media_rating(self, item: object) -> None:
        """Take a rating from the map or Timeline into the already loaded gallery."""

        if not isinstance(item, GalleryItem):
            return
        self._items = [
            item if existing.source_file_id == item.source_file_id else existing for existing in self._items
        ]
        self._apply_filters()

    def _refresh_thumbs(self) -> None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Medien", "Bitte zuerst ein Projekt öffnen.")
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
        QMessageBox.warning(self, "Medien", message)


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
    if kind == "Video":
        return suffix in _VIDEO
    if kind == "Tracks":
        return suffix in _TRACK
    if kind == "Sonstiges":
        return suffix not in _JPEG | _HEIC | _RAW | _VIDEO | _TRACK | {".png", ".webp", ".tif", ".tiff"}
    return True
