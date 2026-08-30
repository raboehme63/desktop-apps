"""Source directory import with background indexing."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select

from travelcore.config import AppSettings
from travelcore.database.models import FileError, SourceFile
from travelcore.exceptions import ProjectError
from travelcore.media.indexer import IndexResult
from travelcore.media.purge import SourceSyncPlan
from travelcore.media.thumbnails import cached_thumbnail_path
from travelcore.media.types import FileKind
from traveljournal.services.workers import IndexLoadRunnable, IndexRunnable
from traveljournal.services.workspace import Workspace

_TABLE_FILL_CHUNK = 80


def import_browse_start(
    current_path: str,
    *,
    source_root: str | None,
    projects_root: Path | None,
) -> str:
    """Start folder for the import picker: current path, then source root, then projects root."""

    for candidate in (current_path, source_root, str(projects_root) if projects_root is not None else ""):
        text = (candidate or "").strip()
        if not text:
            continue
        path = Path(text)
        if path.is_dir():
            return str(path)
    return ""


class ImportView(QWidget):
    status_message = Signal(str)
    import_finished = Signal()
    index_load_progress = Signal(int, int, str)
    index_load_finished = Signal()

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._pool = QThreadPool.globalInstance()
        self._busy = False
        self._list_refresh = QTimer(self)
        self._list_refresh.setSingleShot(True)
        self._list_refresh.setInterval(250)
        self._list_refresh.timeout.connect(self.refresh)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        title = QLabel("Import")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Quellverzeichnis rekursiv durchsuchen. Aufnahmezeit und GPS aus Metadaten; "
            "Fotos ohne Koordinaten werden zeitlich mit GPX- und IGC-Tracks abgeglichen. "
            "Klick oder Mouseover zeigt Vorschau und Metadaten. "
            "IGC-Flüge: Pilot aus dem Log; DHV-Leonardo-Link per Doppelklick. "
            "Synchronisieren entfernt fehlende Dateien aus dem Tagebuch und fragt, "
            "ob neue Medien in die Timeline oder in den Pool sollen."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        picker = QFrame()
        picker.setObjectName("card")
        picker_layout = QHBoxLayout(picker)
        picker_layout.setContentsMargins(16, 14, 16, 14)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Quellverzeichnis mit Originaldateien")
        browse = QPushButton("Ordner wählen")
        browse.clicked.connect(self._browse)
        analyze = QPushButton("Dateien analysieren")
        analyze.setObjectName("primary")
        analyze.clicked.connect(self._start_import)
        self._analyze_button = analyze
        sync = QPushButton("Synchronisieren")
        sync.setToolTip(
            "Fehlende Dateien aus dem Tagebuch entfernen; neue Medien in die Timeline oder den Pool legen"
        )
        sync.clicked.connect(self._start_sync)
        self._sync_button = sync
        picker_layout.addWidget(self.path_edit, 1)
        picker_layout.addWidget(browse)
        picker_layout.addWidget(analyze)
        picker_layout.addWidget(sync)
        root.addWidget(picker)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Bereit")
        root.addWidget(self.progress)

        stats = QFrame()
        stats.setObjectName("card")
        grid = QGridLayout(stats)
        grid.setContentsMargins(16, 14, 16, 14)
        self._stat_labels: dict[str, QLabel] = {}
        titles = {
            "photo": "Fotos",
            "video": "Videos",
            "gps": "Tracks",
            "located": "mit Ort",
            "matched": "aus Abgleich",
            "unlocated": "ohne Ort",
            "text": "Texte",
            "errors": "Fehler",
        }
        tooltips = {
            "located": "Dateien mit GPS-Koordinaten aus Metadaten, Track oder Abgleich.",
            "matched": "Fotos und Videos, denen per GPS-Abgleich eine Position zugeordnet wurde.",
            "unlocated": (
                "Fotos und Videos, denen nach Metadaten und GPS-Abgleich keine Position "
                "zugeordnet werden konnte."
            ),
        }
        for column, key in enumerate(
            ("photo", "video", "gps", "located", "matched", "unlocated", "text", "errors")
        ):
            value = QLabel("0")
            value.setObjectName("statValue")
            label = QLabel(titles[key])
            label.setObjectName("statLabel")
            tip = tooltips.get(key)
            if tip:
                value.setToolTip(tip)
                label.setToolTip(tip)
            cell = QVBoxLayout()
            cell.addWidget(value)
            cell.addWidget(label)
            grid.addLayout(cell, 0, column)
            self._stat_labels[key] = value
        root.addWidget(stats)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Datei", "Typ", "Aufnahmezeit", "GPS", "Kamera / Pilot"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        self.table.itemEntered.connect(self._on_item_entered)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        preview = QFrame()
        preview.setObjectName("card")
        preview.setMinimumWidth(260)
        preview.setMaximumWidth(380)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        preview_layout.setSpacing(10)
        self._preview_image = QLabel("Keine Datei gewählt")
        self._preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_image.setMinimumHeight(220)
        self._preview_image.setObjectName("statLabel")
        self._preview_meta = QLabel("Klick oder Mouseover auf eine Zeile zeigt Metadaten.")
        self._preview_meta.setWordWrap(True)
        self._preview_meta.setObjectName("pageSubtitle")
        self._preview_meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        meta_scroll = QScrollArea()
        meta_scroll.setWidgetResizable(True)
        meta_scroll.setFrameShape(QFrame.Shape.NoFrame)
        meta_scroll.setWidget(self._preview_meta)
        preview_layout.addWidget(self._preview_image)
        preview_layout.addWidget(meta_scroll, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        split.addWidget(preview)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        self._list_summary = QLabel("")
        self._list_summary.setObjectName("pageSubtitle")
        root.addWidget(self._list_summary)

        self._files: dict[int, SourceFile] = {}
        self._dhv_urls: dict[int, str] = {}
        self._preview_id: int | None = None
        self._thumb_cache: tuple[str, QPixmap] | None = None
        self._pending_rows: list[SourceFile] = []
        self._fill_offset = 0
        self._load_generation = 0
        self._emit_import_after_load = False
        self._index_loader: IndexLoadRunnable | None = None
        self._index_loading = False

    def refresh(self) -> None:
        self.refresh_summary()
        if self._busy:
            self._fill_table()
            return
        self.load_index_async()

    def refresh_summary(self) -> None:
        project = self.workspace.project_row()
        if project and project.source_root:
            self.path_edit.setText(project.source_root)
        if self.workspace.current is not None:
            try:
                root = self.workspace.project_settings().source_root
            except ProjectError:
                root = None
            if root:
                self.path_edit.setText(root)
        counts = self.workspace.file_counts()
        for key in ("photo", "video", "gps", "text", "located", "matched", "unlocated"):
            self._stat_labels[key].setText(str(counts.get(key, 0)))
        errors = 0
        if self.workspace.current is not None:
            with self.workspace.current.session_factory() as session:
                errors = (
                    session.scalar(
                        select(func.count())
                        .select_from(FileError)
                        .where(FileError.project_id == self.workspace.current.project_id)
                    )
                    or 0
                )
        self._stat_labels["errors"].setText(str(errors))

    @property
    def is_loading_index(self) -> bool:
        return self._index_loading

    def load_index_async(self) -> None:
        """Read the stored file index in the background, then fill the table in chunks."""

        self._load_generation += 1
        generation = self._load_generation
        self._index_loading = True
        self._pending_rows = []
        self._fill_offset = 0
        self._files = {}
        self._dhv_urls = {}
        self._thumb_cache = None
        self.table.setRowCount(0)
        if self.workspace.current is None:
            self._list_summary.setText("")
            self.progress.setValue(0)
            self.progress.setFormat("Bereit")
            self._notify_index_loaded()
            return
        self.progress.setRange(0, 0)
        self.progress.setFormat("Index wird gelesen…")
        self._list_summary.setText("Index wird gelesen…")
        self.index_load_progress.emit(0, 0, "Index wird gelesen…")
        worker = IndexLoadRunnable(self.workspace)
        self._index_loader = worker
        worker.signals.ready.connect(lambda rows, urls: self._on_index_ready(generation, rows, urls))
        worker.signals.failed.connect(lambda message: self._on_index_failed(generation, message))
        self._pool.start(worker)

    def _on_index_ready(self, generation: int, rows: object, urls: object) -> None:
        if generation != self._load_generation:
            return
        if not isinstance(rows, list):
            rows = []
        self._pending_rows = rows
        self._dhv_urls = urls if isinstance(urls, dict) else {}
        self._fill_offset = 0
        self._files = {}
        self._thumb_cache = None
        total = max(len(self._pending_rows), 1)
        self.table.setRowCount(len(self._pending_rows))
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        if not self._pending_rows:
            self.progress.setFormat("Keine Dateien im Index")
            self._list_summary.setText("Keine Dateien im Index.")
            self._notify_index_loaded()
            return
        self.progress.setFormat("Index wird angezeigt…")
        self.index_load_progress.emit(0, len(self._pending_rows), "Index wird angezeigt…")
        QTimer.singleShot(0, lambda: self._fill_next_chunk(generation))

    def _on_index_failed(self, generation: int, message: str) -> None:
        if generation != self._load_generation:
            return
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Index konnte nicht geladen werden")
        self._list_summary.setText(message)
        self.status_message.emit(f"Index: {message}")
        self._notify_index_loaded()

    def _fill_next_chunk(self, generation: int) -> None:
        if generation != self._load_generation:
            return
        rows = self._pending_rows
        start = self._fill_offset
        if start >= len(rows):
            self._finish_index_load()
            return
        end = min(start + _TABLE_FILL_CHUNK, len(rows))
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        for index in range(start, end):
            item = rows[index]
            self._files[item.id] = item
            self.table.setItem(index, 0, _locked_item(item.filename, item.id))
            self.table.setItem(index, 1, _locked_item(item.file_kind, item.id))
            self.table.setItem(index, 2, _locked_item(_format_captured(item), item.id))
            self.table.setItem(index, 3, _locked_item(_format_gps(item), item.id))
            self.table.setItem(index, 4, _locked_item(item.camera or "", item.id))
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self._fill_offset = end
        total = len(rows)
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(end)
        message = f"Index: {end} von {total} Dateien"
        self.progress.setFormat(progress_bar_format(message))
        self.index_load_progress.emit(end, total, message)
        if end < total:
            QTimer.singleShot(0, lambda: self._fill_next_chunk(generation))
            return
        self._finish_index_load()

    def _finish_index_load(self) -> None:
        total = len(self._pending_rows)
        self._pending_rows = []
        self.progress.setValue(self.progress.maximum())
        self.progress.setFormat(f"{total} Dateien geladen")
        self._list_summary.setText(
            f"{total} Dateien in der Liste. Klick oder Mouseover zeigt Vorschau. "
            "Doppelklick auf eine IGC-Datei setzt den DHV-Leonardo-Link."
        )
        self._notify_index_loaded()

    def _notify_index_loaded(self) -> None:
        self._index_loading = False
        self._index_loader = None
        self.index_load_finished.emit()
        if self._emit_import_after_load:
            self._emit_import_after_load = False
            self.import_finished.emit()

    def _browse(self) -> None:
        source_root = None
        if self.workspace.current is not None:
            try:
                source_root = self.workspace.project_settings().source_root
            except ProjectError:
                source_root = None
        start = import_browse_start(
            self.path_edit.text().strip(),
            source_root=source_root,
            projects_root=self.workspace.projects_root(),
        )
        directory = QFileDialog.getExistingDirectory(self, "Quellverzeichnis wählen", start)
        if directory:
            self.path_edit.setText(directory)

    def _start_import(self) -> None:
        path = self._ready_source_path()
        if path is None:
            return
        self._run_index(path)

    def _start_sync(self) -> None:
        path = self._ready_source_path()
        if path is None:
            return
        try:
            plan = self.workspace.plan_source_sync(path)
        except ProjectError as exc:
            QMessageBox.warning(self, "Synchronisieren", str(exc))
            return
        if plan.new_count == 0 and plan.missing_count == 0:
            QMessageBox.information(
                self,
                "Synchronisieren",
                "Keine neuen und keine fehlenden Dateien. "
                "Unveränderte Dateien können Sie mit „Dateien analysieren“ nachziehen.",
            )
            return
        dialog = SourceSyncDialog(plan, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._run_index(path, remove_missing=True, park_new_media=dialog.park_new_media())

    def _ready_source_path(self) -> Path | None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Import", "Bitte zuerst ein Projekt anlegen oder öffnen.")
            return None
        source = self.path_edit.text().strip()
        if not source:
            QMessageBox.information(self, "Import", "Bitte ein Quellverzeichnis wählen.")
            return None
        path = Path(source)
        if not path.is_dir():
            QMessageBox.warning(self, "Import", "Das gewählte Verzeichnis existiert nicht.")
            return None
        if self._busy:
            return None
        return path

    def _run_index(
        self,
        path: Path,
        *,
        remove_missing: bool = False,
        park_new_media: bool = False,
    ) -> None:
        opened = self.workspace.current
        if opened is None:
            return
        self._busy = True
        self._analyze_button.setEnabled(False)
        self._sync_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setFormat("Verzeichnis wird durchsucht…")
        worker = IndexRunnable(
            opened,
            path,
            remove_missing=remove_missing,
            park_new_media=park_new_media,
        )
        worker.signals.progress.connect(self._on_progress)
        worker.signals.files_ready.connect(self._on_files_ready)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        self._pool.start(worker)
        self.status_message.emit("Verzeichnis wird durchsucht…")

    def _on_progress(self, current: int, total: int, path: str, message: str) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(current)
        status = format_import_status(current, total, message, path)
        self.progress.setFormat(progress_bar_format(message.strip() or Path(path).name))
        self.status_message.emit(status)

    def _on_files_ready(self) -> None:
        self._list_refresh.start()

    def _on_finished(self, result: object) -> None:
        self._busy = False
        self._analyze_button.setEnabled(True)
        self._sync_button.setEnabled(True)
        self._list_refresh.stop()
        if not isinstance(result, IndexResult):
            return
        self.progress.setValue(self.progress.maximum())
        summary = (
            f"Import fertig: {result.indexed} neu, {result.updated} aktualisiert, "
            f"{result.skipped_unchanged} unverändert, {result.removed} entfernt, "
            f"{result.positions_matched} Positionen aus Track, "
            f"{result.positions_unmatched} ohne Ort, "
            f"{result.thumbnails_written} Vorschaubilder, {result.errors} Fehler"
        )
        self.progress.setFormat(summary)
        self.status_message.emit(summary)
        self._emit_import_after_load = True
        QTimer.singleShot(0, self._apply_import_result)

    def _apply_import_result(self) -> None:
        self.refresh_summary()
        self.load_index_async()

    def _on_failed(self, message: str) -> None:
        self._busy = False
        self._analyze_button.setEnabled(True)
        self._sync_button.setEnabled(True)
        self._list_refresh.stop()
        self.refresh()
        self.progress.setFormat("Import fehlgeschlagen")
        QMessageBox.warning(self, "Import", message)
        self.status_message.emit(f"Importfehler: {message}")

    def _fill_table(self) -> None:
        rows = self.workspace.source_files()
        self._files = {item.id: item for item in rows}
        self._dhv_urls = self.workspace.gps_track_urls() if rows else {}
        self._thumb_cache = None
        scroll = self.table.verticalScrollBar().value()
        current = self.table.currentRow()
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            self.table.setItem(index, 0, _locked_item(item.filename, item.id))
            self.table.setItem(index, 1, _locked_item(item.file_kind, item.id))
            self.table.setItem(index, 2, _locked_item(_format_captured(item), item.id))
            self.table.setItem(index, 3, _locked_item(_format_gps(item), item.id))
            self.table.setItem(index, 4, _locked_item(item.camera or "", item.id))
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        if 0 <= current < self.table.rowCount():
            self.table.selectRow(current)
        self.table.verticalScrollBar().setValue(scroll)
        self._list_summary.setText(
            f"{len(rows)} Dateien in der Liste. Klick oder Mouseover zeigt Vorschau. "
            "Doppelklick auf eine IGC-Datei setzt den DHV-Leonardo-Link."
        )
        self._show_selected_preview()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.table.viewport() and event.type() == QEvent.Type.Leave:
            self._show_selected_preview()
        return super().eventFilter(watched, event)

    def _on_item_entered(self, item: QTableWidgetItem) -> None:
        file_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(file_id, int):
            self._show_file_preview(file_id)

    def _on_selection_changed(self) -> None:
        self._show_selected_preview()

    def _show_selected_preview(self) -> None:
        row = self.table.currentRow()
        name = self.table.item(row, 0) if row >= 0 else None
        file_id = name.data(Qt.ItemDataRole.UserRole) if name is not None else None
        if isinstance(file_id, int):
            self._show_file_preview(file_id)
            return
        self._preview_id = None
        self._preview_image.setPixmap(QPixmap())
        self._preview_image.setText("Keine Datei gewählt")
        self._preview_meta.setText("Klick oder Mouseover auf eine Zeile zeigt Metadaten.")

    def _show_file_preview(self, file_id: int) -> None:
        item = self._files.get(file_id)
        if item is None:
            return
        self._preview_id = file_id
        pixmap = self._preview_pixmap(item)
        if pixmap.isNull():
            self._preview_image.setPixmap(QPixmap())
            self._preview_image.setText("Kein Vorschaubild")
        else:
            self._preview_image.setText("")
            self._preview_image.setPixmap(pixmap)
        self._preview_meta.setText(file_preview_text(item, dhv_url=self._dhv_urls.get(file_id, "")))

    def _preview_pixmap(self, item: SourceFile) -> QPixmap:
        thumbs = self.workspace.thumbs_dir()
        if thumbs is None:
            return _placeholder_pixmap()
        size = AppSettings().default_thumbnail_size
        path = cached_thumbnail_path(
            thumbs,
            source_file_id=item.id,
            sha256=item.sha256,
            size=size,
            rotation_degrees=item.rotation_degrees,
            prefer_existing=True,
        )
        key = str(path)
        if self._thumb_cache is not None and self._thumb_cache[0] == key:
            return self._thumb_cache[1]
        if item.file_kind == FileKind.TEXT.value or not path.is_file():
            pixmap = _placeholder_pixmap()
        else:
            loaded = QPixmap(str(path))
            if loaded.isNull():
                pixmap = _placeholder_pixmap()
            else:
                pixmap = loaded.scaled(
                    QSize(240, 240),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        self._thumb_cache = (key, pixmap)
        return pixmap

    def _on_row_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        kind = self.table.item(row, 1)
        name = self.table.item(row, 0)
        if kind is None or name is None or kind.text() != "gps":
            return
        if not name.text().lower().endswith(".igc"):
            return
        file_id = name.data(Qt.ItemDataRole.UserRole)
        if not isinstance(file_id, int):
            return
        pilot = self.table.item(row, 4).text() if self.table.item(row, 4) else ""
        current = self.workspace.gps_track_urls().get(file_id, "")
        dialog = FlightLinkDialog(name.text(), pilot, current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_flight_url(file_id, dialog.url_value())

    def _save_flight_url(self, source_file_id: int, url: str) -> None:
        try:
            self.workspace.set_gps_track_url(source_file_id, url)
        except (ProjectError, ValueError) as exc:
            QMessageBox.warning(self, "DHV-Leonardo", str(exc))
            self.refresh()
            return
        self.refresh()


def format_import_status(current: int, total: int, message: str, path: str = "") -> str:
    """Build a status-bar line from indexer progress."""
    text = message.strip()
    if not text:
        text = Path(path).name or "Import"
    if total <= 0 or current <= 0:
        return text
    percent = min(100, int(round(100 * current / total)))
    return f"{text} · {current} von {total} ({percent} %)"


def progress_bar_format(message: str) -> str:
    """QProgressBar format: only %p/%v/%m are placeholders, a lone % is literal."""
    safe = message.replace("%p", "% p").replace("%v", "% v").replace("%m", "% m")
    text = safe.strip()
    if text:
        return f"{text}  %v von %m (%p %)"
    return "%v von %m (%p %)"


def _format_captured(item: SourceFile) -> str:
    if item.captured_at is None:
        return "–"
    stamp = item.captured_at.strftime("%Y-%m-%d %H:%M:%S")
    if item.timezone_unknown:
        return f"{stamp} (TZ unbekannt)"
    if item.timezone_name:
        return f"{stamp} {item.timezone_name}"
    return stamp


def _format_gps(item: SourceFile) -> str:
    if item.gps_latitude is None or item.gps_longitude is None:
        return "–"
    source = item.position_source or "?"
    return f"{item.gps_latitude:.5f}, {item.gps_longitude:.5f} ({source})"


def file_preview_text(item: SourceFile, *, dhv_url: str = "") -> str:
    """Human-readable metadata block for the Import preview pane."""

    lines = [
        item.filename,
        item.path,
        f"Typ: {item.file_kind} ({item.extension})",
        f"Größe: {_format_size(item.size_bytes)}",
        f"Aufnahme: {_format_captured(item)}",
    ]
    if item.captured_at_source:
        lines.append(f"Zeitquelle: {item.captured_at_source}")
    gps = _format_gps(item)
    if gps != "–":
        extra = ""
        if item.gps_altitude is not None:
            extra = f", {item.gps_altitude:.0f} m"
        lines.append(f"GPS: {gps}{extra}")
    heading = _format_heading(item)
    if heading:
        lines.append(heading)
    if item.camera:
        lines.append(f"Kamera: {item.camera}")
    if item.lens:
        lines.append(f"Objektiv: {item.lens}")
    if item.focal_length is not None:
        lines.append(f"Brennweite: {item.focal_length:g} mm")
    if item.focal_length_35mm is not None:
        lines.append(f"35-mm-äquivalent: {item.focal_length_35mm:g} mm")
    if item.iso is not None:
        lines.append(f"ISO: {item.iso}")
    if item.exposure_time:
        lines.append(f"Belichtung: {item.exposure_time}")
    if item.aperture:
        lines.append(f"Blende: {item.aperture}")
    if item.width and item.height:
        lines.append(f"Bildgröße: {item.width} × {item.height}")
    if item.orientation is not None:
        lines.append(f"Orientierung: {item.orientation}")
    if item.rotation_degrees:
        lines.append(f"Drehung: {item.rotation_degrees}°")
    if dhv_url:
        lines.append(f"DHV-Leonardo: {dhv_url}")
    return "\n".join(lines)


def _format_heading(item: SourceFile) -> str | None:
    if item.heading_degrees is None:
        return None
    ref = "magnetisch" if (item.heading_ref or "").upper() == "M" else "geografisch Nord"
    return f"Blickrichtung: {item.heading_degrees:.1f}° ({ref})"


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _placeholder_pixmap() -> QPixmap:
    pixmap = QPixmap(240, 180)
    pixmap.fill(QColor("#243044"))
    return pixmap


def _locked_item(text: str, source_file_id: int) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setData(Qt.ItemDataRole.UserRole, source_file_id)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    return item


class FlightLinkDialog(QDialog):
    def __init__(self, filename: str, pilot: str, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DHV-Leonardo")
        self.resize(480, 200)
        root = QVBoxLayout(self)
        intro = QLabel(
            f"{filename}\nPilot: {pilot or '—'}\n"
            "Link zum Flug im DHV-Leonardo (XC-Server). Originale IGC-Datei bleibt unverändert."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)
        form = QFormLayout()
        self.url_edit = QLineEdit(url)
        self.url_edit.setPlaceholderText("https://de.dhv.de/dbnx/…")
        form.addRow("DHV-Leonardo", self.url_edit)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def url_value(self) -> str:
        return self.url_edit.text().strip()


def _sync_name_line(count: int, names: tuple[str, ...], *, empty: str, nonempty: str) -> str:
    if count <= 0:
        return empty
    shown = ", ".join(names)
    extra = count - len(names)
    sample = f"{shown} …" if extra > 0 else shown
    return nonempty.format(count=count, sample=sample)


class SourceSyncDialog(QDialog):
    """Confirm purge of missing files and choose Timeline vs Pool for new media."""

    def __init__(self, plan: SourceSyncPlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Synchronisieren")
        self.resize(520, 280)
        root = QVBoxLayout(self)
        intro = QLabel(
            "Das Quellverzeichnis wird mit dem Tagebuch abgeglichen. "
            "Originaldateien bleiben unverändert."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)
        new_line = _sync_name_line(
            plan.new_count,
            plan.new_names,
            empty="Keine neuen Dateien.",
            nonempty="{count} neue Dateien ({sample}).",
        )
        missing_line = _sync_name_line(
            plan.missing_count,
            plan.missing_names,
            empty="Keine fehlenden Dateien.",
            nonempty=(
                "{count} Dateien sind nicht mehr im Ordner ({sample}) "
                "und werden aus dem Tagebuch entfernt (Timeline, Pool, Vorschaubilder)."
            ),
        )
        new_label = QLabel(new_line)
        new_label.setWordWrap(True)
        missing_label = QLabel(missing_line)
        missing_label.setWordWrap(True)
        missing_label.setObjectName("pageSubtitle")
        root.addWidget(new_label)
        root.addWidget(missing_label)
        self._timeline = QRadioButton("In die Timeline (Tage nach Aufnahmezeit)", self)
        self._pool = QRadioButton("In den Medienpool", self)
        self._timeline.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self._timeline)
        group.addButton(self._pool)
        dest = QLabel("Neue Medien")
        dest.setObjectName("pageSubtitle")
        root.addWidget(dest)
        root.addWidget(self._timeline)
        root.addWidget(self._pool)
        has_new = plan.new_count > 0
        dest.setVisible(has_new)
        self._timeline.setVisible(has_new)
        self._pool.setVisible(has_new)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Synchronisieren")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def park_new_media(self) -> bool:
        return self._pool.isChecked() and not self._pool.isHidden()
