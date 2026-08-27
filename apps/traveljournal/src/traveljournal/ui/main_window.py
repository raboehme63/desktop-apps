"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from travelcore.exceptions import ProjectError
from traveljournal.__about__ import app_window_title
from traveljournal.services.workspace import Workspace
from traveljournal.ui.sidebar import Sidebar
from traveljournal.views.export_view import ExportView
from traveljournal.views.import_view import ImportView
from traveljournal.views.map_view import MapView
from traveljournal.views.photos_view import PhotosView
from traveljournal.views.project_view import ProjectView
from traveljournal.views.settings_dialog import SettingsDialog
from traveljournal.views.timeline_view import TimelineView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(app_window_title())
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
        self.export_view = ExportView()

        self._pages = {
            "project": self.stack.addWidget(self.project_view),
            "import": self.stack.addWidget(self.import_view),
            "timeline": self.stack.addWidget(self.timeline_view),
            "map": self.stack.addWidget(self.map_view),
            "photos": self.stack.addWidget(self.photos_view),
            "export": self.stack.addWidget(self.export_view),
        }

        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        status = QStatusBar()
        self.setStatusBar(status)
        self._load_progress = QProgressBar()
        self._load_progress.setMaximumWidth(240)
        self._load_progress.setTextVisible(True)
        self._load_progress.setFormat("Bereit")
        self._load_progress.hide()
        status.addPermanentWidget(self._load_progress)
        self._set_status("Kein Projekt geöffnet")
        self._build_menu()

        self.sidebar.page_changed.connect(self._show_page)
        self.project_view.project_changed.connect(self._on_project_changed)
        self.import_view.status_message.connect(self._set_status)
        self.import_view.import_finished.connect(self._on_import_finished)
        self.import_view.index_load_progress.connect(self._on_index_progress)
        self.import_view.index_load_finished.connect(self._on_index_loaded)
        self.photos_view.status_message.connect(self._set_status)
        self.map_view.status_message.connect(self._set_status)
        self.map_view.open_in_timeline.connect(self._open_timeline_entry)
        self.timeline_view.status_message.connect(self._set_status)
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
        self.map_view.prepare_in_background()

    def _on_import_finished(self) -> None:
        self.project_view.refresh()
        self._set_status("Timeline und Karte werden aktualisiert…")
        QTimer.singleShot(0, self._after_import)

    def _after_import(self) -> None:
        self.timeline_view.rebuild()
        self.map_view.prepare_in_background()

    def _on_index_progress(self, current: int, total: int, message: str) -> None:
        self._load_progress.show()
        if total <= 0:
            self._load_progress.setRange(0, 0)
        else:
            self._load_progress.setRange(0, total)
            self._load_progress.setValue(current)
        self._load_progress.setFormat(message or "Index wird gelesen…")
        self.project_view.set_load_progress(current, total, message)
        self._set_status(message)

    def _on_index_loaded(self) -> None:
        self._load_progress.hide()
        if self.workspace.current is None:
            self.project_view.clear_load_progress()
            self._set_status("Kein Projekt geöffnet")
            return
        self.project_view.clear_load_progress("Index geladen")
        self._set_status("Projekt geladen")
        self.map_view.prepare_in_background()
        key = self.sidebar.current_key()
        if key == "photos":
            self.photos_view.refresh()
        elif key == "map":
            self.map_view.refresh()
        elif key == "timeline":
            self.timeline_view.refresh()

    def _show_page(self, key: str) -> None:
        previous = next(
            (name for name, index in self._pages.items() if index == self.stack.currentIndex()),
            None,
        )
        if previous == "timeline" and key != "timeline" and not self.timeline_view.confirm_leave():
            self.sidebar.set_current("timeline")
            return
        index = self._pages.get(key)
        if index is not None:
            self.stack.setCurrentIndex(index)
            self.sidebar.set_current(key)
        if self.import_view.is_loading_index:
            return
        if key == "photos":
            self.photos_view.refresh()
        if key == "map":
            self.map_view.refresh()
        if key == "timeline":
            self.timeline_view.ensure_loaded()

    def _open_timeline_entry(self, group_key: str) -> None:
        self._show_page("timeline")
        self.timeline_view.reveal_group(group_key)

    def _on_project_changed(self, name: str) -> None:
        self._sync_menu()
        if name:
            self.setWindowTitle(app_window_title(name))
            self.timeline_view.clear()
            self.map_view.clear()
            self.photos_view.clear()
            self._show_page("project")
            self._set_status(f"Projekt geöffnet: {name} — Index wird geladen…")
            self._load_progress.show()
            self._load_progress.setRange(0, 0)
            self._load_progress.setFormat("Index wird gelesen…")
            self.import_view.refresh_summary()
            self.import_view.load_index_async()
            return
        self.setWindowTitle(app_window_title())
        self._load_progress.hide()
        self._set_status("Kein Projekt geöffnet")
        self.project_view.clear_load_progress()
        self.import_view.refresh_summary()
        self.import_view.load_index_async()
        self.photos_view.refresh()
        self.map_view.refresh()
        self.timeline_view.refresh()

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self.timeline_view.confirm_leave():
            event.ignore()
            return
        self.workspace.close()
        super().closeEvent(event)
