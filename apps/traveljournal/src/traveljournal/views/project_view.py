"""Project create / open / save view."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from travelcore.database.project_store import folder_name_from_project_name
from travelcore.exceptions import ProjectError
from traveljournal.services.workspace import Workspace
from traveljournal.widgets.country_picker import CountryPicker


def format_local_datetime(value: datetime) -> str:
    """Show a stored UTC instant as local wall-clock time."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


_EMPTY_DATE = QDate(100, 1, 1)


def _configure_trip_date_edit(edit: QDateEdit) -> None:
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy")
    edit.setSpecialValueText("–")
    edit.setMinimumDate(_EMPTY_DATE)
    edit.setDate(_EMPTY_DATE)
    edit.setMinimumWidth(140)
    edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def _date_from_edit(edit: QDateEdit) -> date | None:
    chosen = edit.date()
    if chosen <= edit.minimumDate():
        return None
    return date(chosen.year(), chosen.month(), chosen.day())


def _set_date_edit(edit: QDateEdit, value: date | None) -> None:
    if value is None:
        edit.setDate(edit.minimumDate())
        return
    edit.setDate(QDate(value.year, value.month, value.day))


class ProjectView(QWidget):
    project_changed = Signal(str)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._span_updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        title = QLabel("Projekt")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Beim Anlegen werden Name und übergeordneter Ordner gewählt; daraus entsteht der Projektordner. "
            "Reise von–bis kommt aus den indexierten Daten und lässt sich hier anpassen; "
            "daraus folgt die Reisedauer. "
            "Bereiste Länder (Flagge und Umriss) erscheinen in der Travelbook-Reiseübersicht."
        )
        subtitle.setObjectName("pageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(12)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Reisename, z. B. Italien 2025")
        card_layout.addWidget(QLabel("Name"))
        card_layout.addWidget(self.name_edit)

        span_caption = QLabel("Reise von–bis")
        span_caption.setObjectName("fieldCaption")
        card_layout.addWidget(span_caption)
        span_row = QHBoxLayout()
        span_row.setSpacing(10)
        span_row.addWidget(QLabel("Von"))
        self.start_edit = QDateEdit()
        _configure_trip_date_edit(self.start_edit)
        span_row.addWidget(self.start_edit, 1)
        span_row.addWidget(QLabel("Bis"))
        self.end_edit = QDateEdit()
        _configure_trip_date_edit(self.end_edit)
        span_row.addWidget(self.end_edit, 1)
        card_layout.addLayout(span_row)
        self.duration_label = QLabel("Dauer: –")
        self.duration_label.setObjectName("pageSubtitle")
        card_layout.addWidget(self.duration_label)
        self.start_edit.dateChanged.connect(self._on_start_changed)
        self.end_edit.dateChanged.connect(self._on_end_changed)

        countries_caption = QLabel("Bereiste Länder")
        countries_caption.setObjectName("fieldCaption")
        card_layout.addWidget(countries_caption)
        self.country_picker = CountryPicker()
        card_layout.addWidget(self.country_picker)

        buttons = QHBoxLayout()
        new_btn = QPushButton("Neues Projekt")
        new_btn.setObjectName("primary")
        open_btn = QPushButton("Projekt öffnen")
        save_btn = QPushButton("Projekt speichern")
        close_btn = QPushButton("Schließen")
        new_btn.clicked.connect(self.create_project)
        open_btn.clicked.connect(self.open_project)
        save_btn.clicked.connect(self.save_project)
        close_btn.clicked.connect(self.close_project)
        buttons.addWidget(new_btn)
        buttons.addWidget(open_btn)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)
        root.addWidget(card)

        info = QFrame()
        info.setObjectName("card")
        info_layout = QGridLayout(info)
        info_layout.setContentsMargins(20, 18, 20, 18)
        self.name_label = QLabel("–")
        self.path_label = QLabel("–")
        self.created_label = QLabel("–")
        self.source_label = QLabel("–")
        self.counts_label = QLabel("–")
        self.name_label.setWordWrap(True)
        self.path_label.setWordWrap(True)
        self.source_label.setWordWrap(True)
        info_layout.addWidget(QLabel("Name"), 0, 0)
        info_layout.addWidget(self.name_label, 0, 1)
        info_layout.addWidget(QLabel("Ordner"), 1, 0)
        info_layout.addWidget(self.path_label, 1, 1)
        info_layout.addWidget(QLabel("Angelegt"), 2, 0)
        info_layout.addWidget(self.created_label, 2, 1)
        info_layout.addWidget(QLabel("Quelle"), 3, 0)
        info_layout.addWidget(self.source_label, 3, 1)
        info_layout.addWidget(QLabel("Index"), 4, 0)
        info_layout.addWidget(self.counts_label, 4, 1)
        root.addWidget(info)

        hint = QLabel(
            "Originalfotos werden nicht kopiert. Die Datenbank speichert nur Pfade, "
            "Metadaten und den SHA-256-Hash."
        )
        hint.setObjectName("pageSubtitle")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.load_progress = QProgressBar()
        self.load_progress.setRange(0, 100)
        self.load_progress.setValue(0)
        self.load_progress.setFormat("Bereit")
        root.addWidget(self.load_progress)
        root.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        current = self.workspace.current
        project = self.workspace.project_row()
        if current is None or project is None:
            self.name_edit.setText("")
            self.name_edit.setEnabled(False)
            self._set_span(None, None)
            self.start_edit.setEnabled(False)
            self.end_edit.setEnabled(False)
            self.country_picker.set_codes(())
            self.country_picker.setEnabled(False)
            self.name_label.setText("–")
            self.path_label.setText("Kein Projekt geöffnet")
            self.created_label.setText("–")
            self.source_label.setText("–")
            self.counts_label.setText("–")
            return
        self.name_edit.setEnabled(True)
        self.name_edit.setText(project.name)
        self.start_edit.setEnabled(True)
        self.end_edit.setEnabled(True)
        start, end = self.workspace.load_trip_span()
        self._set_span(start, end)
        self.country_picker.setEnabled(True)
        self.country_picker.set_codes(self.workspace.load_trip_countries())
        self.name_label.setText(project.name)
        self.path_label.setText(str(current.directory))
        self.created_label.setText(format_local_datetime(project.created_at))
        self.source_label.setText(project.source_root or "noch nicht gewählt")
        try:
            configured = self.workspace.project_settings().source_root
        except ProjectError:
            configured = None
        if configured:
            self.source_label.setText(configured)
        counts = self.workspace.file_counts()
        parts = [f"{kind}: {count}" for kind, count in sorted(counts.items()) if count]
        self.counts_label.setText(", ".join(parts) if parts else "keine Dateien")

    def set_load_progress(self, current: int, total: int, message: str) -> None:
        if total <= 0:
            self.load_progress.setRange(0, 0)
            self.load_progress.setFormat(message or "Index wird gelesen…")
            return
        self.load_progress.setRange(0, total)
        self.load_progress.setValue(current)
        self.load_progress.setFormat(message)

    def clear_load_progress(self, message: str = "Bereit") -> None:
        self.load_progress.setRange(0, 100)
        self.load_progress.setValue(0)
        self.load_progress.setFormat(message)

    def create_project(self) -> None:
        dialog = NewProjectDialog(self, initial_parent=self.workspace.projects_root())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        parent, name = dialog.values()
        try:
            opened = self.workspace.create_project(parent, name)
        except ProjectError as exc:
            QMessageBox.warning(self, "Projekt", str(exc))
            return
        self.refresh()
        self.project_changed.emit(opened.name)

    def open_project(self) -> None:
        start = self.workspace.projects_root()
        directory = QFileDialog.getExistingDirectory(
            self,
            "Projektordner öffnen",
            str(start) if start is not None else "",
        )
        if not directory:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            opened = self.workspace.open_project(Path(directory))
        except ProjectError as exc:
            QMessageBox.warning(self, "Projekt", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh()
        self.project_changed.emit(opened.name)

    def save_project(self) -> None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Projekt", "Bitte zuerst ein Projekt öffnen oder anlegen.")
            return
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.information(self, "Projekt", "Bitte einen Namen eingeben.")
            return
        try:
            self.workspace.rename(name)
            self.workspace.save_trip_span(
                _date_from_edit(self.start_edit),
                _date_from_edit(self.end_edit),
            )
            self.workspace.save_trip_countries(list(self.country_picker.codes()))
        except ProjectError as exc:
            QMessageBox.warning(self, "Projekt", str(exc))
            return
        self.refresh()
        self.project_changed.emit(name)

    def close_project(self) -> None:
        self.workspace.close()
        self.refresh()
        self.project_changed.emit("")

    def _set_span(self, start: date | None, end: date | None) -> None:
        self._span_updating = True
        _set_date_edit(self.start_edit, start)
        _set_date_edit(self.end_edit, end)
        self._span_updating = False
        self._update_duration()

    def _on_start_changed(self) -> None:
        if self._span_updating:
            return
        start = _date_from_edit(self.start_edit)
        end = _date_from_edit(self.end_edit)
        if start is not None and end is not None and start > end:
            self._span_updating = True
            self.end_edit.setDate(self.start_edit.date())
            self._span_updating = False
        self._update_duration()

    def _on_end_changed(self) -> None:
        if self._span_updating:
            return
        start = _date_from_edit(self.start_edit)
        end = _date_from_edit(self.end_edit)
        if start is not None and end is not None and end < start:
            self._span_updating = True
            self.start_edit.setDate(self.end_edit.date())
            self._span_updating = False
        self._update_duration()

    def _update_duration(self) -> None:
        start = _date_from_edit(self.start_edit)
        end = _date_from_edit(self.end_edit)
        if start is None or end is None:
            self.duration_label.setText("Dauer: –")
            return
        days = (end - start).days + 1
        if days == 1:
            self.duration_label.setText("Dauer: 1 Tag")
            return
        self.duration_label.setText(f"Dauer: {days} Tage")


class NewProjectDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_parent: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neues Projekt")
        self.resize(540, 260)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        intro = QLabel(
            "Der Projektordner wird als Unterordner des gewählten Verzeichnisses angelegt. "
            "Der Anzeigename darf Zeichen enthalten, die im Ordnernamen ersetzt werden."
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("z. B. Italien 2025")
        form.addRow("Name", self.name_edit)

        folder_row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("Übergeordneter Ordner")
        if initial_parent is not None:
            self.dir_edit.setText(str(initial_parent))
        browse = QPushButton("Ordner wählen")
        browse.clicked.connect(self._browse_parent)
        folder_row.addWidget(self.dir_edit, 1)
        folder_row.addWidget(browse)
        form.addRow("Verzeichnis", folder_row)

        self.preview_label = QLabel("–")
        self.preview_label.setWordWrap(True)
        form.addRow("Projektordner", self.preview_label)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Anlegen")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.name_edit.textChanged.connect(self._update_preview)
        self.dir_edit.textChanged.connect(self._update_preview)
        self._update_preview()
        self.name_edit.setFocus()

    def values(self) -> tuple[Path, str]:
        name = self.name_edit.text().strip()
        if not name:
            raise ProjectError("Bitte einen Projektnamen eingeben.")
        raw = self.dir_edit.text().strip()
        if not raw:
            raise ProjectError("Bitte einen übergeordneten Ordner wählen.")
        parent = Path(raw).expanduser()
        if not parent.is_dir():
            raise ProjectError(f"Übergeordneter Ordner existiert nicht: {parent}")
        if not folder_name_from_project_name(name):
            raise ProjectError("Der Projektname ergibt keinen gültigen Ordnernamen.")
        return parent, name

    def _browse_parent(self) -> None:
        start = self.dir_edit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "Übergeordneten Ordner wählen", start)
        if directory:
            self.dir_edit.setText(directory)

    def _try_accept(self) -> None:
        try:
            self.values()
        except ProjectError as exc:
            QMessageBox.warning(self, "Neues Projekt", str(exc))
            return
        self.accept()

    def _update_preview(self) -> None:
        name = self.name_edit.text().strip()
        parent = self.dir_edit.text().strip()
        folder = folder_name_from_project_name(name)
        if parent and folder:
            self.preview_label.setText(str(Path(parent) / folder))
            return
        self.preview_label.setText("–")
