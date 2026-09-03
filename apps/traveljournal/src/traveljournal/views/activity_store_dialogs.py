"""Dialogs to pick the activity SQLite file and load tracks from it."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fitnesscore.database.engine import DB_NAME, LEGACY_DB_NAME

_EMPTY_DATE = QDate(100, 1, 1)


def default_activity_db_name() -> str:
    return DB_NAME


def split_activity_db_path(stored: str) -> tuple[Path | None, str]:
    """Directory plus sqlite filename. Default name is ``activity.sqlite``."""

    text = stored.strip()
    if not text:
        return None, DB_NAME
    path = Path(text)
    if path.suffix.lower() == ".sqlite":
        return path.parent if str(path.parent) else None, path.name
    if path.is_dir():
        preferred = path / DB_NAME
        legacy = path / LEGACY_DB_NAME
        if preferred.is_file():
            return path, DB_NAME
        if legacy.is_file():
            return path, LEGACY_DB_NAME
        return path, DB_NAME
    return path.parent if str(path.parent) else None, path.name or DB_NAME


def join_activity_db_path(directory: Path | None, filename: str) -> Path:
    name = filename.strip() or DB_NAME
    if Path(name).suffix.lower() != ".sqlite":
        name = f"{Path(name).name}.sqlite"
    if directory is None:
        return Path(name)
    return directory / Path(name).name


def _configure_date_edit(edit: QDateEdit) -> None:
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy")
    edit.setSpecialValueText("–")
    edit.setMinimumDate(_EMPTY_DATE)
    edit.setDate(_EMPTY_DATE)
    edit.setMinimumWidth(120)
    edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


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


class ActivityDbDialog(QDialog):
    """Pick the SQLite filename (not a folder). Default ``activity.sqlite``."""

    def __init__(
        self,
        current: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Activity-Datenbank")
        self.setMinimumWidth(420)
        directory, filename = split_activity_db_path(current)
        self._directory = directory

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        intro = QLabel(
            "Eine Datenbank für Activity-Tracks und IGC-Flüge. "
            "Wählen Sie den Dateinamen, Standard ist activity.sqlite."
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setText(filename)
        self.name_edit.setPlaceholderText(DB_NAME)
        browse = QPushButton("Durchsuchen…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.name_edit, 1)
        row.addWidget(browse)
        form = QFormLayout()
        form.addRow("Datenbank", row)
        root.addLayout(form)
        self._path_label = QLabel()
        self._path_label.setObjectName("pageSubtitle")
        self._path_label.setWordWrap(True)
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self._path_label)
        self.name_edit.textChanged.connect(self._refresh_path)
        self._refresh_path()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText("Übernehmen")
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setText("Abbrechen")
        root.addWidget(buttons)

    def selected_path(self) -> str:
        return str(join_activity_db_path(self._directory, self.name_edit.text()))

    def _refresh_path(self) -> None:
        path = join_activity_db_path(self._directory, self.name_edit.text())
        if self._directory is None:
            self._path_label.setText("Noch kein Ordner. Über Durchsuchen eine vorhandene Datei wählen.")
            return
        self._path_label.setText(str(path))

    def _browse(self) -> None:
        start = join_activity_db_path(self._directory, self.name_edit.text().strip() or DB_NAME)
        if not start.parent.exists():
            start = Path(DB_NAME)
        chosen, _filter = QFileDialog.getOpenFileName(
            self,
            "Activity-Datenbank wählen",
            str(start),
            "SQLite-Datenbank (*.sqlite);;Alle Dateien (*.*)",
        )
        if not chosen:
            return
        path = Path(chosen)
        self._directory = path.parent
        self.name_edit.setText(path.name or DB_NAME)
        self._refresh_path()

    def _accept(self) -> None:
        name = self.name_edit.text().strip() or DB_NAME
        if self._directory is None:
            QMessageBox.information(
                self,
                "Activity-Datenbank",
                "Bitte über Durchsuchen eine Datenbankdatei wählen.",
            )
            return
        self.name_edit.setText(Path(name).name)
        self.accept()


class ActivityLoadDialog(QDialog):
    """Date range plus which track kinds to load from the activity store."""

    def __init__(
        self,
        *,
        date_from: date | None,
        date_to: date | None,
        include_activities: bool = True,
        include_flights: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Activity-Daten laden")
        self.reload = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        intro = QLabel(
            "Zeitraum kommt von Reise von–bis und lässt sich hier ändern. "
            "Neu laden gleicht mit bereits importierten Tracks ab."
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        self.from_edit = QDateEdit()
        _configure_date_edit(self.from_edit)
        self.to_edit = QDateEdit()
        _configure_date_edit(self.to_edit)
        _set_date_edit(self.from_edit, date_from)
        _set_date_edit(self.to_edit, date_to)
        form.addRow("Von", self.from_edit)
        form.addRow("Bis", self.to_edit)
        root.addLayout(form)

        self.activities_check = QCheckBox("Activity-Tracks")
        self.activities_check.setChecked(include_activities)
        self.flights_check = QCheckBox("Flüge")
        self.flights_check.setChecked(include_flights)
        root.addWidget(self.activities_check)
        root.addWidget(self.flights_check)

        buttons = QDialogButtonBox()
        load = buttons.addButton("Laden", QDialogButtonBox.ButtonRole.AcceptRole)
        reload = buttons.addButton("Neu laden", QDialogButtonBox.ButtonRole.ActionRole)
        cancel = buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        load.setObjectName("primary")
        load.clicked.connect(self._accept_load)
        reload.clicked.connect(self._accept_reload)
        cancel.clicked.connect(self.reject)
        root.addWidget(buttons)

    def date_from(self) -> date | None:
        return _date_from_edit(self.from_edit)

    def date_to(self) -> date | None:
        return _date_from_edit(self.to_edit)

    def include_activities(self) -> bool:
        return self.activities_check.isChecked()

    def include_flights(self) -> bool:
        return self.flights_check.isChecked()

    def _accept_load(self) -> None:
        self.reload = False
        self._accept_if_valid()

    def _accept_reload(self) -> None:
        self.reload = True
        self._accept_if_valid()

    def _accept_if_valid(self) -> None:
        if not self.include_activities() and not self.include_flights():
            QMessageBox.information(
                self,
                "Activity-Daten laden",
                "Bitte Activity-Tracks oder Flüge ankreuzen.",
            )
            return
        start = self.date_from()
        end = self.date_to()
        if start is None or end is None:
            QMessageBox.information(self, "Activity-Daten laden", "Bitte einen Zeitraum von–bis setzen.")
            return
        if end < start:
            QMessageBox.warning(self, "Activity-Daten laden", "Das Endedatum liegt vor dem Startdatum.")
            return
        self.accept()
