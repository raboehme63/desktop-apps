"""Project create / open / save view."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
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
    QVBoxLayout,
    QWidget,
)

from travelcore.database.project_store import folder_name_from_project_name
from travelcore.exceptions import ProjectError
from traveljournal.services.workspace import Workspace


def format_local_datetime(value: datetime) -> str:
    """Show a stored UTC instant as local wall-clock time."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


class ProjectView(QWidget):
    project_changed = Signal(str)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        title = QLabel("Projekt")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Beim Anlegen werden Name und übergeordneter Ordner gewählt; daraus entsteht der Projektordner."
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
            self.name_label.setText("–")
            self.path_label.setText("Kein Projekt geöffnet")
            self.created_label.setText("–")
            self.source_label.setText("–")
            self.counts_label.setText("–")
            return
        self.name_edit.setEnabled(True)
        self.name_edit.setText(project.name)
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
        except ProjectError as exc:
            QMessageBox.warning(self, "Projekt", str(exc))
            return
        self.refresh()
        self.project_changed.emit(name)

    def close_project(self) -> None:
        self.workspace.close()
        self.refresh()
        self.project_changed.emit("")


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
