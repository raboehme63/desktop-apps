"""Main application window."""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from travelcore.exceptions import ProjectError
from traveljournal.services.workspace import Workspace
from traveljournal.ui.sidebar import Sidebar
from traveljournal.views.export_view import ExportView
from traveljournal.views.import_view import ImportView
from traveljournal.views.journal_view import JournalView
from traveljournal.views.map_view import MapView
from traveljournal.views.photos_view import PhotosView
from traveljournal.views.project_view import ProjectView
from traveljournal.views.settings_dialog import SettingsDialog
from traveljournal.views.timeline_view import TimelineView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Reisetagebuch")
        self.resize(1180, 760)
        self.workspace = Workspace()

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.project_view = ProjectView(self.workspace)
        self.import_view = ImportView(self.workspace)
        self.timeline_view = TimelineView(self.workspace)
        self.map_view = MapView(self.workspace)
        self.photos_view = PhotosView(self.workspace)
        self.journal_view = JournalView(self.workspace)
        self.export_view = ExportView()

        self._pages = {
            "project": self.stack.addWidget(self.project_view),
            "import": self.stack.addWidget(self.import_view),
            "timeline": self.stack.addWidget(self.timeline_view),
            "map": self.stack.addWidget(self.map_view),
            "photos": self.stack.addWidget(self.photos_view),
            "journal": self.stack.addWidget(self.journal_view),
            "export": self.stack.addWidget(self.export_view),
        }

        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        status = QStatusBar()
        self.setStatusBar(status)
        self._set_status("Kein Projekt geöffnet")
        self._build_menu()

        self.sidebar.page_changed.connect(self._show_page)
        self.project_view.project_changed.connect(self._on_project_changed)
        self.import_view.status_message.connect(self._set_status)
        self.import_view.import_finished.connect(self.project_view.refresh)
        self.import_view.import_finished.connect(self.photos_view.refresh)
        self.import_view.import_finished.connect(self.map_view.refresh)
        self.import_view.import_finished.connect(self.timeline_view.rebuild)
        self.import_view.import_finished.connect(self.journal_view.refresh)
        self.photos_view.status_message.connect(self._set_status)
        self.map_view.status_message.connect(self._set_status)
        self.timeline_view.status_message.connect(self._set_status)
        self.journal_view.status_message.connect(self._set_status)
        self.timeline_view.timeline_changed.connect(self.journal_view.refresh)
        self.timeline_view.timeline_changed.connect(self.map_view.refresh)
        self.journal_view.timeline_changed.connect(self.timeline_view.refresh)
        self.journal_view.timeline_changed.connect(self.map_view.refresh)
        self.journal_view.timeline_changed.connect(self.photos_view.refresh)
        self._sync_menu()

    def _build_menu(self) -> None:
        bar = self.menuBar()
        project_menu = bar.addMenu("Projekt")
        new_action = QAction("Neues Projekt…", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.project_view.create_project)
        open_action = QAction("Öffnen…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.project_view.open_project)
        save_action = QAction("Speichern", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.project_view.save_project)
        close_action = QAction("Schließen", self)
        close_action.triggered.connect(self.project_view.close_project)
        self._settings_action = QAction("Einstellungen…", self)
        self._settings_action.triggered.connect(self._open_settings)
        quit_action = QAction("Beenden", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        project_menu.addAction(new_action)
        project_menu.addAction(open_action)
        project_menu.addAction(save_action)
        project_menu.addAction(close_action)
        project_menu.addSeparator()
        project_menu.addAction(self._settings_action)
        project_menu.addSeparator()
        project_menu.addAction(quit_action)

    def _sync_menu(self) -> None:
        self._settings_action.setEnabled(self.workspace.current is not None)

    def _open_settings(self) -> None:
        if self.workspace.current is None:
            QMessageBox.information(self, "Einstellungen", "Bitte zuerst ein Projekt anlegen oder öffnen.")
            return
        try:
            current = self.workspace.project_settings()
        except ProjectError as exc:
            QMessageBox.warning(self, "Einstellungen", str(exc))
            return
        dialog = SettingsDialog(current, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            rebased = self.workspace.apply_project_settings(dialog.result_settings())
        except ProjectError as exc:
            QMessageBox.warning(self, "Einstellungen", str(exc))
            return
        self.project_view.refresh()
        self.import_view.refresh()
        self.photos_view.refresh()
        self.timeline_view.refresh()
        self.journal_view.refresh()
        self.map_view.refresh()
        if rebased:
            self._set_status(f"Einstellungen gespeichert. {rebased} Dateipfade angepasst.")
            QMessageBox.information(
                self,
                "Einstellungen",
                f"Der Index wurde auf das neue Wurzelverzeichnis umgeschrieben ({rebased} Dateien). "
                "Die Originaldateien selbst wurden nicht verschoben.",
            )
        else:
            self._set_status("Einstellungen gespeichert.")

    def _show_page(self, key: str) -> None:
        index = self._pages.get(key)
        if index is not None:
            self.stack.setCurrentIndex(index)
            self.sidebar.set_current(key)
        if key == "photos":
            self.photos_view.refresh()
        if key == "map":
            self.map_view.refresh()
        if key == "timeline":
            self.timeline_view.refresh()
        if key == "journal":
            self.journal_view.refresh()

    def _on_project_changed(self, name: str) -> None:
        self._sync_menu()
        if name:
            self.setWindowTitle(f"Reisetagebuch – {name}")
            self._set_status(f"Projekt geöffnet: {name}")
            self.import_view.refresh()
            self.photos_view.refresh()
            self.map_view.refresh()
            self.timeline_view.refresh()
            self.journal_view.refresh()
        else:
            self.setWindowTitle("Reisetagebuch")
            self._set_status("Kein Projekt geöffnet")
            self.photos_view.refresh()
            self.map_view.refresh()
            self.timeline_view.refresh()
            self.journal_view.refresh()

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.workspace.close()
        super().closeEvent(event)
