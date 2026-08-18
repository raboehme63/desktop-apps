"""Source directory import with background indexing."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
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
            "Fotos ohne Koordinaten werden zeitlich mit GPX- und IGC-Tracks abgeglichen. "
            "IGC-Flüge: Pilot aus dem Log, DHV-Leonardo-Link in der Tabelle."
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

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Datei", "Typ", "Aufnahmezeit", "GPS", "Kamera / Pilot", "DHV-Leonardo"]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
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
        self.progress.setFormat("Verzeichnis wird durchsucht…")
        worker = IndexRunnable(self.workspace.current, path)
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
        self._list_refresh.stop()
        if not isinstance(result, IndexResult):
            return
        self.progress.setValue(self.progress.maximum())
        summary = (
            f"Import fertig: {result.indexed} neu, {result.updated} aktualisiert, "
            f"{result.skipped_unchanged} unverändert, {result.positions_matched} Positionen aus Track, "
            f"{result.thumbnails_written} Vorschaubilder, {result.errors} Fehler"
        )
        self.progress.setFormat(summary)
        self.refresh()
        self.import_finished.emit()
        self.status_message.emit(summary)

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
        urls = self.workspace.gps_track_urls()
        scroll = self.table.verticalScrollBar().value()
        current = self.table.currentRow()
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            is_igc = Path(item.path).suffix.lower() == ".igc"
            self.table.setItem(index, 0, _locked_item(item.filename, item.id))
            self.table.setItem(index, 1, _locked_item(item.file_kind, item.id))
            self.table.setItem(index, 2, _locked_item(_format_captured(item), item.id))
            self.table.setItem(index, 3, _locked_item(_format_gps(item), item.id))
            self.table.setItem(index, 4, _locked_item(item.camera or "", item.id))
            link = urls.get(item.id, "") if is_igc else ""
            link_item = QTableWidgetItem(link)
            link_item.setData(Qt.ItemDataRole.UserRole, item.id)
            if is_igc:
                link_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
                )
            else:
                link_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(index, 5, link_item)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        if 0 <= current < self.table.rowCount():
            self.table.selectRow(current)
        self.table.verticalScrollBar().setValue(scroll)
        self._list_summary.setText(
            f"{len(rows)} Dateien in der Liste. Doppelklick auf eine IGC-Datei setzt den DHV-Leonardo-Link."
        )

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
        current = self.table.item(row, 5).text() if self.table.item(row, 5) else ""
        dialog = FlightLinkDialog(name.text(), pilot, current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_flight_url(file_id, dialog.url_value())

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 5:
            return
        file_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(file_id, int):
            return
        self._save_flight_url(file_id, item.text())

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
