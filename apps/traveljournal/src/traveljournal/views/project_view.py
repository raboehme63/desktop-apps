"""Project create / open / save view."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
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
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from travelcore.database.project_catalog import (
    CATALOG_SORT_DATE,
    CATALOG_SORT_NAME,
    ProjectDescriptor,
    filter_project_catalog,
    sort_project_catalog,
)
from travelcore.database.project_store import folder_name_from_project_name
from travelcore.exceptions import ProjectError
from traveljournal.services.workspace import Workspace
from traveljournal.ui.errors import report_exception
from traveljournal.widgets.click_combo import ClickCombo
from traveljournal.widgets.country_picker import CountryPicker
from traveljournal.widgets.switch import SwitchToggle


def format_local_datetime(value: datetime) -> str:
    """Show a stored UTC instant as local wall-clock time."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


_EMPTY_DATE = QDate(100, 1, 1)
CATALOG_VISIBLE_ROWS = 5


def _readonly_switch_row(parent: QWidget | None = None) -> tuple[QWidget, SwitchToggle]:
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    caption = QLabel("Nur lesen")
    caption.setObjectName("fieldCaption")
    switch = SwitchToggle(row)
    switch.setObjectName("projectReadOnlySwitch")
    switch.setAccessibleName("Nur lesen")
    switch.setChecked(True)
    switch.setToolTip("Ausgeschaltet öffnet das Projekt zum Bearbeiten.")
    layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addStretch(1)
    return row, switch


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


def _paths_equal(left: Path | None, right: Path | None) -> bool:
    if left is None or right is None:
        return False
    try:
        return left.expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
            os.path.normpath(str(right))
        )


class CatalogFoldHeader(QFrame):
    """Chevron plus the selected project; click expands the separate project list."""

    toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = True
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)
        self._chevron = QLabel("▸")
        self._chevron.setObjectName("galleryFoldChevron")
        self._current = QLabel("Kein Projekt ausgewählt")
        self._current.setObjectName("projectCatalogCurrent")
        self._current.setWordWrap(False)
        row.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._current, 1, Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_collapsed(True)

    def set_current_text(self, text: str) -> None:
        self._current.setText(text)
        self._current.setToolTip(text)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self._chevron.setText("▸" if self._collapsed else "▾")
        self.setToolTip("Projektliste ausklappen" if self._collapsed else "Projektliste einklappen")

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit()
        super().mouseReleaseEvent(event)


class ProjectView(QWidget):
    project_changed = Signal(str)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._span_updating = False
        self._catalog_rows: list[ProjectDescriptor] = []
        self._catalog_selected: Path | None = None

        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(16)

        title = QLabel("Projekt")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Bekannte Projekte aus dem Stammordner und zuletzt geöffneten Pfaden. "
            "Beim Anlegen werden Name und übergeordneter Ordner gewählt; daraus entsteht der Projektordner. "
            "Reise von–bis kommt aus den indexierten Daten und lässt sich hier anpassen; "
            "daraus folgt die Reisedauer. "
            "Bereiste Länder (Flagge und Umriss) erscheinen in der Travelbook-Reiseübersicht."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        catalog_caption = QLabel("Übersicht")
        catalog_caption.setObjectName("fieldCaption")
        root.addWidget(catalog_caption)
        catalog_tools = QHBoxLayout()
        catalog_tools.setSpacing(8)
        self._catalog_search = QLineEdit()
        self._catalog_search.setObjectName("projectCatalogSearch")
        self._catalog_search.setPlaceholderText("Suchen, * und ? möglich")
        self._catalog_search.setClearButtonEnabled(True)
        catalog_tools.addWidget(self._catalog_search, 1)
        catalog_tools.addWidget(QLabel("Sortierung"))
        self._catalog_sort = ClickCombo()
        self._catalog_sort.setObjectName("projectCatalogSort")
        self._catalog_sort.addItem("Name", CATALOG_SORT_NAME)
        self._catalog_sort.addItem("Datum", CATALOG_SORT_DATE)
        stored_sort = self.workspace.project_catalog_sort()
        self._catalog_sort.setCurrentIndex(1 if stored_sort == CATALOG_SORT_DATE else 0)
        catalog_tools.addWidget(self._catalog_sort)
        root.addLayout(catalog_tools)
        self._catalog_fold = CatalogFoldHeader()
        self._catalog_fold.setObjectName("projectCatalogFold")
        root.addWidget(self._catalog_fold)
        self._catalog_list_box = QWidget()
        list_box = QVBoxLayout(self._catalog_list_box)
        list_box.setContentsMargins(0, 0, 0, 0)
        list_box.setSpacing(8)
        self._catalog_list = QListWidget()
        self._catalog_list.setObjectName("projectCatalogList")
        self._catalog_list.setWordWrap(False)
        self._catalog_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._catalog_list.setSpacing(1)
        self._catalog_list.setUniformItemSizes(True)
        self._catalog_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._catalog_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._catalog_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        list_box.addWidget(self._catalog_list)
        self._catalog_empty = QLabel(
            "Noch keine Projekte. Legen Sie eines an oder öffnen Sie einen Ordner."
        )
        self._catalog_empty.setObjectName("pageSubtitle")
        self._catalog_empty.setWordWrap(True)
        list_box.addWidget(self._catalog_empty)
        root.addWidget(self._catalog_list_box)
        self._catalog_search.textChanged.connect(self._on_catalog_search_changed)
        self._catalog_sort.currentIndexChanged.connect(self._on_catalog_sort_changed)
        self._catalog_list.itemClicked.connect(self._on_catalog_item_clicked)
        self._catalog_list.itemActivated.connect(self._on_catalog_item_clicked)
        self._catalog_fold.toggled.connect(self._toggle_catalog)
        self._set_catalog_collapsed(self.workspace.project_catalog_collapsed(), persist=False)

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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.refresh()

    def refresh(self) -> None:
        self._refresh_catalog()
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
        parts = [
            f"{kind}: {count}"
            for kind, count in sorted(counts.items())
            if count and kind not in {"map", "act", "flights", "other"}
        ]
        self.counts_label.setText(", ".join(parts) if parts else "keine Dateien")

    def _refresh_catalog(self) -> None:
        self._catalog_rows = self.workspace.list_known_projects()
        if self.workspace.current is not None:
            self._catalog_selected = self.workspace.current.directory
        elif self._catalog_selected is None:
            recents = self.workspace.recent_projects()
            self._catalog_selected = recents[0] if recents else None
        self._apply_catalog_filter()
        self._update_catalog_current()

    def _on_catalog_search_changed(self) -> None:
        if self._catalog_search.text().strip():
            self._set_catalog_collapsed(False)
        self._apply_catalog_filter()

    def _on_catalog_sort_changed(self) -> None:
        key = str(self._catalog_sort.currentData() or CATALOG_SORT_NAME)
        self.workspace.set_project_catalog_sort(key)
        self._apply_catalog_filter()

    def _on_catalog_item_clicked(self, item: QListWidgetItem) -> None:
        raw = item.data(Qt.ItemDataRole.UserRole)
        if not raw:
            return
        self._catalog_selected = Path(str(raw))
        self._update_catalog_current()
        self._set_catalog_collapsed(True)

    def _selected_catalog_row(self) -> ProjectDescriptor | None:
        selected = self._catalog_selected
        if selected is None:
            return None
        for row in self._catalog_rows:
            if _paths_equal(row.directory, selected):
                return row
        return None

    def _update_catalog_current(self) -> None:
        row = self._selected_catalog_row()
        if row is None:
            self._catalog_fold.set_current_text("Kein Projekt ausgewählt")
            return
        self._catalog_fold.set_current_text(row.list_label())

    def _apply_catalog_filter(self) -> None:
        key = str(self._catalog_sort.currentData() or CATALOG_SORT_NAME)
        rows = sort_project_catalog(self._catalog_rows, key)
        rows = filter_project_catalog(rows, self._catalog_search.text())
        self._catalog_list.clear()
        selected_item: QListWidgetItem | None = None
        for row in rows:
            item = QListWidgetItem(row.list_label())
            item.setData(Qt.ItemDataRole.UserRole, str(row.directory))
            item.setToolTip(row.list_label())
            if row.missing:
                item.setForeground(QColor("#8b95a8"))
            self._catalog_list.addItem(item)
            if _paths_equal(row.directory, self._catalog_selected):
                selected_item = item
        if selected_item is not None:
            selected_item.setSelected(True)
            self._catalog_list.setCurrentItem(selected_item)
        if not self._catalog_rows:
            self._catalog_empty.setText(
                "Noch keine Projekte. Legen Sie eines an oder öffnen Sie einen Ordner."
            )
            self._catalog_empty.show()
        elif not rows:
            self._catalog_empty.setText("Keine Treffer.")
            self._catalog_empty.show()
        else:
            self._catalog_empty.hide()
        self._sync_catalog_list_height()

    def _catalog_row_height(self) -> int:
        if self._catalog_list.count() > 0:
            row = self._catalog_list.sizeHintForRow(0)
            if row > 0:
                return row
        metrics = self._catalog_list.fontMetrics()
        return metrics.height() + 16

    def _sync_catalog_list_height(self) -> None:
        count = self._catalog_list.count()
        self._catalog_list.setVisible(count > 0)
        if count == 0:
            self._catalog_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self._catalog_list.setFixedHeight(0)
            return
        visible = min(count, CATALOG_VISIBLE_ROWS)
        row = self._catalog_row_height()
        spacing = self._catalog_list.spacing()
        body = visible * row + max(0, visible - 1) * spacing
        extra = 2 * self._catalog_list.frameWidth()
        margins = self._catalog_list.contentsMargins()
        extra += margins.top() + margins.bottom() + 8
        self._catalog_list.setFixedHeight(body + extra)
        if count > CATALOG_VISIBLE_ROWS:
            self._catalog_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self._catalog_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _toggle_catalog(self) -> None:
        self._set_catalog_collapsed(not self._catalog_list_box.isHidden())

    def _set_catalog_collapsed(self, collapsed: bool, *, persist: bool = True) -> None:
        flag = bool(collapsed)
        self._catalog_list_box.setVisible(not flag)
        self._catalog_fold.set_collapsed(flag)
        if not flag:
            self._sync_catalog_list_height()
        if persist:
            self.workspace.set_project_catalog_collapsed(flag)

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
            report_exception(self, "Projekt", exc)
            return
        self.refresh()
        self.project_changed.emit(opened.name)

    def open_project(self) -> None:
        row = self._selected_catalog_row()
        if row is not None:
            dialog = OpenProjectChoiceDialog(self, project_label=row.list_label())
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            if dialog.choice == OpenProjectChoiceDialog.CHOICE_SELECTED:
                self.open_project_at(row.directory, read_only=dialog.read_only)
                return
            if dialog.choice != OpenProjectChoiceDialog.CHOICE_OTHER:
                return
            self._open_project_from_folder_dialog(read_only=dialog.read_only)
            return
        self._open_project_from_folder_dialog()

    def _open_project_from_folder_dialog(self, *, read_only: bool | None = None) -> None:
        start = self.workspace.projects_root()
        directory = QFileDialog.getExistingDirectory(
            self,
            "Projektordner öffnen",
            str(start) if start is not None else "",
        )
        if not directory:
            return
        self.open_project_at(Path(directory), read_only=read_only)

    def open_project_at(self, directory: Path, *, read_only: bool | None = None) -> None:
        path = Path(directory).expanduser()
        if read_only is None:
            mode = OpenModeDialog(self, project_label=str(path))
            if mode.exec() != QDialog.DialogCode.Accepted:
                return
            read_only = mode.read_only
        current = self.workspace.current
        if current is not None:
            try:
                if current.directory.resolve() == path.resolve() and current.read_only == read_only:
                    return
            except OSError:
                pass
        if not (path / "project.sqlite").is_file():
            QMessageBox.warning(self, "Projekt", f"Projektordner nicht gefunden:\n{path}")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            opened = self.workspace.open_project(path, read_only=read_only)
        except ProjectError as exc:
            report_exception(self, "Projekt", exc)
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
            report_exception(self, "Projekt", exc)
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


class OpenProjectChoiceDialog(QDialog):
    """Ask whether to open the catalog selection or browse for another folder."""

    CHOICE_SELECTED = "selected"
    CHOICE_OTHER = "other"

    def __init__(self, parent: QWidget | None = None, *, project_label: str) -> None:
        super().__init__(parent)
        self.choice = ""
        self.setWindowTitle("Projekt öffnen")
        self.resize(520, 220)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)
        intro = QLabel(
            "Soll das ausgewählte Projekt geöffnet werden, oder ein anderes Projekt?"
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)
        current = QLabel(project_label)
        current.setObjectName("projectCatalogCurrent")
        current.setWordWrap(True)
        root.addWidget(current)
        switch_row, self._readonly_switch = _readonly_switch_row(self)
        root.addWidget(switch_row)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        selected_btn = QPushButton("Ausgewähltes Projekt")
        selected_btn.setObjectName("primary")
        other_btn = QPushButton("Anderes Projekt…")
        cancel_btn = QPushButton("Abbrechen")
        selected_btn.clicked.connect(self._choose_selected)
        other_btn.clicked.connect(self._choose_other)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(selected_btn)
        buttons.addWidget(other_btn)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)
        selected_btn.setDefault(True)
        self._selected_btn = selected_btn
        self._other_btn = other_btn
        self._cancel_btn = cancel_btn

    @property
    def read_only(self) -> bool:
        return self._readonly_switch.isChecked()

    def _choose_selected(self) -> None:
        self.choice = self.CHOICE_SELECTED
        self.accept()

    def _choose_other(self) -> None:
        self.choice = self.CHOICE_OTHER
        self.accept()


class OpenModeDialog(QDialog):
    """Ask whether to open a chosen folder as read-only (default) or writable."""

    def __init__(self, parent: QWidget | None = None, *, project_label: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Projekt öffnen")
        self.resize(520, 200)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)
        intro = QLabel("Wie soll das Projekt geöffnet werden? Standard ist Nur lesen.")
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)
        current = QLabel(project_label)
        current.setObjectName("projectCatalogCurrent")
        current.setWordWrap(True)
        root.addWidget(current)
        switch_row, self._readonly_switch = _readonly_switch_row(self)
        root.addWidget(switch_row)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        open_btn = QPushButton("Öffnen")
        open_btn.setObjectName("primary")
        cancel_btn = QPushButton("Abbrechen")
        open_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(open_btn)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)
        open_btn.setDefault(True)
        self._open_btn = open_btn
        self._cancel_btn = cancel_btn

    @property
    def read_only(self) -> bool:
        return self._readonly_switch.isChecked()


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
