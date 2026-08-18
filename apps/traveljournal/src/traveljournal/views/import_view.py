"""Source directory import with background indexing."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select

from travelcore.database.models import FileError, SourceFile
from travelcore.exceptions import ProjectError
from travelcore.media.indexer import IndexResult
from traveljournal.services.workers import IndexRunnable
from traveljournal.services.workspace import Workspace


class ImportView(QWidget):
    status_message = Signal(str)
    import_finished = Signal()

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
            "Fotos ohne Koordinaten werden zeitlich mit GPX-Tracks abgeglichen."
        )
        subtitle.setObjectName("pageSubtitle")
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
        picker_layout.addWidget(self.path_edit, 1)
        picker_layout.addWidget(browse)
        picker_layout.addWidget(analyze)
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
        for column, key in enumerate(("photo", "video", "gps", "located", "text", "errors")):
            titles = {
                "photo": "Fotos",
                "video": "Videos",
                "gps": "Tracks",
                "located": "mit Ort",
                "text": "Texte",
                "errors": "Fehler",
            }
            value = QLabel("0")
            value.setObjectName("statValue")
            label = QLabel(titles[key])
            label.setObjectName("statLabel")
            cell = QVBoxLayout()
            cell.addWidget(value)
            cell.addWidget(label)
            grid.addLayout(cell, 0, column)
            self._stat_labels[key] = value
        root.addWidget(stats)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Datei", "Typ", "Aufnahmezeit", "GPS", "Kamera"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)
        self._list_summary = QLabel("")
        self._list_summary.setObjectName("pageSubtitle")
        root.addWidget(self._list_summary)

    def refresh(self) -> None:
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
        self._fill_table()
        counts = self.workspace.file_counts()
        for key in ("photo", "video", "gps", "text", "located"):
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

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Quellverzeichnis wählen")
        if directory:
            self.path_edit.setText(directory)

    def _start_import(self) -> None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Import", "Bitte zuerst ein Projekt anlegen oder öffnen.")
            return
        source = self.path_edit.text().strip()
        if not source:
            QMessageBox.information(self, "Import", "Bitte ein Quellverzeichnis wählen.")
            return
        path = Path(source)
        if not path.is_dir():
            QMessageBox.warning(self, "Import", "Das gewählte Verzeichnis existiert nicht.")
            return
        if self._busy:
            return
        self._busy = True
        self._analyze_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setFormat("Starte Import…")
        worker = IndexRunnable(self.workspace.current, path)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.files_ready.connect(self._on_files_ready)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        self._pool.start(worker)
        self.status_message.emit("Import läuft…")

    def _on_progress(self, current: int, total: int, path: str) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(current)
        name = Path(path).name
        self.progress.setFormat(f"%v / %m  {name}")

    def _on_files_ready(self) -> None:
        self._list_refresh.start()

    def _on_finished(self, result: object) -> None:
        self._busy = False
        self._analyze_button.setEnabled(True)
        self._list_refresh.stop()
        if not isinstance(result, IndexResult):
            return
        self.progress.setValue(self.progress.maximum())
        self.progress.setFormat(
            f"Fertig: {result.indexed} neu, {result.updated} aktualisiert, "
            f"{result.skipped_unchanged} unverändert, {result.positions_matched} Positionen aus Track, "
            f"{result.thumbnails_written} Vorschaubilder, {result.errors} Fehler"
        )
        self.refresh()
        self.import_finished.emit()
        self.status_message.emit(self.progress.format())

    def _on_failed(self, message: str) -> None:
        self._busy = False
        self._analyze_button.setEnabled(True)
        self._list_refresh.stop()
        self.refresh()
        self.progress.setFormat("Import fehlgeschlagen")
        QMessageBox.warning(self, "Import", message)
        self.status_message.emit(f"Importfehler: {message}")

    def _fill_table(self) -> None:
        rows = self.workspace.source_files()
        scroll = self.table.verticalScrollBar().value()
        current = self.table.currentRow()
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            self.table.setItem(index, 0, QTableWidgetItem(item.filename))
            self.table.setItem(index, 1, QTableWidgetItem(item.file_kind))
            self.table.setItem(index, 2, QTableWidgetItem(_format_captured(item)))
            self.table.setItem(index, 3, QTableWidgetItem(_format_gps(item)))
            self.table.setItem(index, 4, QTableWidgetItem(item.camera or ""))
        self.table.setUpdatesEnabled(True)
        if 0 <= current < self.table.rowCount():
            self.table.selectRow(current)
        self.table.verticalScrollBar().setValue(scroll)
        self._list_summary.setText(f"{len(rows)} Dateien in der Liste")


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
