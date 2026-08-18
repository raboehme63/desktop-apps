"""Project create / open / save view."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from travelcore.exceptions import ProjectError
from traveljournal.services.workspace import Workspace


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
        subtitle = QLabel("Ein Reiseprojekt liegt in einem eigenen Ordner mit SQLite-Datenbank.")
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
        self.path_label = QLabel("–")
        self.created_label = QLabel("–")
        self.source_label = QLabel("–")
        self.counts_label = QLabel("–")
        info_layout.addWidget(QLabel("Ordner"), 0, 0)
        info_layout.addWidget(self.path_label, 0, 1)
        info_layout.addWidget(QLabel("Angelegt"), 1, 0)
        info_layout.addWidget(self.created_label, 1, 1)
        info_layout.addWidget(QLabel("Quelle"), 2, 0)
        info_layout.addWidget(self.source_label, 2, 1)
        info_layout.addWidget(QLabel("Index"), 3, 0)
        info_layout.addWidget(self.counts_label, 3, 1)
        root.addWidget(info)

        hint = QLabel(
            "Originalfotos werden nicht kopiert. Die Datenbank speichert nur Pfade, "
            "Metadaten und den SHA-256-Hash."
        )
        hint.setObjectName("pageSubtitle")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        current = self.workspace.current
        project = self.workspace.project_row()
        if current is None or project is None:
            self.name_edit.setText("")
            self.path_label.setText("Kein Projekt geöffnet")
            self.created_label.setText("–")
            self.source_label.setText("–")
            self.counts_label.setText("–")
            return
        self.name_edit.setText(project.name)
        self.path_label.setText(str(current.directory))
        self.created_label.setText(project.created_at.isoformat(sep=" ", timespec="seconds"))
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

    def create_project(self) -> None:
        name = self.name_edit.text().strip() or "Neue Reise"
        directory = QFileDialog.getExistingDirectory(self, "Projektordner wählen")
        if not directory:
            return
        try:
            self.workspace.create_project(Path(directory), name)
        except ProjectError as exc:
            QMessageBox.warning(self, "Projekt", str(exc))
            return
        self.refresh()
        self.project_changed.emit(name)

    def open_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Projektordner öffnen")
        if not directory:
            return
        try:
            opened = self.workspace.open_project(Path(directory))
        except ProjectError as exc:
            QMessageBox.warning(self, "Projekt", str(exc))
            return
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
