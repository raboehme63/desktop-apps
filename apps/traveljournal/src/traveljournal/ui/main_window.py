"""Main application window."""

from __future__ import annotations

from datetime import date

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
from traveljournal.services.edit_history import redo_focused_text, undo_focused_text
from traveljournal.services.workspace import Workspace
from traveljournal.ui.sidebar import Sidebar
from traveljournal.views.export_view import ExportView
from traveljournal.views.import_view import ImportView
from traveljournal.views.map_view import MapView
from traveljournal.views.photos_view import PhotosView
from traveljournal.views.project_view import ProjectView
from traveljournal.views.help_dialog import HelpDialog
from traveljournal.views.settings_dialog import SettingsDialog
from traveljournal.views.timeline_view import TimelineView
from traveljournal.widgets.media_inspector import MediaInspectorWindow


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
        self.sidebar.set_collapsed(self.workspace.sidebar_collapsed())
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.project_view = ProjectView(self.workspace)
        self.import_view = ImportView(self.workspace)
        self.photos_view = PhotosView(self.workspace)
        self.timeline_view = TimelineView(self.workspace)
        self.map_view = MapView(self.workspace)
        self.export_view = ExportView()

        self._pages = {
            "project": self.stack.addWidget(self.project_view),
            "import": self.stack.addWidget(self.import_view),
            "photos": self.stack.addWidget(self.photos_view),
            "timeline": self.stack.addWidget(self.timeline_view),
            "map": self.stack.addWidget(self.map_view),
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
        self.sidebar.collapsed_changed.connect(self.workspace.set_sidebar_collapsed)
        self.project_view.project_changed.connect(self._on_project_changed)
        self.import_view.status_message.connect(self._set_status)
        self.import_view.import_finished.connect(self._on_import_finished)
        self.import_view.index_load_progress.connect(self._on_index_progress)
        self.import_view.index_load_finished.connect(self._on_index_loaded)
        self.photos_view.status_message.connect(self._set_status)
        self.photos_view.rating_changed.connect(self.timeline_view.apply_media_rating)
        self.photos_view.rating_changed.connect(self.map_view.apply_media_rating)
        self.map_view.status_message.connect(self._set_status)
        self.map_view.open_in_timeline.connect(self._open_timeline_entry)
        self.map_view.insert_section.connect(self._insert_section_between)
        self.map_view.rating_changed.connect(self.timeline_view.apply_media_rating)
        self.map_view.rating_changed.connect(self.photos_view.apply_media_rating)
        self.timeline_view.status_message.connect(self._set_status)
        self.timeline_view.timeline_changed.connect(self._on_timeline_changed)
        self.timeline_view.open_on_map.connect(self._open_map_entry)
        self.timeline_view.open_media_on_map.connect(self._open_map_media)
        self.workspace.history.applied.connect(self._on_history_applied)
        self.workspace.history.index_changed.connect(self._sync_edit_menu)
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

        edit_menu = bar.addMenu("Bearbeiten")
        self._undo_action = QAction("Rückgängig", self)
        self._undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self._undo_action.triggered.connect(self._undo)
        self._redo_action = QAction("Wiederherstellen", self)
        self._redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self._redo_action.triggered.connect(self._redo)
        edit_menu.addAction(self._undo_action)
        edit_menu.addAction(self._redo_action)
        self._sync_edit_menu()

        help_menu = bar.addMenu("Hilfe")
        symbols_action = QAction("Verkehrsmittelsymbole…", self)
        symbols_action.setShortcut(QKeySequence.StandardKey.HelpContents)
        symbols_action.triggered.connect(self._open_help)
        help_menu.addAction(symbols_action)

    def _sync_menu(self) -> None:
        self._settings_action.setEnabled(self.workspace.current is not None)
        self._sync_edit_menu()

    def _sync_edit_menu(self) -> None:
        history = self.workspace.history
        undo_label = history.undo_text().strip()
        redo_label = history.redo_text().strip()
        self._undo_action.setText(f"Rückgängig: {undo_label}" if undo_label else "Rückgängig")
        self._redo_action.setText(f"Wiederherstellen: {redo_label}" if redo_label else "Wiederherstellen")
        self._undo_action.setEnabled(True)
        self._redo_action.setEnabled(True)

    def _undo(self) -> None:
        if undo_focused_text():
            return
        if self.workspace.history.undo():
            self._set_status("Rückgängig")

    def _redo(self) -> None:
        if redo_focused_text():
            return
        if self.workspace.history.redo():
            self._set_status("Wiederhergestellt")

    def _on_history_applied(self) -> None:
        self.timeline_view.refresh(commit=False)
        self.photos_view.refresh()
        self.map_view.refresh(force=True)
        self._sync_inspectors()

    def _sync_inspectors(self) -> None:
        if self.workspace.current is None:
            return
        by_id = {item.source_file_id: item for item in self.workspace.gallery_items()}
        for inspector in self.findChildren(MediaInspectorWindow):
            current = inspector.item()
            updated = by_id.get(current.source_file_id)
            if updated is not None:
                inspector.sync_from_item(updated)

    def _open_help(self) -> None:
        HelpDialog(self).exec()

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
        self.workspace.history.clear()
        self.timeline_view.rebuild()
        self.photos_view.refresh()
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
            self.map_view.refresh(force=previous == "timeline")
        if key == "timeline":
            if previous == "map":
                self.timeline_view.refresh()
            else:
                self.timeline_view.ensure_loaded()

    def _on_timeline_changed(self) -> None:
        self.map_view.prepare_in_background(force=True)

    def _open_timeline_entry(self, group_key: str) -> None:
        self.timeline_view.begin_reveal()
        self._show_page("timeline")
        self.timeline_view.reveal_group(group_key)

    def _insert_section_between(self, span: object) -> None:
        if not isinstance(span, tuple) or len(span) != 2:
            return
        start, end = span
        if not isinstance(start, date) or not isinstance(end, date):
            return
        if self.timeline_view.create_section_between(start, end):
            self._show_page("timeline")

    def _open_map_entry(self, group_key: str) -> None:
        self.map_view.focus_group(group_key)
        self._show_page("map")

    def _open_map_media(self, group_key: str, source_file_id: int) -> None:
        self.map_view.focus_group_media(group_key, source_file_id)
        self._show_page("map")

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
