"""Project settings dialog. Original media files are never written."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from travelcore.project_settings import (
    EXPORT_FORMATS,
    ProjectSettings,
    normalize_map_track_color,
    normalize_stay_link_color,
)
from travelcore.timeline.symbols import TRANSPORT_SYMBOLS
from travelcore.timeline.transfer_links import (
    LINK_DASH_DASHED,
    LINK_DASH_SOLID,
    LINK_GEOMETRY_ARC,
    LINK_GEOMETRY_LINE,
)
from traveljournal.widgets.click_combo import ClickCombo
from traveljournal.widgets.transport_icons import fill_transport_combo, transport_badge_icon

_FORMAT_LABELS = {
    "html": "HTML (Reisebericht)",
    "pdf": "PDF",
    "latex": "LaTeX",
    "cewe": "CEWE-Projekt (.mcf)",
}


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: ProjectSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Projekteinstellungen")
        self.setMinimumSize(480, 360)
        self.resize(560, 620)
        self._settings = settings.model_copy(deep=True)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        body = QWidget()
        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(14)

        intro = QLabel(
            "Die Werte werden in settings.toml im Projektordner gespeichert. "
            "Originaldateien werden nicht verändert."
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        form.addWidget(intro)

        paths = QGroupBox("Originaldateien")
        paths_form = QFormLayout(paths)
        row = QHBoxLayout()
        self.source_edit = QLineEdit(self._settings.paths.source_root or "")
        self.source_edit.setPlaceholderText("Wurzelverzeichnis der Originale")
        browse = QPushButton("Ordner wählen")
        browse.clicked.connect(self._browse_source)
        row.addWidget(self.source_edit, 1)
        row.addWidget(browse)
        paths_form.addRow("Wurzelverzeichnis", row)
        hint = QLabel(
            "Wenn der Ordner verschoben wurde, hier den neuen Pfad eintragen. "
            "Die Pfade im Index werden umgeschrieben, die Dateien selbst nicht."
        )
        hint.setObjectName("pageSubtitle")
        hint.setWordWrap(True)
        paths_form.addRow("", hint)
        form.addWidget(paths)

        export = QGroupBox("Export")
        export_form = QFormLayout(export)
        self.format_combo = QComboBox()
        for key in EXPORT_FORMATS:
            self.format_combo.addItem(_FORMAT_LABELS[key], key)
        index = max(self.format_combo.findData(self._settings.export.default_format), 0)
        self.format_combo.setCurrentIndex(index)
        export_form.addRow("Standardformat", self.format_combo)
        form.addWidget(export)

        matching = QGroupBox("Zuordnung")
        matching_form = QFormLayout(matching)
        self.delta_spin = QSpinBox()
        self.delta_spin.setRange(1, 86_400)
        self.delta_spin.setSuffix(" s")
        self.delta_spin.setValue(self._settings.matching.gps_match_max_delta_seconds)
        matching_form.addRow("GPS-Zeitfenster", self.delta_spin)
        self.timezone_edit = QLineEdit(self._settings.matching.default_timezone or "")
        self.timezone_edit.setPlaceholderText("z. B. Europe/Berlin (optional)")
        matching_form.addRow("Standard-Zeitzone", self.timezone_edit)
        form.addWidget(matching)

        links = QGroupBox("Standard-Verbindung")
        links_form = QFormLayout(links)
        self.link_geometry_combo = ClickCombo()
        self.link_geometry_combo.addItem("Gerade", LINK_GEOMETRY_LINE)
        self.link_geometry_combo.addItem("Bogenlinie", LINK_GEOMETRY_ARC)
        self.link_geometry_combo.setCurrentIndex(
            max(0, self.link_geometry_combo.findData(self._settings.placeholders.default_link_geometry))
        )
        links_form.addRow("Linientyp", self.link_geometry_combo)
        self.link_dash_combo = ClickCombo()
        self.link_dash_combo.addItem("durchgezogen", LINK_DASH_SOLID)
        self.link_dash_combo.addItem("gestrichelt", LINK_DASH_DASHED)
        self.link_dash_combo.setCurrentIndex(
            max(0, self.link_dash_combo.findData(self._settings.placeholders.default_link_dash))
        )
        links_form.addRow("Strich", self.link_dash_combo)
        self.link_symbol_combo = ClickCombo()
        self.link_symbol_combo.addItem(transport_badge_icon("other"), "Pfeil", "")
        fill_transport_combo(
            self.link_symbol_combo,
            tuple((item.key, item.label) for item in TRANSPORT_SYMBOLS),
        )
        self.link_symbol_combo.setCurrentIndex(
            max(0, self.link_symbol_combo.findData(self._settings.placeholders.default_link_symbol))
        )
        links_form.addRow("Symbol", self.link_symbol_combo)
        links_hint = QLabel(
            "Gilt für die ganze Reise, solange ein Abschnitt nichts anderes setzt. "
            "Tag, Aufenthalt und Transfer können Linientyp, Strich und Symbol überschreiben. "
            "Map-Track und Keine Linie bleiben Einstellungen am Abschnitt."
        )
        links_hint.setObjectName("pageSubtitle")
        links_hint.setWordWrap(True)
        links_form.addRow("", links_hint)
        form.addWidget(links)

        extra = QGroupBox("Karte und Weitere")
        extra_form = QFormLayout(extra)
        self.map_combo = QComboBox()
        self.map_combo.setEditable(True)
        self.map_combo.addItems(["leaflet", "offline"])
        self.map_combo.setCurrentText(self._settings.placeholders.map_provider)
        extra_form.addRow("Kartenanbieter", self.map_combo)
        color_row = QHBoxLayout()
        self.link_color_edit = QLineEdit(self._settings.placeholders.map_link_color)
        self.link_color_edit.setPlaceholderText("#ffffff")
        self.link_color_edit.setMaximumWidth(110)
        self.link_color_edit.textChanged.connect(self._sync_link_color_button)
        self.link_color_btn = QPushButton()
        self.link_color_btn.setFixedSize(28, 24)
        self.link_color_btn.setToolTip("Farbe wählen")
        self.link_color_btn.clicked.connect(self._pick_link_color)
        color_row.addWidget(self.link_color_edit)
        color_row.addWidget(self.link_color_btn)
        color_row.addStretch(1)
        extra_form.addRow("Verbindungslinien", color_row)
        self._sync_link_color_button()
        track_row = QHBoxLayout()
        self.track_color_edit = QLineEdit(self._settings.placeholders.map_track_color)
        self.track_color_edit.setPlaceholderText("#5b8def")
        self.track_color_edit.setMaximumWidth(110)
        self.track_color_edit.textChanged.connect(self._sync_track_color_button)
        self.track_color_btn = QPushButton()
        self.track_color_btn.setFixedSize(28, 24)
        self.track_color_btn.setToolTip("Farbe wählen")
        self.track_color_btn.clicked.connect(self._pick_track_color)
        track_row.addWidget(self.track_color_edit)
        track_row.addWidget(self.track_color_btn)
        track_row.addStretch(1)
        extra_form.addRow("Map-Tracks", track_row)
        self._sync_track_color_button()
        self.language_edit = QLineEdit(self._settings.placeholders.journal_language)
        extra_form.addRow("Tagebuchsprache", self.language_edit)
        note = QLabel(
            "leaflet: OpenStreetMap-Kacheln mit lateinischen bzw. deutschen Namen "
            "(Netzwerk, openstreetmap.de). Straßenkarte, Topo (OpenTopoMap) und Satellit (Esri) "
            "schaltet man auf der Karte über das Layer-Symbol um. "
            "Fotokegel, Reserve-Anzeige, Ortsnamen und Straßen auf Satellit stehen im "
            "Zahnrad-Menü unter den Zoom-Buttons und werden in settings.toml mit dem Projekt gespeichert. "
            "offline: nur Track und Marker, ohne Umschalter. "
            "Verbindungslinien zwischen Tag- und Aufenthaltskreisen (Standard weiß). "
            "Map-Tracks (GPX unter .MapTracks/ im Import-Ordner) haben eine eigene Farbe (Standard blau). "
            "Linientyp und Verkehrssymbol der Reise stehen unter Standard-Verbindung. "
            "Tagebuchsprache folgt in einer späteren Phase."
        )
        note.setObjectName("pageSubtitle")
        note.setWordWrap(True)
        extra_form.addRow("", note)
        form.addWidget(extra)

        performance = QGroupBox("Leistung")
        performance_form = QFormLayout(performance)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(0, 64)
        self.workers_spin.setSpecialValueText("Automatisch (Kerne − 1)")
        self.workers_spin.setValue(self._settings.performance.worker_count)
        performance_form.addRow("CPU-Worker", self.workers_spin)
        workers_hint = QLabel(
            "Hash, Metadaten und Vorschaubilder laufen in mehreren Prozessen. "
            "0 nutzt alle Kerne minus einen für die Oberfläche. SQLite schreibt weiter nur in einem Prozess."
        )
        workers_hint.setObjectName("pageSubtitle")
        workers_hint.setWordWrap(True)
        performance_form.addRow("", workers_hint)
        form.addWidget(performance)

        scroll = QScrollArea(self)
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(body)
        self._scroll = scroll
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_source(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Wurzelverzeichnis der Originale")
        if directory:
            self.source_edit.setText(directory)

    def _pick_link_color(self) -> None:
        current = QColor(normalize_stay_link_color(self.link_color_edit.text()))
        picked = QColorDialog.getColor(current, self, "Linienfarbe")
        if picked.isValid():
            self.link_color_edit.setText(picked.name())

    def _pick_track_color(self) -> None:
        current = QColor(normalize_map_track_color(self.track_color_edit.text()))
        picked = QColorDialog.getColor(current, self, "Map-Track-Farbe")
        if picked.isValid():
            self.track_color_edit.setText(picked.name())

    def _sync_link_color_button(self) -> None:
        color = normalize_stay_link_color(self.link_color_edit.text())
        self.link_color_btn.setStyleSheet(f"background: {color}; border: 1px solid #444;")

    def _sync_track_color_button(self) -> None:
        color = normalize_map_track_color(self.track_color_edit.text())
        self.track_color_btn.setStyleSheet(f"background: {color}; border: 1px solid #444;")

    def result_settings(self) -> ProjectSettings:
        settings = self._settings.model_copy(deep=True)
        root = self.source_edit.text().strip()
        settings.paths.source_root = root or None
        data = self.format_combo.currentData()
        if isinstance(data, str):
            settings.export.default_format = data  # type: ignore[assignment]
        settings.matching.gps_match_max_delta_seconds = int(self.delta_spin.value())
        zone = self.timezone_edit.text().strip()
        settings.matching.default_timezone = zone or None
        settings.placeholders.map_provider = self.map_combo.currentText().strip() or "leaflet"
        settings.placeholders.map_link_color = normalize_stay_link_color(self.link_color_edit.text())
        settings.placeholders.map_track_color = normalize_map_track_color(self.track_color_edit.text())
        geometry = self.link_geometry_combo.currentData()
        settings.placeholders.default_link_geometry = (
            "arc" if geometry == LINK_GEOMETRY_ARC else "line"
        )
        dash = self.link_dash_combo.currentData()
        settings.placeholders.default_link_dash = "dashed" if dash == LINK_DASH_DASHED else "solid"
        symbol = self.link_symbol_combo.currentData()
        settings.placeholders.default_link_symbol = symbol if isinstance(symbol, str) else ""
        language = self.language_edit.text().strip() or "de"
        settings.placeholders.journal_language = language
        settings.performance.worker_count = int(self.workers_spin.value())
        return settings
