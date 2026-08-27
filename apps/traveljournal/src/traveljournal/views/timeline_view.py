"""Chronological trip overview. Originals are never written."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QResizeEvent, QTextOption, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.maps.groups import parse_group_key
from travelcore.media.gallery import (
    SORT_FAVORITE,
    SORT_REJECTED,
    SORT_RESERVE,
    GalleryItem,
    effective_sort_status,
)
from travelcore.media.types import FileKind
from travelcore.timeline.build import apply_pending_sections
from travelcore.timeline.links import (
    normalize_leonardo_url,
    parse_leonardo_urls,
    parse_youtube_urls,
    serialize_leonardo_urls,
    serialize_youtube_urls,
)
from travelcore.timeline.sections import (
    KIND_DAY,
    KIND_MOVEMENT,
    KIND_STAY,
    expand_range_selection,
    format_section_span,
    parse_modes,
    serialize_modes,
)
from travelcore.timeline.types import (
    PendingSectionSpec,
    TimelineDay,
    TimelineEntry,
    TimelinePhoto,
    TimelineSection,
    TimelineSnapshot,
)
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.entry_links import (
    LeonardoLinksDialog,
    YouTubeLinksDialog,
    YouTubeThumbsRow,
    igc_flights,
    links_html,
)
from traveljournal.widgets.gallery import GalleryView
from traveljournal.widgets.media_inspector import MediaInspectorWindow

_MEDIA_TABS = (
    ("Alle", None),
    ("Favoriten", SORT_FAVORITE),
    ("Reserve", SORT_RESERVE),
    ("Aussortiert", SORT_REJECTED),
)


def media_tab_key(index: int) -> str:
    if 0 <= index < len(_MEDIA_TABS):
        return _MEDIA_TABS[index][1] or "all"
    return "all"


def media_tab_index(key: str) -> int:
    for index, (_, status) in enumerate(_MEDIA_TABS):
        if (status or "all") == key:
            return index
    return 0


_REVEAL_TOP_PAD = 12


def scroll_offset_to_widget_top(host: QWidget, child: QWidget, *, padding: int = _REVEAL_TOP_PAD) -> int:
    """Scrollbar value that puts ``child``'s top at the top of the scroll host."""

    top = child.mapTo(host, QPoint(0, 0)).y()
    return max(0, top - padding)


class ClickTabBar(QTabBar):
    """Tabs change only on click. Wheel events scroll the timeline instead."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setChangeCurrentOnDrag(False)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        event.ignore()


_MODE_LABELS = (
    ("bus", "Bus"),
    ("train", "Bahn"),
    ("plane", "Flugzeug"),
    ("walk", "zu Fuß"),
    ("car", "Auto"),
    ("bike", "Fahrrad"),
    ("boat", "Schiff"),
    ("other", "Sonstiges"),
)
_COVER_HEAD = 72


class TimelineView(QWidget):
    status_message = Signal(str)
    timeline_changed = Signal()
    open_on_map = Signal(str)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._snapshot: TimelineSnapshot | None = None
        self._base_snapshot: TimelineSnapshot | None = None
        self._pending: list[PendingSectionSpec] = []
        self._pending_youtube: dict[tuple[str, int], list[str]] = {}
        self._next_pending_id = -1
        self._blocks: list[EntryWidget] = []
        self._loading = False
        self._applying_range = False
        self._excluded_ids: set[int] = set()
        self._displayed_selection: set[int] = set()
        self._syncing_tabs = False
        self._loaded_trip_title = ""
        self._pending_reveal: EntryWidget | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        title = QLabel("Timeline")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        trip_row = QHBoxLayout()
        trip_row.setSpacing(10)
        trip_label = QLabel("Reisetitel")
        trip_label.setObjectName("pageSubtitle")
        self._trip_title = QLineEdit()
        self._trip_title.setObjectName("tripTitleEdit")
        self._trip_title.setPlaceholderText("Titel der Reise")
        self._trip_title.setClearButtonEnabled(True)
        self._trip_title.setEnabled(False)
        trip_row.addWidget(trip_label)
        trip_row.addWidget(self._trip_title, 1)
        root.addLayout(trip_row)

        self._subtitle = QLabel(
            "Tage, Transfers und Aufenthalte chronologisch untereinander. "
            "Typ je Karte ändern, oder Objekte markieren und einen Abschnitt anlegen. "
            "Erstes und letztes Objekt anklicken — alles dazwischen wird mitmarkiert. "
            "Strg+Klick nimmt einzelne Objekte dazwischen wieder raus. "
            "Die Zeitspanne kommt aus den gewählten Dateien."
        )
        self._subtitle.setObjectName("pageSubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(self._subtitle)

        toolbar = QHBoxLayout()
        refresh = QPushButton("Timeline aktualisieren")
        refresh.clicked.connect(self.rebuild)
        self._create_button = QPushButton("Neuen Reiseabschnitt erstellen")
        self._create_button.clicked.connect(self._create_section)
        self._save_button = QPushButton("Speichern")
        self._save_button.setObjectName("primary")
        self._save_button.clicked.connect(self._on_save_clicked)
        self._media_tabs = ClickTabBar(self)
        self._media_tabs.setObjectName("mediaSortTabs")
        self._media_tabs.setExpanding(False)
        for label, _status in _MEDIA_TABS:
            self._media_tabs.addTab(label)
        self._media_tabs.setCurrentIndex(media_tab_index(self.workspace.timeline_media_tab()))
        self._media_tabs.currentChanged.connect(self._on_global_media_tab)
        tab_label = QLabel("Register")
        tab_label.setObjectName("pageSubtitle")
        toolbar.addWidget(refresh)
        toolbar.addWidget(self._create_button)
        toolbar.addSpacing(16)
        toolbar.addWidget(tab_label)
        toolbar.addWidget(self._media_tabs)
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
        self._create_button.setEnabled(False)

    def rebuild(self) -> None:
        self._pending_youtube.clear()
        self.refresh(rebuild=True)
        self.timeline_changed.emit()

    def ensure_loaded(self) -> None:
        if self._snapshot is None:
            self.refresh()

    def confirm_leave(self) -> bool:
        """Drop unsaved YouTube links unless Speichern was used; prompt for unsaved sections."""

        self._persist_media_tab()
        self._sync_pending_from_widgets()
        self._stash_pending_youtube()
        if not self._pending and not self._pending_youtube:
            return True
        if self._pending:
            result = QMessageBox.question(
                self,
                "Timeline",
                "Es gibt ungespeicherte Reiseabschnitte. Ohne Speichern gehen sie verloren. "
                "YouTube-Links werden nur mit „Speichern“ in der Timeline übernommen.",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if result == QMessageBox.StandardButton.Cancel:
                return False
            if result == QMessageBox.StandardButton.Save:
                if not self._persist_pending():
                    return False
                if not self._commit_if_dirty():
                    return False
            self._pending.clear()
            self._pending_youtube.clear()
            self._snapshot = None
            self._base_snapshot = None
            return True
        result = QMessageBox.question(
            self,
            "Timeline",
            "YouTube-Links sind nicht gespeichert. Sie werden nur mit „Speichern“ in der Timeline "
            "übernommen und gehen sonst verloren.",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if result != QMessageBox.StandardButton.Discard:
            return False
        self._pending_youtube.clear()
        self._snapshot = None
        self._base_snapshot = None
        return True

    def refresh(self, rebuild: bool = False) -> None:
        self._commit_if_dirty()
        if self.workspace.current is None:
            self._snapshot = None
            self._base_snapshot = None
            self._pending.clear()
            self._pending_youtube.clear()
            self._fill_entries()
            self._set_trip_title_field(None)
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
        self._base_snapshot = snapshot
        self._apply_pending_view()

    def _apply_pending_view(self) -> None:
        self._sync_pending_from_widgets()
        self._stash_pending_youtube()
        snapshot = self._base_snapshot
        if snapshot is None:
            self._snapshot = None
            self._fill_entries()
            self._set_trip_title_field(None)
            return
        shown = apply_pending_sections(snapshot, self._pending)
        self._snapshot = shown
        leftover = sum(1 for entry in shown.entries if entry.leftover_day is not None)
        sections = len(shown.sections)
        unsaved_n = len(self._pending) + len(self._pending_youtube)
        unsaved = f" {unsaved_n} ungespeichert." if unsaved_n else ""
        self._set_trip_title_field(shown)
        self._subtitle.setText(
            f"{sections} Abschnitte, {leftover} Tage.{unsaved} "
            "Auswahl von Fotos, Videos und Tracks erzeugt einen Abschnitt; die Zeit kommt aus den Objekten."
        )
        self._fill_entries()
        self.status_message.emit(f"Timeline: {sections} Abschnitte, {leftover} Tage")

    def clear(self) -> None:
        self._snapshot = None
        self._base_snapshot = None
        self._pending.clear()
        self._pending_youtube.clear()
        self._fill_entries()
        self._set_trip_title_field(None)
        self._subtitle.setText(
            "Index wird geladen…" if self.workspace.current is not None else "Bitte ein Projekt öffnen."
        )

    def _fill_entries(self) -> None:
        self._loading = True
        scroll = self._scroll.verticalScrollBar().value()
        self._host.setUpdatesEnabled(False)
        try:
            for block in self._blocks:
                block.hide()
                self._host_layout.removeWidget(block)
                block.deleteLater()
            self._blocks.clear()
            entries = self._snapshot.entries if self._snapshot is not None else ()
            if not entries:
                self._empty.setVisible(True)
                if self.workspace.current is None:
                    self._empty.setText("Bitte ein Projekt öffnen.")
                elif self._snapshot is None:
                    self._empty.setText("Index wird geladen…")
                else:
                    self._empty.setText("Keine Tage in der Timeline.")
                self._save_button.setEnabled(self._snapshot is not None)
                self._create_button.setEnabled(False)
                return
            self._empty.setVisible(False)
            has_sections = bool(self._snapshot.sections) if self._snapshot is not None else False
            insert_at = max(self._host_layout.count() - 1, 0)
            for entry in entries:
                override = None
                if entry.section is not None:
                    override = self._pending_youtube.get(("section", entry.section.id))
                elif entry.leftover_day is not None:
                    override = self._pending_youtube.get(("day", entry.leftover_day.id))
                block = EntryWidget(
                    entry,
                    workspace=self.workspace,
                    show_as_leftover=has_sections,
                    youtube_override=override,
                    media_tab=self._media_tabs.currentIndex(),
                    parent=self._host,
                )
                block.selection_changed.connect(self._on_block_selection_changed)
                block.dissolve_requested.connect(self._dissolve_section)
                block.kind_changed.connect(lambda kind, widget=block: self._change_entry_kind(widget, kind))
                block.media_tab_changed.connect(self._on_block_media_tab)
                block.item_rating_changed.connect(self._on_item_rating)
                block.open_on_map.connect(self.open_on_map.emit)
                block.gallery.item_activated.connect(self._open_inspector)
                block.track_gallery.item_activated.connect(self._open_inspector)
                self._blocks.append(block)
                self._host_layout.insertWidget(insert_at, block)
                insert_at += 1
            self._save_button.setEnabled(True)
            self._update_create_button()
            self._propagate_media_tab(self._media_tabs.currentIndex(), persist=False)
        finally:
            self._host.setUpdatesEnabled(True)
            self._loading = False
            self._excluded_ids.clear()
            self._displayed_selection = set(self._selected_source_ids())
            self._scroll.verticalScrollBar().setValue(scroll)

    def _update_create_button(self) -> None:
        self._create_button.setEnabled(bool(self._selected_source_ids()))

    def _on_global_media_tab(self, index: int) -> None:
        self._propagate_media_tab(index, persist=True)

    def _on_block_media_tab(self, index: int) -> None:
        self._propagate_media_tab(index, persist=True)

    def _propagate_media_tab(self, index: int, *, persist: bool) -> None:
        if self._syncing_tabs:
            return
        index = max(0, min(index, len(_MEDIA_TABS) - 1))
        self._syncing_tabs = True
        try:
            if self._media_tabs.currentIndex() != index:
                self._media_tabs.blockSignals(True)
                self._media_tabs.setCurrentIndex(index)
                self._media_tabs.blockSignals(False)
            for block in self._blocks:
                block.set_media_tab(index)
            if persist:
                self.workspace.set_timeline_media_tab(media_tab_key(index))
        finally:
            self._syncing_tabs = False

    def _persist_media_tab(self) -> None:
        self.workspace.set_timeline_media_tab(media_tab_key(self._media_tabs.currentIndex()))

    def _open_inspector(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        sequence = [item]
        sender = self.sender()
        if isinstance(sender, GalleryView):
            block = sender.parent()
            if isinstance(block, EntryWidget) and sender is block.gallery:
                sequence = block.inspectable_media()
        else:
            sequence = block.track_gallery.items()
        window = MediaInspectorWindow(item, items=sequence, workspace=self.workspace, parent=self.window())
        window.rating_changed.connect(self._on_item_rating)
        window.rotation_changed.connect(self._on_item_rating)
        window.show()
        window.raise_()
        window.activateWindow()

    def _on_item_rating(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        for block in self._blocks:
            block.sync_rating(item)
        parent = self.window()
        if parent is None:
            return
        for inspector in parent.findChildren(MediaInspectorWindow):
            inspector.sync_from_item(item)

    def _selected_source_ids(self) -> list[int]:
        ids: list[int] = []
        seen: set[int] = set()
        for block in self._blocks:
            for source_id in block.selected_source_ids():
                if source_id in seen:
                    continue
                seen.add(source_id)
                ids.append(source_id)
        return ids

    def _ordered_source_ids(self) -> list[int]:
        ids: list[int] = []
        for block in self._blocks:
            ids.extend(item.source_file_id for item in block.ordered_items())
        return ids

    def _on_block_selection_changed(self) -> None:
        if self._applying_range:
            return
        selected = set(self._selected_source_ids())
        ordered = self._ordered_source_ids()
        ctrl = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        if len(selected) < 2:
            self._excluded_ids.clear()
            self._displayed_selection = selected
            self._update_create_button()
            return
        if ctrl:
            self._excluded_ids |= self._displayed_selection - selected
            self._excluded_ids -= selected - self._displayed_selection
        filled = expand_range_selection(ordered, selected, excluded=self._excluded_ids)
        span = expand_range_selection(ordered, selected)
        self._excluded_ids = span - filled
        if filled != selected:
            self._applying_range = True
            try:
                for block in self._blocks:
                    block.select_ids(filled)
            finally:
                self._applying_range = False
        self._displayed_selection = filled
        self._update_create_button()

    def _create_section(self) -> None:
        source_ids = self._selected_source_ids()
        if not source_ids:
            QMessageBox.information(self, "Timeline", "Bitte zuerst Objekte in den Medienrastern auswählen.")
            return
        if not self._commit_if_dirty():
            return
        items = self._selected_items()
        dialog = NewSectionDialog(items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dialog.values()
        self._pending.append(
            PendingSectionSpec(
                local_id=self._next_pending_id,
                source_file_ids=tuple(source_ids),
                kind=str(payload["kind"]),
                mode=payload.get("mode"),
                title=payload.get("title"),
                notes=payload.get("notes"),
                location_name=payload.get("location_name"),
                location_from=payload.get("location_from"),
                location_to=payload.get("location_to"),
            )
        )
        self._next_pending_id -= 1
        self._apply_pending_view()
        self.status_message.emit("Reiseabschnitt angelegt. Speichern, sonst geht er verloren.")

    def _dissolve_section(self, section_id: int) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Reiseabschnitt auflösen")
        box.setText("Diesen Reiseabschnitt auflösen? Die Medien erscheinen wieder bei den zugehörigen Tagen.")
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Ok).setText("OK")
        box.button(QMessageBox.StandardButton.Cancel).setText("Abbrechen")
        if box.exec() != QMessageBox.StandardButton.Ok:
            return False
        self._pending_youtube.pop(("section", section_id), None)
        if section_id < 0:
            self._pending = [spec for spec in self._pending if spec.local_id != section_id]
            self._apply_pending_view()
            self.status_message.emit("Reiseabschnitt verworfen.")
            return True
        try:
            self.workspace.dissolve_section(section_id)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return False
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Reiseabschnitt aufgelöst.")
        return True

    def _change_entry_kind(self, block: EntryWidget, kind: str) -> None:
        current = block.entry_kind()
        if kind == current:
            return
        if kind == KIND_DAY:
            if current == KIND_DAY:
                return
            if not self._dissolve_section(block.entity_id()):
                block.reset_kind_combo()
            return
        if current == KIND_DAY:
            ids = [item.source_file_id for item in block.ordered_items()]
            if not ids:
                QMessageBox.information(self, "Timeline", "Dieser Tag hat keine Medien für einen Abschnitt.")
                block.reset_kind_combo()
                return
            if not self._commit_if_dirty():
                block.reset_kind_combo()
                return
            title, notes = block.title_edit.text().strip() or None, block.notes_edit.toPlainText()
            self._pending.append(
                PendingSectionSpec(
                    local_id=self._next_pending_id,
                    source_file_ids=tuple(ids),
                    kind=kind,
                    title=title,
                    notes=notes or None,
                    cover_source_file_id=block.cover_source_file_id(),
                    youtube_urls=tuple(block.youtube_urls()),
                    leonardo_urls=tuple(block.leonardo_urls()),
                )
            )
            self._next_pending_id -= 1
            self._apply_pending_view()
            self.status_message.emit("Reiseabschnitt angelegt. Speichern, sonst geht er verloren.")
            return
        if block.entity_id() < 0:
            for spec in self._pending:
                if spec.local_id == block.entity_id():
                    spec.kind = kind
                    if kind != KIND_MOVEMENT:
                        spec.mode = None
                        spec.location_from = None
                        spec.location_to = None
                    else:
                        spec.location_name = None
                    break
            self._apply_pending_view()
            return
        try:
            self.workspace.update_section_kind(block.entity_id(), kind)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            block.reset_kind_combo()
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Abschnittstyp geändert.")

    def reveal_group(self, group_key: str) -> None:
        """Scroll so the matching day or section starts at the top of the list."""

        self.ensure_loaded()
        block = self._block_for_group_key(group_key)
        if block is None:
            return
        self._pending_reveal = block
        QTimer.singleShot(0, self._apply_pending_reveal)
        QTimer.singleShot(32, self._apply_pending_reveal)

    def _block_for_group_key(self, group_key: str) -> EntryWidget | None:
        kind, ident = parse_group_key(group_key)
        if kind is None or ident is None:
            return None
        for block in self._blocks:
            if kind == "section" and block.entity_kind() == "section" and block.entity_id() == ident:
                return block
            if kind == "day" and block.entity_kind() == "day" and block.entity_id() == ident:
                return block
        return None

    def _apply_pending_reveal(self) -> None:
        block = self._pending_reveal
        if block is None or block not in self._blocks:
            return
        host = self._scroll.widget()
        if host is None:
            return
        bar = self._scroll.verticalScrollBar()
        value = scroll_offset_to_widget_top(host, block)
        bar.setValue(min(value, bar.maximum()))

    def _selected_items(self) -> list[GalleryItem]:
        items: list[GalleryItem] = []
        seen: set[int] = set()
        for block in self._blocks:
            for item in block.selected_items():
                if item.source_file_id in seen:
                    continue
                seen.add(item.source_file_id)
                items.append(item)
        return items

    def _trip_title_dirty(self) -> bool:
        return self._trip_title.text().strip() != (self._loaded_trip_title or "").strip()

    def _set_trip_title_field(self, snapshot: TimelineSnapshot | None) -> None:
        if snapshot is None:
            self._trip_title.clear()
            self._trip_title.setEnabled(False)
            self._loaded_trip_title = ""
            return
        self._trip_title.setEnabled(True)
        if not self._trip_title_dirty():
            self._trip_title.setText(snapshot.title)
            self._loaded_trip_title = snapshot.title

    def _commit_trip_title(self) -> bool:
        snapshot = self._snapshot
        if snapshot is None or not self._trip_title_dirty():
            return True
        cleaned = self._trip_title.text().strip()
        if not cleaned:
            self._trip_title.setText(self._loaded_trip_title)
            return True
        try:
            self.workspace.save_trip_title(snapshot.trip_id, cleaned)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return False
        self._loaded_trip_title = cleaned
        return True

    def _sync_pending_from_widgets(self) -> None:
        by_id = {spec.local_id: spec for spec in self._pending}
        for block in self._blocks:
            kind, entity_id, title, notes = block.values()
            spec = by_id.get(entity_id)
            if spec is None or kind != "section":
                continue
            spec.title = title.strip() or None
            spec.notes = notes
            spec.youtube_urls = tuple(block.youtube_urls())
            spec.leonardo_urls = tuple(block.leonardo_urls())
            spec.cover_source_file_id = block.cover_source_file_id()

    def _stash_pending_youtube(self) -> None:
        for block in self._blocks:
            key = block.youtube_key()
            if key[1] <= 0:
                continue
            current = block.youtube_urls()
            if current != block.youtube_from_db():
                self._pending_youtube[key] = current
            else:
                self._pending_youtube.pop(key, None)

    def _persist_pending_youtube(self) -> bool:
        self._stash_pending_youtube()
        if not self._pending_youtube:
            return True
        try:
            for (kind, entity_id), urls in list(self._pending_youtube.items()):
                if entity_id <= 0:
                    continue
                self.workspace.save_youtube_urls(kind, entity_id, urls)
        except ProjectError as exc:
            QMessageBox.warning(self, "YouTube-Links", str(exc))
            return False
        for block in self._blocks:
            if block.youtube_key() in self._pending_youtube:
                block.mark_youtube_clean()
        self._pending_youtube.clear()
        return True

    def _persist_pending(self) -> bool:
        self._sync_pending_from_widgets()
        if not self._pending:
            return True
        try:
            for spec in self._pending:
                self.workspace.create_section(
                    list(spec.source_file_ids),
                    kind=spec.kind,
                    mode=spec.mode,
                    title=spec.title,
                    notes=spec.notes,
                    location_name=spec.location_name,
                    location_from=spec.location_from,
                    location_to=spec.location_to,
                    youtube_urls=list(spec.youtube_urls),
                    leonardo_urls=list(spec.leonardo_urls),
                    cover_source_file_id=spec.cover_source_file_id,
                )
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return False
        self._pending.clear()
        return True

    def _commit_if_dirty(self) -> bool:
        if self._loading:
            return True
        self._sync_pending_from_widgets()
        dirty = [block for block in self._blocks if block.is_dirty()]
        if not dirty and not self._trip_title_dirty():
            return True
        try:
            if not self._commit_trip_title():
                return False
            for block in dirty:
                kind, entity_id, title, notes = block.values()
                if entity_id < 0:
                    block.mark_clean()
                    continue
                if kind == "section":
                    self.workspace.save_section_text(entity_id, title=title, notes=notes)
                else:
                    self.workspace.save_day_text(entity_id, title=title, notes=notes)
                block.mark_clean()
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return False
        return True

    def _on_save_clicked(self) -> None:
        self._stash_pending_youtube()
        if (
            not self._blocks
            and not self._pending
            and not self._pending_youtube
            and not self._trip_title_dirty()
        ):
            QMessageBox.information(self, "Timeline", "Nichts zum Speichern.")
            return
        if not self._persist_pending():
            return
        if not self._commit_if_dirty():
            return
        if not self._persist_pending_youtube():
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Tagebuch gespeichert.")


class EntryWidget(QFrame):
    selection_changed = Signal()
    dissolve_requested = Signal(int)
    kind_changed = Signal(str)
    media_tab_changed = Signal(int)
    item_rating_changed = Signal(object)
    open_on_map = Signal(str)

    def __init__(
        self,
        entry: TimelineEntry,
        *,
        workspace: Workspace | None = None,
        show_as_leftover: bool = False,
        youtube_override: list[str] | None = None,
        media_tab: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.workspace = workspace
        section = entry.section
        day = entry.leftover_day
        youtube: tuple[str, ...] = ()
        leonardo: tuple[str, ...] = ()
        cover_id: int | None = None
        if section is not None:
            self._kind = "section"
            self._entity_id = section.id
            heading_text = _section_heading(section)
            title = section.title or ""
            notes = section.notes or ""
            items = section.items
            youtube = section.youtube_urls
            leonardo = section.leonardo_urls
            cover_id = section.cover_source_file_id
            title_ph = "Titel des Abschnitts"
            notes_ph = "Tagebucheintrag für diesen Abschnitt"
        elif day is not None:
            self._kind = "day"
            self._entity_id = day.id
            heading_text = _leftover_heading(day, leftover=show_as_leftover)
            title = day.title or ""
            notes = day.notes or ""
            items = day.photos
            youtube = day.youtube_urls
            leonardo = day.leonardo_urls
            cover_id = day.cover_source_file_id
            title_ph = "Titel des Tages"
            notes_ph = "Tagebucheintrag — aus importierten Texten vorbefüllt"
        else:
            self._kind = "day"
            self._entity_id = 0
            heading_text = "Leer"
            title = ""
            notes = ""
            items = ()
            title_ph = "Titel"
            notes_ph = ""
        self._db_youtube_urls = list(youtube)
        self._youtube_urls = list(youtube if youtube_override is None else youtube_override)
        self._leonardo_urls = list(leonardo)
        self._cover_id = cover_id
        self._flights = igc_flights(items)
        self._loaded_title = title
        self._loaded_notes = notes
        self._entry_kind = entry.card_kind

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        heading = QLabel(heading_text, self)
        heading.setObjectName("pageSubtitle")
        heading.setWordWrap(True)
        self._menu_button = QToolButton(self)
        self._menu_button.setObjectName("entryMenu")
        self._menu_button.setText("⋯")
        can_menu = self.workspace is not None and (self._kind == "section" or self._entity_id > 0)
        self._menu_button.setEnabled(can_menu)
        self._entry_menu = QMenu(self)
        youtube_action = self._entry_menu.addAction("YouTube-Links…")
        youtube_action.triggered.connect(self._edit_youtube)
        leonardo_action = self._entry_menu.addAction("DHV-Leonardo…")
        leonardo_action.triggered.connect(self._edit_leonardo)
        self._menu_button.clicked.connect(self._popup_entry_menu)
        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 0)
        heading_row.setSpacing(12)
        self._cover_thumb = QLabel(self)
        self._cover_thumb.setObjectName("entryCover")
        self._cover_thumb.setFixedSize(_COVER_HEAD, _COVER_HEAD)
        self._cover_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_thumb.setToolTip("Titelbild")
        self._cover_thumb.hide()
        heading_row.addWidget(self._cover_thumb, 0, Qt.AlignmentFlag.AlignTop)
        self._kind_combo = QComboBox(self)
        self._kind_combo.setObjectName("sectionKind")
        self._kind_combo.addItem("Tag", KIND_DAY)
        self._kind_combo.addItem("Aufenthalt", KIND_STAY)
        self._kind_combo.addItem("Transfer", KIND_MOVEMENT)
        self._kind_combo.setToolTip("Typ dieses Timeline-Eintrags")
        index = max(0, self._kind_combo.findData(self._entry_kind))
        self._kind_combo.setCurrentIndex(index)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_combo)
        heading_row.addWidget(self._kind_combo, 0, Qt.AlignmentFlag.AlignTop)
        heading_row.addWidget(heading, 1)
        self._to_map_button = QPushButton("Zur Karte", self)
        self._to_map_button.setObjectName("entryToMap")
        saved = self._entity_id > 0
        self._to_map_button.setEnabled(saved)
        self._to_map_button.setToolTip(
            "Eintrag auf der Karte zeigen" if saved else "Nach dem Speichern auf der Karte sichtbar"
        )
        self._to_map_button.clicked.connect(self._request_open_on_map)
        heading_row.addWidget(self._to_map_button, 0, Qt.AlignmentFlag.AlignTop)
        if self._kind == "section":
            dissolve = QToolButton(self)
            dissolve.setObjectName("entryMenu")
            dissolve.setText("⊟")
            dissolve.setToolTip("Reiseabschnitt auflösen")
            dissolve.clicked.connect(self._request_dissolve)
            heading_row.addWidget(dissolve, 0, Qt.AlignmentFlag.AlignTop)
        heading_row.addWidget(self._menu_button, 0, Qt.AlignmentFlag.AlignTop)
        self.links_label = QLabel(self)
        self.links_label.setObjectName("pageSubtitle")
        self.links_label.setWordWrap(True)
        self.links_label.setOpenExternalLinks(True)
        self.links_label.setTextFormat(Qt.TextFormat.RichText)
        self.youtube_thumbs = YouTubeThumbsRow(self)
        self._refresh_links()
        self.title_edit = QLineEdit(self)
        self.title_edit.setText(self._loaded_title)
        self.title_edit.setPlaceholderText(title_ph)
        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setPlainText(self._loaded_notes)
        self.notes_edit.setPlaceholderText(notes_ph)
        self.notes_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.notes_edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.notes_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.notes_edit.textChanged.connect(self._fit_notes)
        media_items, track_items = split_media_and_tracks(items)
        media_count = len(media_items)
        track_count = len(track_items)
        media_label = QLabel(
            "Keine Medien"
            if media_count == 0 and track_count == 0
            else (
                f"Medien ({media_count}) — erstes und letztes Objekt anklicken, "
                "dazwischen wird mitmarkiert; Strg+Klick nimmt einzelne wieder raus"
            ),
            self,
        )
        media_label.setObjectName("pageSubtitle")
        media_label.setWordWrap(True)
        media_label.setVisible(media_count > 0 or track_count == 0)
        self._all_gallery = [_gallery_item(photo, cover_id=self._cover_id) for photo in media_items]
        self._media_tabs = ClickTabBar(self)
        self._media_tabs.setObjectName("mediaSortTabs")
        self._media_tabs.setExpanding(False)
        for label, _status in _MEDIA_TABS:
            self._media_tabs.addTab(label)
        self._media_tabs.setVisible(media_count > 0)
        self.gallery = GalleryView(self, show_cover=True)
        self.gallery.set_expand_to_fit(True)
        self.gallery.set_multi_select(True)
        self.gallery.rating_chosen.connect(self._on_rating)
        self.gallery.cover_chosen.connect(self._on_cover)
        self.gallery.setToolTip("T oben links: Titelbild für diesen Tag oder Abschnitt")
        self.gallery.setVisible(media_count > 0)
        model = self.gallery.selectionModel()
        if model is not None:
            model.selectionChanged.connect(lambda *_args: self.selection_changed.emit())
        track_label = QLabel(
            f"Tracks ({track_count}) — erstes und letztes Objekt anklicken, "
            "dazwischen wird mitmarkiert; Strg+Klick nimmt einzelne wieder raus",
            self,
        )
        track_label.setObjectName("pageSubtitle")
        track_label.setWordWrap(True)
        track_label.setVisible(track_count > 0)
        self.track_gallery = GalleryView(self, show_ratings=False, show_cover=True)
        self.track_gallery.set_expand_to_fit(True)
        self.track_gallery.set_multi_select(True)
        self.track_gallery.cover_chosen.connect(self._on_cover)
        self.track_gallery.setToolTip("T oben links: Titelbild für diesen Tag oder Abschnitt")
        self.track_gallery.set_items([_gallery_item(photo, cover_id=self._cover_id) for photo in track_items])
        self.track_gallery.setVisible(track_count > 0)
        track_model = self.track_gallery.selectionModel()
        if track_model is not None:
            track_model.selectionChanged.connect(lambda *_args: self.selection_changed.emit())

        title_label = QLabel("Titel", self)
        notes_label = QLabel("Tagebucheintrag", self)
        layout.addLayout(heading_row)
        layout.addWidget(title_label)
        layout.addWidget(self.title_edit)
        layout.addWidget(notes_label)
        layout.addWidget(self.notes_edit)
        layout.addWidget(self.youtube_thumbs)
        layout.addWidget(self.links_label)
        layout.addWidget(media_label)
        if media_count:
            layout.addWidget(self._media_tabs)
            layout.addWidget(self.gallery)
            self.set_media_tab(media_tab)
        if track_count:
            layout.addWidget(track_label)
            layout.addWidget(self.track_gallery)
        self._media_tabs.currentChanged.connect(self._on_local_media_tab)
        self._refresh_cover_thumb()
        self._fit_notes()

    def values(self) -> tuple[str, int, str, str]:
        return self._kind, self._entity_id, self.title_edit.text(), self.notes_edit.toPlainText()

    def entity_kind(self) -> str:
        return self._kind

    def entity_id(self) -> int:
        return self._entity_id

    def entry_kind(self) -> str:
        return self._entry_kind

    def reset_kind_combo(self) -> None:
        self._kind_combo.blockSignals(True)
        self._kind_combo.setCurrentIndex(max(0, self._kind_combo.findData(self._entry_kind)))
        self._kind_combo.blockSignals(False)

    def _on_kind_combo(self) -> None:
        kind = str(self._kind_combo.currentData() or KIND_DAY)
        if kind == self._entry_kind:
            return
        self.kind_changed.emit(kind)

    def selected_source_ids(self) -> list[int]:
        return [item.source_file_id for item in self.selected_items()]

    def selected_items(self) -> list[GalleryItem]:
        found: list[GalleryItem] = []
        seen: set[int] = set()
        for item in (*self.gallery.selected_items(), *self.track_gallery.selected_items()):
            if item.source_file_id in seen:
                continue
            seen.add(item.source_file_id)
            found.append(item)
        return found

    def ordered_items(self) -> list[GalleryItem]:
        return [*self._all_gallery, *self.track_gallery.items()]

    def inspectable_media(self) -> list[GalleryItem]:
        return list(self._all_gallery)

    def select_ids(self, wanted: set[int]) -> None:
        self.gallery.select_by_source_ids(wanted)
        self.track_gallery.select_by_source_ids(wanted)

    def set_media_tab(self, index: int) -> None:
        index = max(0, min(index, self._media_tabs.count() - 1)) if self._media_tabs.count() else 0
        if self._media_tabs.currentIndex() != index and self._media_tabs.count():
            self._media_tabs.blockSignals(True)
            self._media_tabs.setCurrentIndex(index)
            self._media_tabs.blockSignals(False)
        self._apply_media_tab()

    def sync_rating(self, item: GalleryItem) -> None:
        self._all_gallery = [
            item if existing.source_file_id == item.source_file_id else existing
            for existing in self._all_gallery
        ]
        self._apply_media_tab()
        if self._cover_id == item.source_file_id:
            self._refresh_cover_thumb()

    def is_dirty(self) -> bool:
        return (
            self.title_edit.text() != self._loaded_title
            or self.notes_edit.toPlainText() != self._loaded_notes
        )

    def mark_clean(self) -> None:
        self._loaded_title = self.title_edit.text()
        self._loaded_notes = self.notes_edit.toPlainText()

    def youtube_key(self) -> tuple[str, int]:
        return self._kind, self._entity_id

    def youtube_urls(self) -> list[str]:
        return list(self._youtube_urls)

    def youtube_from_db(self) -> list[str]:
        return list(self._db_youtube_urls)

    def leonardo_urls(self) -> list[str]:
        return list(self._leonardo_urls)

    def cover_source_file_id(self) -> int | None:
        return self._cover_id

    def mark_youtube_clean(self) -> None:
        self._db_youtube_urls = list(self._youtube_urls)

    def _refresh_links(self) -> None:
        self.youtube_thumbs.set_urls(self._youtube_urls)
        text = links_html((), self._flights, self._leonardo_urls)
        self.links_label.setText(text)
        self.links_label.setVisible(bool(text))

    def _popup_entry_menu(self) -> None:
        self._entry_menu.exec(self._menu_button.mapToGlobal(self._menu_button.rect().bottomLeft()))

    def _on_local_media_tab(self, index: int) -> None:
        self._apply_media_tab()
        self.media_tab_changed.emit(index)

    def _apply_media_tab(self) -> None:
        wanted = _MEDIA_TABS[self._media_tabs.currentIndex()][1]
        if wanted is None:
            shown = self._all_gallery
        else:
            shown = [
                item
                for item in self._all_gallery
                if effective_sort_status(item.sort_status, item.is_favorite) == wanted
            ]
        self.gallery.set_items(shown)

    def _on_rating(self, item: object, status: str) -> None:
        if not isinstance(item, GalleryItem):
            return
        current = effective_sort_status(item.sort_status, item.is_favorite)
        next_status = None if current == status else status
        if self.workspace is not None:
            try:
                self.workspace.set_sort_status(item.source_file_id, next_status)
            except ProjectError as exc:
                QMessageBox.warning(self, "Bewertung", str(exc))
                return
        favorite = next_status == SORT_FAVORITE
        updated = replace(item, sort_status=next_status, is_favorite=favorite)
        self.sync_rating(updated)
        self.item_rating_changed.emit(updated)

    def _on_cover(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        next_id = None if self._cover_id == item.source_file_id else item.source_file_id
        if self.workspace is not None and self._entity_id > 0:
            try:
                self.workspace.set_entry_cover(self._kind, self._entity_id, next_id)
            except ProjectError as exc:
                QMessageBox.warning(self, "Titelbild", str(exc))
                return
        self._cover_id = next_id
        self._all_gallery = [
            replace(existing, is_entry_cover=existing.source_file_id == next_id)
            for existing in self._all_gallery
        ]
        self.track_gallery.set_items(
            [
                replace(existing, is_entry_cover=existing.source_file_id == next_id)
                for existing in self.track_gallery.items()
            ]
        )
        self._apply_media_tab()
        self._refresh_cover_thumb()

    def _cover_items(self) -> list[GalleryItem]:
        return [*self._all_gallery, *self.track_gallery.items()]

    def _refresh_cover_thumb(self) -> None:
        item = next((media for media in self._cover_items() if media.source_file_id == self._cover_id), None)
        if item is None or not item.thumbnail_path.is_file():
            self._cover_thumb.hide()
            self._cover_thumb.clear()
            return
        pixmap = QPixmap(str(item.thumbnail_path))
        if pixmap.isNull():
            self._cover_thumb.hide()
            self._cover_thumb.clear()
            return
        self._cover_thumb.setPixmap(
            pixmap.scaled(
                _COVER_HEAD,
                _COVER_HEAD,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._cover_thumb.show()

    def _edit_youtube(self) -> None:
        if self.workspace is None or self._entity_id == 0:
            return
        dialog = YouTubeLinksDialog(self._youtube_urls, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            stored = serialize_youtube_urls(dialog.urls())
        except ProjectError as exc:
            QMessageBox.warning(self, "YouTube-Links", str(exc))
            return
        self._youtube_urls = list(parse_youtube_urls(stored))
        self._refresh_links()

    def _request_dissolve(self) -> None:
        self.dissolve_requested.emit(self._entity_id)

    def _request_open_on_map(self) -> None:
        if self._entity_id <= 0:
            return
        if self._kind == "section":
            self.open_on_map.emit(f"section:{self._entity_id}")
            return
        if self._kind == "day":
            self.open_on_map.emit(f"day:{self._entity_id}")

    def _edit_leonardo(self) -> None:
        if self.workspace is None or self._entity_id == 0:
            return
        dialog = LeonardoLinksDialog(self._flights, self._leonardo_urls, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            igc_urls = {
                source_id: (normalize_leonardo_url(url) if url else "")
                for source_id, url in dialog.values().items()
            }
            for source_id, url in igc_urls.items():
                self.workspace.set_gps_track_url(source_id, url or None)
            if self._entity_id > 0:
                self.workspace.save_leonardo_urls(self._kind, self._entity_id, dialog.extra_urls())
        except (ProjectError, ValueError) as exc:
            QMessageBox.warning(self, "DHV-Leonardo", str(exc))
            return
        self._flights = [
            (source_id, filename, igc_urls.get(source_id, url)) for source_id, filename, url in self._flights
        ]
        stored = serialize_leonardo_urls(dialog.extra_urls())
        self._leonardo_urls = list(parse_leonardo_urls(stored))
        self._refresh_links()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_notes()

    def _fit_notes(self) -> None:
        document = self.notes_edit.document()
        document.setTextWidth(max(self.notes_edit.viewport().width(), 100))
        margins = self.notes_edit.contentsMargins()
        height = int(document.size().height()) + margins.top() + margins.bottom() + 16
        self.notes_edit.setFixedHeight(max(88, height))


class NewSectionDialog(QDialog):
    def __init__(self, items: list[GalleryItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neuer Reiseabschnitt")
        times = [item.captured_at for item in items if item.captured_at is not None]
        started = min(times) if times else None
        ended = max(times) if times else None
        self._form = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItem("Aufenthalt", KIND_STAY)
        self.kind.addItem("Transfer", KIND_MOVEMENT)
        self.kind.currentIndexChanged.connect(self._sync_kind)
        self.mode = ModePicker(self)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("z. B. Besuch von Berlin")
        self.location_name = QLineEdit()
        self.location_name.setPlaceholderText("Ort des Aufenthalts")
        self.location_from = QLineEdit()
        self.location_from.setPlaceholderText("von")
        self.location_to = QLineEdit()
        self.location_to.setPlaceholderText("nach")
        span = QLabel(format_section_span(started, ended))
        span.setObjectName("pageSubtitle")
        self._form.addRow("Typ", self.kind)
        self._form.addRow("Transfer per", self.mode)
        self._form.addRow("Titel", self.title_edit)
        self._form.addRow("Ort", self.location_name)
        self._form.addRow("Von", self.location_from)
        self._form.addRow("Nach", self.location_to)
        self._form.addRow("Zeit aus Objekten", span)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._form.addRow(buttons)
        self._sync_kind()

    def _set_row_visible(self, field: QWidget, visible: bool) -> None:
        field.setVisible(visible)
        label = self._form.labelForField(field)
        if label is not None:
            label.setVisible(visible)

    def _sync_kind(self) -> None:
        movement = self.kind.currentData() == KIND_MOVEMENT
        self._set_row_visible(self.mode, movement)
        self._set_row_visible(self.location_from, movement)
        self._set_row_visible(self.location_to, movement)
        self._set_row_visible(self.location_name, not movement)

    def values(self) -> dict[str, str | None]:
        kind = str(self.kind.currentData())
        movement = kind == KIND_MOVEMENT
        mode = self.mode.serialized() if movement else None
        return {
            "kind": kind,
            "mode": mode,
            "title": self.title_edit.text().strip() or None,
            "notes": None,
            "location_name": None if movement else (self.location_name.text().strip() or None),
            "location_from": (self.location_from.text().strip() or None) if movement else None,
            "location_to": (self.location_to.text().strip() or None) if movement else None,
        }


def _section_heading(section: TimelineSection) -> str:
    span = format_section_span(section.started_at, section.ended_at)
    if section.kind == KIND_MOVEMENT:
        bits = ["Transfer"]
        modes = _format_modes(section.mode)
        if modes:
            bits.append(modes)
        if section.location_from or section.location_to:
            start = section.location_from or "?"
            end = section.location_to or "?"
            bits.append(f"{start} → {end}")
        bits.append(span)
        return " · ".join(bits)
    place = f" in {section.location_name}" if section.location_name else ""
    return f"Aufenthalt{place} · {span}"


def _format_modes(raw: str | None) -> str:
    labels = dict(_MODE_LABELS)
    return ", ".join(labels.get(value, value) for value in parse_modes(raw))


class ModePicker(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(4)
        self._boxes: list[tuple[str, QCheckBox]] = []
        for index, (value, label) in enumerate(_MODE_LABELS):
            box = QCheckBox(label, self)
            self._boxes.append((value, box))
            layout.addWidget(box, index // 4, index % 4)

    def serialized(self) -> str | None:
        return serialize_modes([value for value, box in self._boxes if box.isChecked()])


def _leftover_heading(day: TimelineDay, *, leftover: bool) -> str:
    del leftover
    date_text = day.date.strftime("%d.%m.%Y") if day.date is not None else "Ohne Datum"
    origin = "manuell" if day.origin == "manual" else "automatisch"
    return f"{date_text} · {origin}"


def _gallery_item(photo: TimelinePhoto, *, cover_id: int | None = None) -> GalleryItem:
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
        sort_status=photo.sort_status,
        is_entry_cover=cover_id == photo.source_file_id,
        rotation_degrees=photo.rotation_degrees,
    )


def split_media_and_tracks(
    items: tuple[TimelinePhoto, ...] | list[TimelinePhoto],
) -> tuple[list[TimelinePhoto], list[TimelinePhoto]]:
    media: list[TimelinePhoto] = []
    tracks: list[TimelinePhoto] = []
    for item in items:
        if item.file_kind == FileKind.GPS.value:
            tracks.append(item)
        else:
            media.append(item)
    return media, tracks
