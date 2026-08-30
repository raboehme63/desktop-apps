"""Chronological thumbnail gallery with filters. Originals are only read."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from travelcore.media.gallery import SORT_FAVORITE, GalleryItem, effective_sort_status
from travelcore.timeline.sections import expand_range_selection
from traveljournal.services.workers import ThumbnailRunnable
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.gallery import GalleryView
from traveljournal.widgets.media_inspector import MediaInspectorWindow
from traveljournal.widgets.media_tabs import (
    RATING_TABS,
    ClickTabBar,
    ShowRejectedCheck,
    matches_rating,
    media_tab_index,
    media_tab_key,
    rating_status_at,
    sync_show_rejected_check,
)
from traveljournal.widgets.pool_pane import PoolCollapse, PoolPane

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
        self._applying_range = False
        self._journal_excluded: set[int] = set()
        self._journal_displayed: set[int] = set()
        self._pool_excluded: set[int] = set()
        self._pool_displayed: set[int] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Medien")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Links die Reise-Medien, rechts der Medienpool — jeweils mit Alle / Favoriten / "
            "Reserve / Aussortiert. Ziehen verschiebt zwischen Galerie und Pool. "
            "Pfeil rechts außen klappt den Pool ein und aus; die Breite bleibt erhalten. "
            "Originale bleiben unverändert."
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

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)
        tabs = QHBoxLayout()
        tab_label = QLabel("Register")
        tab_label.setObjectName("pageSubtitle")
        self._media_tabs = ClickTabBar(self)
        self._media_tabs.setObjectName("mediaSortTabs")
        self._media_tabs.setExpanding(False)
        for label, _status in RATING_TABS:
            self._media_tabs.addTab(label)
        self._media_tabs.setCurrentIndex(media_tab_index(self.workspace.timeline_media_tab()))
        self._media_tabs.currentChanged.connect(self._on_media_tab)
        self._show_rejected = ShowRejectedCheck(self)
        self._show_rejected.toggled.connect(self._on_show_rejected)
        tabs.addWidget(tab_label)
        tabs.addWidget(self._media_tabs)
        tabs.addWidget(self._show_rejected)
        tabs.addStretch(1)
        left_layout.addLayout(tabs)
        self.gallery = GalleryView()
        self.gallery.set_multi_select(True)
        self.gallery.set_drag_enabled(True)
        self.gallery.set_accept_pool_drop(True)
        self.gallery.setToolTip("Auf den Medienpool ziehen, oder aus dem Pool hierher zurücklegen.")
        self.gallery.item_activated.connect(self._preview)
        self.gallery.rating_chosen.connect(self._on_rating)
        self.gallery.items_dropped.connect(self._drop_on_gallery)
        gallery_model = self.gallery.selectionModel()
        if gallery_model is not None:
            gallery_model.selectionChanged.connect(self._on_journal_selection)
        left_layout.addWidget(self.gallery, 1)

        self._pool_pane = PoolPane(
            workspace=self.workspace,
            unpark_label="Zurück in die Galerie",
            accept_drops=True,
        )
        self._pool_pane.unpark_requested.connect(self._unpark_selected)
        self._pool_pane.items_dropped.connect(self._drop_on_pool)
        self._pool_pane.item_rating_changed.connect(self._on_pool_rating)
        self._pool_pane.item_activated.connect(self._preview)
        self._pool_pane.show_rejected_changed.connect(self._on_pool_show_rejected)
        pool_model = self._pool_pane.gallery.selectionModel()
        if pool_model is not None:
            pool_model.selectionChanged.connect(self._on_pool_selection)
        self._sync_show_rejected()

        self._split = QSplitter(Qt.Orientation.Horizontal)
        self._split.setObjectName("photosSplit")
        self._split.setChildrenCollapsible(False)
        self._split.addWidget(left)
        self._split.addWidget(self._pool_pane)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 0)
        root.addWidget(self._split, 1)
        self._pool_collapse = PoolCollapse(self, self._split, self._pool_pane, self.workspace)
        self._pool_toggle = self._pool_collapse.toggle

        actions = QHBoxLayout()
        favorite_btn = QPushButton("Favorit umschalten")
        favorite_btn.clicked.connect(self._toggle_favorite)
        pool_btn = QPushButton("In den Pool")
        pool_btn.clicked.connect(self._park_selected)
        self.summary = QLabel("Kein Projekt geöffnet")
        self.summary.setObjectName("pageSubtitle")
        actions.addWidget(favorite_btn)
        actions.addWidget(pool_btn)
        actions.addStretch(1)
        actions.addWidget(self.summary)
        root.addLayout(actions)

    def refresh(self) -> None:
        if self.workspace.current is None:
            self._items = []
            self.gallery.set_items([])
            self._pool_pane.set_items([])
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
        self._sync_show_rejected()
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
        self._sync_show_rejected()
        self._apply_filters()

    def _on_show_rejected(self, checked: bool) -> None:
        self.workspace.set_show_rejected_in_all(checked)
        self._apply_filters()

    def _on_pool_show_rejected(self, _checked: bool) -> None:
        self._sync_show_rejected()
        self._apply_filters()

    def _sync_show_rejected(self) -> None:
        sync_show_rejected_check(
            self._show_rejected, self._media_tabs, checked=self.workspace.show_rejected_in_all()
        )

    def _apply_filters(self) -> None:
        journal, parked = self._partition_filtered()
        wanted = rating_status_at(self._media_tabs.currentIndex())
        include_rejected = self.workspace.show_rejected_in_all()
        shown = [
            item for item in journal if matches_rating(item, wanted, include_rejected=include_rejected)
        ]
        self.gallery.set_items(shown)
        self._journal_excluded.clear()
        self._journal_displayed.clear()
        self._pool_excluded.clear()
        self._pool_displayed.clear()
        self._pool_pane.set_items(parked)
        self.summary.setText(
            f"{len(shown)} in der Galerie, {len(parked)} im Pool · {len(self._items)} Medien"
        )

    def _partition_filtered(self) -> tuple[list[GalleryItem], list[GalleryItem]]:
        query = self.search.text().strip().lower()
        place = self.place.currentIndex()
        kind = self.kind.currentText()
        year_text = self.year.currentText()
        unused = self.unused.isChecked()
        journal: list[GalleryItem] = []
        parked: list[GalleryItem] = []
        for item in self._items:
            if query and query not in item.filename.lower():
                continue
            if place == 1 and item.gps_latitude is None:
                continue
            if place == 2 and item.gps_latitude is not None:
                continue
            if year_text != "Alle Jahre" and (
                item.captured_at is None or str(item.captured_at.year) != year_text
            ):
                continue
            if kind != "Alle Typen" and not _matches_kind(item.extension, kind):
                continue
            if item.parked:
                parked.append(item)
                continue
            if unused and item.used_in_journal:
                continue
            journal.append(item)
        return journal, parked

    def clear(self) -> None:
        self._items = []
        self.gallery.set_items([])
        self._pool_pane.set_items([])
        if self.workspace.current is None:
            self.summary.setText("Kein Projekt geöffnet")
            return
        self.summary.setText("Index wird geladen…")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._pool_collapse.place()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._pool_collapse.sync_from_workspace()

    def _selected_for_rating(self) -> GalleryItem | None:
        return self.gallery.selected_item() or self._pool_pane.gallery.selected_item()

    def _toggle_favorite(self) -> None:
        item = self._selected_for_rating()
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

    def _park_selected(self) -> None:
        ids = [item.source_file_id for item in self.gallery.selected_items()]
        if not ids:
            QMessageBox.information(self, "Medien", "Bitte Medien in der Galerie auswählen.")
            return
        self._park_ids(ids)

    def _unpark_selected(self) -> None:
        ids = self._pool_pane.selected_source_ids()
        if not ids:
            QMessageBox.information(self, "Medien", "Bitte Medien im Pool auswählen.")
            return
        self._unpark_ids(ids)

    def _drop_on_pool(self, source_ids: list[int]) -> None:
        wanted = set(source_ids)
        ids = [
            item.source_file_id
            for item in self._items
            if item.source_file_id in wanted and not item.parked
        ]
        if ids:
            self._park_ids(ids)

    def _drop_on_gallery(self, source_ids: list[int]) -> None:
        wanted = set(source_ids)
        ids = [
            item.source_file_id
            for item in self._items
            if item.source_file_id in wanted and item.parked
        ]
        if ids:
            self._unpark_ids(ids)

    def _park_ids(self, ids: list[int]) -> None:
        try:
            self.workspace.park_media(ids)
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "Medien", str(error))
            return
        parked = {item.source_file_id: item for item in self._items}
        self.refresh()
        self._pool_collapse.set_visible(True)
        first = parked.get(ids[0])
        if first is not None:
            self.rating_changed.emit(replace(first, parked=True))

    def _unpark_ids(self, ids: list[int]) -> None:
        try:
            self.workspace.unpark_media(ids)
        except Exception as error:  # noqa: BLE001
            QMessageBox.warning(self, "Medien", str(error))
            return
        parked = {item.source_file_id: item for item in self._items}
        self.refresh()
        first = parked.get(ids[0])
        if first is not None:
            self.rating_changed.emit(replace(first, parked=False))

    def _on_journal_selection(self, *_args: object) -> None:
        self._journal_excluded, self._journal_displayed = self._fill_gallery_range(
            self.gallery, self._journal_excluded, self._journal_displayed
        )

    def _on_pool_selection(self, *_args: object) -> None:
        self._pool_excluded, self._pool_displayed = self._fill_gallery_range(
            self._pool_pane.gallery, self._pool_excluded, self._pool_displayed
        )

    def _fill_gallery_range(
        self,
        gallery: GalleryView,
        excluded: set[int],
        displayed: set[int],
    ) -> tuple[set[int], set[int]]:
        if self._applying_range:
            return excluded, displayed
        selected = {item.source_file_id for item in gallery.selected_items()}
        ordered = [item.source_file_id for item in gallery.items()]
        if len(selected) < 2:
            return set(), selected
        ctrl = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        holes = set(excluded)
        if ctrl:
            holes |= displayed - selected
            holes -= selected - displayed
        filled = expand_range_selection(ordered, selected, excluded=holes)
        span = expand_range_selection(ordered, selected)
        holes = span - filled
        if filled != selected:
            self._applying_range = True
            try:
                gallery.select_by_source_ids(filled)
            finally:
                self._applying_range = False
        return holes, filled

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

    def _on_pool_rating(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        self._items = [
            item if existing.source_file_id == item.source_file_id else existing for existing in self._items
        ]
        self.rating_changed.emit(item)

    def _preview(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        sequence = self._pool_pane.shown_items() if item.parked else list(self._items)
        window = MediaInspectorWindow(
            item, items=sequence, workspace=self.workspace, parent=self.window()
        )
        window.rating_changed.connect(self._on_inspector_rating)
        window.rotation_changed.connect(self._on_inspector_rating)
        window.park_changed.connect(self._on_inspector_park)
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

    def _on_inspector_park(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        self.refresh()
        if item.parked:
            self._pool_collapse.set_visible(True)
        self.rating_changed.emit(item)
        self.status_message.emit("Medium im Pool." if item.parked else "Medium zurück in der Galerie.")

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
