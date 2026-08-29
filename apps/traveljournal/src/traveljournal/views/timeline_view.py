"""Chronological trip overview. Originals are never written."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, QEvent, QObject, QPoint, Qt, QTime, QTimer, Signal
from PySide6.QtGui import (
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
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
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from travelcore.maps.groups import parse_group_key
from travelcore.media.gallery import (
    SORT_FAVORITE,
    GalleryItem,
    effective_sort_status,
)
from travelcore.media.types import GPS_EXTENSIONS, PHOTO_EXTENSIONS, FileKind
from travelcore.project_settings import DEFAULT_STAY_LINK_COLOR
from travelcore.timeline.build import apply_pending_sections
from travelcore.timeline.journal import calendar_key
from travelcore.timeline.links import (
    is_igc_filename,
    normalize_leonardo_url,
    parse_leonardo_urls,
    parse_youtube_urls,
    serialize_leonardo_urls,
    serialize_youtube_urls,
    youtube_thumbnail_url,
)
from travelcore.timeline.sections import (
    KIND_DAY,
    KIND_MOVEMENT,
    KIND_STAY,
    expand_range_selection,
    format_card_dates,
    format_scroll_date,
    format_section_span,
    insert_dates_between,
    parse_modes,
    serialize_modes,
    span_for_manual_dates,
)
from travelcore.timeline.symbols import TRANSPORT_SYMBOLS
from travelcore.timeline.transfer_links import LINK_GEOMETRY_ARC, LINK_GEOMETRY_LINE, links_from_modes
from travelcore.timeline.types import (
    PendingSectionSpec,
    TimelineEntry,
    TimelineLink,
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
    start_remote_pixmap,
)
from traveljournal.widgets.gallery import GalleryView, source_ids_from_mime
from traveljournal.widgets.join_plus import TimelineSpine as TimelineJoin
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
from traveljournal.widgets.scroll_date import scrollbar_slider_rect as _scrollbar_slider_rect
from traveljournal.widgets.transfer_links import OutboundLinkRow, TransferLinkStrip

_REVEAL_TOP_PAD = 0
_REVEAL_RETRY_MS = (0, 32, 80, 160, 320)


def scroll_offset_to_widget_top(host: QWidget, child: QWidget, *, padding: int = _REVEAL_TOP_PAD) -> int:
    """Scrollbar value that puts ``child``'s top flush with the top of the scroll host."""

    top = child.mapTo(host, QPoint(0, 0)).y()
    return max(0, top - padding)


def scroll_delta_to_widget_top(child: QWidget, viewport: QWidget, *, padding: int = _REVEAL_TOP_PAD) -> int:
    """How much to add to the scrollbar so ``child``'s top sits at the viewport top."""

    return child.mapTo(viewport, QPoint(0, 0)).y() - padding


def span_index_at_mid(spans: list[tuple[int, int]], mid: int) -> int | None:
    """Index of the span that contains ``mid``, else the nearest by center."""

    if not spans:
        return None
    for index, (top, bottom) in enumerate(spans):
        if top <= mid < bottom:
            return index
    best = 0
    best_dist = abs((spans[0][0] + spans[0][1]) / 2 - mid)
    for index, (top, bottom) in enumerate(spans[1:], start=1):
        dist = abs((top + bottom) / 2 - mid)
        if dist < best_dist:
            best = index
            best_dist = dist
    return best


def timeline_center_date(blocks: list[EntryWidget], host: QWidget, mid_y: int) -> str | None:
    """Date of the section that occupies vertical host coordinate ``mid_y``."""

    if not blocks:
        return None
    spans: list[tuple[int, int]] = []
    for block in blocks:
        top = block.mapTo(host, QPoint(0, 0)).y()
        spans.append((top, top + block.height()))
    index = span_index_at_mid(spans, mid_y)
    if index is None:
        return None
    return blocks[index].scroll_date()


_MODE_LABELS = tuple((item.key, item.label) for item in TRANSPORT_SYMBOLS)
_COVER_HEAD = 168
_GALLERY_DRAG_HINT = (
    "Ziehen auf eine andere Karte oder in den Pool. T oben links: Titelbild für diesen Tag oder Abschnitt"
)
_TIMELINE_JOIN_H = 64
_AUTOSCROLL_MARGIN = 72
_AUTOSCROLL_MAX_STEP = 28
_AUTOSCROLL_INTERVAL_MS = 40


def autoscroll_step(
    y: int,
    height: int,
    *,
    margin: int = _AUTOSCROLL_MARGIN,
    max_step: int = _AUTOSCROLL_MAX_STEP,
) -> int:
    """Pixels to add to a vertical scrollbar while dragging. Negative is up.

    ``y`` is the pointer position in a strip of ``height`` (timeline viewport
    or window). Positions above 0 or below ``height`` use full speed so the
    list keeps moving when the cursor leaves the column at the window edge.
    """

    if height <= 0 or max_step <= 0:
        return 0
    band = min(margin, max(1, height // 3))
    if y < 0:
        return -max_step
    if y > height:
        return max_step
    if y < band:
        strength = 1.0 - (y / band)
        return -max(1, round(max_step * strength))
    below = height - y
    if below < band:
        strength = 1.0 - (below / band)
        return max(1, round(max_step * strength))
    return 0


class SectionKindCombo(QComboBox):
    """Type picker whose popup always shows Tag, Aufenthalt and Transfer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaxVisibleItems(3)

    def showPopup(self) -> None:  # noqa: N802
        super().showPopup()
        view = self.view()
        if view is None or self.count() == 0:
            return
        row_h = max(view.sizeHintForRow(0), 28)
        height = row_h * min(3, self.count()) + 6
        view.setFixedHeight(height)
        container = view.parentWidget()
        if container is not None:
            extra = max(4, container.height() - view.height())
            container.setFixedHeight(height + extra)


def _shows_outbound(entry: TimelineEntry, following: TimelineEntry | None) -> bool:
    if following is None or entry.section is None or entry.card_kind == KIND_MOVEMENT:
        return False
    return following.card_kind != KIND_MOVEMENT


def _copy_pending_spec(spec: PendingSectionSpec) -> PendingSectionSpec:
    return replace(
        spec,
        source_file_ids=tuple(spec.source_file_ids),
        youtube_urls=tuple(spec.youtube_urls),
        leonardo_urls=tuple(spec.leonardo_urls),
    )


class TimelineView(QWidget):
    status_message = Signal(str)
    timeline_changed = Signal()
    open_on_map = Signal(str)
    open_media_on_map = Signal(str, int)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._snapshot: TimelineSnapshot | None = None
        self._base_snapshot: TimelineSnapshot | None = None
        self._pending: list[PendingSectionSpec] = []
        self._pending_youtube: dict[tuple[str, int], list[str]] = {}
        self._next_pending_id = -1
        self._blocks: list[EntryWidget] = []
        self._joins: list[TimelineJoin] = []
        self._loading = False
        self._applying_range = False
        self._excluded_ids: set[int] = set()
        self._displayed_selection: set[int] = set()
        self._syncing_tabs = False
        self._loaded_trip_title = ""
        self._pending_reveal: EntryWidget | None = None
        self._media_ratings_stale = False
        self._media_tab_touched = False

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
        self._trip_title.textChanged.connect(self._update_save_button)
        trip_row.addWidget(trip_label)
        trip_row.addWidget(self._trip_title, 1)
        root.addLayout(trip_row)

        self._subtitle = QLabel(
            "Tage, Transfers und Aufenthalte chronologisch untereinander. "
            "Typ je Karte ändern, Objekte markieren und einen Abschnitt anlegen, "
            "oder ohne Auswahl einen leeren Abschnitt mit Datum erzeugen "
            "(Tag: am, Aufenthalt/Transfer: von–bis). "
            "⋯-Menü löscht einen Abschnitt; die Medien landen im Pool. "
            "Pfeil rechts außen klappt den Medienpool ein und aus; die Breite bleibt erhalten."
        )
        self._subtitle.setObjectName("pageSubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(self._subtitle)

        toolbar = QHBoxLayout()
        refresh = QPushButton("Timeline aktualisieren")
        refresh.clicked.connect(self.rebuild)
        self._create_button = QPushButton("Neuen Reiseabschnitt erstellen")
        self._create_button.clicked.connect(self._create_section)
        self._park_button = QPushButton("In den Pool")
        self._park_button.setToolTip("Ausgewählte Medien aus dem Tagebuch nehmen")
        self._park_button.clicked.connect(self._park_selected)
        self._journal_button = QPushButton("Journal-Zeit…")
        self._journal_button.setToolTip("Ausgewählte Medien auf der Timeline-Uhr verschieben")
        self._journal_button.clicked.connect(self._set_journal_time)
        self._reset_button = QPushButton("Originalzeit")
        self._reset_button.setToolTip("Journal-Zeit auf die Aufnahmezeit zurücksetzen")
        self._reset_button.clicked.connect(self._reset_journal_time)
        self._save_button = QPushButton("Speichern")
        self._save_button.setObjectName("primary")
        self._save_button.clicked.connect(self._on_save_clicked)
        self._media_tabs = ClickTabBar(self)
        self._media_tabs.setObjectName("mediaSortTabs")
        self._media_tabs.setExpanding(False)
        for label, _status in RATING_TABS:
            self._media_tabs.addTab(label)
        self._media_tabs.setCurrentIndex(media_tab_index(self.workspace.timeline_media_tab(), RATING_TABS))
        self._media_tabs.currentChanged.connect(self._on_global_media_tab)
        self._show_rejected = ShowRejectedCheck(self)
        self._show_rejected.toggled.connect(self._on_show_rejected)
        tab_label = QLabel("Register")
        tab_label.setObjectName("pageSubtitle")
        toolbar.addWidget(refresh)
        toolbar.addWidget(self._create_button)
        toolbar.addWidget(self._park_button)
        toolbar.addWidget(self._journal_button)
        toolbar.addWidget(self._reset_button)
        toolbar.addSpacing(16)
        toolbar.addWidget(tab_label)
        toolbar.addWidget(self._media_tabs)
        toolbar.addWidget(self._show_rejected)
        toolbar.addStretch(1)
        toolbar.addWidget(self._save_button)
        root.addLayout(toolbar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 8, 0)
        self._host_layout.setSpacing(0)
        self._empty = QLabel("Bitte ein Projekt öffnen.")
        self._empty.setObjectName("pageSubtitle")
        self._empty.setWordWrap(True)
        self._host_layout.addWidget(self._empty)
        self._tail = QWidget(self._host)
        self._tail.setObjectName("timelineRevealTail")
        self._host_layout.addWidget(self._tail)
        self._scroll.setWidget(self._host)
        self._preserve_scroll = True
        self._revealing = False
        self._scroll_slider_down = False
        self._scroll_date = QLabel(self._scroll)
        self._scroll_date.setObjectName("timelineScrollDate")
        self._scroll_date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll_date.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._scroll_date.hide()
        self._scroll_hide = QTimer(self)
        self._scroll_hide.setSingleShot(True)
        self._scroll_hide.setInterval(900)
        self._scroll_hide.timeout.connect(self._scroll_date.hide)
        bar = self._scroll.verticalScrollBar()
        bar.valueChanged.connect(self._on_timeline_scroll)
        bar.actionTriggered.connect(self._on_scroll_action)
        bar.sliderPressed.connect(self._on_scroll_slider_pressed)
        bar.sliderReleased.connect(self._on_scroll_slider_released)
        bar.rangeChanged.connect(self._on_scroll_range_changed)
        self._scroll.installEventFilter(self)
        self._pool_pane = PoolPane(
            workspace=self.workspace,
            accept_drops=True,
            gallery_drag_hint=("Medien einer Karte hierher ziehen; aus dem Pool auf einen Abschnitt legen."),
        )
        self._pool_pane.unpark_requested.connect(self._unpark_selected)
        self._pool_pane.item_rating_changed.connect(self._on_item_rating)
        self._pool_pane.gallery.item_activated.connect(self._open_inspector)
        self._pool_pane.show_rejected_changed.connect(self._on_pool_show_rejected)
        self._pool_pane.items_dropped.connect(self._drop_on_timeline_pool)
        self._drag_scroll = QTimer(self)
        self._drag_scroll.setInterval(_AUTOSCROLL_INTERVAL_MS)
        self._drag_scroll.timeout.connect(self._on_drag_scroll_tick)
        self._wire_drag_scroll(self._pool_pane.gallery)
        self._split = QSplitter(Qt.Orientation.Horizontal)
        self._split.setObjectName("timelineSplit")
        self._split.setChildrenCollapsible(False)
        self._split.addWidget(self._scroll)
        self._split.addWidget(self._pool_pane)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 0)
        root.addWidget(self._split, 1)
        self._pool_collapse = PoolCollapse(self, self._split, self._pool_pane, self.workspace)
        self._pool_toggle = self._pool_collapse.toggle
        self._sync_show_rejected()
        self._save_button.setEnabled(False)
        self._create_button.setEnabled(False)
        self._park_button.setEnabled(False)
        self._journal_button.setEnabled(False)
        self._reset_button.setEnabled(False)

    def rebuild(self) -> None:
        self.workspace.history.clear()
        self._pending_youtube.clear()
        self.refresh(rebuild=True)
        self.timeline_changed.emit()

    def ensure_loaded(self) -> None:
        self._propagate_media_tab(
            media_tab_index(self.workspace.timeline_media_tab(), RATING_TABS), persist=False
        )
        self._sync_show_rejected()
        self._pool_pane.sync_tab_from_workspace()
        if self._snapshot is None or self._media_ratings_stale:
            self.refresh()
            self._media_ratings_stale = False

    def apply_media_rating(self, item: object) -> None:
        """Take a rating from the Medien page into already loaded timeline cards."""

        self._media_ratings_stale = True
        if not isinstance(item, GalleryItem):
            return
        loaded = self._snapshot is not None
        if item.parked:
            if loaded and not self._pool_pane.contains(item.source_file_id):
                self.refresh()
                return
        elif loaded and not self._item_on_timeline(item.source_file_id):
            self.refresh()
            return
        self._on_item_rating(item)

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

    def refresh(self, rebuild: bool = False, *, commit: bool = True) -> None:
        if commit:
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
        self._apply_pending_view(sync=commit)

    def _apply_pending_view(self, *, sync: bool = True) -> None:
        if sync:
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
        leftover = sum(1 for entry in shown.entries if entry.card_kind == KIND_DAY)
        sections = sum(1 for entry in shown.entries if entry.card_kind != KIND_DAY)
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
            self._clear_entry_rows()
            if self.workspace.current is None:
                self._empty.setVisible(True)
                self._empty.setText("Bitte ein Projekt öffnen.")
                self._create_button.setEnabled(False)
                self._park_button.setEnabled(False)
                self._journal_button.setEnabled(False)
                self._reset_button.setEnabled(False)
                self._pool_pane.set_items([])
                return
            parked = self._parked_items()
            self._pool_pane.set_items(parked)
            entries = self._snapshot.entries if self._snapshot is not None else ()
            if self._snapshot is None:
                self._empty.setVisible(True)
                self._empty.setText("Index wird geladen…")
            elif not entries:
                self._empty.setVisible(True)
                self._empty.setText("Keine Tage in der Timeline.")
            else:
                self._empty.setVisible(False)
            has_sections = bool(self._snapshot.sections) if self._snapshot is not None else False
            insert_at = max(self._host_layout.count() - 1, 0)
            join_color = self._join_color()
            for index, entry in enumerate(entries):
                if index:
                    previous = entries[index - 1]
                    start, end = insert_dates_between(
                        _entry_span_dates(previous)[1],
                        _entry_span_dates(entry)[0],
                    )
                    join = TimelineJoin(join_color, self._host)
                    join.add_requested.connect(
                        lambda start=start, end=end: self._create_section_at_join(start, end)
                    )
                    self._joins.append(join)
                    self._host_layout.insertWidget(insert_at, join)
                    insert_at += 1
                override = None
                if entry.section is not None:
                    override = self._pending_youtube.get(("section", entry.section.id))
                elif entry.leftover_day is not None:
                    override = self._pending_youtube.get(("day", entry.leftover_day.id))
                following = entries[index + 1] if index + 1 < len(entries) else None
                block = EntryWidget(
                    entry,
                    workspace=self.workspace,
                    show_as_leftover=has_sections,
                    youtube_override=override,
                    show_outbound=_shows_outbound(entry, following),
                    media_tab=self._media_tabs.currentIndex(),
                    parent=self._host,
                )
                block.selection_changed.connect(self._on_block_selection_changed)
                block.dissolve_requested.connect(self._dissolve_section)
                block.delete_requested.connect(self._delete_section)
                block.span_requested.connect(self._edit_section_span)
                block.journal_changed.connect(self._on_journal_changed)
                block.kind_changed.connect(lambda kind, widget=block: self._change_entry_kind(widget, kind))
                block.media_tab_changed.connect(self._on_block_media_tab)
                block.item_rating_changed.connect(self._on_item_rating)
                block.open_on_map.connect(self.open_on_map.emit)
                block.open_media_on_map.connect(self.open_media_on_map.emit)
                block.content_changed.connect(self._update_save_button)
                block.pool_dropped.connect(lambda ids, widget=block: self._drop_pool_on_entry(widget, ids))
                block.gallery.item_activated.connect(self._open_inspector)
                block.track_gallery.item_activated.connect(self._open_inspector)
                self._wire_drag_scroll(block.gallery)
                self._wire_drag_scroll(block.track_gallery)
                self._blocks.append(block)
                self._host_layout.insertWidget(insert_at, block)
                insert_at += 1
            self._update_create_button()
            self._propagate_media_tab(self._media_tabs.currentIndex(), persist=False)
        finally:
            self._host.setUpdatesEnabled(True)
            self._loading = False
            self._excluded_ids.clear()
            self._displayed_selection = set(self._selected_source_ids())
            self._sync_reveal_tail()
            if self._preserve_scroll:
                self._scroll.verticalScrollBar().setValue(scroll)
            self._preserve_scroll = True
            self._update_save_button()

    def _clear_entry_rows(self) -> None:
        for widget in (*self._blocks, *self._joins):
            widget.hide()
            self._host_layout.removeWidget(widget)
            widget.deleteLater()
        self._blocks.clear()
        self._joins.clear()

    def _join_color(self) -> str:
        try:
            return self.workspace.map_link_color()
        except ProjectError:
            return DEFAULT_STAY_LINK_COLOR

    def _parked_items(self) -> list[GalleryItem]:
        if self.workspace.current is None:
            return []
        return [item for item in self.workspace.gallery_items() if item.parked]

    def _update_create_button(self) -> None:
        has_selection = bool(self._selected_source_ids())
        self._create_button.setEnabled(self._snapshot is not None)
        self._create_button.setToolTip(
            "Ausgewählte Medien in einem neuen Abschnitt zusammenfassen"
            if has_selection
            else "Leeren Abschnitt mit Datum (Tag: am, Aufenthalt/Transfer: von–bis) anlegen"
        )
        self._park_button.setEnabled(has_selection)
        self._journal_button.setEnabled(has_selection)
        self._reset_button.setEnabled(has_selection)

    def _set_pool_visible(self, visible: bool) -> None:
        self._pool_collapse.set_visible(visible)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._pool_collapse.place()
        self._sync_reveal_tail()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._pool_collapse.sync_from_workspace()

    def _on_global_media_tab(self, index: int) -> None:
        self._media_tab_touched = True
        self._propagate_media_tab(index, persist=True)

    def _on_block_media_tab(self, index: int) -> None:
        self._media_tab_touched = True
        self._propagate_media_tab(index, persist=True)

    def _propagate_media_tab(self, index: int, *, persist: bool) -> None:
        if self._syncing_tabs:
            return
        index = max(0, min(index, len(RATING_TABS) - 1))
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
        self._sync_show_rejected()

    def _sync_show_rejected(self) -> None:
        sync_show_rejected_check(
            self._show_rejected, self._media_tabs, checked=self.workspace.show_rejected_in_all()
        )

    def _on_show_rejected(self, checked: bool) -> None:
        self.workspace.set_show_rejected_in_all(checked)
        for block in self._blocks:
            block._apply_media_tab()
        self._pool_pane.refresh_rating_filter()

    def _on_pool_show_rejected(self, _checked: bool) -> None:
        self._sync_show_rejected()
        for block in self._blocks:
            block._apply_media_tab()

    def _persist_media_tab(self) -> None:
        self.workspace.set_timeline_media_tab(media_tab_key(self._media_tabs.currentIndex()))

    def _open_inspector(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        sequence = [item]
        sender = self.sender()
        if isinstance(sender, GalleryView):
            parent = sender.parent()
            if isinstance(parent, EntryWidget):
                if sender is parent.gallery:
                    sequence = parent.inspectable_media()
                elif sender is parent.track_gallery:
                    sequence = parent.track_gallery.items()
            elif isinstance(parent, PoolPane):
                sequence = parent.gallery.items()
        window = MediaInspectorWindow(item, items=sequence, workspace=self.workspace, parent=self.window())
        window.rating_changed.connect(self._on_item_rating)
        window.rotation_changed.connect(self._on_item_rating)
        window.park_changed.connect(self._on_inspector_park)
        window.show()
        window.raise_()
        window.activateWindow()

    def _on_item_rating(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        for block in self._blocks:
            block.sync_rating(item)
        if self._pool_pane.contains(item.source_file_id):
            self._pool_pane.sync_rating(item)
        parent = self.window()
        if parent is None:
            return
        for inspector in parent.findChildren(MediaInspectorWindow):
            inspector.sync_from_item(item)

    def _on_inspector_park(self, item: object) -> None:
        if not isinstance(item, GalleryItem):
            return
        self.refresh()
        self.timeline_changed.emit()
        if item.parked:
            self._set_pool_visible(True)
        self.status_message.emit("Medium im Pool." if item.parked else "Medium zurück in der Timeline.")

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

    def create_section_between(self, start: date, end: date) -> bool:
        if not self._commit_if_dirty():
            return False
        dialog = EmptySectionDialog(start, self, until=end)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._append_pending_section(dialog.values(), ())
        return True

    def _create_section_at_join(self, start: date, end: date) -> None:
        self.create_section_between(start, end)

    def _create_section(self) -> None:
        source_ids = self._selected_source_ids()
        if not self._commit_if_dirty():
            return
        if source_ids:
            dialog = NewSectionDialog(self._selected_items(), self)
        else:
            chosen = self._default_section_date()
            dialog = EmptySectionDialog(chosen, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._append_pending_section(dialog.values(), source_ids)

    def _append_pending_section(
        self,
        payload: dict[str, object],
        source_ids: list[int] | tuple[int, ...],
    ) -> None:
        started = payload.get("started_at")
        ended = payload.get("ended_at")
        spec = PendingSectionSpec(
            local_id=self._next_pending_id,
            source_file_ids=tuple(source_ids),
            kind=str(payload["kind"]),
            mode=payload.get("mode") if isinstance(payload.get("mode"), str) else None,
            title=payload.get("title") if isinstance(payload.get("title"), str) else None,
            notes=payload.get("notes") if isinstance(payload.get("notes"), str) else None,
            location_name=payload.get("location_name")
            if isinstance(payload.get("location_name"), str)
            else None,
            location_from=payload.get("location_from")
            if isinstance(payload.get("location_from"), str)
            else None,
            location_to=payload.get("location_to") if isinstance(payload.get("location_to"), str) else None,
            started_at=started if isinstance(started, datetime) else None,
            ended_at=ended if isinstance(ended, datetime) else None,
            links=_links_from_payload(payload),
        )
        index = len(self._pending)
        self._pending.append(spec)
        self._next_pending_id -= 1
        self._record_pending_insert(_copy_pending_spec(spec), index)
        self._apply_pending_view()
        self.status_message.emit("Reiseabschnitt angelegt. Speichern, sonst geht er verloren.")

    def _default_section_date(self) -> date:
        if self._snapshot is not None:
            for entry in reversed(self._snapshot.entries):
                key = calendar_key(entry.started_at)
                if key is not None:
                    return key
        return date.today()

    def _dissolve_section(self, section_id: int) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Reiseabschnitt auflösen")
        box.setText(
            "Diesen Reiseabschnitt auflösen? Die Medien werden nach Journal-Zeit wieder Tagen zugeordnet."
        )
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Ok).setText("OK")
        box.button(QMessageBox.StandardButton.Cancel).setText("Abbrechen")
        if box.exec() != QMessageBox.StandardButton.Ok:
            return False
        self._pending_youtube.pop(("section", section_id), None)
        if section_id < 0:
            removed = next((spec for spec in self._pending if spec.local_id == section_id), None)
            index = next((i for i, spec in enumerate(self._pending) if spec.local_id == section_id), 0)
            self._pending = [spec for spec in self._pending if spec.local_id != section_id]
            if removed is not None:
                self._record_pending_remove(
                    _copy_pending_spec(removed), index, title="Abschnitt auflösen"
                )
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

    def _delete_section(self, section_id: int) -> bool:
        pending = section_id < 0
        box = QMessageBox(self)
        box.setWindowTitle("Reiseabschnitt löschen")
        if pending:
            box.setText("Diesen noch nicht gespeicherten Abschnitt verwerfen?")
        else:
            box.setText("Diesen Reiseabschnitt löschen? Alle Medien landen im Medienpool.")
        box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Ok).setText("OK")
        box.button(QMessageBox.StandardButton.Cancel).setText("Abbrechen")
        if box.exec() != QMessageBox.StandardButton.Ok:
            return False
        self._pending_youtube.pop(("section", section_id), None)
        if pending:
            removed = next((spec for spec in self._pending if spec.local_id == section_id), None)
            index = next((i for i, spec in enumerate(self._pending) if spec.local_id == section_id), 0)
            self._pending = [spec for spec in self._pending if spec.local_id != section_id]
            if removed is not None:
                self._record_pending_remove(_copy_pending_spec(removed), index)
            self._apply_pending_view()
            self.status_message.emit("Reiseabschnitt verworfen.")
            return True
        try:
            self.workspace.delete_section(section_id)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return False
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Reiseabschnitt gelöscht. Medien liegen im Pool.")
        self._set_pool_visible(True)
        return True

    def _edit_section_span(self, section_id: int) -> None:
        section = self._section_by_id(section_id)
        if section is None:
            return
        dialog = SectionSpanDialog(section.kind, section.started_at, section.ended_at, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        started, ended = dialog.span()
        done = "Datum gesetzt." if section.kind == KIND_DAY else "Zeitraum gesetzt."
        if section_id < 0:
            self._sync_pending_from_widgets()
            for spec in self._pending:
                if spec.local_id != section_id:
                    continue
                previous = (spec.started_at, spec.ended_at)
                spec.started_at = started
                spec.ended_at = ended
                self._record_pending_span(spec, previous, (started, ended))
                break
            self._apply_pending_view()
            self.status_message.emit(f"{done} Speichern, sonst geht die Änderung verloren.")
            return
        if not self._commit_if_dirty():
            return
        try:
            self.workspace.set_section_span(section_id, started, ended)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit(done)

    def _section_by_id(self, section_id: int) -> TimelineSection | None:
        if self._snapshot is None:
            return None
        for entry in self._snapshot.entries:
            if entry.section is not None and entry.section.id == section_id:
                return entry.section
        return None

    def _park_selected(self) -> None:
        ids = self._selected_source_ids()
        if not ids:
            return
        self._park_ids(ids)

    def _park_ids(self, source_ids: list[int]) -> None:
        ids = list(dict.fromkeys(source_ids))
        if not ids:
            return
        try:
            self.workspace.park_media(ids)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit(f"{len(ids)} Medien im Pool.")
        self._set_pool_visible(True)

    def _unpark_selected(self) -> None:
        ids = self._pool_pane.selected_source_ids()
        if not ids:
            return
        try:
            self.workspace.unpark_media(ids)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit(f"{len(ids)} Medien zurück in der Timeline.")

    def _drop_on_timeline_pool(self, source_ids: list[int]) -> None:
        ids = [
            source_id for source_id in dict.fromkeys(source_ids) if not self._pool_pane.contains(source_id)
        ]
        if not ids:
            return
        self._park_ids(ids)

    def _drop_pool_on_entry(self, block: EntryWidget, source_ids: list[int]) -> None:
        ids = [
            source_id for source_id in dict.fromkeys(source_ids) if source_id not in block.member_source_ids()
        ]
        if not ids:
            return
        if not block.accepts_pool_drop():
            QMessageBox.information(
                self,
                "Timeline",
                "Bitte auf einen gespeicherten Tag, Transfer oder Aufenthalt legen.",
            )
            return
        if not self._commit_if_dirty():
            return
        keep_gps = self._confirm_keep_gps(ids, block)
        if keep_gps is None:
            return
        try:
            self.workspace.move_members(block.entity_id(), ids, keep_gps=keep_gps)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit(f"{len(ids)} Medien dem Abschnitt zugeordnet.")

    def _incoming_gps_count(self, source_ids: list[int]) -> int:
        wanted = set(source_ids)
        return sum(
            1
            for item in self.workspace.gallery_items()
            if item.source_file_id in wanted
            and item.gps_latitude is not None
            and item.gps_longitude is not None
        )

    def _section_has_map_anchor(self, block: EntryWidget, incoming: set[int]) -> bool:
        if not block.accepts_pool_drop():
            return False
        return any(
            item.source_file_id not in incoming and _gallery_item_has_map_position(item)
            for item in block.ordered_items()
        )

    def _confirm_keep_gps(self, source_ids: list[int], block: EntryWidget) -> bool | None:
        gps_count = self._incoming_gps_count(source_ids)
        if gps_count == 0 or not self._section_has_map_anchor(block, set(source_ids)):
            return True
        box = QMessageBox(self)
        box.setWindowTitle("GPS auf der Karte")
        if gps_count == 1:
            box.setText(
                "Dieses Medium hat eigene GPS-Koordinaten — etwa ein Foto, das zu Hause "
                "aufgenommen wurde. Auf der Karte die Originalposition behalten oder die "
                "Position des Abschnitts verwenden?"
            )
        else:
            box.setText(
                f"{gps_count} Medien haben eigene GPS-Koordinaten — etwa Fotos, die zu Hause "
                "aufgenommen wurden. Auf der Karte die Originalposition behalten oder die "
                "Position des Abschnitts verwenden? Mehrere Medien liegen dann leicht versetzt, "
                "nicht genau übereinander."
            )
        keep_btn = box.addButton("GPS behalten", QMessageBox.ButtonRole.YesRole)
        adopt_btn = box.addButton("Abschnittsposition", QMessageBox.ButtonRole.NoRole)
        box.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == keep_btn:
            return True
        if clicked == adopt_btn:
            return False
        return None

    def _item_on_timeline(self, source_file_id: int) -> bool:
        return any(
            any(existing.source_file_id == source_file_id for existing in block.ordered_items())
            for block in self._blocks
        )

    def _on_journal_changed(self) -> None:
        self.refresh()
        self.timeline_changed.emit()

    def _set_journal_time(self) -> None:
        items = self._selected_items()
        if not items:
            return
        stamps = [item.journal_at or item.captured_at for item in items]
        stamps = [item for item in stamps if item is not None]
        initial = min(stamps) if stamps else datetime.now(tz=UTC)
        dialog = JournalTimeDialog(initial, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.workspace.set_journal_at([item.source_file_id for item in items], dialog.value())
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Journal-Zeit gesetzt.")

    def _reset_journal_time(self) -> None:
        ids = self._selected_source_ids()
        if not ids:
            return
        try:
            self.workspace.reset_journal(ids)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Journal-Zeit auf Aufnahmezeit zurückgesetzt.")

    def _change_entry_kind(self, block: EntryWidget, kind: str) -> None:
        current = block.entry_kind()
        if kind == current:
            return
        if block.entity_id() < 0:
            if kind == KIND_DAY:
                if not self._dissolve_section(block.entity_id()):
                    block.reset_kind_combo()
                return
            for spec in self._pending:
                if spec.local_id == block.entity_id():
                    previous = (
                        spec.kind,
                        spec.mode,
                        spec.location_name,
                        spec.location_from,
                        spec.location_to,
                        spec.links,
                        spec.outbound,
                    )
                    spec.kind = kind
                    if kind != KIND_MOVEMENT:
                        spec.mode = None
                        spec.location_from = None
                        spec.location_to = None
                        if spec.outbound is None:
                            spec.outbound = next(
                                (
                                    item
                                    for item in spec.links
                                    if item.geometry in {LINK_GEOMETRY_LINE, LINK_GEOMETRY_ARC}
                                ),
                                None,
                            )
                        spec.links = ()
                    else:
                        spec.location_name = None
                        if (
                            not spec.links
                            and spec.outbound is not None
                            and spec.outbound.geometry in {LINK_GEOMETRY_LINE, LINK_GEOMETRY_ARC}
                        ):
                            spec.links = (spec.outbound,)
                        spec.outbound = None
                    self._record_pending_kind(
                        spec,
                        previous,
                        (
                            spec.kind,
                            spec.mode,
                            spec.location_name,
                            spec.location_from,
                            spec.location_to,
                            spec.links,
                            spec.outbound,
                        ),
                    )
                    break
            self._apply_pending_view()
            return
        if current == KIND_DAY and kind == KIND_DAY:
            return
        try:
            self.workspace.update_section_kind(block.entity_id(), kind)
        except ProjectError as exc:
            if kind == KIND_DAY:
                if not self._dissolve_section(block.entity_id()):
                    block.reset_kind_combo()
                return
            QMessageBox.warning(self, "Timeline", str(exc))
            block.reset_kind_combo()
            return
        self.refresh()
        self.timeline_changed.emit()
        self.status_message.emit("Abschnittstyp geändert.")

    def reveal_group(self, group_key: str) -> None:
        """Scroll so the matching day or section sits flush under the timeline toolbar."""

        self.ensure_loaded()
        block = self._block_for_group_key(group_key)
        if block is None:
            return
        self._pending_reveal = block
        for delay in _REVEAL_RETRY_MS:
            QTimer.singleShot(delay, self._apply_pending_reveal)

    def begin_reveal(self) -> None:
        """Skip restoring the old scrollbar position on the next refresh."""

        self._preserve_scroll = False

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
        if block is None or block not in self._blocks or self._revealing:
            return
        viewport = self._scroll.viewport()
        bar = self._scroll.verticalScrollBar()
        self._revealing = True
        try:
            self._sync_reveal_tail()
            delta = scroll_delta_to_widget_top(block, viewport)
            if delta == 0:
                return
            bar.setValue(max(0, min(bar.maximum(), bar.value() + delta)))
        finally:
            self._revealing = False

    def _sync_reveal_tail(self) -> None:
        extra = max(0, self._scroll.viewport().height() - 24)
        self._tail.setMinimumHeight(extra)

    def _wire_drag_scroll(self, gallery: GalleryView) -> None:
        gallery.drag_started.connect(self._begin_drag_scroll)
        gallery.drag_finished.connect(self._end_drag_scroll)

    def _begin_drag_scroll(self) -> None:
        if not self._drag_scroll.isActive():
            self._drag_scroll.start()

    def _end_drag_scroll(self) -> None:
        self._drag_scroll.stop()

    def _drag_scroll_delta(self, y: int | None = None) -> int:
        viewport = self._scroll.viewport()
        height = viewport.height()
        if y is not None:
            return autoscroll_step(y, height)
        cursor = QCursor.pos()
        origin = viewport.mapToGlobal(QPoint(0, 0))
        from_viewport = autoscroll_step(cursor.y() - origin.y(), height)
        win = self.window()
        from_window = 0
        if win is not None:
            from_window = autoscroll_step(win.mapFromGlobal(cursor).y(), win.height())
        if abs(from_window) > abs(from_viewport):
            return from_window
        return from_viewport

    def _on_drag_scroll_tick(self) -> None:
        delta = self._drag_scroll_delta()
        if not delta:
            return
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.value() + delta)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        scroll = getattr(self, "_scroll", None)
        if scroll is not None and watched is scroll and event.type() == QEvent.Type.Resize:
            self._place_scroll_date()
        return super().eventFilter(watched, event)

    def _on_scroll_slider_pressed(self) -> None:
        self._pending_reveal = None
        self._scroll_slider_down = True
        self._scroll_hide.stop()
        self._sync_scroll_date(show=True)

    def _on_scroll_action(self, _action: int) -> None:
        self._pending_reveal = None

    def _on_scroll_slider_released(self) -> None:
        self._scroll_slider_down = False
        self._scroll_hide.start()

    def _on_timeline_scroll(self, _value: int = 0) -> None:
        if self._revealing:
            return
        self._sync_scroll_date(show=True)
        if not self._scroll_slider_down:
            self._scroll_hide.start()

    def _on_scroll_range_changed(self, *_args: int) -> None:
        if self._pending_reveal is not None:
            self._apply_pending_reveal()
        if not self._scroll_date.isHidden():
            self._place_scroll_date()

    def _sync_scroll_date(self, *, show: bool) -> None:
        if self._loading or not show:
            self._scroll_date.hide()
            return
        bar = self._scroll.verticalScrollBar()
        host = self._scroll.widget()
        viewport = self._scroll.viewport()
        if not self._blocks or bar.maximum() <= 0 or host is None:
            self._scroll_date.hide()
            return
        mid_y = bar.value() + viewport.height() // 2
        text = timeline_center_date(self._blocks, host, mid_y)
        if not text:
            self._scroll_date.hide()
            return
        self._scroll_date.setText(text)
        self._scroll_date.adjustSize()
        self._scroll_date.show()
        self._place_scroll_date()

    def _place_scroll_date(self) -> None:
        if self._scroll_date.isHidden():
            return
        bar = self._scroll.verticalScrollBar()
        handle = _scrollbar_slider_rect(bar)
        if not handle.isValid() or handle.height() <= 0:
            return
        label = self._scroll_date
        label.adjustSize()
        bar_origin = bar.mapTo(self._scroll, QPoint(0, 0))
        handle_center = bar.mapTo(self._scroll, handle.center())
        anchor_x = bar_origin.x()
        if anchor_x <= 0:
            anchor_x = self._scroll.viewport().width()
        x = anchor_x - label.width()
        y = handle_center.y() - label.height() // 2
        y = max(0, min(y, self._scroll.height() - label.height()))
        x = max(0, min(x, self._scroll.width() - label.width()))
        label.move(x, y)
        label.raise_()

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

    def _has_unsaved_work(self) -> bool:
        if self._pending:
            return True
        if self._trip_title_dirty():
            return True
        for block in self._blocks:
            if block.is_dirty():
                return True
            if block.youtube_urls() != block.youtube_from_db():
                return True
        return bool(self._pending_youtube)

    def _update_save_button(self) -> None:
        if self._loading:
            return
        self._save_button.setEnabled(self._has_unsaved_work())

    def _set_trip_title_field(self, snapshot: TimelineSnapshot | None) -> None:
        if snapshot is None:
            self._trip_title.blockSignals(True)
            self._trip_title.clear()
            self._trip_title.blockSignals(False)
            self._trip_title.setEnabled(False)
            self._loaded_trip_title = ""
            return
        self._trip_title.setEnabled(True)
        if not self._trip_title_dirty():
            self._trip_title.blockSignals(True)
            self._trip_title.setText(snapshot.title)
            self._trip_title.blockSignals(False)
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

    def _record_pending_insert(self, spec: PendingSectionSpec, index: int) -> None:
        snapshot = _copy_pending_spec(spec)

        def undo() -> None:
            self._remove_pending_id(snapshot.local_id)

        def redo() -> None:
            self._insert_pending_copy(snapshot, index)

        self.workspace.history.push("Abschnitt einfügen", undo, redo)

    def _record_pending_remove(
        self,
        spec: PendingSectionSpec,
        index: int,
        *,
        title: str = "Abschnitt löschen",
    ) -> None:
        snapshot = _copy_pending_spec(spec)

        def undo() -> None:
            self._insert_pending_copy(snapshot, index)

        def redo() -> None:
            self._remove_pending_id(snapshot.local_id)

        self.workspace.history.push(title, undo, redo)

    def _insert_pending_copy(self, spec: PendingSectionSpec, index: int) -> None:
        if any(existing.local_id == spec.local_id for existing in self._pending):
            return
        self._pending.insert(max(0, min(index, len(self._pending))), _copy_pending_spec(spec))

    def _remove_pending_id(self, local_id: int) -> None:
        self._pending = [spec for spec in self._pending if spec.local_id != local_id]
        self._pending_youtube.pop(("section", local_id), None)

    def _record_pending_kind(
        self,
        spec: PendingSectionSpec,
        previous: tuple[object, ...],
        current: tuple[object, ...],
    ) -> None:
        if previous == current:
            return
        local_id = spec.local_id

        def undo() -> None:
            self._set_pending_kind_fields(local_id, previous)

        def redo() -> None:
            self._set_pending_kind_fields(local_id, current)

        self.workspace.history.push("Abschnittstyp", undo, redo)

    def _set_pending_kind_fields(self, local_id: int, fields: tuple[object, ...]) -> None:
        kind, mode, location_name, location_from, location_to, links, outbound = fields
        for spec in self._pending:
            if spec.local_id != local_id:
                continue
            spec.kind = str(kind)
            spec.mode = mode if isinstance(mode, str) else None
            spec.location_name = location_name if isinstance(location_name, str) else None
            spec.location_from = location_from if isinstance(location_from, str) else None
            spec.location_to = location_to if isinstance(location_to, str) else None
            spec.links = links if isinstance(links, tuple) else ()
            spec.outbound = outbound if isinstance(outbound, TimelineLink) or outbound is None else None
            return

    def _record_pending_span(
        self,
        spec: PendingSectionSpec,
        previous: tuple[datetime | None, datetime | None],
        current: tuple[datetime | None, datetime | None],
    ) -> None:
        if previous == current:
            return
        local_id = spec.local_id

        def undo() -> None:
            self._set_pending_span(local_id, previous)

        def redo() -> None:
            self._set_pending_span(local_id, current)

        self.workspace.history.push("Datum", undo, redo)

    def _set_pending_span(self, local_id: int, span: tuple[datetime | None, datetime | None]) -> None:
        for spec in self._pending:
            if spec.local_id != local_id:
                continue
            spec.started_at, spec.ended_at = span
            return

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
            spec.links = tuple(block.transfer_links())
            spec.outbound = block.outbound_link()

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
        specs = [_copy_pending_spec(spec) for spec in self._pending]
        try:
            for index, spec in enumerate(specs):
                self._persist_one_pending(spec, index)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return False
        self._pending.clear()
        return True

    def _persist_one_pending(self, spec: PendingSectionSpec, index: int) -> None:
        before = self.workspace._capture_placement(list(spec.source_file_ids))
        section_id = self.workspace.create_section(
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
            started_at=spec.started_at,
            ended_at=spec.ended_at,
            record=False,
        )
        self._save_pending_links(section_id, spec)
        created = [section_id]
        snapshot = _copy_pending_spec(spec)

        def undo() -> None:
            self.workspace._undo_created_section(before, created)
            self._insert_pending_copy(snapshot, index)

        def redo() -> None:
            self._remove_pending_id(snapshot.local_id)
            created[0] = self.workspace.create_section(
                list(snapshot.source_file_ids),
                kind=snapshot.kind,
                mode=snapshot.mode,
                title=snapshot.title,
                notes=snapshot.notes,
                location_name=snapshot.location_name,
                location_from=snapshot.location_from,
                location_to=snapshot.location_to,
                youtube_urls=list(snapshot.youtube_urls),
                leonardo_urls=list(snapshot.leonardo_urls),
                cover_source_file_id=snapshot.cover_source_file_id,
                started_at=snapshot.started_at,
                ended_at=snapshot.ended_at,
                record=False,
            )
            self._save_pending_links(created[0], snapshot)

        self.workspace.history.push("Abschnitt einfügen", undo, redo)

    def _save_pending_links(self, section_id: int, spec: PendingSectionSpec) -> None:
        if spec.kind == KIND_MOVEMENT:
            links = list(spec.links) or list(links_from_modes(spec.mode))
            if links:
                self.workspace.save_transfer_links(section_id, links)
            return
        self.workspace.save_outbound_link(section_id, spec.outbound)

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
                    if block.entry_kind() == KIND_MOVEMENT:
                        self.workspace.save_transfer_links(entity_id, block.transfer_links())
                    else:
                        self.workspace.save_outbound_link(entity_id, block.outbound_link())
                else:
                    self.workspace.save_day_text(entity_id, title=title, notes=notes)
                block.mark_clean()
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return False
        self._update_save_button()
        return True

    def _on_save_clicked(self) -> None:
        self._stash_pending_youtube()
        if not self._has_unsaved_work():
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
    delete_requested = Signal(int)
    span_requested = Signal(int)
    journal_changed = Signal()
    kind_changed = Signal(str)
    media_tab_changed = Signal(int)
    item_rating_changed = Signal(object)
    open_on_map = Signal(str)
    open_media_on_map = Signal(str, int)
    content_changed = Signal()
    pool_dropped = Signal(list)

    def __init__(
        self,
        entry: TimelineEntry,
        *,
        workspace: Workspace | None = None,
        show_as_leftover: bool = False,
        youtube_override: list[str] | None = None,
        show_outbound: bool = False,
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
            date_text = format_card_dates(section.started_at, section.ended_at)
            extra_text = _card_extra(section)
            title = section.title or ""
            notes = section.notes or ""
            items = section.items
            youtube = section.youtube_urls
            leonardo = section.leonardo_urls
            cover_id = section.cover_source_file_id
            title_ph = "Titel des Abschnitts"
            notes_ph = "Tagebucheintrag für diesen Abschnitt"
            self._center_date = format_scroll_date(section.started_at, section.ended_at)
        elif day is not None:
            self._kind = "day"
            self._entity_id = day.id
            date_text = day.date.strftime("%d.%m.%Y") if day.date is not None else "Ohne Datum"
            extra_text = "ohne Abschnitt" if show_as_leftover else ""
            title = day.title or ""
            notes = day.notes or ""
            items = day.photos
            youtube = day.youtube_urls
            leonardo = day.leonardo_urls
            cover_id = day.cover_source_file_id
            title_ph = "Titel des Tages"
            notes_ph = "Tagebucheintrag — aus importierten Texten vorbefüllt"
            self._center_date = day.date.strftime("%d.%m.%Y") if day.date is not None else "Ohne Datum"
        else:
            self._kind = "day"
            self._entity_id = 0
            date_text = "Ohne Datum"
            extra_text = ""
            title = ""
            notes = ""
            items = ()
            title_ph = "Titel"
            notes_ph = ""
            self._center_date = "Ohne Datum"
        self._db_youtube_urls = list(youtube)
        self._youtube_urls = list(youtube if youtube_override is None else youtube_override)
        self._leonardo_urls = list(leonardo)
        self._cover_id = cover_id
        self._cover_reply = None
        self._cover_gen = 0
        self._flights = igc_flights(items)
        self._loaded_title = title
        self._loaded_notes = notes
        self._link_strip: TransferLinkStrip | None = None
        self._outbound_row: OutboundLinkRow | None = None
        self._loaded_links: tuple[TimelineLink, ...] = (
            section.links if section is not None and section.kind == KIND_MOVEMENT else ()
        )
        self._loaded_outbound = section.outbound if section is not None else None
        self._entry_kind = entry.card_kind

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

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
        if self._kind == "section" and self._entity_id > 0:
            sort_action = self._entry_menu.addAction("Nach Journal-Zeit sortieren")
            sort_action.triggered.connect(self._sort_by_journal)
        if self._kind == "section":
            span_label = "Datum…" if self._entry_kind == KIND_DAY else "Zeitraum…"
            span_action = self._entry_menu.addAction(span_label)
            span_action.triggered.connect(self._request_span)
            self._entry_menu.addSeparator()
            delete_action = self._entry_menu.addAction("Löschen…")
            delete_action.triggered.connect(self._request_delete)
        self._menu_button.clicked.connect(self._popup_entry_menu)
        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 0)
        heading_row.setSpacing(12)
        self._cover_thumb = QLabel(self)
        self._cover_thumb.setObjectName("entryCover")
        self._cover_thumb.setFixedSize(_COVER_HEAD, _COVER_HEAD)
        self._cover_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_thumb.setToolTip("Titelbild")
        heading_row.addWidget(self._cover_thumb, 0, Qt.AlignmentFlag.AlignTop)
        meta = QVBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(4)
        type_row = QHBoxLayout()
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(8)
        self._kind_combo = SectionKindCombo(self)
        self._kind_combo.setObjectName("sectionKind")
        self._kind_combo.addItem("Tag", KIND_DAY)
        self._kind_combo.addItem("Aufenthalt", KIND_STAY)
        self._kind_combo.addItem("Transfer", KIND_MOVEMENT)
        self._kind_combo.setToolTip("Typ dieses Timeline-Eintrags")
        self._kind_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        index = max(0, self._kind_combo.findData(self._entry_kind))
        self._kind_combo.setCurrentIndex(index)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_combo)
        type_row.addWidget(self._kind_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        self._date_label = QLabel(date_text, self)
        self._date_label.setObjectName("entryDates")
        type_row.addWidget(self._date_label, 0, Qt.AlignmentFlag.AlignVCenter)
        type_row.addStretch(1)
        self._to_map_button = QPushButton("Zur Karte", self)
        self._to_map_button.setObjectName("entryToMap")
        saved = self._entity_id > 0
        self._to_map_button.setEnabled(saved)
        self._to_map_button.setToolTip(
            "Eintrag auf der Karte zeigen" if saved else "Nach dem Speichern auf der Karte sichtbar"
        )
        self._to_map_button.clicked.connect(self._request_open_on_map)
        type_row.addWidget(self._to_map_button, 0)
        if self._kind == "section" and self._entry_kind != KIND_DAY:
            dissolve = QToolButton(self)
            dissolve.setObjectName("entryMenu")
            dissolve.setText("⊟")
            dissolve.setToolTip("Reiseabschnitt auflösen")
            dissolve.clicked.connect(self._request_dissolve)
            type_row.addWidget(dissolve, 0)
        type_row.addWidget(self._menu_button, 0)
        meta.addLayout(type_row)
        self._extra_label = QLabel(extra_text, self)
        self._extra_label.setObjectName("entryExtra")
        self._extra_label.setWordWrap(True)
        self._extra_label.setVisible(bool(extra_text))
        meta.addWidget(self._extra_label)
        if section is not None and section.kind == KIND_MOVEMENT:
            self._link_strip = TransferLinkStrip(self)
            self._link_strip.set_tracks(_gpx_track_choices(items))
            self._link_strip.set_links(section.links)
            self._link_strip.links_changed.connect(self.content_changed.emit)
            meta.addWidget(self._link_strip)
        elif show_outbound and section is not None and section.kind != KIND_MOVEMENT:
            self._outbound_row = OutboundLinkRow(self)
            self._outbound_row.set_link(section.outbound)
            self._outbound_row.changed.connect(self.content_changed.emit)
            meta.addWidget(self._outbound_row)
        title_label = QLabel("Titel", self)
        title_label.setObjectName("fieldCaption")
        meta.addWidget(title_label)
        self.title_edit = QLineEdit(self)
        self.title_edit.setText(self._loaded_title)
        self.title_edit.setPlaceholderText(title_ph)
        meta.addWidget(self.title_edit)
        meta.addStretch(1)
        heading_row.addLayout(meta, 1)
        self.links_label = QLabel(self)
        self.links_label.setObjectName("pageSubtitle")
        self.links_label.setWordWrap(True)
        self.links_label.setOpenExternalLinks(True)
        self.links_label.setTextFormat(Qt.TextFormat.RichText)
        self.youtube_thumbs = YouTubeThumbsRow(self)
        self._refresh_links()
        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setPlainText(self._loaded_notes)
        self.notes_edit.setPlaceholderText(notes_ph)
        self.notes_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.notes_edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.notes_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.notes_edit.textChanged.connect(self._fit_notes)
        self.title_edit.textChanged.connect(self.content_changed.emit)
        self.notes_edit.textChanged.connect(self.content_changed.emit)
        media_items, track_items = split_media_and_tracks(items)
        media_count = len(media_items)
        track_count = len(track_items)
        media_label = QLabel(
            "Keine Medien" if media_count == 0 and track_count == 0 else f"Medien ({media_count})",
            self,
        )
        media_label.setObjectName("fieldCaption")
        media_label.setVisible(media_count > 0 or track_count == 0)
        self._all_gallery = [_gallery_item(photo, cover_id=self._cover_id) for photo in media_items]
        self._media_tabs = ClickTabBar(self)
        self._media_tabs.setObjectName("mediaSortTabs")
        self._media_tabs.setExpanding(False)
        for label, _status in RATING_TABS:
            self._media_tabs.addTab(label)
        self._media_tabs.setVisible(media_count > 0)
        self.gallery = GalleryView(self, show_cover=True)
        self.gallery.set_expand_to_fit(True)
        self.gallery.set_multi_select(True)
        self.gallery.rating_chosen.connect(self._on_rating)
        self.gallery.cover_chosen.connect(self._on_cover)
        self.gallery.enable_to_map_menu(self._item_can_open_on_map)
        self.gallery.map_requested.connect(self._request_open_item_on_map)
        self.gallery.setToolTip(_GALLERY_DRAG_HINT)
        self.gallery.setVisible(media_count > 0)
        model = self.gallery.selectionModel()
        if model is not None:
            model.selectionChanged.connect(lambda *_args: self.selection_changed.emit())
        track_label = QLabel(f"Tracks ({track_count})", self)
        track_label.setObjectName("fieldCaption")
        track_label.setVisible(track_count > 0)
        self.track_gallery = GalleryView(self, show_ratings=False, show_cover=True)
        self.track_gallery.set_expand_to_fit(True)
        self.track_gallery.set_multi_select(True)
        self.track_gallery.cover_chosen.connect(self._on_cover)
        self.track_gallery.enable_to_map_menu(self._item_can_open_on_map)
        self.track_gallery.map_requested.connect(self._request_open_item_on_map)
        self.track_gallery.setToolTip(_GALLERY_DRAG_HINT)
        self.track_gallery.set_items([_gallery_item(photo, cover_id=self._cover_id) for photo in track_items])
        self.track_gallery.setVisible(track_count > 0)
        track_model = self.track_gallery.selectionModel()
        if track_model is not None:
            track_model.selectionChanged.connect(lambda *_args: self.selection_changed.emit())

        notes_label = QLabel("Tagebucheintrag", self)
        notes_label.setObjectName("fieldCaption")
        layout.addLayout(heading_row)
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
        self.setAcceptDrops(True)
        self.title_edit.setAcceptDrops(False)
        self.notes_edit.setAcceptDrops(False)
        self.gallery.set_drag_enabled(True)
        self.track_gallery.set_drag_enabled(True)
        self.gallery.set_accept_pool_drop(True)
        self.track_gallery.set_accept_pool_drop(True)
        self.gallery.items_dropped.connect(self.pool_dropped.emit)
        self.track_gallery.items_dropped.connect(self.pool_dropped.emit)
        self.gallery.drop_hover.connect(self._set_drop_highlight)
        self.track_gallery.drop_hover.connect(self._set_drop_highlight)

    def values(self) -> tuple[str, int, str, str]:
        return self._kind, self._entity_id, self.title_edit.text(), self.notes_edit.toPlainText()

    def entity_kind(self) -> str:
        return self._kind

    def entity_id(self) -> int:
        return self._entity_id

    def scroll_date(self) -> str:
        return self._center_date

    def accepts_pool_drop(self) -> bool:
        return self._kind == "section" and self._entity_id > 0

    def member_source_ids(self) -> set[int]:
        return {item.source_file_id for item in self.ordered_items()}

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self.accepts_pool_drop() and source_ids_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self._set_drop_highlight(True)
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self.accepts_pool_drop() and source_ids_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._set_drop_highlight(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_drop_highlight(False)
        ids = source_ids_from_mime(event.mimeData())
        if not ids or not self.accepts_pool_drop():
            event.ignore()
            return
        event.acceptProposedAction()
        self.pool_dropped.emit(ids)

    def _set_drop_highlight(self, active: bool) -> None:
        self.setProperty("dropTarget", "true" if active else "false")
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

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
        return list(self.gallery.items())

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
            or self.transfer_links() != list(self._loaded_links)
            or self.outbound_link() != self._loaded_outbound
        )

    def mark_clean(self) -> None:
        self._loaded_title = self.title_edit.text()
        self._loaded_notes = self.notes_edit.toPlainText()
        self._loaded_links = tuple(self.transfer_links())
        self._loaded_outbound = self.outbound_link()

    def transfer_links(self) -> list[TimelineLink]:
        if self._link_strip is None:
            return []
        return _compact_links(self._link_strip.links())

    def outbound_link(self) -> TimelineLink | None:
        if self._outbound_row is None:
            return self._loaded_outbound
        return self._outbound_row.to_link()

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
        wanted = rating_status_at(self._media_tabs.currentIndex())
        include_rejected = self.workspace is not None and self.workspace.show_rejected_in_all()
        shown = [
            item
            for item in self._all_gallery
            if matches_rating(item, wanted, include_rejected=include_rejected)
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

    def _abort_cover_fetch(self) -> None:
        reply = self._cover_reply
        self._cover_reply = None
        if reply is not None:
            reply.abort()

    def _fallback_cover_item(self) -> GalleryItem | None:
        for item in self._all_gallery:
            if item.extension.lower() in PHOTO_EXTENSIONS:
                return item
        for item in self.track_gallery.items():
            if item.extension.lower() in GPS_EXTENSIONS:
                return item
        return None

    def _refresh_cover_thumb(self) -> None:
        self._cover_gen += 1
        gen = self._cover_gen
        self._abort_cover_fetch()
        items = self._cover_items()
        item = next((media for media in items if media.source_file_id == self._cover_id), None)
        if item is None:
            item = self._fallback_cover_item()
        if item is not None and item.thumbnail_path.is_file():
            pixmap = QPixmap(str(item.thumbnail_path))
            if not pixmap.isNull():
                self._cover_thumb.setPixmap(_scaled_cover(pixmap, _COVER_HEAD))
                return
        youtube = youtube_thumbnail_url(self._youtube_urls[0]) if self._youtube_urls else None
        if youtube:
            self._cover_thumb.clear()
            self._cover_reply = start_remote_pixmap(
                youtube, lambda pixmap, token=gen: self._on_cover_youtube(pixmap, token)
            )
            return
        self._cover_thumb.clear()

    def _on_cover_youtube(self, pixmap: QPixmap | None, gen: int) -> None:
        if gen != self._cover_gen:
            return
        self._cover_reply = None
        if pixmap is None or pixmap.isNull():
            self._cover_thumb.clear()
            return
        self._cover_thumb.setPixmap(_scaled_cover(pixmap, _COVER_HEAD))

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
        self.content_changed.emit()

    def _sort_by_journal(self) -> None:
        if self.workspace is None or self._kind != "section" or self._entity_id <= 0:
            return
        try:
            self.workspace.sort_members_by_journal(self._entity_id)
        except ProjectError as exc:
            QMessageBox.warning(self, "Timeline", str(exc))
            return
        self.journal_changed.emit()

    def _request_dissolve(self) -> None:
        self.dissolve_requested.emit(self._entity_id)

    def _request_delete(self) -> None:
        self.delete_requested.emit(self._entity_id)

    def _request_span(self) -> None:
        self.span_requested.emit(self._entity_id)

    def _request_open_on_map(self) -> None:
        if self._entity_id <= 0:
            return
        if self._kind == "section":
            self.open_on_map.emit(f"section:{self._entity_id}")
            return
        if self._kind == "day":
            self.open_on_map.emit(f"day:{self._entity_id}")

    def _item_can_open_on_map(self, item: GalleryItem) -> bool:
        return self._entity_id > 0 and _gallery_item_has_map_position(item)

    def _request_open_item_on_map(self, item: object) -> None:
        if not isinstance(item, GalleryItem) or not self._item_can_open_on_map(item):
            return
        if self._kind == "section":
            self.open_media_on_map.emit(f"section:{self._entity_id}", item.source_file_id)
            return
        if self._kind == "day":
            self.open_media_on_map.emit(f"day:{self._entity_id}", item.source_file_id)

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


class JournalTimeDialog(QDialog):
    def __init__(self, initial: datetime, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Journal-Zeit")
        stamp = initial if initial.tzinfo is not None else initial.replace(tzinfo=UTC)
        layout = QFormLayout(self)
        self._edit = QDateTimeEdit(self)
        self._edit.setCalendarPopup(True)
        self._edit.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
        self._edit.setDateTime(
            QDateTime(
                QDate(stamp.year, stamp.month, stamp.day),
                QTime(stamp.hour, stamp.minute, stamp.second),
            )
        )
        layout.addRow("Position auf der Timeline", self._edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def value(self) -> datetime:
        stamp = self._edit.dateTime()
        date = stamp.date()
        clock = stamp.time()
        return datetime(
            date.year(),
            date.month(),
            date.day(),
            clock.hour(),
            clock.minute(),
            clock.second(),
            tzinfo=UTC,
        )


class NewSectionDialog(QDialog):
    def __init__(self, items: list[GalleryItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neuer Reiseabschnitt")
        times = [item.journal_at or item.captured_at for item in items if item.journal_at or item.captured_at]
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


class EmptySectionDialog(QDialog):
    def __init__(
        self,
        initial: date,
        parent: QWidget | None = None,
        *,
        until: date | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neuer Reiseabschnitt")
        end = until or initial
        self._form = QFormLayout(self)
        self._form.setContentsMargins(20, 16, 20, 16)
        self._form.setHorizontalSpacing(16)
        self._form.setVerticalSpacing(12)
        self.kind = QComboBox()
        self.kind.addItem("Tag", KIND_DAY)
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
        self.date_edit = QDateEdit(self)
        _configure_date_edit(self.date_edit, initial)
        self.from_edit = QDateEdit(self)
        _configure_date_edit(self.from_edit, initial)
        self.until_edit = QDateEdit(self)
        _configure_date_edit(self.until_edit, end)
        self._form.addRow("Typ", self.kind)
        self._form.addRow("Transfer per", self.mode)
        self._form.addRow("Titel", self.title_edit)
        self._form.addRow("Am", self.date_edit)
        self._form.addRow("Von Datum", self.from_edit)
        self._form.addRow("Bis Datum", self.until_edit)
        self._form.addRow("Ort", self.location_name)
        self._form.addRow("Von", self.location_from)
        self._form.addRow("Nach", self.location_to)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        self._form.addRow(buttons)
        self.setMinimumWidth(360)
        self._sync_kind()

    def _set_row_visible(self, field: QWidget, visible: bool) -> None:
        field.setVisible(visible)
        label = self._form.labelForField(field)
        if label is not None:
            label.setVisible(visible)

    def _sync_kind(self) -> None:
        kind = self.kind.currentData()
        movement = kind == KIND_MOVEMENT
        stay = kind == KIND_STAY
        tag = kind == KIND_DAY
        self._set_row_visible(self.mode, movement)
        self._set_row_visible(self.location_from, movement)
        self._set_row_visible(self.location_to, movement)
        self._set_row_visible(self.location_name, stay)
        self._set_row_visible(self.date_edit, tag)
        self._set_row_visible(self.from_edit, not tag)
        self._set_row_visible(self.until_edit, not tag)
        self.adjustSize()

    def _try_accept(self) -> None:
        try:
            self.values()
        except ProjectError as exc:
            QMessageBox.warning(self, "Reiseabschnitt", str(exc))
            return
        self.accept()

    def values(self) -> dict[str, object]:
        kind = str(self.kind.currentData())
        if kind == KIND_DAY:
            started, ended = span_for_manual_dates(kind, _date_from_edit(self.date_edit))
        else:
            started, ended = span_for_manual_dates(
                kind, _date_from_edit(self.from_edit), _date_from_edit(self.until_edit)
            )
        movement = kind == KIND_MOVEMENT
        return {
            "kind": kind,
            "mode": self.mode.serialized() if movement else None,
            "title": self.title_edit.text().strip() or None,
            "notes": None,
            "location_name": None if kind != KIND_STAY else (self.location_name.text().strip() or None),
            "location_from": (self.location_from.text().strip() or None) if movement else None,
            "location_to": (self.location_to.text().strip() or None) if movement else None,
            "started_at": started,
            "ended_at": ended,
        }


class SectionSpanDialog(QDialog):
    """Edit Tag (am) or Stay/Transfer (von–bis) without changing originals."""

    def __init__(
        self,
        kind: str,
        started_at: datetime | None,
        ended_at: datetime | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        start = calendar_key(started_at) or date.today()
        end = calendar_key(ended_at) or start
        self.setWindowTitle("Datum" if kind == KIND_DAY else "Zeitraum")
        self._form = QFormLayout(self)
        self._form.setContentsMargins(20, 16, 20, 16)
        self._form.setHorizontalSpacing(16)
        self._form.setVerticalSpacing(12)
        self.date_edit = QDateEdit(self)
        _configure_date_edit(self.date_edit, start)
        self.from_edit = QDateEdit(self)
        _configure_date_edit(self.from_edit, start)
        self.until_edit = QDateEdit(self)
        _configure_date_edit(self.until_edit, end)
        self.from_edit.hide()
        self.until_edit.hide()
        self.date_edit.hide()
        if kind == KIND_DAY:
            self._form.addRow("Am", self.date_edit)
            self.date_edit.show()
        else:
            self._form.addRow("Von", self.from_edit)
            self._form.addRow("Bis", self.until_edit)
            self.from_edit.show()
            self.until_edit.show()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        self._form.addRow(buttons)
        self.setMinimumWidth(360)
        self.adjustSize()

    def _try_accept(self) -> None:
        try:
            self.span()
        except ProjectError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        self.accept()

    def span(self) -> tuple[datetime, datetime]:
        if self._kind == KIND_DAY:
            return span_for_manual_dates(self._kind, _date_from_edit(self.date_edit))
        return span_for_manual_dates(
            self._kind, _date_from_edit(self.from_edit), _date_from_edit(self.until_edit)
        )


def _date_from_edit(edit: QDateEdit) -> date:
    chosen = edit.date()
    return date(chosen.year(), chosen.month(), chosen.day())


def _entry_span_dates(entry: TimelineEntry) -> tuple[date | None, date | None]:
    if entry.section is not None:
        start = calendar_key(entry.section.started_at) or calendar_key(entry.started_at)
        end = calendar_key(entry.section.ended_at) or start
        return start, end
    if entry.leftover_day is not None and entry.leftover_day.date is not None:
        return entry.leftover_day.date, entry.leftover_day.date
    key = calendar_key(entry.started_at)
    return key, key


def _configure_date_edit(edit: QDateEdit, value: date) -> None:
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy")
    edit.setDate(QDate(value.year, value.month, value.day))
    edit.setMinimumWidth(168)
    edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def _card_extra(section: TimelineSection) -> str:
    if section.kind == KIND_MOVEMENT:
        bits: list[str] = []
        symbols = [item.symbol for item in section.links if item.symbol]
        modes = _format_modes(",".join(symbols) if symbols else section.mode)
        if modes:
            bits.append(modes)
        if section.location_from or section.location_to:
            start = section.location_from or "?"
            end = section.location_to or "?"
            bits.append(f"{start} → {end}")
        return " · ".join(bits)
    if section.kind == KIND_STAY and section.location_name:
        return section.location_name
    return ""


def _scaled_cover(pixmap: QPixmap, size: int) -> QPixmap:
    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scaled.width() == size and scaled.height() == size:
        return scaled
    x = max(0, (scaled.width() - size) // 2)
    y = max(0, (scaled.height() - size) // 2)
    return scaled.copy(x, y, size, size)


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
        journal_at=photo.journal_at,
        display_latitude=photo.display_latitude,
        display_longitude=photo.display_longitude,
    )


def _gallery_item_has_map_position(item: GalleryItem) -> bool:
    if item.display_latitude is not None and item.display_longitude is not None:
        return True
    return item.gps_latitude is not None and item.gps_longitude is not None


def _gpx_track_choices(items: tuple[TimelinePhoto, ...] | list[TimelinePhoto]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for item in items:
        if item.file_kind != FileKind.GPS.value or is_igc_filename(item.filename):
            continue
        found.append((item.source_file_id, item.filename))
    return found


def _compact_links(links: list[TimelineLink]) -> list[TimelineLink]:
    if len(links) != 1:
        return list(links)
    link = links[0]
    if (
        link.geometry == LINK_GEOMETRY_LINE
        and not link.symbol
        and link.track_source_file_id is None
        and link.end_latitude is None
    ):
        return []
    return list(links)


def _links_from_payload(payload: dict[str, object]) -> tuple[TimelineLink, ...]:
    raw = payload.get("links")
    if isinstance(raw, tuple) and raw:
        return raw
    mode = payload.get("mode") if isinstance(payload.get("mode"), str) else None
    return links_from_modes(mode)


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
